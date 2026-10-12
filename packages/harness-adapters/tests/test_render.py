"""Unit tests of `render` (contract B.3) against the real descriptors in harnesses/."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from handler_contracts import AgentSpec, McpServer, StdioMcpServer
from handler_harness import RenderError, catalog, harness_hosts
from handler_harness import render as render_launch
from handler_harness.render import SANDBOX_ENV, SANDBOX_ENV_SCRIPT

FIXTURES = Path(__file__).parent / "fixtures"
SCOPE = "/home/you/code/project"
STATE_ROOT = "/data/agent-state/a1b2c3"
CARGO = {"~/.cargo": "/home/you/.cache/handler-ai/cargo"}


def agent(**overrides: Any) -> AgentSpec:
    """The reference agent: Claude Code on the account claude-perso, model opus."""
    base = {"harness": "claude-code", "account": "claude-perso", "config": {"model": "opus"}}
    return AgentSpec.model_validate(base | overrides)


def render(*args: Any, **kwargs: Any) -> Any:
    """`render` for an agent in bypass mode, unless the test says otherwise."""
    options: dict[str, Any] = {"permission_mode": "bypass"} | kwargs
    return render_launch(*args, **options)


def servers(*docs: dict[str, Any]) -> list[McpServer]:
    """MCP servers as an agent's addons give them to `render`."""
    return TypeAdapter(list[McpServer]).validate_python(list(docs))


def claude() -> Any:
    return catalog.get("claude-code").descriptor


def test_all_descriptors_load() -> None:
    names = [h.name for h in catalog.all_harnesses()]
    assert names == ["claude-code", "codex", "pi", "vibe"]


def test_golden_claude_perso() -> None:
    """The full HarnessLaunch for the reference agent, with the state handler keeps for it and an
    addon's MCP server. Update the fixture deliberately."""
    launch = render(
        claude(), agent(), SCOPE, state_root=STATE_ROOT, mcp_servers=servers(DOCS), caches=CARGO
    )
    actual = json.loads(launch.model_dump_json(by_alias=True, exclude_none=True))
    expected = json.loads((FIXTURES / "claude-perso.launch.json").read_text())
    assert actual == expected


def test_caches_are_mounted_in_the_harness_home() -> None:
    launch = render(claude(), agent(), SCOPE, caches=CARGO | {"/opt/x": "/h/x"})
    caches = {m.target: (m.source, m.read_only) for m in launch.mounts if m.kind == "cache"}
    assert caches == {
        "/home/agent/.cargo": ("/home/you/.cache/handler-ai/cargo", False),
        "/opt/x": ("/h/x", False),
    }
    assert not [m for m in render(claude(), agent(), SCOPE).mounts if m.kind == "cache"]


def test_permission_mode_is_an_acp_session_mode() -> None:
    launch = render(claude(), agent(), SCOPE)
    assert launch.session_defaults is not None
    assert launch.session_defaults.mode_id == "bypassPermissions"
    vibe_agent = agent(harness="vibe", config={})
    vibe = render(catalog.get("vibe").descriptor, vibe_agent, SCOPE)
    assert vibe.session_defaults is not None and vibe.session_defaults.mode_id == "auto-approve"


def test_model_goes_through_acp_config_option() -> None:
    launch = render(claude(), agent(), SCOPE)
    assert launch.session_defaults is not None
    assert launch.session_defaults.config_options == {"model": "opus"}
    assert "ANTHROPIC_MODEL" not in launch.env


def test_the_account_s_plan_is_told_to_the_harness() -> None:
    """Claude Code cannot learn it from a token login (B.1 `login.planEnv`)."""
    launch = render(claude(), agent(account_plan="max"), SCOPE)
    assert launch.env["CLAUDE_CODE_SUBSCRIPTION_TYPE"] == "max"
    unset = render(claude(), agent(), SCOPE)
    assert "CLAUDE_CODE_SUBSCRIPTION_TYPE" not in unset.env


