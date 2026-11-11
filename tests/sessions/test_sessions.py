"""Contract F conformance: daemon-held sessions of a real handlerd (contract F).

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
from handler_harness.render import FILTERED_NETWORK

from ..support.acp_client import AcpClient, AcpError
from ..support.daemon import Daemon


@pytest.fixture
def ad_hoc(daemon: Daemon) -> dict[str, Any]:
    return daemon.create_ad_hoc(
        "fake", daemon.make_scope(), addons=[{"addon": "fake-browser", "binding": "browser"}]
    )


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


@pytest.mark.rule(
    "session.outlives-its-clients",
    "attach.clients-cannot-bypass-the-policy",
    "attach.one-conversation-per-session",
    "policy.starts-in-its-own-mode",
    "policy.its-tools-mcp-servers-win",
)
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
            "lastStopReason": None,
        }
        acp_id = get_session(daemon, session["id"])["acpSessionId"]
        assert client.prompt(acp_id, "hello")["stopReason"] == "end_turn"
        assert client.text() == "ok"
        client.prompt(acp_id, "report")
        # P8 applies to the daemon's own session/new too
        assert json.loads(client.text()[2:])["mcpServers"] == ["fake-browser"]
        with pytest.raises(AcpError, match="-32010"):
            client.request("session/new", {"cwd": session["scope"], "mcpServers": []})
    finally:
        client.close()
    listed = get_session(daemon, session["id"])
    assert listed["attached"] == 0 and listed["state"] == "running"  # detaching stops nothing


@pytest.mark.rule(
    "session.instructions-go-with-the-first-turn",
    "history.the-log-is-the-history",
    "launch.a-filtered-agent-is-told",
)
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
    assert sent == [f"Be brief.\n\n{FILTERED_NETWORK}\n\nhello", "again"]  # filtered


def test_an_agent_s_title_made_of_handler_s_words_is_not_taken(daemon: Daemon) -> None:
    """Codex titles a session with the start of its first prompt: Handler's words when the
    agent's instructions went first. If this fails: every filtered Codex session is titled with
    Handler's network instruction, shown as the person's words in the session list."""
    agent = daemon.create_ad_hoc("fake", daemon.make_scope(), instructions="Be brief.")
    session = create_session(daemon, agent, prompt="retitle")
    log = daemon.config_dir.parent / "state" / "sessions" / session["id"] / "events.ndjson"
    deadline = time.monotonic() + 30
    while "titled" not in (log.read_text() if log.exists() else ""):
        assert time.monotonic() < deadline
        time.sleep(0.1)
    assert get_session(daemon, session["id"])["title"] == "retitle"  # the person's request
    assert "session_info_update" not in log.read_text()  # nor shown to a client
    client, _ = attach(daemon, session)
    try:
        acp_id = get_session(daemon, session["id"])["acpSessionId"]
        client.prompt(acp_id, "retitle")  # the person's words alone: the agent's title is taken
    finally:
        client.close()
    assert get_session(daemon, session["id"])["title"] == "retitle..."


def test_origin(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    """Who started a session (F.3): the client says; an interactive one keeps no answer."""
    session = create_session(daemon, ad_hoc, prompt="hello", origin="cli")
    assert session["origin"] == "cli"
    wait_state(daemon, session["id"], "running")
    assert "answer" not in get_session(daemon, session["id"])
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": ad_hoc["id"], "origin": "task"})
        assert r.status_code == 422


@pytest.mark.rule(
    "session.outlives-its-clients",
    "session.idle-stop-spares-work-in-progress",
    "attach.permission-requests-wait-for-a-client",
    "history.the-log-is-the-history",
)
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
            "content": {"type": "text", "text": f"{FILTERED_NETWORK}\n\npermission"},
        }  # its first prompt: what its filtered network means first
        assert loaded["state"]["busy"] is True and loaded["state"]["pendingPermissions"] == 1
        assert loaded["state"]["turnStartedAt"]  # the elapsed time survives a reload
        ended = second.wait_notification("_handler/turn_ended")  # the re-sent request was answered
        assert ended == {"stopReason": "end_turn"}
        assert len(second.permission_requests) == 1
        assert '"optionId": "no"' in second.text()  # answered by the second tab
    finally:
        second.close()


@pytest.mark.rule("attach.every-client-sees-the-same-conversation")
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
        hello = {"type": "text", "text": f"{FILTERED_NETWORK}\n\nhello"}  # the first prompt
        assert updates[-2:] == [
            {"sessionUpdate": "user_message_chunk", "content": hello},
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


@pytest.mark.rule("attach.the-first-permission-answer-wins")
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


@pytest.mark.rule("session.one-sandbox-at-a-time", "attach.at-most-8-clients")
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


@pytest.mark.rule("attach.one-turn-at-a-time")
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


@pytest.mark.rule("attach.a-late-client-learns-how-the-turn-ended")
def test_an_interrupted_turn_is_told_to_who_attaches_later(
    daemon: Daemon, ad_hoc: dict[str, Any]
) -> None:
    """F.7: a client that was away (a phone asleep) learns how the last turn ended."""
    session = create_session(daemon, ad_hoc)
    client, _ = attach(daemon, session)
    acp_id = get_session(daemon, session["id"])["acpSessionId"]
    send_prompt(client, acp_id, "sleep")
    time.sleep(0.3)
    client.send({"method": "session/cancel", "params": {"sessionId": acp_id}})
    while client.wait_notification("_handler/session_state")["busy"]:
        pass
    client.close()
    later, loaded = attach(daemon, session)
    try:
        assert loaded["state"]["lastStopReason"] == "cancelled"
        assert later.prompt(acp_id, "hello")["stopReason"] == "end_turn"
        assert later.wait_notification("_handler/session_state")["lastStopReason"] == "end_turn"
    finally:
        later.close()


@pytest.mark.rule(
    "session.attaching-resumes-a-stopped-session",
    "history.the-log-is-the-history",
    "policy.starts-in-its-own-mode",
)
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


def ran_with(daemon: Daemon, session: dict[str, Any]) -> str:
    """The model the session's harness runs with (attached: started again if stopped)."""
    client, _ = attach(daemon, session)
    try:
        client.prompt(get_session(daemon, session["id"])["acpSessionId"], "report")
        chunks = [u for u in client.updates if u.get("method") == "session/update"]
        report = json.loads(chunks[-1]["params"]["update"]["content"]["text"])  # not the replay
        return report["options"]["model"]
    finally:
        client.close()


