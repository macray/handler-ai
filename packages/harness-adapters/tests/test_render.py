"""Unit tests of `render` (contract B.3) against the real descriptors in harnesses/."""

import builtins
import contextlib
import io
import json
import os
import socket
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from pydantic import TypeAdapter

from handler_contracts import AgentSpec, CacheDeclaration, McpServer, StdioMcpServer
from handler_harness import RenderError, catalog, harness_hosts, starting_instructions
from handler_harness import render as render_launch
from handler_harness.render import FILTERED_NETWORK, SANDBOX_ENV, SANDBOX_ENV_SCRIPT

FIXTURES = Path(__file__).parent / "fixtures"
STATE_ROOT = "/data/agent-state/a1b2c3"


def cache(target: str, bin_: str | None = None) -> CacheDeclaration:
    return CacheDeclaration(target=target, about="x", bin=bin_)


CARGO = [(cache("~/.cargo"), "/home/you/.cache/handler-ai/cargo")]


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


@pytest.mark.rule("harness.no-telemetry-no-self-update")
def test_golden_claude_perso() -> None:
    """The full HarnessLaunch for the reference agent, with the state handler keeps for it and an
    addon's MCP server. Update the fixture deliberately."""
    launch = render(
        claude(), agent(), state_root=STATE_ROOT, mcp_servers=servers(DOCS), caches=CARGO
    )
    actual = json.loads(launch.model_dump_json(by_alias=True, exclude_none=True))
    expected = json.loads((FIXTURES / "claude-perso.launch.json").read_text())
    assert actual == expected


def test_caches_are_in_the_harness_home() -> None:
    caches = [*CARGO, (cache("/opt/x"), "/h/x"), (cache("~/.bun", "bin"), "/h/bun")]
    launch = render(claude(), agent(), caches=caches)
    assert [(c.target, c.source, c.path) for c in launch.caches] == [
        ("/home/agent/.cargo", "/home/you/.cache/handler-ai/cargo", None),
        ("/opt/x", "/h/x", None),
        ("/home/agent/.bun", "/h/bun", "/home/agent/.bun/bin"),  # its commands, on PATH
    ]
    assert render(claude(), agent()).caches == []


@pytest.mark.rule("launch.mode-and-model-over-acp")
def test_permission_mode_is_an_acp_session_mode() -> None:
    launch = render(claude(), agent())
    assert launch.session_defaults is not None
    assert launch.session_defaults.mode_id == "bypassPermissions"
    vibe_agent = agent(harness="vibe", config={})
    vibe = render(catalog.get("vibe").descriptor, vibe_agent)
    assert vibe.session_defaults is not None and vibe.session_defaults.mode_id == "auto-approve"


@pytest.mark.rule("launch.mode-and-model-over-acp")
def test_model_goes_through_acp_config_option() -> None:
    launch = render(claude(), agent())
    assert launch.session_defaults is not None
    assert launch.session_defaults.config_options == {"model": "opus"}
    assert "ANTHROPIC_MODEL" not in launch.env


@pytest.mark.rule("launch.the-plan-is-told")
def test_the_account_s_plan_is_told_to_the_harness() -> None:
    """Claude Code cannot learn it from a token login (B.1 `login.planEnv`)."""
    launch = render(claude(), agent(account_plan="max"))
    assert launch.env["CLAUDE_CODE_SUBSCRIPTION_TYPE"] == "max"
    unset = render(claude(), agent())
    assert "CLAUDE_CODE_SUBSCRIPTION_TYPE" not in unset.env


@pytest.mark.rule("launch.account-connectors-off")
def test_account_connectors_off_by_default() -> None:
    launch = render(claude(), agent())
    assert launch.env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
    on = render(claude(), agent(config={"accountConnectors": True}))
    assert "ENABLE_CLAUDEAI_MCP_SERVERS" not in on.env


DOCS = {"type": "http", "name": "docs", "url": "https://mcp.example.org/sse"}


