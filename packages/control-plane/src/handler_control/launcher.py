"""Starting one agent for one ACP connection: the whole composition, in order.

agent spec (E) ─► addons (G), skills (D.17) ─► secrets + config files ─► render (B)
               ─► compose (B+G → A) ─► sandbox (A)

The agent spec is the harness of the model the connection runs with (the agent's or another), with
its account or provider resolved (access.py); the harness's own state is kept in agent_state.py.
"""

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from handler_contracts import (
    DEFAULT_MAX_MESSAGE_BYTES,
    AgentSpec,
    FilteredNetwork,
    HarnessDescriptor,
    HarnessLaunch,
    HostFolder,
    RequiredHost,
    SandboxSpec,
    SessionMount,
    TerminalStart,
    egress_target,
)
from handler_harness import RenderError, catalog, harness_hosts, images, render
from handler_harness.providers import egress as provider_egress

from . import (
    access,
    accounts,
    addons,
    agent_state,
    areas,
    caches,
    compose,
    config_files,
    folders,
    knowledge,
    providers,
    runtime,
    sandbox_process,
    secrets,
    skills,
    toolbox,
)
from .agents import AgentRecord, RunsAs
from .settings import Settings


class AgentStartError(RuntimeError):
    """The connection cannot be served (bad account or provider, scope, secret, render…)."""


class ImageMissingError(AgentStartError):
    """An image the sandbox needs is not built (A.7: a launch never builds one). `target`: the
    build that makes it (D.4)."""

    def __init__(self, target: str) -> None:
        self.target = target
        if target == NETWORK_FILTER:
            what = "the network filter is"
        elif target.startswith(ADDON):
            what = f"the programs of the {target.removeprefix(ADDON)} tool are"
        else:
            what = f"the image of {target} is"
        typed = f"tool:{target.removeprefix(ADDON)}" if target.startswith(ADDON) else target
        super().__init__(
            f"{what} not built yet: Settings → Sandboxes, or `handler image rebuild {typed}`"
        )


NETWORK_FILTER, ADDON = "network-filter", "addon:"  # build targets (D.4)
# agents with a network allow-list or a secret need it; handlerd builds it as it starts (D.4)
NETWORK_FILTER_MISSING = str(ImageMissingError(NETWORK_FILTER))


def missing(target: str) -> AgentStartError:
    """The error for an image `target` builds that seems missing: the runtime cannot run now (its
    engine stopped knows of no image), else it is not built."""
    if why := runtime.not_ready():
        return AgentStartError(f"sandboxes cannot start now: {why}")
    return ImageMissingError(target)


def _require_images(spec: SandboxSpec, harness: str) -> None:
    """Each image the sandbox needs is built: the network filter when it needs one, its harness's,
    its addons' (their folders, each mounted at <ADDONS_ROOT>/<its name>, G.2)."""
    if runtime.missing_proxy(spec):
        raise missing(NETWORK_FILTER)
    if not runtime.exists(spec.image):
        raise missing(harness)
    for addon in spec.addons:
        if not Path(addon.source).is_dir():
            raise ImageMissingError(f"{ADDON}{PurePosixPath(addon.target).name}")


@dataclass
class StartedAgent:
    connection_id: str
    spec: SandboxSpec
    launch: HarnessLaunch
    process: object  # asyncio.subprocess.Process (a terminal's: subprocess.Popen)
    seen: list[SessionMount]  # what its sandbox sees of the host (F.8)
    # filtered sandboxes: the required entries (harness, account or provider, addons), so the
    # agent's own can be changed live on top (A.4); None otherwise
    egress_base: list[str] | None = None
    # on a provider: its endpoint's entry (A.3), the host the agent's model calls
    model_host: str | None = None


def agent_spec(settings: Settings, runs: RunsAs) -> AgentSpec:
    """A model the agent runs with: its harness with its account or provider, resolved (E1)."""
    assert runs.harness is not None  # an agent program's: the model alone has no sandbox (D.18)
    try:
        return access.resolve(
            settings.sources,
            runs.harness,
            account=runs.account,
            provider=runs.provider,
            model=runs.model,
        )
    except ValueError as e:
        raise AgentStartError(str(e)) from None


def model_host(settings: Settings, runs: RunsAs) -> str | None:
    """The host the agent's model calls when it runs on a provider (its endpoint's entry, A.3);
    None on an account."""
    if runs.provider is None:
        return None
    resolved = agent_spec(settings, runs)
    assert resolved.provider_spec is not None  # on a provider
    return provider_egress(catalog.get(resolved.harness).descriptor, resolved.provider_spec)


