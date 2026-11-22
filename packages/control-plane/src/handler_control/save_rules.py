"""The rules an agent or a project must pass before it is saved — whoever asks (the Control API
today): what it runs as (E1), its folder (D.13, A2), its tools (G3), knowledge (D.5), display
(A.6), permission mode, what a save widens (risks, D.8), what it adds to the toolbox (B.6),
skills (D.17), agents set up from a definition (D.18, D.23, H.2), one project per folder and
agent names (D.8).

Errors say which check failed (`title`, the problem title clients see) and what is wrong:
CheckError (the request is wrong), ForbiddenError (outside what handler allows), ConflictError (with
the current state, or a risk not confirmed).
"""

from collections.abc import Collection, Sequence
from pathlib import Path

from handler_contracts import (
    ABILITIES,
    Ability,
    AddonUse,
    AgentInterface,
    AgentOrigin,
    AgentRequest,
    AgentSettings,
    CreateProjectRequest,
    KnowledgeFolderUse,
    KnowledgeUse,
    ModelAccess,
    ProjectSettingsRequest,
)
from handler_harness import RenderError, catalog, harness_env

from . import (
    access,
    addons,
    agents_files,
    areas,
    compose,
    folders,
    handler_needs,
    interfaces,
    knowledge,
    knowledge_schemas,
    launcher,
    llm,
    model_agent,
    runtime,
    skills,
    toolbox,
)
from .agents import (
    AgentRecord,
    AgentRegistry,
    CheckedSettings,
    NotAgentsModelError,
    RunsAs,
    with_knowledge_tool,
)
from .projects import ProjectRecord, ProjectRegistry
from .settings import Settings


class CheckError(ValueError):
    """An agent or a project cannot be saved like this."""

    def __init__(self, title: str, detail: str) -> None:
        super().__init__(detail)
        self.title = title


class ForbiddenError(CheckError):
    """Outside what handler allows (the work folders)."""


class ConflictError(CheckError):
    """In conflict with the current state, or widening what an agent may do unconfirmed."""


class ToolboxChangesError(ConflictError):
    """The save needs system packages the toolbox lacks, not confirmed (`toolboxAdds`)."""

    def __init__(self, adds: dict[str, list[str]]) -> None:
        listed = ", ".join(f"{name} (for {', '.join(c)})" for name, c in adds.items())
        super().__init__(
            "toolbox changes not confirmed",
            f"saving adds to the toolbox, for every agent, then rebuilds it: {listed}",
        )
        self.adds = list(adds)


# ── agents ──────────────────────────────────────────────────────────────


def checked_settings(
    settings: Settings, body: AgentSettings, folder: str | None, given: Sequence[AddonUse] = ()
) -> CheckedSettings:
    """An agent's settings in `folder`, checked: its model's harness with its account or provider
    (E1; the account's harness by default), the folder in the work folders (D.13, A2; None: a
    folderless agent, D.18), its addons with those its project gives (`given`, G3: not one of
    them), knowledge folders (D.5), display (A.6), permission mode (one its harness offers),
    interface (D.18: a job never asks). On the model alone (D.18): its provider, and its
    knowledge not more than a call takes."""
    if body.model_alone:
        model = checked_model_alone(settings, body.model)
    else:
        model = checked_model(settings, body.model)
        check_permissions(body.permissions, model)
    scope = checked_folder(settings, folder) if folder else None
    if body.interface is not None:
        check_interface(body.interface, body.permissions)
    if twice := sorted({u.addon for u in body.addons} & {u.addon for u in given}):
        raise CheckError("given by its project", f"{', '.join(twice)}: its project gives it")
    notes = checked_knowledge(settings, body.knowledge, body.model_alone)
    check_schemas(settings, body.schemas, body.model_alone)
    if not body.model_alone:  # no sandbox, no addons (its project's do not reach it)
        try:
            uses = with_knowledge_tool([*body.addons, *given], bool(body.schemas))
            selected = addons.check(settings.bindings_dir, uses)
        except addons.SelectionError as e:
            raise CheckError("tools unusable", str(e)) from None
        check_runtime_gives(body)
        check_env(settings, body, model, selected)
        check_blocked(settings, body, model, uses)
    own = body.model_dump(include=set(AgentSettings.model_fields) - {"model"})
    return CheckedSettings(**own | {"model": model, "scope": scope, "knowledge": notes})