def test_http_mcp_server_host_added_to_egress() -> None:
    launch = render(claude(), agent(), mcp_servers=servers(DOCS))
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
    launch = render(claude(), agent(), mcp_servers=servers(DOCS))
    assert launch.egress == [host for host, _ in hosts]


STDIO = {"name": "browser", "command": "playwright-mcp", "args": ["--isolated"]}
STDIO_SERVER = StdioMcpServer.model_validate(STDIO)


@pytest.mark.rule("launch.mcp-servers-reach-every-harness")
def test_mcp_servers_go_to_every_session() -> None:
    launch = render(claude(), agent(), mcp_servers=servers(STDIO))
    assert launch.session_defaults is not None
    [server] = launch.session_defaults.mcp_servers or []  # wrapped: mcpEnv = "sandbox"
    assert (server.name, server.args[-2:]) == ("browser", ["playwright-mcp", "--isolated"])


@pytest.mark.rule("launch.what-it-cannot-honour-fails")
def test_mcp_transport_the_harness_does_not_accept_is_refused() -> None:
    """B5: never silently dropped."""
    no_mcp = claude().model_copy(update={"mcp_transports": []})
    with pytest.raises(RenderError, match="does not accept stdio MCP servers"):
        render(no_mcp, agent(), mcp_servers=servers(STDIO))
    vibe_agent = agent(harness="vibe", config={})
    with pytest.raises(RenderError, match="does not accept http MCP servers"):
        render(catalog.get("vibe").descriptor, vibe_agent, mcp_servers=servers(DOCS))


LOCAL = {
    "apiVersion": "handler.provider/v1",
    "endpoints": {"openai-chat": "http://127.0.0.1:3000/v1"},
    "models": [{"id": "qwen"}],
}


@pytest.mark.rule("launch.stdio-mcp-servers-see-the-sandbox")
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
    launch = render(vibe, vibe_agent, provider_key="k", mcp_servers=servers(STDIO))
    assert launch.session_defaults is not None
    [server] = launch.session_defaults.mcp_servers or []
    assert server.model_dump(exclude_defaults=True) == {
        "name": "browser",
        "command": SANDBOX_ENV,
        "args": ["--drop", "MISTRAL_API_KEY", "--", "playwright-mcp", "--isolated"],
    }
    claude_launch = render(claude(), agent(), account_token="t", mcp_servers=servers(STDIO))
    assert claude_launch.session_defaults is not None
    [server] = claude_launch.session_defaults.mcp_servers or []
    assert server.args[:3] == ["--drop", "CLAUDE_CODE_OAUTH_TOKEN", "--"]  # the account's token


@pytest.mark.rule("launch.mcp-servers-reach-every-harness")
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
    launch = render(pi, pi_agent, mcp_servers=servers(stdio, http))
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
    assert file.mode == "0444" and not file.writable
    assert "mcp.example.org:443" in launch.egress
    none = render(pi, pi_agent)
    assert none.files == []  # no mcp.json without servers
    claude_launch = render(claude(), agent(), mcp_servers=servers(STDIO))
    assert claude_launch.files == []  # it takes them from session/new


@pytest.mark.rule("launch.what-it-cannot-honour-fails")
def test_mcp_server_names_are_unique() -> None:
    twice = servers(STDIO, STDIO | {"command": "other"})
    with pytest.raises(RenderError, match="two MCP servers are named browser"):
        render(claude(), agent(), mcp_servers=twice)


@pytest.mark.rule("launch.secrets-only-in-its-environment")
def test_the_accounts_token_only_in_env() -> None:
    launch = render(claude(), agent(), account_token="sk-test")
    assert launch.env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-test"
    assert "sk-test" not in " ".join(launch.argv)
    on_provider = agent(
        account=None,
        provider="local",
        providerSpec=LOCAL | {"endpoints": {"anthropic": "http://127.0.0.1:3000"}},
        config={},
    )
    launch = render(claude(), on_provider, account_token="sk-test")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in launch.env  # only an account's