def prepare(
    settings: Settings,
    agent: AgentRecord,
    runs: RunsAs,
    connection_id: str,
    *,
    session_state: str | None = None,
    terminal: TerminalStart | None = None,
    folder: str | None = None,
    subject: HostFolder | None = None,
) -> tuple[SandboxSpec, HarnessLaunch, list[str] | None, list[SessionMount]]:
    """Everything up to the SandboxSpec — no side effects except reading files and secrets.
    Also returns the required allow-list entries (see StartedAgent.egress_base): those of `runs`,
    the agent's model it runs with, never of its other models; and what the sandbox sees of the
    host (F.8).

    `session_state`: for a Session (F), its folder for the harness's per-session slot.
    `terminal`: the harness's own terminal program on the client's terminal (D.16), not ACP.
    `folder`: a folderless agent's session's own folder (D.18), where it works.
    `subject`: what a session works on, mounted read-only: a run's (an agent with an interface,
    D.18), a plan builder's project (D.27).
    """
    if agent.model_alone:  # its sessions talk to handlerd's model agent (sessions.py)
        raise AgentStartError("an agent on the model alone works in sessions only (D.18)")
    resolved = agent_spec(settings, runs)
    try:
        areas.check(settings.sources, agent.area, runs.account, runs.provider)
    except areas.AreaError as e:
        raise AgentStartError(str(e)) from None
    roots: tuple[str, ...] = ()
    if agent.scope is None:
        if folder is None:
            raise AgentStartError("a folderless agent works in sessions only (D.18)")
        roots = (str(sessions_root(settings)), str(plan_drafts_root(settings)))
    try:
        scope = compose.check_scope(folders.roots(settings), agent.scope or folder or "", roots)
        if terminal is not None and terminal.folder is not None:
            scope = compose.narrowed_scope(scope, terminal.folder)
        store = secrets.SecretStore(settings.data_dir)
        selected = addons.check(settings.bindings_dir, agent.addon_uses)
        extra = addons.resolve(selected, store)
        extra.images.extend(addons.tools(settings, selected))
        chosen = [*agent.skills, *agent.project_skills]  # its own, then its project's
        extra.skills.extend(skills.paths(settings.skills_dir, chosen))
        knowledge_root, _ = knowledge.root(settings)
        notes = knowledge.check(knowledge_root, agent.knowledge)
        provider_key = provider_secret(resolved, store)
        contents = config_files.resolve_all(resolved.files)
        descriptor = catalog.get(resolved.harness).descriptor
        account_token = account_login(settings, resolved, descriptor, store)
        login_file = read_login_file(resolved, descriptor)
        delivery = secrets.Delivery(agent.network)
        account_token, provider_key = _deliver(
            settings,
            delivery,
            resolved,
            descriptor,
            account_token=account_token,
            provider_key=provider_key,
            extra=extra,
        )
        state_root = str(agent_state.root(settings.data_dir, agent, runs))
        launch = render(
            descriptor,
            resolved,
            contents,
            session_state=session_state,
            state_root=state_root,
            provider_key=provider_key,
            account_token=account_token,
            login_file=login_file,
            skills=extra.skills,
            mcp_servers=extra.mcp_servers,
            terminal=terminal.args if terminal is not None else None,
            instructions=agent.instructions if terminal is not None else None,
            network=agent.network,
            permission_mode=agent.permissions,
            caches=caches.mounts(
                settings, agent.caches, agent.project_id, [u.addon for u in agent.addon_uses]
            ),
        )
        name = f"handler-{agent.id}-{connection_id}"
        known = knowledge.folders(knowledge_root, notes)
        spec = compose.sandbox_spec(
            name=name,
            launch=launch,
            scope=scope,
            network=agent.network,
            enforcement=agent.egress,
            confinement=agent.confinement,
            allow=agent.allow,
            blocked=agent.blocked,
            labels={"handler.agent": agent.id, "handler.connection": connection_id}
            | ({"handler.terminal": "1"} if terminal is not None else {}),
            addons=extra,
            knowledge=known,
            subject=subject,
            display=agent.display,  # its runtime finds the screen (A.6)
            terminal=terminal,
            paste=str(paste_folder(settings, name)) if terminal is not None else None,
            injections=delivery.injections,
            daemons=toolbox.daemons(settings),
        )
    except (
        compose.ScopeError,
        compose.AddonConflictError,
        compose.DaemonConflictError,
        addons.SelectionError,
        knowledge.KnowledgeError,
        secrets.SecretError,
        config_files.ConfigFileError,
        RenderError,
        catalog.UnknownHarnessError,
        skills.SkillError,
    ) as e:
        raise AgentStartError(str(e)) from None
    base = None
    if isinstance(spec.network, FilteredNetwork):
        base = compose.required_egress(launch, extra.egress)
    seen = compose.seen(launch=launch, scope=scope, addons=extra, knowledge=known, subject=subject)
    return spec, launch, base, seen


