"""Unit tests of the ACP policy state machine (contract C.4, P1-P9)."""

from typing import Any

import pytest

from handler_contracts import (
    FilteredNetwork,
    HttpMcpServer,
    NoNetwork,
    OpenNetwork,
    SessionDefaults,
    StdioMcpServer,
)
from handler_control.policy import AcpPolicy, ToAgent, ToClient

SCOPE = "/home/you/code/project"
ALLOW = FilteredNetwork(
    mode="filtered", allow=["api.anthropic.com:443", "*.example.org:443"], enforcement="enforce"
)


def policy(**kw: Any) -> AcpPolicy:
    return AcpPolicy(scope=SCOPE, network=kw.pop("network", ALLOW), **kw)


def req(i: Any, method: str, **params: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": i, "method": method, "params": params}


def new_session(i: Any = 1, cwd: str = SCOPE, **params: Any) -> dict[str, Any]:
    return req(i, "session/new", cwd=cwd, mcpServers=params.pop("mcpServers", []), **params)


def only(actions: list[ToAgent | ToClient], kind: type[ToAgent | ToClient]) -> dict[str, Any]:
    assert len(actions) == 1 and isinstance(actions[0], kind), actions
    return actions[0].msg


# P1
def test_initialize_forces_capabilities_off() -> None:
    caps = {"fs": {"readTextFile": True, "writeTextFile": True}, "terminal": True, "other": 1}
    out = only(policy().from_client(req(0, "initialize", clientCapabilities=caps)), ToAgent)
    sent = out["params"]["clientCapabilities"]
    assert sent == {
        "fs": {"readTextFile": False, "writeTextFile": False},
        "terminal": False,
        "other": 1,
    }


# P2
@pytest.mark.parametrize("cwd", [SCOPE, f"{SCOPE}/sub", f"{SCOPE}/sub/../other"])
def test_cwd_inside_scope_is_forwarded(cwd: str) -> None:
    only(policy().from_client(new_session(cwd=cwd)), ToAgent)


@pytest.mark.parametrize(
    "cwd", ["/etc", f"{SCOPE}/../other", "/home/you/code/projectx", "relative", None]
)
def test_cwd_outside_scope_is_refused(cwd: Any) -> None:
    for method in ("session/new", "session/load", "session/resume"):
        out = only(policy().from_client(req(7, method, cwd=cwd, mcpServers=[])), ToClient)
        assert out["id"] == 7
        assert out["error"]["code"] == -32001 and out["error"]["data"] == {"policy": "P2"}


# P3
def test_mcp_http_server_must_be_allowed() -> None:
    ok = {"type": "http", "name": "a", "url": "https://mcp.example.org/x", "headers": []}
    bad = {"type": "http", "name": "b", "url": "https://evil.test/x", "headers": []}
    stdio = {"name": "c", "command": "x", "args": [], "env": []}
    only(policy().from_client(new_session(mcpServers=[ok, stdio])), ToAgent)
    out = only(policy().from_client(new_session(mcpServers=[bad])), ToClient)
    assert out["error"]["data"] == {"policy": "P3"}
    for url in ("https://mcp.example.org:8443/x", "http://mcp.example.org/x"):  # :8443, :80
        other_port = {"type": "http", "name": "d", "url": url, "headers": []}
        out = only(policy().from_client(new_session(mcpServers=[other_port])), ToClient)
        assert out["error"]["data"] == {"policy": "P3"}
    only(
        policy(network=OpenNetwork(mode="open")).from_client(new_session(mcpServers=[bad])), ToAgent
    )
    none = policy(network=NoNetwork(mode="none"))
    only(none.from_client(new_session(mcpServers=[ok])), ToClient)


# P4
@pytest.mark.parametrize("method", ["fs/read_text_file", "fs/write_text_file", "terminal/create"])
def test_agent_fs_terminal_requests_never_reach_client(method: str) -> None:
    out = only(policy().from_agent(req(900, method, path="/etc/passwd")), ToAgent)
    assert out["id"] == 900 and out["error"]["code"] == -32003


def test_agent_fs_notification_dropped() -> None:
    assert policy().from_agent({"jsonrpc": "2.0", "method": "terminal/output", "params": {}}) == []


# P5
def test_client_heartbeat_dropped() -> None:
    assert policy().from_client({"jsonrpc": "2.0", "method": "$/ping"}) == []


def test_client_dollar_request_is_not_dropped() -> None:
    only(policy().from_client(req(3, "$/cancel_request")), ToAgent)


# P6
def test_extensions_forwarded_and_logged() -> None:
    events: list[str] = []
    p = policy(on_event=events.append)
    only(p.from_client(req(1, "_vendor/x")), ToAgent)
    only(p.from_agent({"jsonrpc": "2.0", "method": "_auth/status_update", "params": {}}), ToClient)
    assert len(events) == 2


# P7
DEFAULTS = SessionDefaults(mode_id="bypassPermissions", config_options={"model": "opus"})
NEW_RESULT = {
    "sessionId": "s1",
    "modes": {"currentModeId": "default", "availableModes": []},
    "configOptions": [
        {"id": "model", "currentValue": "default"},
        {"id": "effort", "currentValue": "high"},
    ],
}


def test_session_defaults_applied_before_client_sees_session() -> None:
    p = policy(session_defaults=DEFAULTS)
    only(p.from_client(new_session(i=5)), ToAgent)
    set_mode = only(p.from_agent({"jsonrpc": "2.0", "id": 5, "result": NEW_RESULT}), ToAgent)
    assert set_mode["method"] == "session/set_mode"
    assert set_mode["params"] == {"sessionId": "s1", "modeId": "bypassPermissions"}
    set_opt = only(p.from_agent({"jsonrpc": "2.0", "id": set_mode["id"], "result": {}}), ToAgent)
    assert set_opt["method"] == "session/set_config_option"
    assert set_opt["params"] == {"sessionId": "s1", "configId": "model", "value": "opus"}
    final = only(p.from_agent({"jsonrpc": "2.0", "id": set_opt["id"], "result": {}}), ToClient)
    assert final["id"] == 5
    assert final["result"]["modes"]["currentModeId"] == "bypassPermissions"
    assert final["result"]["configOptions"] == [
        {"id": "model", "currentValue": "opus"},
        {"id": "effort", "currentValue": "high"},
    ]


def test_session_defaults_applied_after_session_load() -> None:
    """A loaded session runs in a new sandbox: the agent's mode applies again (P7)."""
    p = policy(session_defaults=DEFAULTS)
    only(p.from_client(req(6, "session/load", sessionId="s9", cwd=SCOPE, mcpServers=[])), ToAgent)
    loaded = {k: v for k, v in NEW_RESULT.items() if k != "sessionId"}
    set_mode = only(p.from_agent({"jsonrpc": "2.0", "id": 6, "result": loaded}), ToAgent)
    assert set_mode["params"] == {"sessionId": "s9", "modeId": "bypassPermissions"}
    set_opt = only(p.from_agent({"jsonrpc": "2.0", "id": set_mode["id"], "result": {}}), ToAgent)
    final = only(p.from_agent({"jsonrpc": "2.0", "id": set_opt["id"], "result": {}}), ToClient)
    assert final["id"] == 6
    assert final["result"]["modes"]["currentModeId"] == "bypassPermissions"


def test_session_defaults_failure_is_an_error_for_the_client() -> None:
    p = policy(session_defaults=DEFAULTS)
    p.from_client(new_session(i=5))
    set_mode = only(p.from_agent({"jsonrpc": "2.0", "id": 5, "result": NEW_RESULT}), ToAgent)
    error = {"code": -32602, "message": "unknown mode"}
    out = only(p.from_agent({"jsonrpc": "2.0", "id": set_mode["id"], "error": error}), ToClient)
    assert out["id"] == 5 and out["error"]["code"] == -32004
    assert "unknown mode" in out["error"]["message"]


def test_session_new_error_passes_through() -> None:
    p = policy(session_defaults=DEFAULTS)
    p.from_client(new_session(i=5))
    error = {"jsonrpc": "2.0", "id": 5, "error": {"code": -32000, "message": "auth"}}
    assert only(p.from_agent(error), ToClient) == error


def test_no_defaults_means_plain_forwarding() -> None:
    p = policy()
    p.from_client(new_session(i=5))
    response = {"jsonrpc": "2.0", "id": 5, "result": NEW_RESULT}
    assert only(p.from_agent(response), ToClient) == response


def test_other_traffic_forwarded_unchanged() -> None:
    p = policy()
    update = {"jsonrpc": "2.0", "method": "session/update", "params": {"x": 1}}
    assert only(p.from_agent(update), ToClient) == update
    prompt = req(9, "session/prompt", sessionId="s1", prompt=[])
    assert only(p.from_client(prompt), ToAgent) == prompt


# P8
BROWSER = StdioMcpServer(name="browser", command="playwright-mcp", args=["--isolated"])
BROWSER_WIRE = {"name": "browser", "command": "playwright-mcp", "args": ["--isolated"], "env": []}


@pytest.mark.parametrize("method", ["session/new", "session/load", "session/resume"])
def test_platform_mcp_servers_added_to_every_session(method: str) -> None:
    p = policy(session_defaults=SessionDefaults(mcp_servers=[BROWSER]))
    mine = {"name": "mine", "command": "x", "args": [], "env": []}
    out = only(p.from_client(req(3, method, cwd=SCOPE, mcpServers=[mine])), ToAgent)
    assert out["params"]["mcpServers"] == [mine, BROWSER_WIRE]
    out = only(p.from_client(req(4, method, cwd=SCOPE)), ToAgent)
    assert out["params"]["mcpServers"] == [BROWSER_WIRE]


def test_platform_mcp_server_replaces_a_client_one_with_its_name() -> None:
    events: list[str] = []
    p = policy(session_defaults=SessionDefaults(mcp_servers=[BROWSER]), on_event=events.append)
    theirs = {"name": "browser", "command": "/usr/bin/evil", "args": [], "env": []}
    out = only(p.from_client(new_session(mcpServers=[theirs])), ToAgent)
    assert out["params"]["mcpServers"] == [BROWSER_WIRE]
    assert events == ["client MCP server 'browser' replaced by the platform's"]


def test_malformed_client_mcp_servers_are_left_to_the_agent() -> None:
    p = policy(session_defaults=SessionDefaults(mcp_servers=[BROWSER]))
    out = only(p.from_client(new_session(mcpServers="nope")), ToAgent)
    assert out["params"]["mcpServers"] == "nope"


def test_platform_http_mcp_server_is_checked_by_p3() -> None:
    docs = HttpMcpServer(type="http", name="docs", url="https://mcp.example.org/x")
    p = policy(network=NoNetwork(mode="none"), session_defaults=SessionDefaults(mcp_servers=[docs]))
    out = only(p.from_client(new_session()), ToClient)
    assert out["error"]["data"] == {"policy": "P3"}


# P9


def test_instructions_go_before_the_first_prompt_of_a_new_session() -> None:
    p = policy(instructions="Answer in French.")
    p.from_client(new_session(i=5))
    only(p.from_agent({"jsonrpc": "2.0", "id": 5, "result": NEW_RESULT}), ToClient)
    first = req(6, "session/prompt", sessionId="s1", prompt=[{"type": "text", "text": "hello"}])
    sent = only(p.from_client(first), ToAgent)
    assert sent["params"]["prompt"] == [{"type": "text", "text": "Answer in French.\n\nhello"}]
    second = req(7, "session/prompt", sessionId="s1", prompt=[{"type": "text", "text": "again"}])
    assert only(p.from_client(second), ToAgent) == second


def test_instructions_wait_for_the_session_defaults() -> None:
    p = policy(session_defaults=DEFAULTS, instructions="Answer in French.")
    p.from_client(new_session(i=5))
    set_mode = only(p.from_agent({"jsonrpc": "2.0", "id": 5, "result": NEW_RESULT}), ToAgent)
    set_opt = only(p.from_agent({"jsonrpc": "2.0", "id": set_mode["id"], "result": {}}), ToAgent)
    only(p.from_agent({"jsonrpc": "2.0", "id": set_opt["id"], "result": {}}), ToClient)
    image = {"type": "image", "data": "…", "mimeType": "image/png"}
    sent = only(p.from_client(req(6, "session/prompt", sessionId="s1", prompt=[image])), ToAgent)
    assert sent["params"]["prompt"] == [{"type": "text", "text": "Answer in French."}, image]


def test_a_loaded_session_is_not_instructed_again() -> None:
    p = policy(instructions="Answer in French.")
    p.from_client(req(6, "session/load", sessionId="s9", cwd=SCOPE, mcpServers=[]))
    only(p.from_agent({"jsonrpc": "2.0", "id": 6, "result": {}}), ToClient)
    prompt = req(7, "session/prompt", sessionId="s9", prompt=[{"type": "text", "text": "hi"}])
    assert only(p.from_client(prompt), ToAgent) == prompt
