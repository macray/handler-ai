"""Contract C conformance: the ACP WebSocket endpoint of a real handlerd (docs/dev/contracts.md §C).

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

from handler_contracts import ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX

from ..support.acp_client import AcpClient, AcpError
from ..support.daemon import UI_ORIGIN, Daemon


@pytest.fixture
def scope(daemon: Daemon) -> Path:
    return daemon.make_scope()


@pytest.fixture
def ad_hoc(daemon: Daemon, scope: Path) -> dict[str, Any]:
    return daemon.create_ad_hoc("fake", scope, bindings=["browser"], model="big-model")


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


def test_auth_and_origin(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    url, good = ad_hoc["acpUrl"], BEARER_SUBPROTOCOL_PREFIX + daemon.token
    assert _status(daemon, url, [ACP_SUBPROTOCOL]) == 401
    assert _status(daemon, url, [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + "wrong"]) == 401
    assert _status(daemon, url, [ACP_SUBPROTOCOL, good], origin="http://evil.test") == 403
    assert _status(daemon, url, [ACP_SUBPROTOCOL, good], origin=UI_ORIGIN) == 101
    missing = f"{daemon.ws_base}/v1/agents/nope/acp"
    assert _status(daemon, missing, [ACP_SUBPROTOCOL, good]) == 404


def test_subprotocol_negotiated(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(ad_hoc["acpUrl"], subprotocols=protocols) as ws:  # ty: ignore[invalid-argument-type]
        assert ws.subprotocol == ACP_SUBPROTOCOL


# ── C.4 policy, end to end ─────────────────────────────────────────────


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
    assert first["prompt"] == ["Answer briefly.\n\nreport"]
    assert second["prompt"] == ["report"]


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


def test_large_message_arrives_whole(daemon: Daemon, ad_hoc: dict[str, Any], scope: Path) -> None:
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        client.initialize()
        session = client.new_session(str(scope))
        client.prompt(session["sessionId"], "big")
    finally:
        client.close()
    assert len(client.text()) == 1_000_000


def test_non_object_messages_are_dropped(
    daemon: Daemon, ad_hoc: dict[str, Any], scope: Path
) -> None:
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        client._send_line("not json")
        client._send_line(json.dumps([{"jsonrpc": "2.0", "id": 99, "method": "initialize"}]))
        client.initialize()  # the connection is still usable
    finally:
        client.close()


def _close_of(ws: Any) -> tuple[int, str]:
    try:
        while True:
            ws.recv(timeout=30)
    except ConnectionClosed as e:
        assert e.rcvd is not None
        return e.rcvd.code, e.rcvd.reason


def test_binary_frame_closes_1003(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(ad_hoc["acpUrl"], subprotocols=protocols) as ws:  # ty: ignore[invalid-argument-type]
        ws.send(b"\x00\x01")
        assert _close_of(ws)[0] == 1003


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