def test_account_connectors_off_by_default() -> None:
    launch = render(claude(), agent(), SCOPE)
    assert launch.env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
    on = render(claude(), agent(config={"accountConnectors": True}), SCOPE)
    assert "ENABLE_CLAUDEAI_MCP_SERVERS" not in on.env


DOCS = {"type": "http", "name": "docs", "url": "https://mcp.example.org/sse"}


def test_http_mcp_server_host_added_to_egress() -> None:
    launch = render(claude(), agent(), SCOPE, mcp_servers=servers(DOCS))
    assert "mcp.example.org:443" in launch.egress  # https: port 443 (the URL's scheme)
    assert launch.egress[:2] == ["api.anthropic.com:443", "platform.claude.com:443"]


def test_each_host_says_what_requires_it() -> None:
    """What clients are shown (Agent.requiredHosts): the launch's egress, with its reasons."""
    hosts = harness_hosts(claude(), agent(), servers(DOCS))
    assert hosts == [
        ("api.anthropic.com:443", "account claude-perso"),
        ("platform.claude.com:443", "account claude-perso"),
        ("mcp.example.org:443", "MCP server docs"),
    ]
    launch = render(claude(), agent(), SCOPE, mcp_servers=servers(DOCS))
    assert launch.egress == [host for host, _ in hosts]


STDIO = {"name": "browser", "command": "playwright-mcp", "args": ["--isolated"]}
STDIO_SERVER = StdioMcpServer.model_validate(STDIO)


def test_mcp_servers_go_to_every_session() -> None:
    launch = render(claude(), agent(), SCOPE, mcp_servers=servers(STDIO))
    assert launch.session_defaults is not None
    given = launch.session_defaults.mcp_servers or []
    assert [s.model_dump(exclude_defaults=True) for s in given] == [STDIO]


def test_mcp_transport_the_harness_does_not_accept_is_refused() -> None:
    """B5: never silently dropped."""
    no_mcp = claude().model_copy(update={"mcp_transports": []})
    with pytest.raises(RenderError, match="does not accept stdio MCP servers"):
        render(no_mcp, agent(), SCOPE, mcp_servers=servers(STDIO))
    vibe_agent = agent(harness="vibe", config={})
    with pytest.raises(RenderError, match="does not accept http MCP servers"):
        render(catalog.get("vibe").descriptor, vibe_agent, SCOPE, mcp_servers=servers(DOCS))


LOCAL = {
    "apiVersion": "handler.provider/v1",
    "endpoints": {"openai-chat": "http://127.0.0.1:3000/v1"},
    "models": [{"id": "qwen"}],
}


def test_clean_env_harness_gets_its_stdio_servers_wrapped() -> None:
    """vibe starts MCP servers with HOME and PATH only: in a container, handler-sandbox-env gives
    them the sandbox's environment back, without vibe's own key (here, its provider's)."""
    vibe_agent = agent(
        harness="vibe",
        account=None,
        provider="local",
        providerSpec=LOCAL,
        config={},
    )
    vibe = catalog.get("vibe").descriptor
    launch = render(vibe, vibe_agent, SCOPE, provider_key="k", mcp_servers=servers(STDIO))
    assert launch.session_defaults is not None
    [server] = launch.session_defaults.mcp_servers or []
    assert server.model_dump(exclude_defaults=True) == {
        "name": "browser",
        "command": SANDBOX_ENV,
        "args": ["--drop", "MISTRAL_API_KEY", "--", "playwright-mcp", "--isolated"],
    }
    claude_launch = render(claude(), agent(), SCOPE, mcp_servers=servers(STDIO))
    assert claude_launch.session_defaults is not None
    assert claude_launch.session_defaults.mcp_servers == [STDIO_SERVER]  # it inherits