def check_env(
    settings: Settings, body: AgentSettings, model: RunsAs, selected: list[addons.Selected]
) -> None:
    """The agent's own variables (D.8): none its harness sets on its model, in its permission
    mode, none of its tools' (its own and its project's), none of the toolbox's daemons its
    sandbox starts. A session on another model, a terminal or a harness changed since is
    checked again when it starts (compose)."""
    if not body.env:
        return
    try:
        resolved = launcher.agent_spec(settings, model)
        descriptor = catalog.get(resolved.harness).descriptor
        owners = dict.fromkeys(
            harness_env(descriptor, resolved, body.permissions), descriptor.product
        )
    except (launcher.AgentStartError, RenderError) as e:
        raise CheckError("model access unusable", str(e)) from None
    owners |= {name: f"the tool {tool}" for name, tool in addons.env_owners(selected).items()}
    if body.schemas:
        owners[compose.SCHEMAS_ENV] = "Handler (its schemas)"
    started = compose.started_daemons(toolbox.daemons(settings), body.confinement, body.display)
    owners |= {name: f"the toolbox ({d.command})" for d in started for name in d.env}
    if taken := sorted(body.env.keys() & owners.keys()):
        said = "; ".join(f"{name} is set by {owners[name]}" for name in taken)
        raise CheckError("environment variables taken", said)


def covers(entry: str, host: str) -> bool:
    """Whether an entry (A.3) takes in every target of `host`, an entry too: itself, or a
    wildcard over its domain on its port."""
    if entry == host:
        return True
    name, _, port = entry.rpartition(":")
    other, _, other_port = host.rpartition(":")
    return name.startswith("*.") and port == other_port and other.endswith(name[1:])


def check_blocked(
    settings: Settings, body: AgentSettings, model: RunsAs, uses: list[AddonUse]
) -> None:
    """A filtered agent keeps no host blocked that its model or one of its tools requires: the
    filter refuses a kept-blocked host whatever allows it (A.3), so the agent could not work."""
    if body.network != "filtered" or not body.blocked:
        return
    try:
        resolved = launcher.agent_spec(settings, model)
        required = launcher.required_hosts(settings, resolved, uses)
    except launcher.AgentStartError as e:
        raise CheckError("model access unusable", str(e)) from None
    if clash := [
        f"{entry} ({r.host} is required by {r.by})"
        for entry in body.blocked
        for r in required
        if covers(entry, r.host)
    ]:
        raise CheckError("a required host kept blocked", "; ".join(clash))


def check_runtime_gives(body: AgentSettings) -> None:
    """The abilities its sandboxes would need that the runtime lacks on this computer (A.8) are
    refused now, not when the agent starts (A1). Nothing is refused when the runtime cannot say
    (it cannot run)."""
    supported = runtime.supports()
    if supported is None:
        return
    needed: set[Ability] = set()
    if body.confinement != "strict":
        needed.add(body.confinement)
    if body.display:
        needed.add("display")
    if missing := needed - set(supported.abilities):
        words = ", ".join(ABILITIES[a] for a in sorted(missing))
        raise ConflictError(
            "not on this computer", f"not on this computer: {words} (handler setup says why)"
        )


def check_interface(interface: AgentInterface, permissions: str) -> None:
    """A form and maybe a result (D.18): a job never asks (no one is there to answer)."""
    try:
        interfaces.check(interface)
    except interfaces.InterfaceError as e:
        raise CheckError("interface invalid", str(e)) from None
    if interface.result is None and interface.timeout_sec is not None:
        raise CheckError("interface invalid", "timeoutSec: a job's (with a result) only")
    if interface.result is not None and permissions != "bypass":
        raise CheckError(
            "interface invalid",
            'it runs unattended: permission mode "bypass" (no one is there to answer)',
        )


def checked_knowledge(
    settings: Settings, uses: list[KnowledgeFolderUse], model_alone: bool
) -> list[KnowledgeFolderUse]:
    """Its notes folders (D.5), as paths in the root with their access; on the model alone, read
    only (it has no sandbox to write from) and not more notes than a call takes (D.18)."""
    if model_alone and any(u.access == "write" for u in uses):
        raise CheckError("notes unusable", "the model alone reads its notes only: it writes none")
    try:
        root, _ = knowledge.root(settings)
        checked = knowledge.check(root, uses)
        if model_alone:
            model_agent.knowledge_prompt(knowledge.notes(root, [u.folder for u in checked]))
    except knowledge.KnowledgeError as e:
        raise CheckError("notes unusable", str(e)) from None
    except model_agent.KnowledgeTooLargeError as e:
        raise CheckError("notes too large", str(e)) from None
    return checked


