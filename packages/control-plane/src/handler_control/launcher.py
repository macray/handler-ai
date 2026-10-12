"""Starting one agent for one ACP connection: the whole composition, in order.

agent spec (E) ─► bindings (G), skills (D.17) ─► secrets + config files ─► render (B)
               ─► compose (B+G → A) ─► sandbox (A)

The agent spec is the harness of the model the connection runs with (one of the agent's), with
its account or provider resolved (access.py); the harness's own state is kept in agent_state.py.
"""

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path

from handler_contracts import (
    DEFAULT_MAX_MESSAGE_BYTES,
    AgentSpec,
    FilteredNetwork,
    HarnessDescriptor,
    HarnessLaunch,
    Mount,
    RequiredHost,
    SandboxSpec,
    TerminalStart,
    egress_target,
)
from handler_harness import RenderError, catalog, harness_hosts, images, render

from . import (
    access,
    accounts,
    addons,
    agent_state,
    caches,
    compose,
    config_files,
    contexts,
    display,
    folders,
    knowledge,
    providers,
    runtime,
    sandbox_process,
    secrets,
    skills,
)
from .agents import AgentRecord, CheckedSettings, RunsAs
from .settings import Settings


class AgentStartError(RuntimeError):
    """The connection cannot be served (bad account or provider, scope, secret, render…)."""


# agents with a network allow-list or a secret need it; handlerd builds it as it starts (D.4)
NETWORK_FILTER_MISSING = (
    "the network filter is not built yet: Settings → Images, "
    "or `handler image rebuild network-filter`"
)


def _require_network_filter(spec: SandboxSpec) -> None:
    if runtime.missing_proxy(spec):
        raise AgentStartError(NETWORK_FILTER_MISSING)


@dataclass
class StartedAgent:
    connection_id: str
    spec: SandboxSpec
    launch: HarnessLaunch
    process: object  # asyncio.subprocess.Process (a terminal's: subprocess.Popen)
    # filtered sandboxes: the required entries (harness, account or provider, addons), so the
    # agent's own can be changed live on top (A.4); None otherwise
    egress_base: list[str] | None = None


def agent_spec(settings: Settings, runs: RunsAs) -> AgentSpec:
    """One of the agent's models: its harness with its account or provider, resolved (E1)."""
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