def _deliver(
    settings: Settings,
    delivery: secrets.Delivery,
    agent: AgentSpec,
    descriptor: HarnessDescriptor,
    *,
    account_token: str | None,
    provider_key: str | None,
    extra: addons.AddonLaunch,
) -> tuple[str | None, str | None]:
    """The launch's secrets as its sandbox gets them (A.3): phantoms its proxy swaps back towards
    their hosts (the login's, the provider's endpoints, the addon's), where they can be. Returns
    the account's token and the provider's key so; the addons' env is changed in place."""
    if account_token is not None:
        assert descriptor.login is not None and agent.account is not None
        loaded = accounts.get(settings.accounts_dir, agent.account).account
        assert loaded is not None and loaded.token is not None  # resolved: account_login
        name = secrets.name_of(loaded.token, accounts.token_path(agent.account))
        account_token = delivery.give(name, account_token, descriptor.login.hosts)
    if provider_key is not None:
        spec = agent.provider_spec
        assert spec is not None and spec.api_key is not None and agent.provider is not None
        hosts = [egress_target(url) for url in spec.endpoints.values()]
        name = secrets.name_of(spec.api_key, providers.key_path(agent.provider))
        provider_key = delivery.give(name, provider_key, hosts)
    for env, (name, hosts) in extra.secret_env.items():
        extra.env[env] = delivery.give(name, extra.env[env], hosts)
    return account_token, provider_key


def required_hosts(settings: Settings, spec: AgentSpec, agent: AgentRecord) -> list[RequiredHost]:
    """What a filtered agent reaches whatever its own entries say, and what requires it (A.3):
    its harness's hosts (account login, HTTP MCP servers, provider endpoint) and its addons'. Built
    from the same functions as its sandboxes' allow-list (render's egress, the addons' G4), without
    reading any secret. AgentStartError when the agent cannot start."""
    try:
        selected = addons.check(settings.bindings_dir, agent.addon_uses)
        descriptor = catalog.get(spec.harness).descriptor
        hosts = harness_hosts(descriptor, spec, addons.mcp_servers(selected))
    except (addons.SelectionError, catalog.UnknownHarnessError, RenderError) as e:
        raise AgentStartError(str(e)) from None
    found = [RequiredHost(host=host, by=by) for host, by in hosts]
    for s in selected:
        by = f"the {s.addon.name} tool" + (f": {s.binding.name}" if s.binding else "")
        found += [RequiredHost(host=h, by=by) for h in addons.egress([s])]
    return found


def account_login(
    settings: Settings,
    agent: AgentSpec,
    descriptor: HarnessDescriptor,
    store: secrets.SecretStore,
) -> str | None:
    """A token login's token, from where the account says (E2); None for a file login (found by
    `access.resolve`). AgentStartError when the account is not logged in or its token is not one
    its harness takes (`tokenPrefix`); SecretError when its token cannot be read."""
    login = descriptor.login
    if agent.account is None or login is None:
        return None
    if login.token:
        loaded = accounts.get(settings.accounts_dir, agent.account)
        ref = loaded.account.token if loaded.account else None
        if ref is None:
            raise AgentStartError(f"account '{agent.account}' is not logged in")
        token = secrets.resolve(ref, store)
        if (error := accounts.token_error(login, token)) is not None:
            raise AgentStartError(f"account '{agent.account}': {error}")
        return token
    if agent.account_login is None:
        raise AgentStartError(f"account '{agent.account}' is not logged in")
    return None