def check_schemas(settings: Settings, uses: list[KnowledgeUse], model_alone: bool) -> None:
    """Its knowledge uses (D.29): schemas of the Library an agent can use (those they extend
    too); none on the model alone: no sandbox, no tool to work with them (D.18)."""
    if not uses:
        return
    if model_alone:
        raise CheckError("model alone", "a schema needs an agent program: it has no tools")
    try:
        knowledge_schemas.files(settings.schemas_dir, [u.schema_id for u in uses])
    except knowledge_schemas.SchemaError as e:
        raise CheckError("schemas unusable", str(e)) from None


def session_model(settings: Settings, agent: AgentRecord, given: ModelAccess | None) -> RunsAs:
    """The model a session or a terminal of the agent runs with: `given`, the agent's or any
    other (D.19), else the agent's; ConflictError when it is not made for its project's area."""
    try:
        runs = agent.runs_as(given)
    except NotAgentsModelError:
        assert given is not None  # else the agent's
        check_model = checked_model_alone if agent.model_alone else checked_model
        runs = check_model(settings, given)
    check_for_area(settings, agent.area, runs)
    return runs


def check_permissions(mode: str, model: RunsAs) -> None:
    """A permission mode the harness of the agent's model offers."""
    harness = model.harness
    assert harness is not None  # resolved by checked_model
    offered = catalog.get(harness).descriptor.permissions
    if mode not in offered:
        raise CheckError(
            "permission mode not offered",
            f'harness "{harness}" has no mode "{mode}" (it offers: {", ".join(offered)})',
        )


def checked_model_alone(settings: Settings, m: ModelAccess) -> RunsAs:
    """The model of an agent on the model alone (D.18): a provider and its model that
    handlerd can call (llm.py); no harness."""
    if m.provider is None or m.harness is not None:
        raise CheckError("model access unusable", "the model alone runs on a provider, no harness")
    try:
        llm.check(settings.providers_dir, m.provider, m.model)
    except ValueError as e:
        raise CheckError("model access unusable", str(e)) from None
    return RunsAs(**m.model_dump())


def check_for_area(settings: Settings, area: str | None, m: ModelAccess) -> None:
    """ConflictError when that model's account or provider is not made for the area (D.19)."""
    try:
        areas.check(settings.sources, area, m.account, m.provider)
    except areas.AreaError as e:
        raise ConflictError("not for this project's area", str(e)) from None


def checked_model(settings: Settings, m: ModelAccess) -> RunsAs:
    """An agent's model: its harness (an account's by default) with its account or
    provider and model, resolved (E1)."""
    sources = settings.sources
    try:
        harness = m.harness or access.account_harness(sources, m.account or "")
        access.resolve(sources, harness, account=m.account, provider=m.provider, model=m.model)
    except ValueError as e:
        raise CheckError("model access unusable", str(e)) from None
    return RunsAs(**m.model_dump() | {"harness": harness})


_WIDER = {
    # log only lets every host through: wider than enforcing, short of open (A.4)
    "network": {"none": 0, "filtered": 1, "log-only": 2, "open": 3},
    "confinement": {"strict": 0, "nested": 1, "privileged": 2},
    "permissions": {"ask": 0, "accept-edits": 1, "bypass": 2},
}
_RISK = {
    "log-only": "log only: every host gets through, only logged",
    "open": "an open network: anything on the internet and your LAN",
    "nested": "it runs containers (a weaker confinement)",
    "privileged": "a privileged sandbox: about as safe as no sandbox",
    "bypass": "auto-approve: it never asks before acting",
}


def _risk_value(settings: AgentSettings | None, name: str) -> str:
    """A setting as `_WIDER` ranks it (None: the preset of new agents); the network of a
    filtered agent in log only is "log-only"."""
    value = getattr(settings, name) if settings else AgentSettings.model_fields[name].default
    egress = settings.egress if settings else AgentSettings.model_fields["egress"].default
    learning = name == "network" and value == "filtered" and egress == "log-only"
    return "log-only" if learning else value


