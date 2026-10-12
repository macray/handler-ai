"""Contract F conformance: daemon-held sessions of a real handlerd (docs/dev/contracts.md §F).

The agent is the fake agent (tests/support/fake_agent.py), run on the host by the fake sandbox
(tests/support/fake_sandbox.py). The daemon runs
with a 2 s idle timeout, so unattached idle sessions stop quickly.
"""

import json
import time
from pathlib import Path
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

from handler_contracts import ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX

from ..support.acp_client import AcpClient, AcpError
from ..support.daemon import Daemon


@pytest.fixture
def ad_hoc(daemon: Daemon) -> dict[str, Any]:
    return daemon.create_ad_hoc("fake", daemon.make_scope(), bindings=["browser"])


def create_session(daemon: Daemon, ad_hoc: dict[str, Any], **body: Any) -> dict[str, Any]:
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": ad_hoc["id"]} | body)
        assert r.status_code == 202, r.text
        return r.json()


def get_session(daemon: Daemon, sid: str) -> dict[str, Any]:
    with daemon.http() as c:
        return c.get(f"/v1/sessions/{sid}").json()


def wait_state(daemon: Daemon, sid: str, state: str, timeout: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session = get_session(daemon, sid)
        if session["state"] == state:
            return session
        time.sleep(0.1)
    raise AssertionError(f"session {sid} never reached {state}: {session}")


def attach(daemon: Daemon, session: dict[str, Any]) -> tuple[AcpClient, dict[str, Any]]:
    """initialize + session/load (the attach proper); returns the client and the load result,
    with the `_handler/session_state` that follows it under "state"."""
    client = daemon.connect(session["acpUrl"])
    client.initialize()
    acp_id = get_session(daemon, session["id"])["acpSessionId"]
    loaded = client.request(
        "session/load", {"sessionId": acp_id, "cwd": session["scope"], "mcpServers": []}
    )
    return client, loaded | {"state": client.wait_notification("_handler/session_state")}


def stops(daemon: Daemon, sid: str) -> list[str]:
    """How the session stopped each time (F.5 `how`), from its event log."""
    log = daemon.config_dir.parent / "state" / "sessions" / sid / "events.ndjson"
    events = [json.loads(line) for line in log.read_text().splitlines()]
    return [e["how"] for e in events if e["kind"] == "lifecycle" and e["event"] == "stopped"]


def send_prompt(client: AcpClient, acp_id: str, text: str, rid: int = 900) -> None:
    """A prompt whose answer we do not wait for."""
    params = {"sessionId": acp_id, "prompt": [{"type": "text", "text": text}]}
    client.send({"id": rid, "method": "session/prompt", "params": params})


def test_create_attach_prompt(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    session = create_session(daemon, ad_hoc)
    assert session["state"] == "starting" and session["acpUrl"].endswith(
        f"/v1/sessions/{session['id']}/acp"
    )
    client, loaded = attach(daemon, session)
    try:
        assert loaded["modes"]["currentModeId"] == "yolo"  # P7 applied by the daemon
        assert loaded["state"] == {
            "state": "running",
            "busy": False,
            "turnStartedAt": None,
            "pendingPermissions": 0,
            "attached": 1,
        }
        acp_id = get_session(daemon, session["id"])["acpSessionId"]
        assert client.prompt(acp_id, "hello")["stopReason"] == "end_turn"
        assert client.text() == "ok"
        client.prompt(acp_id, "report")
        # P8 applies to the daemon's own session/new too
        assert json.loads(client.text()[2:])["mcpServers"] == ["playwright"]
        with pytest.raises(AcpError, match="-32010"):
            client.request("session/new", {"cwd": session["scope"], "mcpServers": []})
    finally:
        client.close()
    listed = get_session(daemon, session["id"])
    assert listed["attached"] == 0 and listed["state"] == "running"  # detaching stops nothing


def test_instructions_go_with_the_first_prompt(daemon: Daemon) -> None:
    """A session created without a request: the agent's instructions go with the first prompt a
    client sends, before its text, and only with that one (F.3)."""
    agent = daemon.create_ad_hoc("fake", daemon.make_scope(), instructions="Be brief.")
    session = create_session(daemon, agent)
    client, _ = attach(daemon, session)
    try:
        acp_id = get_session(daemon, session["id"])["acpSessionId"]
        client.prompt(acp_id, "hello")
        client.prompt(acp_id, "again")
    finally:
        client.close()
    log = daemon.config_dir.parent / "state" / "sessions" / session["id"] / "events.ndjson"
    events = [json.loads(line) for line in log.read_text().splitlines()]
    sent = [
        e["update"]["content"]["text"]
        for e in events
        if e["kind"] == "update" and e["update"]["sessionUpdate"] == "user_message_chunk"
    ]
    assert sent == ["Be brief.\n\nhello", "again"]


def test_origin(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    """Who started a session (F.3): the client says; an interactive one keeps no answer."""
    session = create_session(daemon, ad_hoc, prompt="hello", origin="cli")
    assert session["origin"] == "cli"
    wait_state(daemon, session["id"], "running")
    assert "answer" not in get_session(daemon, session["id"])
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": ad_hoc["id"], "origin": "task"})
        assert r.status_code == 422


def test_reload_during_a_turn_keeps_it(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    """The first tab goes away while the agent waits for a permission; the reload answers it."""
    session = create_session(daemon, ad_hoc)
    first, _ = attach(daemon, session)
    acp_id = get_session(daemon, session["id"])["acpSessionId"]
    first.send(
        {
            "id": 900,
            "method": "session/prompt",
            "params": {"sessionId": acp_id, "prompt": [{"type": "text", "text": "permission"}]},
        }
    )
    deadline = time.monotonic() + 30
    while get_session(daemon, session["id"])["pendingPermissions"] == 0:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    first.close()  # reload: the turn is still in progress
    time.sleep(3)  # longer than the idle timeout: a busy session is not stopped
    assert get_session(daemon, session["id"])["busy"] is True

    second, loaded = attach(daemon, session)
    try:
        replayed = [
            u["params"]["update"] for u in second.updates if u["method"] == "session/update"
        ]
        assert replayed[0] == {
            "sessionUpdate": "user_message_chunk",
            "content": {"type": "text", "text": "permission"},
        }
        assert loaded["state"]["busy"] is True and loaded["state"]["pendingPermissions"] == 1
        assert loaded["state"]["turnStartedAt"]  # the elapsed time survives a reload
        ended = second.wait_notification("_handler/turn_ended")  # the re-sent request was answered
        assert ended == {"stopReason": "end_turn"}
        assert len(second.permission_requests) == 1
        assert '"optionId": "no"' in second.text()  # answered by the second tab
    finally:
        second.close()


def test_several_attachments_see_the_same_session(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    """F.7: a prompt from one client is shown to the other, with the turn and the busy state."""
    session = create_session(daemon, ad_hoc)
    first, _ = attach(daemon, session)
    second, loaded = attach(daemon, session)
    try:
        assert loaded["state"]["attached"] == 2
        acp_id = get_session(daemon, session["id"])["acpSessionId"]
        assert first.prompt(acp_id, "hello")["stopReason"] == "end_turn"
        assert second.wait_notification("_handler/turn_ended") == {"stopReason": "end_turn"}
        updates = [u["params"]["update"] for u in second.updates if u["method"] == "session/update"]
        assert updates[-2:] == [
            {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "hello"}},
            {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ok"}},
        ]
        states = [
            u["params"]["busy"] for u in second.updates if u["method"] == "_handler/session_state"
        ]
        assert True in states  # the turn was shown as in progress
        first.request("session/set_mode", {"sessionId": acp_id, "modeId": "edits"})
        mode = second.wait_notification("session/update")
        assert mode["update"] == {"sessionUpdate": "current_mode_update", "currentModeId": "edits"}
        assert get_session(daemon, session["id"])["attached"] == 2
    finally:
        first.close()
        second.close()


def test_first_permission_answer_wins(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    session = create_session(daemon, ad_hoc)
    watcher, _ = attach(daemon, session)
    watcher.on_permission = "ignore"
    answerer, _ = attach(daemon, session)
    try:
        acp_id = get_session(daemon, session["id"])["acpSessionId"]
        assert answerer.prompt(acp_id, "permission")["stopReason"] == "end_turn"
        resolved = watcher.wait_notification("_handler/permission_resolved")
        assert resolved["toolCallId"] == "t1"
        assert resolved["outcome"] == {"outcome": "selected", "optionId": "no"}
        assert len(watcher.permission_requests) == 1  # it was asked too
        # a late answer is dropped: the agent got exactly one
        watcher.send({"id": resolved["requestId"], "result": {"outcome": {"outcome": "cancelled"}}})
        assert answerer.prompt(acp_id, "hello")["stopReason"] == "end_turn"
        assert '"optionId": "no"' in answerer.text()
    finally:
        watcher.close()
        answerer.close()


def test_too_many_attachments_close_the_oldest(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    """HANDLER_SESSION_MAX_ATTACH is 2 in these tests: a third attachment closes the first."""
    session = create_session(daemon, ad_hoc)
    wait_state(daemon, session["id"], "running")
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(session["acpUrl"], subprotocols=protocols) as old:  # ty: ignore[invalid-argument-type]
        old.send('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1}}')
        old.recv()
        second, _ = attach(daemon, session)
        third, _ = attach(daemon, session)
        with pytest.raises(ConnectionClosed) as closed:
            while True:
                old.recv(timeout=10)
        assert closed.value.rcvd is not None
        assert (closed.value.rcvd.code, closed.value.rcvd.reason) == (4001, "attached elsewhere")
        second.close()
        third.close()
    with daemon.http() as c:
        assert len(c.get(f"/v1/agents/{ad_hoc['id']}").json()["connections"]) == 1  # one sandbox


def test_turn_in_progress_refuses_a_second_prompt(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    session = create_session(daemon, ad_hoc)
    client, _ = attach(daemon, session)
    try:
        acp_id = get_session(daemon, session["id"])["acpSessionId"]
        send_prompt(client, acp_id, "sleep")
        time.sleep(0.3)
        with pytest.raises(AcpError, match="-32011"):
            client.prompt(acp_id, "hello")
        client.send({"method": "session/cancel", "params": {"sessionId": acp_id}})
    finally:
        client.close()


def test_stop_then_attach_restarts_and_replays(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    session = create_session(daemon, ad_hoc)
    client, _ = attach(daemon, session)
    acp_id = get_session(daemon, session["id"])["acpSessionId"]
    client.prompt(acp_id, "hello")
    client.close()
    with daemon.http() as c:
        assert c.post(f"/v1/sessions/{session['id']}/stop").json()["state"] == "stopped"
    assert stops(daemon, session["id"]) == ["explicit"]

    again, loaded = attach(daemon, session)  # restarts the agent: session/load, P7 again
    try:
        assert loaded["modes"]["currentModeId"] == "yolo"
        assert again.text() == "ok"  # our log, not the agent's replay ("resumed …")
        assert again.prompt(acp_id, "hello")["stopReason"] == "end_turn"
    finally:
        again.close()


def test_a_session_runs_with_the_model_asked_for(daemon: Daemon) -> None:
    """D.1, F.3, D.19: a session runs with the model asked for, one of the agent's (default: its
    first) or another, and resumes with it, also once the agent no longer lists it."""
    small, big = ({"account": "fake", "model": m} for m in ("small", "big-model"))
    agent = daemon.create_ad_hoc(None, daemon.make_scope(), models=[small, big])
    first = create_session(daemon, agent)
    assert (first["harness"], first["account"], first["model"]) == ("fake", "fake", "small")
    session = create_session(daemon, agent, model=big)
    assert session["model"] == "big-model"
    wait_state(daemon, first["id"], "running")
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "model": {"account": "nope"}})
        assert r.status_code == 400 and r.json()["title"] == "model access unusable"
    other = create_session(daemon, agent, model={"account": "fake", "model": "tiny"})
    assert other["model"] == "tiny"  # not one of the agent's
    wait_state(daemon, other["id"], "running")
    wait_state(daemon, session["id"], "running")
    with daemon.http() as c:
        for sid in (first["id"], session["id"], other["id"]):
            assert c.post(f"/v1/sessions/{sid}/stop").status_code == 200
        body = {"models": [{"account": "echo-box"}], "scope": agent["scope"]}
        assert c.put(f"/v1/agents/{agent['id']}", json=body).status_code == 200
    client, _ = attach(daemon, session)  # its own model, which the agent no longer lists
    client.close()
    assert get_session(daemon, session["id"])["model"] == "big-model"


def test_stopped_before_its_first_turn_restarts_fresh(
    daemon: Daemon, ad_hoc: dict[str, Any]
) -> None:
    """F.6: the agent kept nothing to load (Vibe saves a session at its first turn's end): a
    new agent session, still known to the clients by the recorded id."""
    session = create_session(daemon, ad_hoc)
    wait_state(daemon, session["id"], "running")
    acp_id = get_session(daemon, session["id"])["acpSessionId"]
    with daemon.http() as c:
        assert c.post(f"/v1/sessions/{session['id']}/stop").json()["state"] == "stopped"

    client, loaded = attach(daemon, session)
    try:
        assert loaded["state"]["state"] == "running" and loaded["modes"]["currentModeId"] == "yolo"
        assert get_session(daemon, session["id"])["acpSessionId"] == acp_id
        client.prompt(acp_id, "report")
        report = json.loads(client.text())
        assert "session/load" not in report["methods"] and report["promptSession"] == "own"
        updates = [u for u in client.updates if u.get("method") == "session/update"]
        assert updates and {u["params"]["sessionId"] for u in updates} == {acp_id}
    finally:
        client.close()
    with daemon.http() as c:
        assert c.post(f"/v1/sessions/{session['id']}/stop").json()["state"] == "stopped"

    client, _ = attach(daemon, session)  # it had a turn: the agent's own session is loaded
    try:
        client.prompt(acp_id, "report")
        chunks = [u for u in client.updates if u.get("method") == "session/update"]
        report = json.loads(chunks[-1]["params"]["update"]["content"]["text"])  # not the replay
        assert "session/load" in report["methods"] and report["promptSession"] == "own"
    finally:
        client.close()


def test_idle_session_stops_and_can_be_deleted(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    session = create_session(daemon, ad_hoc)
    wait_state(daemon, session["id"], "running")
    stopped = wait_state(daemon, session["id"], "stopped", timeout=10)  # 2 s idle, no client
    assert "error" not in stopped and stopped["canResume"] is True
    assert stops(daemon, session["id"]) == ["idle"]
    folder = daemon.config_dir.parent / "state" / "sessions" / session["id"]
    assert (folder / "events.ndjson").exists()
    with daemon.http() as c:
        assert c.delete(f"/v1/sessions/{session['id']}").status_code == 204
        assert c.get(f"/v1/sessions/{session['id']}").status_code == 404
    assert not folder.exists()


def test_unknown_session_and_auth(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    session = create_session(daemon, ad_hoc)
    good = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    for url, protocols, status in [
        (f"{daemon.ws_base}/v1/sessions/s_nope/acp", good, 404),
        (session["acpUrl"], [ACP_SUBPROTOCOL], 401),
    ]:
        with pytest.raises(InvalidStatus) as denied:
            connect(url, subprotocols=protocols)  # ty: ignore[invalid-argument-type]
        assert denied.value.response.status_code == status
    with daemon.http() as c:
        assert c.post("/v1/sessions", json={"agentId": "nope"}).status_code == 404
        ids = [s["id"] for s in c.get("/v1/sessions", params={"agentId": ad_hoc["id"]}).json()]
        assert ids == [session["id"]]


def test_session_folder_is_private(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    session = create_session(daemon, ad_hoc)
    folder = daemon.config_dir.parent / "state" / "sessions" / session["id"]
    assert Path(folder).stat().st_mode & 0o777 == 0o700