@pytest.mark.rule("launch.what-it-cannot-honour-fails", "launch.skills-read-only-under-their-name")
def test_render_errors() -> None:
    with pytest.raises(RenderError, match="not 'claude-code'"):
        render(claude(), agent(harness="vibe"))
    with pytest.raises(RenderError, match="two skills are named 'review'"):
        render(claude(), agent(), skills=["/a/review", "/b/review"])


@pytest.mark.rule("launch.what-it-cannot-honour-fails")
def test_unmapped_permission_mode_is_refused() -> None:
    """pi never asks: an agent wanting "ask" must fail, not silently run in bypass."""
    pi = catalog.get("pi").descriptor
    assert list(pi.permissions) == ["bypass"]
    p = agent(harness="pi", config={})
    with pytest.raises(RenderError, match="no permission mode 'ask'"):
        render(pi, p, permission_mode="ask")
    launch = render(pi, agent(harness="pi", config={}))
    assert launch.session_defaults is None  # bypass = {}: pi's default


@pytest.mark.rule("launch.skills-read-only-under-their-name")
def test_skills_are_read_only_folders_under_their_name() -> None:
    skills = ["/home/you/skills/podman", "/opt/team-skills/review"]
    launch = render(claude(), agent(), skills=skills)
    given = {f.target: (f.source, f.writable) for f in launch.skills}
    assert given == {
        "/home/agent/.claude/skills/podman": ("/home/you/skills/podman", False),
        "/home/agent/.claude/skills/review": ("/opt/team-skills/review", False),
    }


def test_config_file_becomes_a_writable_file_for_vibe() -> None:
    vibe = catalog.get("vibe").descriptor
    p = agent(harness="vibe", config={}, files={"config_toml": {"content": "x = 1"}})
    launch = render(vibe, p, {"config_toml": "x = 1"})
    [f] = launch.files
    assert (f.target, f.content, f.writable, f.mode) == (
        "/home/agent/.vibe/config.toml",
        "x = 1",
        True,
        "0600",
    )


@pytest.mark.rule("toolbox.nothing-of-handler-in-it")
def test_sandbox_env_comes_with_the_harnesses_that_use_it() -> None:
    """mcpEnv = "sandbox" (B.1): the wrapper is in the launch, not in the toolbox."""
    vibe = render(catalog.get("vibe").descriptor, agent(harness="vibe", config={}))
    [tool] = vibe.tools
    assert (tool.target, tool.content) == (SANDBOX_ENV, SANDBOX_ENV_SCRIPT)


@pytest.mark.rule("launch.what-it-cannot-honour-fails")
def test_unknown_config_file_is_an_error() -> None:
    with pytest.raises(RenderError, match="config file 'nope'"):
        render(claude(), agent(files={"nope": {"content": "x"}}), {"nope": "x"})


def test_per_session_slot_is_bound_by_the_daemon_only() -> None:
    vibe = catalog.get("vibe").descriptor
    p = agent(harness="vibe", config={})
    launch = render(vibe, p)
    assert launch.folders == []
    launch = render(vibe, p, session_state="/state/sessions/s_1/agent")
    state = [(f.source, f.target, f.writable) for f in launch.folders]
    assert state == [("/state/sessions/s_1/agent", "/home/agent/.vibe/logs/session", True)]


# ── state: the agent's own, the account's login, the daemon's sessions ──


def test_the_agent_s_own_state_is_kept_by_handler() -> None:
    p = agent()
    launch = render(claude(), p, state_root="/data/agent-state/work")
    assert [(f.target, f.source, f.writable) for f in launch.folders] == [
        ("/home/agent/.claude", "/data/agent-state/work/config_dir", True)
    ]
    assert [(f.target, f.source) for f in launch.kept_files] == [
        ("/home/agent/.claude.json", "/data/agent-state/work/config_json/config_json")
    ]
    launch = render(claude(), p)  # no state root (handler-harness render): nothing bound
    assert launch.folders == [] and launch.kept_files == []


