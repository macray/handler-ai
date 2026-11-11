"""`render` — contract B.3: (descriptor, agent, secrets) → HarnessLaunch.

Pure function (B1): no container, network or filesystem access. It only translates the
harness-neutral agent (its account or provider, model) into what this harness needs, expressed
as intent (the files group's needs, env, egress, session defaults), never as sandbox
implementation details (B2).

Read top-down: `render` calls one small function per concern.
"""

import json
from dataclasses import dataclass, field

from handler_contracts import (
    HARNESS_LAUNCH_API_VERSION,
    AgentSpec,
    CacheDeclaration,
    CacheFolder,
    File,
    HandlerTool,
    HarnessDescriptor,
    HarnessLaunch,
    HostFolder,
    HttpMcpServer,
    KeptFile,
    LoginRecipe,
    McpServer,
    NetworkMode,
    NeutralConfig,
    PermissionMode,
    SessionDefaults,
    StateSlot,
    StdioMcpServer,
    egress_target,
    mcp_transport,
)

from . import images, providers
from .catalog import DATA

# Restores the sandbox's environment for the MCP servers of a harness with `mcpEnv = "sandbox"`
# (B.1): given to its sandboxes as a file, so any toolbox (with python3) works. Read once here, so
# `render` itself reads nothing.
SANDBOX_ENV = "/opt/handler/bin/handler-sandbox-env"
SANDBOX_ENV_SCRIPT = (DATA / "handler-sandbox-env").read_text()


# What an agent whose network is filtered is told before its first turn (A.3): the filter's
# refusal says it too (its 403), but an agent told before does not guess a proxy problem.
FILTERED_NETWORK = (
    "Your network goes through Handler's network filter: only allowed hosts answer. When a host "
    "is refused: if your task cannot be done well without it, ask the user to allow it, naming "
    "the host and port, and end your turn; if you can do the task well without it, go on, and "
    "say at the end which host was refused and what you did instead. Never try to get around "
    "the filter (other proxies, mirrors of the same service, other ports)."
)


def starting_instructions(instructions: str | None, network: NetworkMode) -> str | None:
    """The instructions the agent starts with: its own, then, when its network is filtered,
    what that means for it (a blank line between them). None when there are none."""
    told = [instructions] if instructions else []
    if network == "filtered":
        told.append(FILTERED_NETWORK)
    return "\n\n".join(told) or None


class RenderError(ValueError):
    """The agent cannot be expressed for this harness (E1, B5)."""