def test_mcp_config_file_harness_gets_its_servers_in_a_file() -> None:
    """pi-acp ignores session/new's MCP servers: render writes them where pi-mcp-adapter reads
    them, wrapped (pi gives them its provider keys; on an account, it has none in its env)."""
    http = {
        "type": "http",
        "name": "docs",
        "url": "https://mcp.example.org/x",
        "headers": [{"name": "X-Token", "value": "t"}],
    }
    stdio = STDIO | {"env": [{"name": "A", "value": "1"}]}
    pi_agent = agent(harness="pi", config={})
    pi = catalog.get("pi").descriptor
    launch = render(pi, pi_agent, SCOPE, mcp_servers=servers(stdio, http))
    [file] = [f for f in launch.files if f.target == "/home/agent/.config/mcp/mcp.json"]
    assert json.loads(file.content) == {
        "settings": {"allowInstall": False, "scriptMode": False},
        "mcpServers": {
            "browser": {
                "command": SANDBOX_ENV,
                "args": ["--", "playwright-mcp", "--isolated"],
                "env": {"A": "1"},
                "directTools": True,
            },
            "docs": {
                "url": "https://mcp.example.org/x",
                "headers": {"X-Token": "t"},
                "directTools": True,
            },
        },
    }
    assert file.mode == "0444" and not file.seed
    assert "mcp.example.org:443" in launch.egress
    none = render(pi, pi_agent, SCOPE)
    assert [f.target for f in none.files] == [SANDBOX_ENV]  # no mcp.json without servers
    claude_launch = render(claude(), agent(), SCOPE, mcp_servers=servers(STDIO))
    assert claude_launch.files == []  # it takes them from session/new


def test_mcp_server_names_are_unique() -> None:
    twice = servers(STDIO, STDIO | {"command": "other"})
    with pytest.raises(RenderError, match="two MCP servers are named browser"):
        render(claude(), agent(), SCOPE, mcp_servers=twice)


def test_the_accounts_token_only_in_env() -> None:
    launch = render(claude(), agent(), SCOPE, account_token="sk-test")
    assert launch.env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-test"
    assert "sk-test" not in " ".join(launch.argv)
    on_provider = agent(
        account=None,
        provider="local",
        providerSpec=LOCAL | {"endpoints": {"anthropic": "http://127.0.0.1:3000"}},
        config={},
    )
    launch = render(claude(), on_provider, SCOPE, account_token="sk-test")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in launch.env  # only an account's


def test_render_errors() -> None:
    with pytest.raises(RenderError, match="not 'claude-code'"):
        render(claude(), agent(harness="vibe"), SCOPE)
    with pytest.raises(RenderError, match="two skills are named 'review'"):
        render(claude(), agent(), SCOPE, skills=["/a/review", "/b/review"])


def test_unmapped_permission_mode_is_refused() -> None:
    """pi never asks: an agent wanting "ask" must fail, not silently run in bypass."""
    pi = catalog.get("pi").descriptor
    assert list(pi.permissions) == ["bypass"]
    p = agent(harness="pi", config={})
    with pytest.raises(RenderError, match="no permission mode 'ask'"):
        render(pi, p, SCOPE, permission_mode="ask")
    launch = render(pi, agent(harness="pi", config={}), SCOPE)
    assert launch.session_defaults is None  # bypass = {}: pi's default


def test_skills_are_mounted_read_only_under_their_name() -> None:
    skills = ["/home/you/skills/podman", "/opt/team-skills/review"]
    launch = render(claude(), agent(), SCOPE, skills=skills)
    mounted = {m.target: (m.source, m.read_only) for m in launch.mounts if m.kind == "config"}
    assert mounted == {
        "/home/agent/.claude/skills/podman": ("/home/you/skills/podman", True),
        "/home/agent/.claude/skills/review": ("/opt/team-skills/review", True),
    }


def test_config_file_becomes_a_seeded_file_for_vibe() -> None:
    vibe = catalog.get("vibe").descriptor
    p = agent(harness="vibe", config={}, files={"config_toml": {"content": "x = 1"}})
    launch = render(vibe, p, SCOPE, {"config_toml": "x = 1"})
    [f] = [f for f in launch.files if f.target != SANDBOX_ENV]
    assert (f.target, f.content, f.seed, f.mode) == (
        "/home/agent/.vibe/config.toml",
        "x = 1",
        True,
        "0600",
    )
    assert "/home/agent/.vibe" in launch.writable_paths