@pytest.mark.rule("launch.a-login-only-read-is-given-as-a-copy")
def test_the_accounts_login_file_is_kept_or_given() -> None:
    """A login file the harness refreshes is a kept file; one it only reads, its content."""
    codex = catalog.get("codex").descriptor
    kept = "/data/accounts/chatgpt/credential"
    p = agent(harness="codex", config={}, accountLogin=kept)
    launch = render(codex, p, state_root="/data/agent-state/work")
    assert [(f.target, f.source) for f in launch.kept_files] == [
        ("/home/agent/.codex/auth.json", kept)
    ]
    vibe = catalog.get("vibe").descriptor  # its login file is read-only
    p = agent(harness="vibe", config={}, accountLogin="/data/accounts/m/credential")
    with pytest.raises(RenderError, match="the login's content is not given"):
        render(vibe, p)
    launch = render(vibe, p, login_file="MISTRAL_API_KEY=k\n")
    assert launch.kept_files == []
    [file] = launch.files
    assert (file.target, file.content, file.mode, file.writable) == (
        "/home/agent/.vibe/.env", "MISTRAL_API_KEY=k\n", "0400", False
    )  # fmt: skip
    assert launch.egress[0] == "api.mistral.ai:443"  # the login's hosts


# ── terminal (D.16) ─────────────────────────────────────────────────────


@pytest.mark.rule("terminal.runs-with-the-agent-s-settings")
def test_terminal_gets_the_agent_s_settings_as_flags_then_the_user_s_args() -> None:
    docs = servers(DOCS)
    launch = render(claude(), agent(), mcp_servers=docs, terminal=["--resume"])
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
    acp = render(claude(), agent(), mcp_servers=docs)
    assert (launch.folders, launch.caches, launch.kept_files) == (acp.folders, acp.caches,
                                                                 acp.kept_files)  # fmt: skip
    assert launch.env == acp.env and launch.egress == acp.egress


@pytest.mark.rule("terminal.runs-with-the-agent-s-settings")
def test_terminal_flags_follow_the_permission_mode_and_model() -> None:
    plain = agent(config={})
    launch = render(
        claude(),
        plain,
        mcp_servers=servers(STDIO),
        terminal=[],
        permission_mode="accept-edits",
    )
    assert launch.argv[:3] == ["claude", "--permission-mode", "acceptEdits"]
    assert "--model" not in launch.argv
    [file] = [f for f in launch.files if f.target.endswith("terminal-mcp.json")]
    assert json.loads(file.content)["mcpServers"]["browser"] == {
        "type": "stdio",
        "command": SANDBOX_ENV,
        "args": ["--", "playwright-mcp", "--isolated"],
    }


@pytest.mark.rule(
    "launch.what-it-cannot-honour-fails",
    "launch.mode-and-model-over-acp",
    "terminal.runs-with-the-agent-s-settings",
)
def test_the_agent_s_permission_mode() -> None:
    launch = render(claude(), agent(), permission_mode="ask")
    assert launch.session_defaults is not None and launch.session_defaults.mode_id == "default"
    terminal = render(claude(), agent(config={}), terminal=[], permission_mode="ask")
    assert terminal.argv == ["claude", "--permission-mode", "default"]
    pi = catalog.get("pi").descriptor
    with pytest.raises(RenderError, match="no permission mode 'ask'"):
        render(pi, agent(harness="pi", config={}), permission_mode="ask")