def render(
    descriptor: HarnessDescriptor,
    agent: AgentSpec,
    files: dict[str, str] | None = None,
    *,
    permission_mode: PermissionMode,
    session_state: str | None = None,
    state_root: str | None = None,
    provider_key: str | None = None,
    account_token: str | None = None,
    login_file: str | None = None,
    skills: list[str] | None = None,
    mcp_servers: list[McpServer] | None = None,
    terminal: list[str] | None = None,
    instructions: str | None = None,
    network: NetworkMode = "none",
    caches: list[tuple[CacheDeclaration, str]] | None = None,
) -> HarnessLaunch:
    """Return the launch intent.

    `account_token` (a token login's), `provider_key` and `files` arrive resolved (values,
    contents) from the control plane; an account's login file is `agent.account_login`, and
    `login_file` its content when the harness only reads it (a read-only slot: given as a file).
    `session_state`: a Session's own folder, bound to the harness's per-session slot (F.2).
    `state_root`: the folder handler keeps for the agent's own state (history, settings): each of
    those slots is bound to a folder of that name in it. None: not bound.
    `skills` (skill folders) and `mcp_servers`: the agent's and its addons' (G4, D.17).
    `terminal`: run the harness's own terminal program instead of its ACP adapter (D.16), with
    these arguments after the ones its settings give it. `instructions`: the agent's, for that
    terminal program (an ACP session gets them with its first prompt instead, C.4 P9 and F.3),
    with what a `filtered` `network` means for it (`starting_instructions`), when the terminal
    program can take instructions.
    `permission_mode`: the agent's starting mode (D.8), one the descriptor maps.
    `caches`: each cache the agent gets (the toolbox's, its addons') with its host folder, as the
    agent's project shares them.
    """
    if agent.harness != descriptor.name:
        raise RenderError(f"agent is for harness '{agent.harness}', not '{descriptor.name}'")

    state = state_needs(descriptor, agent, session_state, state_root, login_file)
    provided = express_provider(descriptor, agent, provider_key)
    login = descriptor.login if agent.account else None
    token_env = {login.token: account_token} if login and login.token and account_token else {}
    env = dict(descriptor.env or {}) | token_env | provided.env | plan_env(login, agent)
    mode = descriptor.permissions.get(permission_mode)  # decision 4: ACP, env fallback
    if mode is None:
        raise RenderError(
            f"harness '{descriptor.name}' has no permission mode '{permission_mode}' "
            f"(it offers: {', '.join(descriptor.permissions)})"
        )
    env |= mode.env or {}
    session = SessionDefaults(mode_id=mode.session_mode)
    config = agent.config
    if agent.provider_spec is not None and config is not None:
        # the provider's model is written in the harness's configuration, not chosen over ACP
        config = config.model_copy(update={"model": None})
    secret_env = [*token_env, *provided.secret_env]
    session, config_env = apply_neutral_config(
        descriptor, config, session, mcp_servers or [], secret_env=secret_env
    )
    egress = [host for host, _ in harness_hosts(descriptor, agent, mcp_servers or [])]
    env |= config_env

    argv, extra_files = list(descriptor.acp_command), mcp_config_file(descriptor, session)
    if terminal is not None:
        argv, extra_files, terminal_env = terminal_command(
            descriptor, permission_mode, session, terminal, instructions, network=network
        )
        env |= terminal_env
        session = SessionDefaults()  # nothing goes over ACP

    launch = HarnessLaunch(
        api_version=HARNESS_LAUNCH_API_VERSION,
        image=images.ref(descriptor.image, images.LATEST),  # B.6
        argv=argv,
        home=descriptor.home,
        env=env,
        folders=state.folders,
        skills=skill_folders(descriptor, skills or []),
        caches=cache_folders(descriptor, caches or []),
        kept_files=state.kept_files,
        files=config_files(descriptor, agent, files or {}, provided.files)
        + extra_files
        + state.files,
        tools=sandbox_env_tool(descriptor),
        egress=egress,
        session_defaults=session if session.model_dump(exclude_none=True) else None,
    )
    return launch


# ── one function per concern ────────────────────────────────────────────


def harness_hosts(
    descriptor: HarnessDescriptor, agent: AgentSpec, mcp_servers: list[McpServer]
) -> list[tuple[str, str]]:
    """The hosts the agent needs on this harness (A.3), once each, with what requires them: its
    account's login hosts, its HTTP MCP servers, its provider's endpoint. The launch's egress is
    these hosts; the control plane shows them with their reason (Agent.requiredHosts)."""
    found: dict[str, str] = {}
    login = descriptor.login if agent.account else None
    for host in login.hosts if login else []:
        found.setdefault(host, f"account {agent.account}")
    for server in mcp_servers:
        if not isinstance(server, HttpMcpServer):
            continue
        try:
            target = egress_target(server.url)  # host:port, 443/80 by default (A.3)
        except ValueError as e:
            raise RenderError(f"MCP server '{server.name}': {e}") from None
        found.setdefault(target, f"MCP server {server.name}")
    if agent.provider_spec is not None:
        try:
            host = providers.egress(descriptor, agent.provider_spec)
        except providers.ProviderError as e:
            raise RenderError(str(e)) from None
        found.setdefault(host, f"provider {agent.provider}")
    return list(found.items())


@dataclass
class StateNeeds:
    folders: list[HostFolder] = field(default_factory=list)
    kept_files: list[KeptFile] = field(default_factory=list)
    files: list[File] = field(default_factory=list)