@pytest.mark.rule("session.runs-with-the-model-asked-for")
def test_a_session_runs_with_the_model_asked_for(daemon: Daemon) -> None:
    """D.1, F.3, D.19: a session runs with the model asked for, the agent's (the default) or
    another, and resumes with it; started with the agent's, it resumes with the agent's new one
    on the same harness and access, if any."""
    agent = daemon.create_ad_hoc("fake", daemon.make_scope(), model="small")
    first = create_session(daemon, agent)
    assert (first["harness"], first["account"], first["model"]) == ("fake", "fake", "small")
    session = create_session(daemon, agent, model={"account": "fake", "model": "big-model"})
    assert session["model"] == "big-model"
    wait_state(daemon, first["id"], "running")
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "model": {"account": "nope"}})
        assert r.status_code == 400 and r.json()["title"] == "model access unusable"
    wait_state(daemon, session["id"], "running")
    assert ran_with(daemon, session) == "big-model"  # not the agent's on that account
    with daemon.http() as c:
        for sid in (first["id"], session["id"]):
            assert c.post(f"/v1/sessions/{sid}/stop").status_code == 200
        body = {"model": {"account": "fake", "model": "medium"}, "scope": agent["scope"]}
        assert c.put(f"/v1/agents/{agent['id']}", json=body).status_code == 200
    assert ran_with(daemon, session) == "big-model"  # picked for it alone: as it was
    assert ran_with(daemon, first) == "medium"  # the agent's, changed since
    assert get_session(daemon, session["id"])["model"] == "big-model"


@pytest.mark.rule("session.attaching-resumes-a-stopped-session")
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