def read_login_file(agent: AgentSpec, descriptor: HarnessDescriptor) -> str | None:
    """The content of an account's login file its harness only reads (a read-only slot): given
    to the sandbox as a file (A.1 `files`), the account's own never mounted. AgentStartError when
    it cannot be read."""
    login = descriptor.login
    if agent.account_login is None or login is None or login.file is None:
        return None
    if not descriptor.state_slots[login.file].read_only:
        return None  # a kept file: the harness refreshes it
    try:
        return Path(agent.account_login).read_text()
    except OSError as e:
        raise AgentStartError(f"account '{agent.account}': its login cannot be read: {e}") from None


def provider_secret(agent: AgentSpec, store: secrets.SecretStore) -> str | None:
    """The key of the agent's provider, if it has one."""
    spec = agent.provider_spec
    return secrets.resolve(spec.api_key, store) if spec is not None and spec.api_key else None


def secret_values(settings: Settings, agent: AgentRecord, runs: RunsAs) -> list[str]:
    """Invariant 4: the values to redact, those of the account or provider it runs with and of
    its addons' bindings (G4). [] if they cannot be read (the agent cannot start without them
    either)."""
    store = secrets.SecretStore(settings.data_dir)
    try:
        resolved = agent_spec(settings, runs)
        own = []
        descriptor = catalog.get(resolved.harness).descriptor
        if token := account_login(settings, resolved, descriptor, store):
            own.append(token)
        if (key := provider_secret(resolved, store)) is not None:
            own.append(key)
    except (AgentStartError, secrets.SecretError, catalog.UnknownHarnessError):
        return []
    return own + addons.secret_values(settings.bindings_dir, agent.addon_uses, store)


async def harness_version(harness: str) -> str | None:
    """What the harness image installed (B.6), recorded on sessions. None when unknown."""
    try:
        h = catalog.get(harness)
    except catalog.UnknownHarnessError:
        return None
    latest = images.ref(h.descriptor.image, images.LATEST)
    return await asyncio.to_thread(runtime.version, latest, images.version_file(h))


def _ensure_state(settings: Settings, agent: AgentRecord, runs: RunsAs) -> None:
    assert runs.harness is not None  # an agent program's
    descriptor = catalog.get(runs.harness).descriptor
    agent_state.ensure(descriptor, agent_state.root(settings.data_dir, agent, runs))


def sessions_root(settings: Settings) -> Path:
    """Where sessions keep their folders (F.2): a folderless agent's session works in its own
    (`<id>/work/`)."""
    return settings.state_dir / "sessions"


def plan_drafts_root(settings: Settings) -> Path:
    """Where Handler keeps plan drafts (D.27): a plan builder's session works in its draft's
    (`<id>/draft/`)."""
    return settings.state_dir / "plan-drafts"


async def start(
    settings: Settings,
    agent: AgentRecord,
    runs: RunsAs,
    connection_id: str | None = None,
    session_state: str | None = None,
    *,
    folder: str | None = None,
    subject: HostFolder | None = None,
) -> StartedAgent:
    connection_id = connection_id or uuid.uuid4().hex[:8]
    spec, launch, base, seen = prepare(
        settings,
        agent,
        runs,
        connection_id,
        session_state=session_state,
        folder=folder,
        subject=subject,
    )
    assert runs.harness is not None  # an agent program's (prepare)
    await asyncio.to_thread(_require_images, spec, runs.harness)
    _ensure_state(settings, agent, runs)
    process = await sandbox_process.start_async(spec, line_limit=DEFAULT_MAX_MESSAGE_BYTES)
    model = model_host(settings, runs)
    return StartedAgent(connection_id, spec, launch, process, seen, base, model)


def paste_folder(settings: Settings, sandbox: str) -> Path:
    """Where a terminal's client puts what it pastes (D.16), read-only in the sandbox."""
    return settings.runtime_dir / "terminals" / sandbox


def start_terminal(
    settings: Settings, agent: AgentRecord, runs: RunsAs, terminal: TerminalStart
) -> tuple[StartedAgent, int]:
    """D.16: the harness's terminal program, in a sandbox that outlives handlerd
    (`sandbox_process.start_detached`); also returns the file of its launcher's output."""
    connection_id = uuid.uuid4().hex[:8]
    spec, launch, base, seen = prepare(settings, agent, runs, connection_id, terminal=terminal)
    assert runs.harness is not None  # an agent program's (prepare)
    _require_images(spec, runs.harness)
    _ensure_state(settings, agent, runs)
    paste_folder(settings, spec.name).mkdir(mode=0o755, parents=True)  # its parent is private
    process, output = sandbox_process.start_detached(spec)
    return StartedAgent(connection_id, spec, launch, process, seen, egress_base=base), output