def state_needs(
    descriptor: HarnessDescriptor,
    agent: AgentSpec,
    session_state: str | None = None,
    state_root: str | None = None,
    login_file: str | None = None,
) -> StateNeeds:
    """Required slots must be bound. Three kinds of slot: the account's login file
    (`agent.account_login`, kept by handler), the session history (the daemon's, F.2) and the rest,
    the agent's own state: its folder in `state_root`. A folder slot is a folder; a file slot a
    kept file, or, when the harness only reads it (an account's login), a file of its content
    (`login_file`)."""
    found = StateNeeds()
    for name, slot in descriptor.state_slots.items():
        source = _state_source(
            descriptor, name, slot, agent, session_state=session_state, state_root=state_root
        )
        if source is None:
            continue
        target = expand_home(slot.target, descriptor.home)
        if slot.kind == "dir":
            found.folders.append(
                HostFolder(source=source, target=target, writable=not slot.read_only)
            )
        elif not slot.read_only:
            found.kept_files.append(KeptFile(source=source, target=target))
        elif login_file is None:
            raise RenderError(f"state slot '{name}': the login's content is not given")
        else:
            found.files.append(File(target=target, content=login_file, mode="0400"))
    return found


def _state_source(
    descriptor: HarnessDescriptor,
    name: str,
    slot: StateSlot,
    agent: AgentSpec,
    *,
    session_state: str | None,
    state_root: str | None,
) -> str | None:
    """The host path bound to state slot `name`, None when it is not bound."""
    if slot.per_session:  # bound by the daemon to a Session's own folder (F.2)
        return session_state or None
    if slot.credential:  # the account's login
        login = descriptor.login
        return agent.account_login if login and login.file == name and agent.account else None
    if state_root is not None:  # a file in a folder of its own (A.1: a writable file mount)
        return f"{state_root}/{name}/{name}" if slot.kind == "file" else f"{state_root}/{name}"
    if slot.required:
        raise RenderError(f"required state slot '{name}' is not bound")
    return None


def plan_env(login: LoginRecipe | None, agent: AgentSpec) -> dict[str, str]:
    """The account's plan, where the harness reads it (its login's `planEnv`)."""
    if login is None or login.plan_env is None or agent.account_plan is None:
        return {}
    return {login.plan_env: agent.account_plan}


def express_provider(
    descriptor: HarnessDescriptor, agent: AgentSpec, key: str | None
) -> providers.Expressed:
    """The agent's provider written for the harness (env, config files); nothing without one."""
    if agent.provider_spec is None:
        return providers.Expressed()
    try:
        return providers.express(
            descriptor,
            agent.provider_spec,
            agent.config.model if agent.config else None,
            key,
            has_instructions="instructions_md" in (agent.files or {}),
        )
    except providers.ProviderError as e:
        raise RenderError(f"provider '{agent.provider}': {e}") from None


def config_files(
    descriptor: HarnessDescriptor,
    agent: AgentSpec,
    contents: dict[str, str],
    provided: dict[str, str] | None = None,
) -> list[File]:
    """Config file slots (E1 + required) → files at the harness's expected paths, read-only, or
    writable when the harness rewrites it (`seed`). A slot is filled by the provider's `files`
    for this harness or written from the provider, not both."""
    provided = provided or {}
    filled = (agent.files or {}).keys() | provided.keys()
    for unknown in filled - descriptor.config_files.keys():
        raise RenderError(f"config file '{unknown}' is not declared by harness '{descriptor.name}'")
    if clash := sorted(provided.keys() & contents.keys()):
        raise RenderError(
            f"config file {', '.join(clash)}: written from provider '{agent.provider}', so the "
            "provider's [files] cannot fill it too"
        )
    contents = contents | provided
    generated = []
    for name, slot in descriptor.config_files.items():
        if name in contents:
            target = expand_home(slot.target, descriptor.home)
            mode = "0600" if slot.seed else "0444"
            generated.append(
                File(target=target, content=contents[name], mode=mode, writable=slot.seed)
            )
        elif slot.required:
            raise RenderError(f"required config file '{name}' is not filled (provider [files])")
    return generated


def cache_folders(
    descriptor: HarnessDescriptor, caches: list[tuple[CacheDeclaration, str]]
) -> list[CacheFolder]:
    """Caches are harness-independent; only their target is placed under this harness's home."""
    found = []
    for cache, source in caches:
        target = expand_home(cache.target, descriptor.home)
        path = f"{target}/{cache.bin}" if cache.bin else None
        found.append(CacheFolder(source=source, target=target, path=path))
    return found