@pytest.mark.rule("session.a-start-that-fails-says-why", "image.a-launch-never-builds-one")
def test_an_image_not_built_leaves_it_stopped_until_it_is(
    daemon: Daemon, ad_hoc: dict[str, Any]
) -> None:
    """F.1, A.7: nothing launched, the build that makes the image said; it starts once built."""
    missing = daemon.config_dir.parent / "fake-ran" / "harness-image-missing"
    missing.touch()
    try:
        session = create_session(daemon, ad_hoc)
        stopped = wait_state(daemon, session["id"], "stopped")
        assert stopped["missingImage"] == "fake"
        assert "`handler image rebuild fake`" in stopped["error"]
    finally:
        missing.unlink()
    client, _ = attach(daemon, session)  # built now: it starts
    try:
        running = get_session(daemon, session["id"])
        assert running["state"] == "running"
        assert "missingImage" not in running and "error" not in running
    finally:
        client.close()


@pytest.mark.rule("session.a-first-request-waits-for-its-image")
def test_the_first_request_is_sent_once_the_image_is_built(daemon: Daemon) -> None:
    """F.1, F.3: the request typed before the image exists is kept, said, and sent with the
    agent's instructions once the session starts; once only."""
    agent = daemon.create_ad_hoc("fake", daemon.make_scope(), instructions="Be brief.")
    missing = daemon.config_dir.parent / "fake-ran" / "harness-image-missing"
    missing.touch()
    try:
        session = create_session(daemon, agent, prompt="report")
        stopped = wait_state(daemon, session["id"], "stopped")
        assert stopped["missingImage"] == "fake" and stopped["request"] == "report"
        with pytest.raises(EOFError):  # still not built: its start refused, the request kept
            attach(daemon, session)
        assert wait_state(daemon, session["id"], "stopped")["request"] == "report"
    finally:
        missing.unlink()
    log = daemon.config_dir.parent / "state" / "sessions" / session["id"] / "events.ndjson"

    def sent() -> list[str]:
        events = [json.loads(line) for line in log.read_text().splitlines()]
        return [
            e["update"]["content"]["text"]
            for e in events
            if e["kind"] == "update" and e["update"]["sessionUpdate"] == "user_message_chunk"
        ]

    client, _ = attach(daemon, session)  # built now: it starts, with the request
    try:
        deadline = time.monotonic() + 30
        while not sent() or get_session(daemon, session["id"])["busy"]:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert "request" not in get_session(daemon, session["id"])
    finally:
        client.close()
    wait_state(daemon, session["id"], "stopped", timeout=10)  # idle
    attach(daemon, session)[0].close()  # started again: nothing sent again
    assert sent() == [f"Be brief.\n\n{FILTERED_NETWORK}\n\nreport"]


