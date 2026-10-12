"""The rules an agent or a project must pass before it is saved — whoever asks (the Control API
today): what it runs as (E1), its folder (D.13, A2), its tools (G3), knowledge (D.5), display
(A.6), permission mode, what a save widens (risks, D.8), skills (D.17), built-in agents set up
once (D.18), one project per folder and agent names (D.8).

Errors say which check failed (`title`, the problem title clients see) and what is wrong:
CheckError (the request is wrong), ForbiddenError (outside what handler allows), ConflictError (with
the current state, or a risk not confirmed).
"""

from handler_contracts import (
    AdHocAgentRequest,
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
    builtin_agents,
    compose,
    contexts,
    display,
    folders,
    interfaces,
    knowledge,
    skills,
)
from .agents import AgentRecord, AgentRegistry, CheckedSettings, ModelNotListedError, RunsAs
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
    """An agent's settings in `folder`, checked: each model's harness with its account or provider
    (E1; the account's harness by default), the folder in the work folders (D.13, A2; None: a
    folderless agent, D.18), bindings (G3), knowledge folders (D.5), display (A.6), permission
    mode (one every harness of its models offers), interface (D.18)."""
    models = [checked_model(settings, m) for m in body.models]
    if len({m.model_dump_json() for m in models}) != len(models):
        raise CheckError("model access unusable", "a model is listed twice")
    for harness in dict.fromkeys(m.harness for m in models):
        offered = catalog.get(harness).descriptor.permissions  # checked by checked_model
        if body.permissions not in offered:
            raise CheckError(
                "permission mode not offered",
                f'harness "{harness}" has no mode "{body.permissions}" '
                f"(it offers: {', '.join(offered)})",
            )
    try:
        scope = compose.check_scope(folders.roots(settings), folder) if folder else None
    except compose.ScopeError as e:
        raise ForbiddenError("scope not allowed", str(e)) from None
    if body.interface is not None:
        try:
            interfaces.check(body.interface)
        except interfaces.InterfaceError as e:
            raise CheckError("interface invalid", str(e)) from None
        if body.permissions != "bypass":
            raise CheckError(
                "interface invalid",
                'it runs unattended: permission mode "bypass" (no one is there to answer)',
            )
    try:
        addons.check(settings.bindings_dir, body.bindings)
    except addons.SelectionError as e:
        raise CheckError("bindings unusable", str(e)) from None
    try:
        root, _ = knowledge.root(settings)
        notes = knowledge.check(root, body.knowledge)
    except knowledge.KnowledgeError as e:
        raise CheckError("knowledge unusable", str(e)) from None
    if body.display:
        try:
            display.wayland_socket()
        except display.DisplayError as e:
            raise ConflictError("no display", str(e)) from None
    own = body.model_dump(include=set(AgentSettings.model_fields) - {"models"})
    return CheckedSettings(**own | {"models": models, "scope": scope, "knowledge": notes})


def session_model(settings: Settings, agent: AgentRecord, given: ModelAccess | None) -> RunsAs:
    """The model a session or a terminal of the agent runs with: `given`, one of the agent's or
    any other (D.19), else its first; ConflictError when it is not made for its project's
    context."""
    try:
        runs = agent.runs_as(given)
    except ModelNotListedError:
        assert given is not None  # its first is listed
        runs = checked_model(settings, given)
    check_for_context(settings, agent.context, runs)
    return runs


def check_for_context(settings: Settings, context: str | None, m: ModelAccess) -> None:
    """ConflictError when that model's account or provider is not made for the context (D.19)."""
    try:
        contexts.check(settings.sources, context, m.account, m.provider)
    except contexts.ContextError as e:
        raise ConflictError("not for this project's context", str(e)) from None


def checked_model(settings: Settings, m: ModelAccess) -> RunsAs:
    """One of an agent's models: its harness (an account's by default) with its account or
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
    agents, D.8): a wider network (log only included), confinement or permission mode."""
    found = []
    for name, rank in _WIDER.items():
        value = _risk_value(new, name)
        if rank[value] > rank[_risk_value(old, name)]:
            found.append(_RISK.get(value, f'{name} "{value}"'))
    return found