def agent_risks(old: AgentSettings | None, new: AgentSettings) -> list[str]:
    """What a save gives the agent beyond what it had (a new one: beyond the preset of new
    agents, D.8): a wider network (log only included), confinement or permission mode, a notes
    folder it may now write (D.5). None on the model alone: no sandbox, no tools, nothing to
    widen (D.18)."""
    if new.model_alone:
        return []
    found = []
    for name, rank in _WIDER.items():
        value = _risk_value(new, name)
        if rank[value] > rank[_risk_value(old, name)]:
            found.append(_RISK.get(value, f'{name} "{value}"'))
    wrote = {u.folder for u in old.knowledge if u.access == "write"} if old else set()
    for use in new.knowledge:
        if use.access == "write" and use.folder not in wrote:
            found.append(f"notes {use.folder} read-write: it can change or delete any file there")
    return found


def check_risks(old: AgentSettings | None, new: AgentSettings, body: AgentRequest) -> None:
    """Refused unless the client confirmed what the save widens (D.8)."""
    if (found := agent_risks(old, new)) and not body.confirm_risks:
        raise ConflictError("risks not confirmed", "; ".join(found))


def check_toolbox(
    settings: Settings,
    agents: Sequence[tuple[AgentSettings, Sequence[AddonUse], str]],
    confirmed: Collection[str],
) -> None:
    """Refused unless the client confirmed the system packages the save adds to the toolbox for
    what the agents need (B.6): `agents` are each one's settings, its project's addons and who it
    is. A need no system package provides is not refused: its addon says what it lacks."""
    needs = [n for a, given, by in agents for n in toolbox.agent_needs(a, given, by)]
    adds = toolbox.to_add(settings, needs).adds
    if any(name not in confirmed for name in adds):
        raise ToolboxChangesError(adds)


def agent_name(body: AgentRequest, project: ProjectRecord | None) -> str | None:
    """Its name as typed: required in a project (its goal, D.8), else optional (its folder's)."""
    name = (body.name or "").strip() or None
    if project is not None and name is None:
        raise CheckError("name required", "an agent of a project is named after its goal")
    return name


def check_unique_names(names: list[str]) -> None:
    lowered = [n.lower() for n in names]
    if dupes := sorted({n for n in lowered if lowered.count(n) > 1}):
        raise ConflictError("agent names must differ", ", ".join(dupes))


def check_instructions(instructions: str | None, interface: AgentInterface | None) -> None:
    """The form's fields its instructions name exist (D.18)."""
    try:
        interfaces.check_instructions(instructions, interface)
    except interfaces.InterfaceError as e:
        raise CheckError("instructions invalid", str(e)) from None


def check_project_addons(settings: Settings, uses: list[AddonUse]) -> None:
    """A project gives addons that fit together (G3), whatever its agents are."""
    try:
        addons.check(settings.bindings_dir, uses)
    except addons.SelectionError as e:
        raise CheckError("tools unusable", str(e)) from None


def check_project_skills(settings: Settings, names: list[str]) -> None:
    """A project gives skills of the library that agents can use (D.17)."""
    for name in names:
        if (skill := skills.get(settings.skills_dir, name)).error:
            raise CheckError("skills unusable", f"{name}: {skill.error}")


def check_skills(settings: Settings, body: AgentRequest, project: ProjectRecord | None) -> None:
    """An agent picks valid skills of the library, not those its project gives to all its
    agents (D.17); none on the model alone: a skill may run scripts (D.18)."""
    names = body.skills
    if body.model_alone and names:
        raise CheckError("model alone", "a skill needs an agent program: it may run scripts")
    for name in names:
        if (skill := skills.get(settings.skills_dir, name)).error:
            raise CheckError("skills unusable", f"{name}: {skill.error}")
        if project is not None and name in project.skills:
            raise CheckError("given by its project", f"{name}: {project.name} gives it")


def check_origin(
    settings: Settings, origin: AgentOrigin | None, current: AgentRecord | None
) -> Path | None:
    """What an agent is set up from: an agents file's agent (D.23, the file read) or one of
    Handler's needs' definition (D.18, its current version); an agent keeps its origin (none
    stays none). Returns
    the definition's folder for a new agent (its skills go to the library, its checks to the
    agent), None otherwise."""
    if current is not None and origin != current.origin:
        raise ConflictError("origin cannot change", "an agent keeps what it was set up from")
    if origin is None or current is not None:
        return None
    try:
        if origin.kind == "agents-file":
            return agents_files.part_folder(settings, origin)
        return handler_needs.folder(origin)
    except (agents_files.AgentsFileError, handler_needs.NeedError) as e:
        raise (ConflictError if e.status == 409 else CheckError)(e.title, str(e)) from None