@pytest.mark.rule("session.a-start-that-fails-says-why")
def test_a_sandbox_that_did_not_start_says_why(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    """Its launcher's own reason (A.1), not only its exit code."""
    fails = daemon.config_dir.parent / "fake-ran" / "setup-fails"
    fails.touch()
    try:
        session = create_session(daemon, ad_hoc)
        failed = wait_state(daemon, session["id"], "failed")
    finally:
        fails.unlink()
    assert failed["error"] == "setup failed: the fake was told to"


@pytest.mark.rule("network.a-stopped-filter-ends-its-sandbox")
def test_a_sandbox_ended_by_its_launcher_says_why(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    """A running session's sandbox ended by its launcher, its filter stopped (A.1's 67): the
    session stops with the launcher's own reason."""
    ran = daemon.config_dir.parent / "fake-ran"
    (ran / "filter-watched").touch()
    try:
        session = create_session(daemon, ad_hoc)
        wait_state(daemon, session["id"], "running")
        (ran / "filter-stopped").touch()
        stopped = wait_state(daemon, session["id"], "stopped")
    finally:
        for name in ("filter-watched", "filter-stopped"):
            (ran / name).unlink(missing_ok=True)
    assert stopped["error"] == "its network filter stopped, so the sandbox was ended"


@pytest.mark.rule("session.idle-stop-spares-work-in-progress", "session.only-you-delete-a-session")
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


@pytest.mark.rule("attach.only-with-the-token")
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


@pytest.mark.rule("session.its-folder-is-yours-alone")
def test_session_folder_is_private(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    session = create_session(daemon, ad_hoc)
    folder = daemon.config_dir.parent / "state" / "sessions" / session["id"]
    assert Path(folder).stat().st_mode & 0o777 == 0o700


def _log(daemon: Daemon, sid: str) -> list[dict[str, Any]]:
    folder = daemon.config_dir.parent / "state" / "sessions" / sid
    return [json.loads(line) for line in (folder / "events.ndjson").read_text().splitlines()]


@pytest.mark.rule("session.a-daemon-restart-stops-its-sessions")
def test_a_crashed_daemon_s_live_sessions_are_stopped_when_it_starts(
    daemon: Daemon, ad_hoc: dict[str, Any]
) -> None:
    """handlerd killed with a session in a turn: started again, it lists that session stopped,
    its turn ended (`daemon_restarted`); one that never got a conversation is failed.

    If this fails: sessions show as running after a restart, with no sandbox behind them, or a
    turn stays open forever in their history."""
    in_turn = create_session(daemon, ad_hoc)
    client, _ = attach(daemon, in_turn)
    send_prompt(client, get_session(daemon, in_turn["id"])["acpSessionId"], "sleep")
    client.wait_notification("_handler/session_state")  # busy
    unstarted = create_session(daemon, ad_hoc)
    wait_state(daemon, unstarted["id"], "running")
    daemon.process.kill()
    daemon.process.wait(timeout=30)
    client.close()
    # as a crash during its start leaves it: live, no conversation yet
    record = daemon.config_dir.parent / "state" / "sessions" / unstarted["id"] / "session.json"
    data = json.loads(record.read_text())
    record.write_text(json.dumps(data | {"state": "starting", "acp_session_id": None}))
    daemon.restart()
    assert get_session(daemon, in_turn["id"])["state"] == "stopped"
    assert get_session(daemon, unstarted["id"])["state"] == "failed"
    turns = [e for e in _log(daemon, in_turn["id"]) if e["kind"] == "turn"]
    assert turns[-1]["phase"] == "end" and turns[-1]["stopReason"] == "daemon_restarted"
    assert stops(daemon, in_turn["id"])[-1] == "daemon_restarted"


@pytest.mark.rule("session.agent-exit-stops-the-session")
def test_an_agent_exiting_by_itself_closes_its_clients(
    daemon: Daemon, ad_hoc: dict[str, Any]
) -> None:
    """The agent exits in a turn: an attached client is closed with 4002, the session is stopped
    with the exit code, its turn logged as ended.

    If this fails: a client keeps waiting on a session with no agent behind it."""
    session = create_session(daemon, ad_hoc)
    acp_id = wait_state(daemon, session["id"], "running")["acpSessionId"]
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(session["acpUrl"], subprotocols=protocols) as ws:  # ty: ignore[invalid-argument-type]
        prompt = {"sessionId": acp_id, "prompt": [{"type": "text", "text": "exit"}]}
        ws.send(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "session/prompt", "params": prompt})
        )
        with pytest.raises(ConnectionClosed) as closed:
            while True:
                ws.recv(timeout=10)
    assert closed.value.rcvd is not None and closed.value.rcvd.code == 4002
    stopped = wait_state(daemon, session["id"], "stopped")
    assert "agent exited (3)" in stopped["error"]
    turns = [e for e in _log(daemon, session["id"]) if e["kind"] == "turn"]
    assert turns[-1]["phase"] == "end" and turns[-1]["stopReason"] == "stopped"


def _reattach(daemon: Daemon, session: dict[str, Any], after: int) -> AcpClient:
    """session/load with `afterSeq` (F.7): the log replayed from there."""
    client = daemon.connect(session["acpUrl"])
    client.initialize()
    params = {"cwd": session["scope"], "mcpServers": [], "_meta": {"handler.dev/afterSeq": after}}
    acp_id = get_session(daemon, session["id"])["acpSessionId"]
    client.request("session/load", {"sessionId": acp_id} | params)
    return client


def _seqs(client: AcpClient) -> list[int]:
    return [
        u["params"]["_meta"]["handler.dev/seq"]
        for u in client.updates
        if u["method"] == "session/update"
    ]


@pytest.mark.rule("attach.a-slow-client-never-holds-up-the-agent")
def test_a_client_attaching_again_after_its_last_seq_misses_nothing(
    daemon: Daemon, ad_hoc: dict[str, Any]
) -> None:
    """A client closed as too slow (or dropped) attaches again with the last `seq` it got: it is
    given every update after it, and none it already had.

    If this fails: a phone that fell behind loses part of the conversation, or shows it twice."""
    session = create_session(daemon, ad_hoc)
    dropped, _ = attach(daemon, session)
    acp_id = get_session(daemon, session["id"])["acpSessionId"]
    assert dropped.prompt(acp_id, "hello")["stopReason"] == "end_turn"
    last = max(_seqs(dropped))
    dropped.close()
    other, _ = attach(daemon, session)
    other.updates.clear()  # its replay
    other.prompt(acp_id, "report")
    missed = other.text()
    other.close()
    again = _reattach(daemon, session, after=last)
    whole = _reattach(daemon, session, after=0)
    try:
        assert again.text() == missed
        assert _seqs(again) == [s for s in _seqs(whole) if s > last] != []
    finally:
        again.close()
        whole.close()


@pytest.mark.rule("acp.every-message-goes-through-the-policy")
def test_a_batch_or_an_unreadable_line_reaches_neither_side_of_a_session(
    daemon: Daemon, ad_hoc: dict[str, Any]
) -> None:
    """A client's batch and a line that is no JSON never reach the session's agent, even with a
    message the policy would let through in it; the agent's own never reach the client.

    If this fails: a message hidden in a batch reaches the other side unjudged."""
    session = create_session(daemon, ad_hoc)
    client, _ = attach(daemon, session)
    acp_id = get_session(daemon, session["id"])["acpSessionId"]
    try:
        params = {"sessionId": acp_id, "modeId": "ask"}
        mode = {"jsonrpc": "2.0", "id": 99, "method": "session/set_mode", "params": params}
        client._send_line("not json")
        client._send_line(json.dumps([mode]))
        client.updates.clear()
        client.prompt(acp_id, "report")
        # the fake agent reads one JSON object a line: either would have ended it
        assert json.loads(client.text())["mode"] == "yolo"  # the session's own, not the batch's
        client.updates.clear()
        client.prompt(acp_id, "batch")
        assert client.text() == "ok"  # not the batch's "hidden"
    finally:
        client.close()


@pytest.mark.rule("acp.too-big-closes")
def test_a_session_whose_agent_sends_over_16_mib_is_stopped(
    daemon: Daemon, ad_hoc: dict[str, Any]
) -> None:
    """If this fails: one huge message from a session's agent fills handlerd's memory, or the
    session goes on with a conversation cut in two."""
    session = create_session(daemon, ad_hoc)
    client, _ = attach(daemon, session)
    try:
        send_prompt(client, get_session(daemon, session["id"])["acpSessionId"], "huge")
        wait_state(daemon, session["id"], "stopped")
    finally:
        client.close()
    (stopped,) = [e for e in _log(daemon, session["id"]) if e.get("event") == "stopped"]
    assert (stopped["detail"], stopped["how"]) == ("agent message too big", "error")


@pytest.mark.rule("acp.stderr-never-reaches-a-client")
def test_a_session_s_agent_s_stderr_goes_to_handlerd_s_log_only(
    daemon: Daemon, ad_hoc: dict[str, Any]
) -> None:
    """If this fails: a harness's debug output, a stack trace with a token in it, shows in your
    conversation or its history."""
    session = create_session(daemon, ad_hoc)
    client, _ = attach(daemon, session)
    acp_id = get_session(daemon, session["id"])["acpSessionId"]
    try:
        client.prompt(acp_id, "stderr")
        client.prompt(acp_id, "hello")  # anything relayed after it has arrived
    finally:
        client.close()
    assert "stderr of" not in json.dumps(client.updates)
    assert "stderr of" not in json.dumps(_log(daemon, session["id"]))
    deadline = time.monotonic() + 10
    while f"stderr of {acp_id}" not in Path(daemon.log.name).read_text(errors="replace"):
        assert time.monotonic() < deadline, "not in handlerd's log"
        time.sleep(0.1)