def test_sandbox_env_comes_with_the_harnesses_that_use_it() -> None:
    """mcpEnv = "sandbox" (B.1): the wrapper is in the launch, not in the toolbox."""
    vibe = render(catalog.get("vibe").descriptor, agent(harness="vibe", config={}), SCOPE)
    [f] = [f for f in vibe.files if f.target == SANDBOX_ENV]
    assert (f.content, f.mode, f.seed) == (SANDBOX_ENV_SCRIPT, "0755", False)
    claude = render(catalog.get("claude-code").descriptor, agent(), SCOPE)
    assert SANDBOX_ENV not in [f.target for f in claude.files]


def test_unknown_config_file_is_an_error() -> None:
    with pytest.raises(RenderError, match="config file 'nope'"):
        render(claude(), agent(files={"nope": {"content": "x"}}), SCOPE, {"nope": "x"})


def test_per_session_slot_is_bound_by_the_daemon_only() -> None:
    vibe = catalog.get("vibe").descriptor
    p = agent(harness="vibe", config={})
    launch = render(vibe, p, SCOPE)
    assert not [m for m in launch.mounts if m.kind == "state"]
    launch = render(vibe, p, SCOPE, session_state="/state/sessions/s_1/agent")
    state = [(m.source, m.target, m.read_only) for m in launch.mounts if m.kind == "state"]
    assert state == [("/state/sessions/s_1/agent", "/home/agent/.vibe/logs/session", False)]


# ── state: the agent's own, the account's login, the daemon's sessions ──


def test_the_agent_s_own_state_is_kept_by_handler() -> None:
    p = agent()
    launch = render(claude(), p, SCOPE, state_root="/data/agent-state/work")
    state = {m.target: m.source for m in launch.mounts if m.kind == "state"}
    assert state == {
        "/home/agent/.claude": "/data/agent-state/work/config_dir",
        "/home/agent/.claude.json": "/data/agent-state/work/config_json",
    }
    launch = render(claude(), p, SCOPE)  # no state root (handler-harness render): nothing bound
    assert not [m for m in launch.mounts if m.kind == "state"]


def test_the_accounts_login_file_is_bound_writable() -> None:
    codex = catalog.get("codex").descriptor
    kept = "/data/accounts/chatgpt/credential"
    p = agent(harness="codex", config={}, accountLogin=kept)
    launch = render(codex, p, SCOPE, state_root="/data/agent-state/work")
    state = {m.target: (m.source, m.read_only) for m in launch.mounts if m.kind == "state"}
    assert state == {"/home/agent/.codex/auth.json": (kept, False)}
    vibe = catalog.get("vibe").descriptor  # its login file is read-only
    p = agent(harness="vibe", config={}, accountLogin="/data/accounts/m/credential")
    launch = render(vibe, p, SCOPE)
    state = {m.target: (m.source, m.read_only) for m in launch.mounts if m.kind == "state"}
    assert state == {"/home/agent/.vibe/.env": ("/data/accounts/m/credential", True)}
    assert launch.egress[0] == "api.mistral.ai:443"  # the login's hosts


# ── terminal (D.16) ─────────────────────────────────────────────────────


def test_terminal_gets_the_agent_s_settings_as_flags_then_the_user_s_args() -> None:
    docs = servers(DOCS)
    launch = render(claude(), agent(), SCOPE, mcp_servers=docs, terminal=["--resume"])
    mcp = "/home/agent/.handler/terminal-mcp.json"
    assert launch.argv == [
        "claude", "--dangerously-skip-permissions", "--model", "opus", "--mcp-config", mcp,
        "--resume",
    ]  # fmt: skip
    assert launch.session_defaults is None  # nothing goes over ACP
    [file] = [f for f in launch.files if f.target == mcp]
    assert json.loads(file.content) == {
        "mcpServers": {"docs": {"type": "http", "url": "https://mcp.example.org/sse"}}
    }
    assert file.mode == "0444"
    # the rest is the ACP launch's: state, caches, env, egress
    acp = render(claude(), agent(), SCOPE, mcp_servers=docs)
    assert launch.mounts == acp.mounts and launch.env == acp.env and launch.egress == acp.egress