def prepare(
    settings: Settings,
    agent: AgentRecord,
    runs: RunsAs,
    connection_id: str,
    *,
    session_state: str | None = None,
    terminal: TerminalStart | None = None,
    folder: str | None = None,
    subject: Mount | None = None,
) -> tuple[SandboxSpec, HarnessLaunch, list[str] | None]:
    """Everything up to the SandboxSpec — no side effects except reading files and secrets.
    Also returns the required allow-list entries (see StartedAgent.egress_base): those of `runs`,
    the agent's model it runs with, never of its other models.

    `session_state`: for a Session (F), its folder for the harness's per-session slot.
    `terminal`: the harness's own terminal program on the client's terminal (D.16), not ACP.
    `folder`: a folderless agent's session's own folder (D.18), where it works.
    `subject`: what a run of an agent with an interface works on, mounted read-only (D.18).
    """
    resolved = agent_spec(settings, runs)
    try:
        contexts.check(settings.sources, agent.context, runs.account, runs.provider)
    except contexts.ContextError as e:
        raise AgentStartError(str(e)) from None
    roots: tuple[str, ...] = ()
    if agent.scope is None:
        if folder is None:
            raise AgentStartError("a folderless agent works in sessions only (D.18)")
        roots = (str(sessions_root(settings)),)
    try:
        scope = compose.check_scope(folders.roots(settings), agent.scope or folder or "", roots)
        store = secrets.SecretStore(settings.data_dir)
        selected = addons.check(settings.bindings_dir, agent.bindings)
        extra = addons.resolve(selected, store)
        chosen = [*agent.skills, *agent.project_skills]  # its own, then its project's
        extra.skills.extend(skills.paths(settings.skills_dir, chosen))
        knowledge_root, _ = knowledge.root(settings)
        notes = knowledge.check(knowledge_root, agent.knowledge)
        provider_key = provider_secret(resolved, store)
        contents = config_files.resolve_all(resolved.files)
        descriptor = catalog.get(resolved.harness).descriptor
        account_token = account_login(settings, resolved, descriptor, store)
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
        screen = display.wayland() if agent.display else None  # only when asked for (A.6)
        launch = render(
            descriptor,
            resolved,
            scope,
            contents,
            session_state=session_state,
            state_root=state_root,
            provider_key=provider_key,
            account_token=account_token,
            skills=extra.skills,
            mcp_servers=extra.mcp_servers,
            terminal=terminal.args if terminal is not None else None,
            instructions=agent.instructions if terminal is not None else None,
            permission_mode=agent.permissions,
            caches=caches.mounts(settings, agent.caches, agent.project_id),
        )
        spec = compose.sandbox_spec(
            name=f"handler-{agent.id}-{connection_id}",
            launch=launch,
            scope=scope,
            network=agent.network,
            enforcement=agent.egress,
            confinement=agent.confinement,
            allow=agent.allow,
            labels={"handler.agent": agent.id, "handler.connection": connection_id}
            | ({"handler.terminal": "1"} if terminal is not None else {}),
            addons=extra,
            knowledge=knowledge.mounts(knowledge_root, notes),
            subject=subject,
            display=screen,
            terminal=terminal,
            injections=delivery.injections,
        )
    except (
        compose.ScopeError,
        compose.AddonConflictError,
        addons.SelectionError,
        display.DisplayError,
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
    return spec, launch, base


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


def required_hosts(
    settings: Settings, spec: AgentSpec, agent: CheckedSettings
) -> list[RequiredHost]:
    """What a filtered agent reaches whatever its own entries say, and what requires it (A.3):
    its harness's hosts (account login, HTTP MCP servers, provider endpoint) and its addons'. Built
    from the same functions as its sandboxes' allow-list (render's egress, the addons' G4), without
    reading any secret. AgentStartError when the agent cannot start."""
    try:
        selected = addons.check(settings.bindings_dir, agent.bindings)
        descriptor = catalog.get(spec.harness).descriptor
        hosts = harness_hosts(descriptor, spec, addons.mcp_servers(selected))
    except (addons.SelectionError, catalog.UnknownHarnessError, RenderError) as e:
        raise AgentStartError(str(e)) from None
    found = [RequiredHost(host=host, by=by) for host, by in hosts]
    for binding in selected:
        assert binding.addon is not None  # checked: a valid binding has its addon
        by = f"addon {binding.addon.name}: {binding.name}"
        found += [RequiredHost(host=h, by=by) for h in addons.egress([binding])]
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


def provider_secret(agent: AgentSpec, store: secrets.SecretStore) -> str | None:
    """The key of the agent's provider, if it has one."""
    spec = agent.provider_spec
    return secrets.resolve(spec.api_key, store) if spec is not None and spec.api_key else None


def secret_values(settings: Settings, agent: CheckedSettings, runs: RunsAs) -> list[str]:
    """Invariant 4: the values to redact, those of the account or provider it runs with and of
    its bindings (G4). [] if they cannot be read (the agent cannot start without them either)."""
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
    return own + addons.secret_values(settings.bindings_dir, agent.bindings, store)


async def harness_version(harness: str) -> str | None:
    """What the harness image installed (B.6), recorded on sessions. None when unknown."""
    try:
        h = catalog.get(harness)
    except catalog.UnknownHarnessError:
        return None
    latest = images.ref(h.descriptor.image, images.LATEST)
    return await asyncio.to_thread(runtime.version, latest, images.version_file(h))


def _ensure_state(settings: Settings, agent: AgentRecord, runs: RunsAs) -> None:
    descriptor = catalog.get(runs.harness).descriptor
    agent_state.ensure(descriptor, agent_state.root(settings.data_dir, agent, runs))


def sessions_root(settings: Settings) -> Path:
    """Where sessions keep their folders (F.2): a folderless agent's session works in its own
    (`<id>/work/`)."""
    return settings.state_dir / "sessions"


async def start(
    settings: Settings,
    agent: AgentRecord,
    runs: RunsAs,
    connection_id: str | None = None,
    session_state: str | None = None,
    *,
    folder: str | None = None,
    subject: Mount | None = None,
) -> StartedAgent:
    connection_id = connection_id or uuid.uuid4().hex[:8]
    spec, launch, base = prepare(
        settings,
        agent,
        runs,
        connection_id,
        session_state=session_state,
        folder=folder,
        subject=subject,
    )
    await asyncio.to_thread(_require_network_filter, spec)
    _ensure_state(settings, agent, runs)
    process = await sandbox_process.start_async(spec, line_limit=DEFAULT_MAX_MESSAGE_BYTES)
    return StartedAgent(connection_id, spec, launch, process, egress_base=base)


def start_terminal(
    settings: Settings, agent: AgentRecord, runs: RunsAs, terminal: TerminalStart
) -> tuple[StartedAgent, int]:
    """D.16: the harness's terminal program, in a sandbox that outlives handlerd
    (`sandbox_process.start_detached`); also returns the file of its launcher's output."""
    connection_id = uuid.uuid4().hex[:8]
    spec, launch, base = prepare(settings, agent, runs, connection_id, terminal=terminal)
    _require_network_filter(spec)
    _ensure_state(settings, agent, runs)
    process, output = sandbox_process.start_detached(spec)
    return StartedAgent(connection_id, spec, launch, process, egress_base=base), output