@pytest.mark.rule("terminal.runs-with-the-agent-s-settings")
def test_terminal_without_flags_gets_the_model_and_mcp_servers_in_env() -> None:
    """Vibe's terminal has no model or MCP-config flags: VIBE_* env vars override its config."""
    vibe = catalog.get("vibe").descriptor
    p = agent(harness="vibe", config={"model": "mistral-medium-3.5"})
    launch = render(
        vibe, p, mcp_servers=servers(STDIO), terminal=["--resume"], permission_mode="ask"
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
    plain = render(vibe, agent(harness="vibe", config={}), terminal=[])
    assert plain.argv == ["vibe", "--agent", "auto-approve"]
    assert "VIBE_ACTIVE_MODEL" not in plain.env and "VIBE_MCP_SERVERS" not in plain.env


@pytest.mark.rule("terminal.runs-with-the-agent-s-settings")
def test_terminal_needs_a_terminal_program() -> None:
    codex = catalog.get("codex").descriptor
    with pytest.raises(RenderError, match="has no terminal program"):
        render(codex, agent(harness="codex", config={}), terminal=[])


@pytest.mark.rule("terminal.runs-with-the-agent-s-settings")
def test_terminal_gets_the_agent_s_instructions_in_its_system_prompt() -> None:
    launch = render(claude(), agent(config={}), terminal=["-c"], instructions="Be brief.")
    assert launch.argv == [
        "claude", "--dangerously-skip-permissions", "--append-system-prompt", "Be brief.", "-c"
    ]  # fmt: skip
    vibe = catalog.get("vibe").descriptor
    with pytest.raises(RenderError, match="cannot take the agent's instructions"):
        render(vibe, agent(harness="vibe", config={}), terminal=[], instructions="Be brief.")
    plain = render(vibe, agent(harness="vibe", config={}), terminal=[], instructions="")
    assert plain.argv == ["vibe", "--agent", "auto-approve"]


@pytest.mark.rule("launch.a-filtered-agent-is-told")
def test_a_filtered_agent_starts_told_what_a_refused_host_means() -> None:
    assert FILTERED_NETWORK.startswith("Your network goes through Handler's network filter")
    assert "ask the user to allow it" in FILTERED_NETWORK
    assert "Never try to get around the filter" in FILTERED_NETWORK
    told = starting_instructions("Be brief.", "filtered")
    assert told == f"Be brief.\n\n{FILTERED_NETWORK}"
    assert starting_instructions(None, "filtered") == FILTERED_NETWORK
    for network in ("open", "none"):  # nothing is refused: nothing to say
        assert starting_instructions("Be brief.", network) == "Be brief."
        assert starting_instructions(None, network) is None
        assert starting_instructions("", network) is None


@pytest.mark.rule("launch.a-filtered-agent-is-told", "terminal.runs-with-the-agent-s-settings")
def test_a_filtered_terminal_is_told_where_it_can_take_instructions() -> None:
    launch = render(claude(), agent(config={}), terminal=[], network="filtered")
    assert launch.argv == [
        "claude", "--dangerously-skip-permissions", "--append-system-prompt", FILTERED_NETWORK
    ]  # fmt: skip
    told = render(
        claude(), agent(config={}), terminal=[], instructions="Be brief.", network="filtered"
    )
    assert told.argv[-1] == f"Be brief.\n\n{FILTERED_NETWORK}"
    plain = render(claude(), agent(config={}), terminal=[], network="open")
    assert plain.argv == ["claude", "--dangerously-skip-permissions"]
    vibe = catalog.get("vibe").descriptor  # takes no instructions: goes without them
    quiet = render(vibe, agent(harness="vibe", config={}), terminal=[], network="filtered")
    assert quiet.argv == ["vibe", "--agent", "auto-approve"]


@pytest.mark.rule("terminal.runs-with-the-agent-s-settings")
def test_terminal_without_mcp_servers_gets_no_config() -> None:
    launch = render(claude(), agent(config={}), terminal=[])
    assert launch.argv == ["claude", "--dangerously-skip-permissions"]


@contextlib.contextmanager
def host_out_of_reach() -> Iterator[list[str]]:
    """Files, processes, sockets and the environment out of reach: each use is refused, and
    listed (a refusal the code under test catches is still seen)."""
    touched: list[str] = []

    def refused(what: str) -> Callable[..., Any]:
        def refuse(*args: Any, **kwargs: Any) -> Any:
            touched.append(f"{what}{args[:1]}")
            raise PermissionError(what)

        return refuse

    reach = [
        (builtins, "open"), (io, "open"), (os, "open"), (os, "listdir"), (os, "scandir"),
        (os, "stat"), (os, "getenv"), (os, "system"), (os, "execv"), (os, "execvp"),
        (subprocess, "Popen"), (socket, "socket"), (socket, "create_connection"),
        (socket, "getaddrinfo"),
    ]  # fmt: skip
    with contextlib.ExitStack() as stack:
        for module, name in reach:
            stack.enter_context(
                mock.patch.object(module, name, refused(f"{module.__name__}.{name}"))
            )
        yield touched


@pytest.mark.rule("launch.render-is-pure-intent")
@pytest.mark.parametrize("name", [h.name for h in catalog.all_harnesses()])
def test_render_reads_nothing_starts_nothing_and_gives_the_same_launch(name: str) -> None:
    """Every harness's launch, rendered twice with the host out of reach: nothing touched, the
    same launch, written as intent with no container engine in it.

    If this fails: a dry run (`handler-harness render`) changes something on the host, or an
    adapter works only with one container engine."""
    descriptor = catalog.get(name).descriptor
    spec = agent(harness=name, account=f"{name}-account", config={})
    mode, mcp = next(iter(descriptor.permissions)), servers(STDIO)  # every harness takes stdio
    with host_out_of_reach() as touched:
        twice = [
            render_launch(descriptor, spec, permission_mode=mode, mcp_servers=mcp) for _ in range(2)
        ]
    assert touched == []
    first, second = (launch.model_dump_json(by_alias=True) for launch in twice)
    assert first == second
    for engine in ("podman", "docker", "--mount", "--network", "--volume"):
        assert engine not in first


# what each harness has to switch off its telemetry, feedback, update checks and self-updates
PRIVACY: dict[str, dict[str, str]] = {
    "claude-code": {
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY": "1",
    },
    "codex": {"CODEX_PATH": "handler-codex"},  # its switches are config keys: the wrapper's
    "pi": {"PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0", "PI_OFFLINE": "1"},
    "vibe": {
        "VIBE_ENABLE_TELEMETRY": "false",
        "VIBE_ENABLE_UPDATE_CHECKS": "false",
        "VIBE_ENABLE_AUTO_UPDATE": "false",
    },
}
CODEX_OVERRIDES = [
    "analytics.enabled=false",
    "feedback.enabled=false",
    "check_for_update_on_startup=false",
    "otel.metrics_exporter=none",
]


def test_every_harness_says_how_its_telemetry_is_off() -> None:
    """If this fails: a harness was added without its privacy settings being looked for."""
    assert sorted(PRIVACY) == sorted(h.name for h in catalog.all_harnesses())


@pytest.mark.rule("harness.no-telemetry-no-self-update")
@pytest.mark.parametrize("name", sorted(PRIVACY))
def test_every_launch_of_a_harness_has_its_telemetry_and_updates_off(name: str) -> None:
    """Its ACP launch, and its terminal program's when it has one, run with each of its
    switches off.

    If this fails: a harness reports your use to its vendor beyond the model calls, or updates
    itself past the check."""
    harness = catalog.get(name)
    spec = agent(harness=name, account=f"{name}-account", config={})
    mode = next(iter(harness.descriptor.permissions))
    launches = [render_launch(harness.descriptor, spec, permission_mode=mode)]
    if harness.descriptor.terminal is not None:
        terminal = render_launch(harness.descriptor, spec, permission_mode=mode, terminal=[])
        launches.append(terminal)
    for launch in launches:
        assert PRIVACY[name].items() <= launch.env.items()


@pytest.mark.rule("harness.no-telemetry-no-self-update")
def test_handler_codex_starts_codex_with_its_telemetry_and_updates_off() -> None:
    """If this fails: Codex sends analytics, feedback and metrics to its vendor, or checks for
    updates, whatever its configuration says."""
    containerfile = (catalog.get("codex").directory / "Containerfile").read_text()
    wrapper = next(
        line for line in containerfile.splitlines() if "/usr/local/bin/handler-codex" in line
    )
    wrapper = containerfile[: containerfile.index(wrapper)].rsplit("printf", 1)[1]
    for override in CODEX_OVERRIDES:
        assert f"-c {override}" in wrapper
