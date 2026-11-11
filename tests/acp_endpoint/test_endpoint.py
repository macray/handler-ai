"""Contract C conformance: the ACP WebSocket endpoint of a real handlerd (contract C).

The agent is the fake agent (tests/support/fake_agent.py), run on the host by the fake sandbox,
so these tests exercise the transport and the policy, not a container.
"""

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

from handler_contracts import (
    ACP_SUBPROTOCOL,
    BEARER_SUBPROTOCOL_PREFIX,
    DEFAULT_MAX_MESSAGE_BYTES,
    AcpCloseCode,
)
from handler_harness.render import FILTERED_NETWORK

from ..support.acp_client import AcpClient, AcpError
from ..support.daemon import UI_ORIGIN, Daemon


@pytest.fixture
def scope(daemon: Daemon) -> Path:
    return daemon.make_scope()


@pytest.fixture
def ad_hoc(daemon: Daemon, scope: Path) -> dict[str, Any]:
    return daemon.create_ad_hoc(
        "fake", scope, addons=[{"addon": "fake-browser", "binding": "browser"}], model="big-model"
    )


def report(client: AcpClient, session: str) -> dict[str, Any]:
    before = len(client.text())
    client.prompt(session, "report")
    return json.loads(client.text()[before:])


# ── C.1 transport & auth ───────────────────────────────────────────────


def _status(daemon: Daemon, url: str, protocols: list[str], origin: str | None = None) -> int:
    headers = {"Origin": origin} if origin else None
    try:
        with connect(url, subprotocols=protocols, additional_headers=headers):  # ty: ignore[invalid-argument-type]
            return 101
    except InvalidStatus as e:
        return e.response.status_code