def skill_folders(descriptor: HarnessDescriptor, skills: list[str]) -> list[HostFolder]:
    """Each skill folder, read-only, in the harness's skills folder, under its own name (so
    skills from different places combine)."""
    if not skills:
        return []
    if descriptor.skills_dir is None:
        raise RenderError(f"harness '{descriptor.name}' does not support skills")
    root = expand_home(descriptor.skills_dir, descriptor.home)
    by_name: dict[str, str] = {}
    for source in skills:
        name = source.rsplit("/", 1)[-1]
        if name in by_name:
            raise RenderError(f"two skills are named '{name}': {by_name[name]} and {source}")
        by_name[name] = source
    return [
        HostFolder(source=source, target=f"{root}/{name}", writable=False)
        for name, source in by_name.items()
    ]


def apply_neutral_config(
    descriptor: HarnessDescriptor,
    config: NeutralConfig | None,
    session: SessionDefaults,
    servers: list[McpServer],
    *,
    secret_env: list[str] | None = None,
) -> tuple[SessionDefaults, dict[str, str]]:
    """Neutral config and MCP servers → (session defaults, env). B5: unsupported fields are
    errors."""
    env: dict[str, str] = {}
    config = config or NeutralConfig()
    if config.model is not None:
        if descriptor.model_option is None:
            raise RenderError(f"harness '{descriptor.name}' cannot select a model")
        options = {descriptor.model_option: config.model}
        session = session.model_copy(update={"config_options": options})
    if servers:
        session = session.model_copy(
            update={"mcp_servers": mcp_servers(descriptor, servers, secret_env=secret_env)}
        )
    if not config.account_connectors and descriptor.account_connectors:
        env |= descriptor.account_connectors.off_env
    return session, env


def mcp_servers(
    descriptor: HarnessDescriptor,
    servers: list[McpServer],
    *,
    secret_env: list[str] | None = None,
) -> list[McpServer]:
    """The addons' MCP servers, passed to every session by the control plane (P8). B5: a
    transport the harness does not accept is an error.

    A harness with `mcpEnv = "sandbox"` (it starts stdio servers with a reduced environment, or
    with its own secrets) gets them wrapped with handler-sandbox-env (`sandbox_env_tool`):
    every server then sees the sandbox's environment (proxy, display, its addon's settings and
    secrets) whatever the harness, without the harness's own secrets (`secret_env`: the account's
    token and the provider's key)."""
    names = [s.name for s in servers]
    if duplicates := sorted({n for n in names if names.count(n) > 1}):
        raise RenderError(f"two MCP servers are named {', '.join(duplicates)}")
    for server in servers:
        if (transport := mcp_transport(server)) not in descriptor.mcp_transports:
            accepted = ", ".join(descriptor.mcp_transports) or "none"
            raise RenderError(
                f"harness '{descriptor.name}' does not accept {transport} MCP servers "
                f"('{server.name}'; it accepts: {accepted})"
            )
    if descriptor.mcp_env == "sandbox":
        drop = [a for name in secret_env or [] for a in ("--drop", name)]
        servers = [
            s.model_copy(update={"command": SANDBOX_ENV, "args": [*drop, "--", s.command, *s.args]})
            if isinstance(s, StdioMcpServer)
            else s
            for s in servers
        ]
    return servers


def sandbox_env_tool(descriptor: HarnessDescriptor) -> list[HandlerTool]:
    """`handler-sandbox-env`, for a harness whose MCP servers `mcp_servers` wraps with it."""
    if descriptor.mcp_env != "sandbox":
        return []
    return [HandlerTool(target=SANDBOX_ENV, content=SANDBOX_ENV_SCRIPT)]


def mcp_config_file(descriptor: HarnessDescriptor, session: SessionDefaults) -> list[File]:
    """For a harness that does not take MCP servers from session/new (`mcpConfigFile`): the same
    servers, in the common mcp.json format, where it reads them. Their tools are registered as
    tools of their own (`directTools`, pi-mcp-adapter), as the other harnesses do; the adapter's
    extras beyond its `mcp` proxy tool are turned off. Values are written as they are (the
    adapter expands `${VAR}` in them)."""
    if descriptor.mcp_config_file is None or not session.mcp_servers:
        return []
    entries: dict[str, dict[str, object]] = {}
    for server in session.mcp_servers:
        if isinstance(server, StdioMcpServer):
            entry: dict[str, object] = {"command": server.command, "args": server.args}
            if server.env:
                entry["env"] = {e.name: e.value for e in server.env}
        else:  # http, with an SSE fallback
            entry = {"url": server.url}
            if server.headers:
                entry["headers"] = {h.name: h.value for h in server.headers}
        entries[server.name] = entry | {"directTools": True}
    # no installing servers from the model's `mcp` tool, no `mcpScript` JavaScript tool
    settings = {"allowInstall": False, "scriptMode": False}
    content = json.dumps({"settings": settings, "mcpServers": entries}, indent=2) + "\n"
    target = expand_home(descriptor.mcp_config_file, descriptor.home)
    return [File(target=target, content=content, mode="0444")]


