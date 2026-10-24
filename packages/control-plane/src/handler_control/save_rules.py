"""The rules an agent or a project must pass before it is saved — whoever asks (the Control API
today): what it runs as (E1), its folder (D.13, A2), its tools (G3), knowledge (D.5), display
(A.6), permission mode, what a save widens (risks, D.8), skills (D.17), agents set up from a
definition (D.18, D.23, H.2), one project per folder and agent names (D.8).

Errors say which check failed (`title`, the problem title clients see) and what is wrong:
CheckError (the request is wrong), ForbiddenError (outside what handler allows), ConflictError (with
the current state, or a risk not confirmed).
"""

from collections.abc import Callable, Collection
from pathlib import Path

from handler_contracts import (
    AgentInterface,
    AgentOrigin,
    AgentRequest,
    AgentSettings,
    CreateProjectRequest,
    ModelAccess,
    ProjectSettingsRequest,
)
from handler_harness import catalog

from . import (
    access,
    addons,
    agents_files,
    areas,
    compose,
    display,
    folders,
    handler_needs,
    interfaces,
    knowledge,
    llm,
    model_agent,
    skills,
)
from .agents import AgentRecord, AgentRegistry, CheckedSettings, NotAgentsModelError, RunsAs
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


# ── agents ──────────────────────────────────────────────────────────────


def checked_settings(
    settings: Settings, body: AgentSettings, folder: str | None
) -> CheckedSettings:
    """An agent's settings in `folder`, checked: its model's harness with its account or provider
    (E1; the account's harness by default), the folder in the work folders (D.13, A2; None: a
    folderless agent, D.18), bindings (G3), knowledge folders (D.5), display (A.6), permission
    mode (one its harness offers), interface (D.18: a job never asks). On the model alone (D.18):
    its provider, and its knowledge not more than a call takes."""
    if body.model_alone:
        model = checked_model_alone(settings, body.model)
    else:
        model = checked_model(settings, body.model)
        check_permissions(body.permissions, model)
    try:
        scope = compose.check_scope(folders.roots(settings), folder) if folder else None
    except compose.ScopeError as e:
        raise ForbiddenError("scope not allowed", str(e)) from None
    if body.interface is not None:
        check_interface(body.interface, body.permissions)
    try:
        addons.check(settings.bindings_dir, body.bindings)
    except addons.SelectionError as e:
        raise CheckError("bindings unusable", str(e)) from None
    notes = checked_knowledge(settings, body.knowledge, body.model_alone)
    if body.display:
        try:
            display.wayland_socket()
        except display.DisplayError as e:
            raise ConflictError("no display", str(e)) from None
    own = body.model_dump(include=set(AgentSettings.model_fields) - {"model"})
    return CheckedSettings(**own | {"model": model, "scope": scope, "knowledge": notes})


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


def checked_knowledge(settings: Settings, folders: list[str], model_alone: bool) -> list[str]:
    """Its knowledge folders (D.5), as paths in the root; on the model alone, not more notes
    than a call takes (D.18)."""
    try:
        root, _ = knowledge.root(settings)
        checked = knowledge.check(root, folders)
        if model_alone:
            model_agent.knowledge_prompt(knowledge.notes(root, checked))
    except knowledge.KnowledgeError as e:
        raise CheckError("knowledge unusable", str(e)) from None
    except model_agent.KnowledgeTooLargeError as e:
        raise CheckError("knowledge too large", str(e)) from None
    return checked


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
    agents, D.8): a wider network (log only included), confinement or permission mode. None on
    the model alone: no sandbox, no tools, nothing to widen (D.18)."""
    if new.model_alone:
        return []
    found = []
    for name, rank in _WIDER.items():
        value = _risk_value(new, name)
        if rank[value] > rank[_risk_value(old, name)]:
            found.append(_RISK.get(value, f'{name} "{value}"'))
    return found


def check_risks(old: AgentSettings | None, new: AgentSettings, body: AgentRequest) -> None:
    """Refused unless the client confirmed what the save widens (D.8)."""
    if (found := agent_risks(old, new)) and not body.confirm_risks:
        raise ConflictError("risks not confirmed", "; ".join(found))


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
    settings: Settings,
    origin: AgentOrigin | None,
    current: AgentRecord | None,
    app_definition: Callable[[AgentOrigin], Path],
) -> Path | None:
    """What an agent is set up from: an app's need's definition (H.2, found by
    `app_definition`), an agents file's agent (D.23, the file read) or one of Handler's needs'
    definition (D.18, its current version); an agent keeps its origin (none stays none). Returns
    the definition's folder for a new agent (its skills go to the library, its checks to the
    agent), None otherwise."""
    if current is not None and origin != current.origin:
        raise ConflictError("origin cannot change", "an agent keeps what it was set up from")
    if origin is None or current is not None:
        return None
    if origin.kind == "app":
        return app_definition(origin)
    try:
        if origin.kind == "agents-file":
            return agents_files.part_folder(settings, origin)
        return handler_needs.folder(origin)
    except (agents_files.AgentsFileError, handler_needs.NeedError) as e:
        raise (ConflictError if e.status == 409 else CheckError)(e.title, str(e)) from None


def check_home(body: AgentRequest, current: AgentRecord | None, apps: Collection[str]) -> None:
    """Its home (D.1, H.14): given at creation, never changed. An app's part is set up from
    that app's need; Chat's agents are chats with no folder (each conversation gets one)."""
    if current is not None:
        if (body.project_id, body.app, body.chat) != (
            current.project_id,
            current.app,
            current.chat,
        ):
            raise ConflictError("home cannot change", "an agent stays where it was made")
        return
    from_app = body.origin.name if body.origin and body.origin.kind == "app" else None
    if body.chat:
        if body.scope is not None or body.interface is not None:
            raise CheckError("a chat", "Chat's agents have no folder and no form")
        return
    if from_app != body.app:
        why = (
            f"set up from a need of the app {from_app}, it is one of its parts (app {from_app})"
            if from_app
            else f"one of the app {body.app}'s parts is set up from one of its needs"
        )
        raise CheckError("an app's agent", why)
    if body.app is not None and body.app not in apps:
        raise CheckError("unknown app", body.app)


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
    """A new project's agents, checked, in its folder."""
    for a in body.agents:
        if a.project_id is not None or a.app is not None or a.chat or a.scope is not None:
            raise CheckError("a new project's agent", "its home and folder are the project's")
    checked = [checked_settings(settings, a, body.folder) for a in body.agents]
    for a, agent in zip(body.agents, checked, strict=True):
        check_risks(None, agent, a)
        check_skills(settings, a, None)
        check_instructions(a.instructions, a.interface)
    check_area(settings, body.area, checked)
    check_project_skills(settings, body.skills)
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
    checked = [checked_settings(settings, a.settings, body.folder) for a in agents]
    check_area(settings, body.area, checked)
    check_project_skills(settings, body.skills)
    scopes = [c.scope for c in checked]
    return scopes[0] or body.folder if scopes else body.folder