def check_home(body: AgentRequest, current: AgentRecord | None) -> None:
    """Its home (D.1): given at creation, never changed. Chat's agents are chats with no folder
    (each conversation gets one)."""
    if current is not None:
        if (body.project_id, body.chat) != (current.project_id, current.chat):
            raise ConflictError("home cannot change", "an agent stays where it was made")
        return
    if body.chat and (body.scope is not None or body.interface is not None):
        raise CheckError("a chat", "Chat's agents have no folder and no form")


def check_outside_identity(
    registry: AgentRegistry,
    scope: str | None,
    name: str | None,
    current: AgentRecord | None = None,
) -> None:
    """Outside projects an agent is its folder and its name (D.1): the same command in the same
    folder always gives the same agent, so no two share them."""
    taken = registry.outside(scope, name)
    if taken is not None and taken is not current:
        where = f"in {scope}" if scope else "with a folder per session"
        called = f"named {taken.name}" if taken.name else "unnamed"
        raise ConflictError("agent exists", f"agent {taken.id} ({called}) works {where}")


def checked_folder(settings: Settings, folder: str) -> str:
    """A folder agents work in, checked: inside the work folders, links resolved (D.13, A2)."""
    try:
        return compose.check_scope(folders.roots(settings), folder)
    except compose.ScopeError as e:
        raise ForbiddenError("scope not allowed", str(e)) from None


# ── projects ────────────────────────────────────────────────────────────


def check_project(
    projects: ProjectRegistry, body: ProjectSettingsRequest, current: str | None = None
) -> None:
    """One project per folder (the folder says which project a directory belongs to)."""
    other = projects.by_folder(body.folder)
    if other is not None and other.id != current:
        raise ConflictError("folder already used", f"project '{other.name}' uses {body.folder}")


def check_area(settings: Settings, area: str | None, agents: list[CheckedSettings]) -> None:
    """A project's area (D.19): one that exists, and the model of each of its agents made for it."""
    if area is None:
        return
    if area not in areas.load(settings):
        raise CheckError("unknown area", area)
    for agent in agents:
        check_for_area(settings, area, agent.model)


def new_project_agents(
    settings: Settings, projects: ProjectRegistry, body: CreateProjectRequest
) -> list[CheckedSettings]:
    """A new project's agents (none, or more), checked, in its folder."""
    for a in body.agents:
        if a.project_id is not None or a.chat or a.scope is not None:
            raise CheckError("a new project's agent", "its home and folder are the project's")
    checked = [checked_settings(settings, a, body.folder, body.addons) for a in body.agents]
    for a, agent in zip(body.agents, checked, strict=True):
        check_risks(None, agent, a)
        check_skills(settings, a, None)
        check_instructions(a.instructions, a.interface)
    named = [(c, body.addons, f"agent:{a.name}") for a, c in zip(body.agents, checked, strict=True)]
    check_toolbox(settings, named, body.toolbox_adds)
    check_area(settings, body.area, checked)
    check_project_skills(settings, body.skills)
    check_project_addons(settings, body.addons)
    return checked


def project_folder(
    settings: Settings,
    projects: ProjectRegistry,
    project: ProjectRecord,
    body: ProjectSettingsRequest,
) -> str:
    """A project's folder after a full update, checked: its agents' settings must still pass
    there, their models in its area; its default agent must be one of them."""
    check_project(projects, body, project.id)
    agents = projects.agents(project)
    if body.default_agent is not None and body.default_agent not in {a.id for a in agents}:
        raise CheckError("unknown agent", body.default_agent)
    given = {u.addon for u in body.addons}  # an agent that picked one drops it (give_addons)
    checked = [
        checked_settings(
            settings,
            a.settings.model_copy(update={"addons": [u for u in a.addons if u.addon not in given]}),
            body.folder,
            body.addons,
        )
        for a in agents
    ]
    check_area(settings, body.area, checked)
    check_project_skills(settings, body.skills)
    check_project_addons(settings, body.addons)
    named = [(c, body.addons, f"agent:{a.id}") for a, c in zip(agents, checked, strict=True)]
    check_toolbox(settings, named, body.toolbox_adds)
    scopes = [c.scope for c in checked]
    return scopes[0] or body.folder if scopes else checked_folder(settings, body.folder)