@pytest.mark.rule("connect.only-with-the-token", "connect.browsers-only-from-handler-s-pages")
def test_auth_and_origin(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    url, good = ad_hoc["acpUrl"], BEARER_SUBPROTOCOL_PREFIX + daemon.token
    assert _status(daemon, url, [ACP_SUBPROTOCOL]) == 401
    assert _status(daemon, url, [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + "wrong"]) == 401
    assert _status(daemon, url, [ACP_SUBPROTOCOL, good], origin="http://evil.test") == 403
    assert _status(daemon, url, [ACP_SUBPROTOCOL, good], origin=UI_ORIGIN) == 101
    missing = f"{daemon.ws_base}/v1/agents/nope/acp"
    assert _status(daemon, missing, [ACP_SUBPROTOCOL, good]) == 404


@pytest.mark.rule("connect.only-with-the-token")
def test_subprotocol_negotiated(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(ad_hoc["acpUrl"], subprotocols=protocols) as ws:  # ty: ignore[invalid-argument-type]
        assert ws.subprotocol == ACP_SUBPROTOCOL


# ── C.4 policy, end to end ─────────────────────────────────────────────


@pytest.mark.rule(
    "policy.never-the-client-s-files-or-terminal",
    "policy.heartbeats-stop-at-handlerd",
    "policy.starts-in-its-own-mode",
    "policy.its-tools-mcp-servers-win",
)
def test_p1_p5_p7_p8(daemon: Daemon, ad_hoc: dict[str, Any], scope: Path) -> None:
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        client.send({"method": "$/ping"})  # P5: must not reach the agent
        client.initialize({"fs": {"readTextFile": True, "writeTextFile": True}, "terminal": True})
        session = client.new_session(str(scope))
        # P7: the client only sees the session once the defaults are applied
        assert session["modes"]["currentModeId"] == "yolo"
        assert session["configOptions"][0]["currentValue"] == "big-model"
        seen = report(client, session["sessionId"])
    finally:
        client.close()
    assert seen["capabilities"] == {
        "fs": {"readTextFile": False, "writeTextFile": False},
        "terminal": False,
    }
    assert seen["mode"] == "yolo" and seen["options"] == {"model": "big-model"}
    assert "$/ping" not in seen["methods"]
    assert seen["mcpServers"] == ["fake-browser"]  # P8: its addon's, though the client sent none


@pytest.mark.rule(
    "policy.instructions-go-once-with-the-first-prompt", "launch.a-filtered-agent-is-told"
)
def test_p9_instructions_go_with_the_first_prompt(daemon: Daemon, scope: Path) -> None:
    agent = daemon.create_ad_hoc("fake", scope, name="briefed", instructions="Answer briefly.")
    client = daemon.connect(agent["acpUrl"])
    try:
        client.initialize()
        session = client.new_session(str(scope))["sessionId"]
        first = report(client, session)
        second = report(client, session)
    finally:
        client.close()
    assert first["prompt"] == [f"Answer briefly.\n\n{FILTERED_NETWORK}\n\nreport"]  # filtered
    assert second["prompt"] == ["report"]


@pytest.mark.rule("connection.runs-with-the-model-named")
def test_a_connection_names_the_model_it_runs_with(
    daemon: Daemon, ad_hoc: dict[str, Any], scope: Path
) -> None:
    """C.1: `?account=…&model=…` (or provider and harness): one of the agent's models or any
    other (D.19), checked before the connection is accepted; none: the agent's first."""
    good = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    url = ad_hoc["acpUrl"]
    assert _status(daemon, f"{url}?account=nope", good) == 400
    assert _status(daemon, f"{url}?model=small-model", good) == 400  # no account or provider
    client = daemon.connect(f"{url}?account=fake&model=small-model")
    try:
        client.initialize()
        session = client.new_session(str(scope))
        assert session["configOptions"][0]["currentValue"] == "small-model"
    finally:
        client.close()


@pytest.mark.rule("policy.works-only-in-its-folder")
def test_p2_cwd_outside_scope(daemon: Daemon, ad_hoc: dict[str, Any], scope: Path) -> None:
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        client.initialize()
        with pytest.raises(AcpError) as e:
            client.new_session("/etc")
        assert e.value.error["code"] == -32001
        session = client.new_session(str(scope))
        seen = report(client, session["sessionId"])
    finally:
        client.close()
    assert seen["methods"].count("session/new") == 1  # the refused one never reached the agent


@pytest.mark.rule("policy.never-the-client-s-files-or-terminal")
def test_p4_agent_cannot_use_client_fs(daemon: Daemon, ad_hoc: dict[str, Any], scope: Path) -> None:
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        client.initialize()
        session = client.new_session(str(scope))
        client.prompt(session["sessionId"], "fs")
    finally:
        client.close()
    assert client.other_agent_requests == []  # the client never saw fs/read_text_file
    agent_got = json.loads(client.text())
    assert agent_got["error"]["code"] == -32003


# ── framing, size, lifecycle (C.1, C.3) ────────────────────────────────


@pytest.mark.rule("acp.one-message-per-frame")
def test_large_message_arrives_whole(daemon: Daemon, ad_hoc: dict[str, Any], scope: Path) -> None:
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        client.initialize()
        session = client.new_session(str(scope))
        client.prompt(session["sessionId"], "big")
    finally:
        client.close()
    assert len(client.text()) == 1_000_000


@pytest.mark.rule("acp.every-message-goes-through-the-policy")
def test_a_batch_or_an_unreadable_line_reaches_neither_side(
    daemon: Daemon, ad_hoc: dict[str, Any], scope: Path
) -> None:
    """A client's batch and a line that is no JSON never reach the agent, even with a message
    the policy would let through in it; the agent's own never reach the client.

    If this fails: a message hidden in a batch reaches the other side unjudged."""
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        client.initialize()
        session = client.new_session(str(scope))["sessionId"]
        client._send_line("not json")
        new = {"jsonrpc": "2.0", "id": 99, "method": "session/new", "params": {"cwd": str(scope)}}
        client._send_line(json.dumps([new]))
        # the fake agent reads one JSON object a line: either would have ended it
        assert report(client, session)["methods"].count("session/new") == 1
        client.updates.clear()
        client.prompt(session, "batch")
        assert client.text() == "ok"  # not the batch's "hidden"
    finally:
        client.close()


def _close_of(ws: Any) -> tuple[int, str]:
    try:
        while True:
            ws.recv(timeout=30)
    except ConnectionClosed as e:
        assert e.rcvd is not None
        return e.rcvd.code, e.rcvd.reason


def _conversation(daemon: Daemon, agent: dict[str, Any], scope: Path) -> tuple[str, str]:
    """A whole conversation as its client sees it (the agent's session id made "S"), and the
    sandbox it ran in."""
    client = daemon.connect(agent["acpUrl"])
    try:
        got = [client.initialize()]
        got.append(client.new_session(str(scope)))
        session = got[-1]["sessionId"]
        got.append(client.prompt(session, "hello"))
        with daemon.http() as c:
            (connection,) = c.get(f"/v1/agents/{agent['id']}").json()["connections"]
    finally:
        client.close()
    return json.dumps(got + client.updates).replace(session, "S"), connection["sandbox"]


@pytest.mark.rule("acp.the-sandbox-is-not-in-acp")
def test_a_conversation_is_the_same_whatever_the_agent_s_network(daemon: Daemon) -> None:
    """The same conversation with agents that differ only by their network (none, filtered,
    open) gives their clients the same messages, naming no sandbox, image or proxy.

    If this fails: a client works with one agent and not another, or learns the computer's
    internals."""
    seen = {}
    for network in ("none", "filtered", "open"):
        scope = daemon.make_scope()
        agent = daemon.create_ad_hoc("fake", scope, network=network)
        conversation, sandbox = _conversation(daemon, agent, scope)
        seen[network] = conversation.replace(str(scope), "SCOPE")
        for internal in (sandbox, "handler-ai-", "proxy", "podman", "container"):
            assert internal not in conversation, f"{network}: {internal}"
    assert seen["none"] == seen["filtered"] == seen["open"]


def _logged(daemon: Daemon, text: str) -> bool:
    deadline = time.monotonic() + 10
    while text not in Path(daemon.log.name).read_text(errors="replace"):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    return True


@pytest.mark.rule("acp.stderr-never-reaches-a-client")
def test_the_agent_s_stderr_goes_to_handlerd_s_log_only(
    daemon: Daemon, ad_hoc: dict[str, Any], scope: Path
) -> None:
    """If this fails: a harness's debug output, a stack trace with a token in it, shows in your
    conversation, or breaks the client's parsing."""
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        client.initialize()
        session = client.new_session(str(scope))["sessionId"]
        client.prompt(session, "stderr")
        client.prompt(session, "hello")  # anything relayed after it has arrived
    finally:
        client.close()
    assert "stderr of" not in json.dumps(client.updates)
    assert _logged(daemon, f"stderr of {session}")


OVER_THE_LIMIT = "x" * (DEFAULT_MAX_MESSAGE_BYTES + 1)


@pytest.mark.rule("acp.too-big-closes")
def test_a_client_message_over_16_mib_closes_1009(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    """If this fails: one huge message from a client fills handlerd's memory."""
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(ad_hoc["acpUrl"], subprotocols=protocols, max_size=None) as ws:  # ty: ignore[invalid-argument-type]
        ws.send(OVER_THE_LIMIT)
        assert _close_of(ws)[0] == AcpCloseCode.MESSAGE_TOO_BIG


@pytest.mark.rule("acp.too-big-closes")
def test_an_agent_message_over_16_mib_closes_1009(
    daemon: Daemon, ad_hoc: dict[str, Any], scope: Path
) -> None:
    """If this fails: one huge message from an agent fills handlerd's memory, or reaches the
    client cut."""
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(ad_hoc["acpUrl"], subprotocols=protocols, max_size=None) as ws:  # ty: ignore[invalid-argument-type]

        def request(rid: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
            ws.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}))
            while (msg := json.loads(ws.recv(timeout=10))).get("id") != rid:
                pass
            return msg["result"]

        request(1, "initialize", {"protocolVersion": 1})
        session = request(2, "session/new", {"cwd": str(scope), "mcpServers": []})["sessionId"]
        prompt = {"sessionId": session, "prompt": [{"type": "text", "text": "huge"}]}
        ws.send(
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "session/prompt", "params": prompt})
        )
        assert _close_of(ws) == (AcpCloseCode.MESSAGE_TOO_BIG, "agent message too big")