def check_risks(
    old: AgentSettings | None, new: AgentSettings, body: AgentRequest | AdHocAgentRequest
) -> None:
    """Refused unless the client confirmed what the save widens (D.8)."""
    if (found := agent_risks(old, new)) and not body.confirm_risks:
        raise ConflictError("risks not confirmed", "; ".join(found))


def agent_name(body: AgentRequest) -> str:
    """An agent of a project's name: its goal, as typed (required, D.8)."""
    return body.name.strip()


def check_unique_names(names: list[str]) -> None:
    lowered = [n.lower() for n in names]
    if dupes := sorted({n for n in lowered if lowered.count(n) > 1}):
        raise ConflictError("agent names must differ", ", ".join(dupes))


def check_skills(settings: Settings, names: list[str], project: ProjectRecord | None) -> None:
    """An agent picks valid skills of the library, not those its project gives to all its
    agents (D.17)."""
    for name in names:
        if (skill := skills.get(settings.skills_dir, name)).error:
            raise CheckError("skills unusable", f"{name}: {skill.error}")
        if project is not None and name in project.skills:
            raise CheckError("given by its project", f"{name}: {project.name} gives it")


def check_origin(
    registry: AgentRegistry, origin: str | None, current: AgentRecord | None = None
) -> builtin_agents.LoadedBuiltin | None:
    """The built-in agent an ad-hoc agent is set up from (D.18): one handler ships, set up once; an
    agent keeps its origin (none stays none). Returns it, None for an agent without one."""
    if current is not None and origin != current.origin:
        raise ConflictError("origin cannot change", f"{current.origin} → {origin}")
    if origin is None:
        return None
    loaded = builtin_agents.get(origin)
    if loaded is None:
        raise CheckError("unknown built-in agent", origin)
    taken = next((r for r in registry.agents.values() if r.origin == origin), None)
    if taken is not None and taken is not current:
        raise ConflictError("built-in agent already set up", f"{origin}: agent {taken.id}")
    return loaded


def check_ad_hoc_identity(
    registry: AgentRegistry,
    scope: str | None,
    name: str | None,
    current: AgentRecord | None = None,
) -> None:
    """An ad-hoc agent is its folder and its name (D.1): the same command in the same folder
    always gives the same agent, so no two share them."""
    taken = registry.ad_hoc(scope, name)
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


def check_context(settings: Settings, context: str | None, agents: list[CheckedSettings]) -> None:
    """A project's context (D.19): one that exists, and every model of its agents made for it."""
    if context is None:
        return
    if context not in contexts.load(settings):
        raise CheckError("unknown context", context)
    for agent in agents:
        for m in agent.models:
            check_for_context(settings, context, m)


def new_project_agents(
    settings: Settings, projects: ProjectRegistry, body: CreateProjectRequest
) -> list[CheckedSettings]:
    """A new project's agents, checked, in its folder."""
    checked = [checked_settings(settings, a, body.folder) for a in body.agents]
    for a, agent in zip(body.agents, checked, strict=True):
        check_risks(None, agent, a)
        check_skills(settings, a.skills, None)
    check_context(settings, body.context, checked)
    return checked


def project_folder(
    settings: Settings,
    projects: ProjectRegistry,
    project: ProjectRecord,
    body: ProjectSettingsRequest,
) -> str:
    """A project's folder after a full update, checked: its agents' settings must still pass
    there, their models in its context; its default agent must be one of them."""
    check_project(projects, body, project.id)
    agents = projects.agents(project)
    if body.default_agent is not None and body.default_agent not in {a.id for a in agents}:
        raise CheckError("unknown agent", body.default_agent)
    checked = [checked_settings(settings, a.settings, body.folder) for a in agents]
    check_context(settings, body.context, checked)
    scopes = [c.scope for c in checked]
    return scopes[0] or body.folder if scopes else body.folder