def test_terminal_flags_follow_the_permission_mode_and_model() -> None:
    plain = agent(config={})
    launch = render(
        claude(),
        plain,
        SCOPE,
        mcp_servers=servers(STDIO),
        terminal=[],
        permission_mode="accept-edits",
    )
    assert launch.argv[:3] == ["claude", "--permission-mode", "acceptEdits"]
    assert "--model" not in launch.argv
    [file] = [f for f in launch.files if f.target.endswith("terminal-mcp.json")]
    assert json.loads(file.content)["mcpServers"]["browser"] == {
        "type": "stdio",
        "command": "playwright-mcp",
        "args": ["--isolated"],
    }


def test_the_agent_s_permission_mode() -> None:
    launch = render(claude(), agent(), SCOPE, permission_mode="ask")
    assert launch.session_defaults is not None and launch.session_defaults.mode_id == "default"
    terminal = render(claude(), agent(config={}), SCOPE, terminal=[], permission_mode="ask")
    assert terminal.argv == ["claude", "--permission-mode", "default"]
    pi = catalog.get("pi").descriptor
    with pytest.raises(RenderError, match="no permission mode 'ask'"):
        render(pi, agent(harness="pi", config={}), SCOPE, permission_mode="ask")


def test_terminal_without_flags_gets_the_model_and_mcp_servers_in_env() -> None:
    """Vibe's terminal has no model or MCP-config flags: VIBE_* env vars override its config."""
    vibe = catalog.get("vibe").descriptor
    p = agent(harness="vibe", config={"model": "mistral-medium-3.5"})
    launch = render(
        vibe, p, SCOPE, mcp_servers=servers(STDIO), terminal=["--resume"], permission_mode="ask"
    )
    assert launch.argv == ["vibe", "--agent", "ask", "--resume"]
    assert launch.env["VIBE_ACTIVE_MODEL"] == "mistral-medium-3.5"
    assert json.loads(launch.env["VIBE_MCP_SERVERS"]) == [
        {
            "name": "browser",
            "transport": "stdio",
            "command": SANDBOX_ENV,
            "args": ["--", "playwright-mcp", "--isolated"],
            "env": {},
        }
    ]
    assert not [f for f in launch.files if f.target.endswith("terminal-mcp.json")]
    plain = render(vibe, agent(harness="vibe", config={}), SCOPE, terminal=[])
    assert plain.argv == ["vibe", "--agent", "auto-approve"]
    assert "VIBE_ACTIVE_MODEL" not in plain.env and "VIBE_MCP_SERVERS" not in plain.env


def test_terminal_needs_a_terminal_program() -> None:
    codex = catalog.get("codex").descriptor
    with pytest.raises(RenderError, match="has no terminal program"):
        render(codex, agent(harness="codex", config={}), SCOPE, terminal=[])


def test_terminal_gets_the_agent_s_instructions_in_its_system_prompt() -> None:
    launch = render(claude(), agent(config={}), SCOPE, terminal=["-c"], instructions="Be brief.")
    assert launch.argv == [
        "claude", "--dangerously-skip-permissions", "--append-system-prompt", "Be brief.", "-c"
    ]  # fmt: skip
    vibe = catalog.get("vibe").descriptor
    with pytest.raises(RenderError, match="cannot take the agent's instructions"):
        render(vibe, agent(harness="vibe", config={}), SCOPE, terminal=[], instructions="Be brief.")
    plain = render(vibe, agent(harness="vibe", config={}), SCOPE, terminal=[], instructions="")
    assert plain.argv == ["vibe", "--agent", "auto-approve"]


def test_terminal_without_mcp_servers_gets_no_config() -> None:
    launch = render(claude(), agent(config={}), SCOPE, terminal=[])
    assert launch.argv == ["claude", "--dangerously-skip-permissions"]