TERMINAL_MCP_CONFIG = "~/.handler/terminal-mcp.json"


def terminal_command(
    descriptor: HarnessDescriptor,
    permission_mode: PermissionMode,
    session: SessionDefaults,
    args: list[str],
    instructions: str | None = None,
    *,
    network: NetworkMode = "none",
) -> tuple[list[str], list[File], dict[str, str]]:
    """D.16: the harness's terminal program, given as flags or env vars what an ACP session gets
    as session defaults (permission mode, model, MCP servers) and the agent's instructions, then
    `args`; the file of MCP servers (a generated file) and the env vars. A terminal program
    that cannot take instructions fails with the agent's, and goes without the network's."""
    term = descriptor.terminal
    if term is None:
        raise RenderError(f"harness '{descriptor.name}' has no terminal program")
    argv, files, env = [*term.command, *term.permissions[permission_mode]], [], {}
    model = (session.config_options or {}).get(descriptor.model_option or "")
    if model is not None:
        if term.model_flag is not None:
            argv += [term.model_flag, model]
        elif term.model_env is not None:
            env[term.model_env] = model
        else:
            raise RenderError(f"the terminal of harness '{descriptor.name}' cannot select a model")
    if session.mcp_servers:
        if term.mcp_config_flag is not None:
            target = expand_home(TERMINAL_MCP_CONFIG, descriptor.home)
            entries = _mcp_entries(session.mcp_servers)
            content = json.dumps({"mcpServers": entries}, indent=2) + "\n"
            files.append(File(target=target, content=content, mode="0444"))
            argv += [term.mcp_config_flag, target]
        elif term.mcp_servers_env is not None:
            env[term.mcp_servers_env] = json.dumps(_vibe_mcp_servers(session.mcp_servers))
        else:
            raise RenderError(f"the terminal of harness '{descriptor.name}' cannot get MCP servers")
    if instructions and term.instructions_flag is None:
        raise RenderError(
            f"the terminal of harness '{descriptor.name}' cannot take the agent's "
            "instructions: use `handler run`, or remove the instructions from the agent"
        )
    told = starting_instructions(instructions, network)
    if told and term.instructions_flag is not None:
        argv += [term.instructions_flag, told]
    return [*argv, *args], files, env


def _mcp_entries(servers: list[McpServer]) -> dict[str, dict[str, object]]:
    """MCP servers in Claude Code's `--mcp-config` format."""
    entries: dict[str, dict[str, object]] = {}
    for server in servers:
        entry: dict[str, object]
        if isinstance(server, StdioMcpServer):
            entry = {"type": "stdio", "command": server.command, "args": server.args}
            if server.env:
                entry["env"] = {e.name: e.value for e in server.env}
        else:
            entry = {"type": mcp_transport(server), "url": server.url}
            if server.headers:
                entry["headers"] = {h.name: h.value for h in server.headers}
        entries[server.name] = entry
    return entries


def _vibe_mcp_servers(servers: list[McpServer]) -> list[dict[str, object]]:
    """MCP servers in Vibe's `mcp_servers` format (its descriptor takes stdio ones only)."""
    entries: list[dict[str, object]] = []
    for server in servers:
        if not isinstance(server, StdioMcpServer):
            raise RenderError(f"MCP server '{server.name}': Vibe's terminal takes stdio ones only")
        env = {e.name: e.value for e in server.env}
        entry = {"name": server.name, "transport": "stdio", "command": server.command}
        entries.append(entry | {"args": server.args, "env": env})
    return entries


# ── helpers ─────────────────────────────────────────────────────────────


def expand_home(path: str, home: str) -> str:
    if path == "~":
        return home
    if path.startswith("~/"):
        return f"{home}/{path[2:]}"
    return path