@pytest.mark.rule("acp.one-message-per-frame")
def test_binary_frame_closes_1003(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(ad_hoc["acpUrl"], subprotocols=protocols) as ws:  # ty: ignore[invalid-argument-type]
        ws.send(b"\x00\x01")
        assert _close_of(ws)[0] == 1003


@pytest.mark.rule("connection.one-sandbox-per-connection")
def test_agent_exit_closes_1011(daemon: Daemon, ad_hoc: dict[str, Any], scope: Path) -> None:
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(ad_hoc["acpUrl"], subprotocols=protocols) as ws:  # ty: ignore[invalid-argument-type]
        ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))
        ws.recv(timeout=30)
        new = {"cwd": str(scope), "mcpServers": []}
        ws.send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": new}))
        ws.recv(timeout=30)
        prompt = {"sessionId": "s1", "prompt": [{"type": "text", "text": "exit"}]}
        ws.send(
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "session/prompt", "params": prompt})
        )
        assert _close_of(ws) == (1011, "agent exited (3)")


def _connections(daemon: Daemon, agent_id: str) -> list[Any]:
    with daemon.http() as c:
        return c.get(f"/v1/agents/{agent_id}").json()["connections"]


@pytest.mark.rule("connection.one-sandbox-per-connection")
def test_connection_tracked_and_released(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    client = daemon.connect(ad_hoc["acpUrl"])
    client.initialize()
    assert len(_connections(daemon, ad_hoc["id"])) == 1
    client.close()
    deadline = time.monotonic() + 30
    while _connections(daemon, ad_hoc["id"]) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert _connections(daemon, ad_hoc["id"]) == []


def test_deleting_the_agent_closes_connections(daemon: Daemon, scope: Path) -> None:
    ad_hoc = daemon.create_ad_hoc("fake", scope, network="open")
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(ad_hoc["acpUrl"], subprotocols=protocols) as ws:  # ty: ignore[invalid-argument-type]
        ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))
        ws.recv(timeout=30)
        with daemon.http() as c:
            assert c.delete(f"/v1/agents/{ad_hoc['id']}").status_code == 204
        code, _ = _close_of(ws)
        assert code == 1011
    with daemon.http() as c:
        assert c.get(f"/v1/agents/{ad_hoc['id']}").status_code == 404


def test_health_is_public(daemon: Daemon) -> None:
    assert httpx.get(f"{daemon.base_url}/v1/health").json()["status"] == "ok"
