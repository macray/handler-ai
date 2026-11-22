"""Remote control conformance (remote design, contract D.7): a real handlerd, a real
gateway, a device in Python. The gateway is treated as hostile where it matters: envelopes replayed,
held back, altered, or sent back to their sender are refused by handlerd.
"""

import contextlib
import secrets
import socket
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

import httpx
import pytest

from handler_control import remote as remote_module
from handler_control import remote_crypto as rc

from ..support.acp_client import AcpClient
from ..support.daemon import FAKE_SECRET, Daemon, start_daemon
from ..support.remote import Device, DeviceError, Gateway, start_gateway


@pytest.fixture(scope="module")
def gateway() -> Iterator[Gateway]:
    yield from start_gateway()


@pytest.fixture(scope="module")
def daemon(gateway: Gateway) -> Iterator[Daemon]:
    for d in start_daemon():
        with d.http() as c:
            body = {"gatewayUrl": gateway.url, "hostToken": gateway.host_token}
            assert c.put("/v1/remote/gateway", json=body).status_code == 200
        yield d


def remote(daemon: Daemon) -> dict[str, Any]:
    with daemon.http() as c:
        return c.get("/v1/remote").json()


def wait_light(daemon: Daemon, light: str, timeout: float = 20) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while (status := remote(daemon))["light"] != light:
        assert time.monotonic() < deadline, status
        time.sleep(0.1)
    return status


def running_session(daemon: Daemon) -> dict[str, Any]:
    ad_hoc = daemon.create_ad_hoc("fake", daemon.make_scope())
    with daemon.http() as c:
        session = c.post("/v1/sessions", json={"agentId": ad_hoc["id"]}).json()
        deadline = time.monotonic() + 30
        while (session := c.get(f"/v1/sessions/{session['id']}").json())["state"] != "running":
            assert time.monotonic() < deadline, session
            time.sleep(0.1)
    return session


def share(daemon: Daemon, session: dict[str, Any], enabled: bool = True) -> httpx.Response:
    with daemon.http() as c:
        return c.put(f"/v1/sessions/{session['id']}/remote", json={"enabled": enabled})


def pair(daemon: Daemon, name: str = "phone") -> Device:
    with daemon.http() as c:
        r = c.post("/v1/remote/devices", json={"name": name})
        assert r.status_code == 201, r.text
        return Device(r.json()["pairingUrl"])


def attach(device: Device, session: dict[str, Any]) -> dict[str, Any]:
    s = session["id"]
    device.request(s, "initialize", {"protocolVersion": 1, "clientCapabilities": {}})
    params = {"sessionId": session["acpSessionId"], "cwd": session["scope"], "mcpServers": []}
    return device.request(s, "session/load", params)


@pytest.fixture
def shared(daemon: Daemon) -> dict[str, Any]:
    session = running_session(daemon)
    assert share(daemon, session).json()["remote"] is True
    return session


@pytest.mark.rule(
    "remote.polls-only-while-something-is-reachable",
    "remote.the-light-says-why",
    "phone-session.off-until-you-switch-it-on",
)
def test_light_follows_sharing(daemon: Daemon) -> None:
    assert remote(daemon)["light"] == "ok"  # Connect's try, kept while nothing is shared
    session = running_session(daemon)
    share(daemon, session)
    status = wait_light(daemon, "ok")
    assert session["id"] in status["sharedSessions"] and status["hostId"].startswith("h_")
    share(daemon, session, False)
    wait_light(daemon, "idle")


@pytest.mark.rule("envelope.acknowledged-by-the-host", "phone.an-ordinary-attachment")
def test_device_drives_a_shared_session(daemon: Daemon, shared: dict[str, Any]) -> None:
    device = pair(daemon)
    listed = device.request(None, "_handler/remote/list_sessions")["sessions"]
    [mine] = [s for s in listed if s["id"] == shared["id"]]
    assert mine["program"] == "Fake"  # its product name, not the code name "fake"
    loaded = attach(device, shared)
    assert loaded["modes"]["currentModeId"] == "yolo"

    local = daemon.connect(shared["acpUrl"])  # a tab attached too (F.7)
    try:
        local.initialize()
        params = {"sessionId": shared["acpSessionId"], "cwd": shared["scope"], "mcpServers": []}
        local.request("session/load", params)
        prompt = {"sessionId": shared["acpSessionId"], "prompt": [{"type": "text", "text": "hi"}]}
        assert device.request(shared["id"], "session/prompt", prompt)["stopReason"] == "end_turn"
        assert device.text(shared["id"]) == "ok"
        assert local.wait_notification("_handler/turn_ended") == {"stopReason": "end_turn"}
        assert any(
            u["params"]["update"].get("sessionUpdate") == "user_message_chunk"
            for u in local.updates
            if u["method"] == "session/update"
        )  # the tab saw the phone's prompt
    finally:
        local.close()
    # the gateway said "fetched", and handler acknowledged, every envelope the device sent
    device.poll(wait=0)
    assert set(device.fetched) >= set(device.acks) and len(device.acks) >= 3
    status = remote(daemon)
    assert [d["attached"] for d in status["devices"] if d["name"] == "phone"][-1] == [shared["id"]]


def test_one_envelope_s_requests_answered_together_at_once(
    daemon: Daemon, shared: dict[str, Any]
) -> None:
    """The phone's home asks several things in one envelope: their answers come back in one,
    without the wait that gathers an agent's streamed output (the person waits on them)."""
    device = pair(daemon)
    device.request(None, "_handler/remote/list_sessions")  # the host is polling
    methods = [
        "_handler/remote/list_apps",
        "_handler/remote/inbox",
        "_handler/remote/list_sessions",
    ]
    fastest = 10.0
    for _ in range(3):  # the best of three: a loaded machine adds its own delays
        ids = [f"home-{secrets.token_hex(4)}" for _ in methods]
        frames = [
            {"s": None, "m": {"jsonrpc": "2.0", "id": i, "method": m}}
            for i, m in zip(ids, methods, strict=True)
        ]
        before, start = len(device.envelopes), time.monotonic()
        device.send(frames)
        device.wait_until(
            lambda ids=ids: all(any(f["m"].get("id") == i for f in device.frames) for i in ids)
        )
        fastest = min(fastest, time.monotonic() - start)
        answered = [
            e
            for e in device.envelopes[before:]
            if any(
                f["m"].get("id") in ids
                for f in rc.open_envelope(device.key, device.host_id, device.id, "up", e)["frames"]
            )
        ]
        assert len(answered) == 1  # together
    assert fastest < remote_module.FLUSH_DELAY  # at once


@pytest.mark.rule("phone.an-ordinary-attachment")
def test_device_answers_a_permission_request(daemon: Daemon, shared: dict[str, Any]) -> None:
    device = pair(daemon)
    attach(device, shared)
    s = shared["id"]
    prompt = {
        "sessionId": shared["acpSessionId"],
        "prompt": [{"type": "text", "text": "permission"}],
    }
    rid = device.call(s, "session/prompt", prompt)
    asked = device.wait_frame(lambda f: f["m"].get("method") == "session/request_permission")
    device.answer(s, asked["m"]["id"], "yes")
    done = device.wait_frame(lambda f: f["s"] == s and f["m"].get("id") == rid)
    assert done["m"]["result"]["stopReason"] == "end_turn"
    assert '"optionId": "yes"' in device.text(s)


def prompt(device: Device, session: dict[str, Any], text: str) -> int:
    """A turn started from the device (attached), not waited for: its request's id."""
    params = {"sessionId": session["acpSessionId"], "prompt": [{"type": "text", "text": text}]}
    return device.call(session["id"], "session/prompt", params)


def turn_ended(device: Device, session: dict[str, Any], rid: int) -> None:
    device.wait_frame(lambda f: f["s"] == session["id"] and f["m"].get("id") == rid)


def asked(device: Device, session: dict[str, Any]) -> dict[str, Any]:
    return device.wait_frame(
        lambda f: f["s"] == session["id"] and f["m"].get("method") == "session/request_permission"
    )["m"]


def listed(device: Device, session: dict[str, Any]) -> dict[str, Any]:
    """The session as the device's list says it."""
    sessions = device.request(None, "_handler/remote/list_sessions")["sessions"]
    return next(s for s in sessions if s["id"] == session["id"])


def at(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


@pytest.mark.rule(
    "phone.its-list-says-what-each-session-does",
    "phone.an-ask-is-risky-unless-known-safe",
    "phone.messages-are-contract-documents",
)
def test_the_list_says_what_a_shared_session_does(daemon: Daemon, shared: dict[str, Any]) -> None:
    """D.7: since when each shared session is in its state (the ask's arrival, its turn's start,
    its last turn's end), the agent's last step in one line, and the first ask it waits on: its
    tool call's id, its title, its kind and its risk (decided by the host).

    If this fails: the phone shows a session as it was, without what it is doing, or an ask
    without what it asks, or lets a risky ask be allowed with a tap."""
    device = pair(daemon)
    attach(device, shared)
    s = shared["id"]
    with daemon.http() as c:
        started = at(c.get(f"/v1/sessions/{s}").json()["lastActivityAt"])
    idle = listed(device, shared)
    assert (idle["busy"], at(idle["since"])) == (False, started) and "ask" not in idle

    rid = prompt(device, shared, "sleep")
    state = device.wait_frame(
        lambda f: f["s"] == s and (f["m"].get("params") or {}).get("busy") is True
    )["m"]["params"]
    working = listed(device, shared)
    assert working["busy"] and at(working["since"]) == at(state["turnStartedAt"])
    device.send([{"s": s, "m": {"jsonrpc": "2.0", "method": "session/cancel", "params": {
        "sessionId": shared["acpSessionId"]}}}])  # fmt: skip
    turn_ended(device, shared, rid)

    rid = prompt(device, shared, "steps")
    turn_ended(device, shared, rid)
    done = listed(device, shared)
    with daemon.http() as c:
        ended = at(c.get(f"/v1/sessions/{s}").json()["lastActivityAt"])
    assert not done["busy"] and at(done["since"]) == ended > started
    assert done["last"] == "All 42 tests pass"

    rid = prompt(device, shared, "permission execute")
    request = asked(device, shared)
    waiting = listed(device, shared)
    assert waiting["ask"] == {
        "toolCallId": "t2", "summary": "Run npm test", "kind": "execute", "risk": "risky"
    }  # fmt: skip
    assert waiting["pendingPermissions"] == 1 and at(waiting["since"]) > ended
    assert waiting["last"] == "All 42 tests pass"  # kept until the agent's first update
    device.answer(s, request["id"], "no")
    turn_ended(device, shared, rid)
    assert "ask" not in listed(device, shared)

    cases = [
        (
            "permission read",
            {"toolCallId": "t2", "summary": "Read notes.md", "kind": "read"},
            "safe",
        ),
        ("permission read ../outside.md", {"toolCallId": "t3", "kind": "read"}, "risky"),
        ("permission", {"toolCallId": "t1", "summary": "rm -rf /"}, "risky"),  # no kind: absent
    ]
    for text, ask, risk in cases:
        rid = prompt(device, shared, text)
        request = asked(device, shared)
        mine = listed(device, shared)
        assert {k: v for k, v in mine["ask"].items() if k in ask} == ask, text
        assert mine["ask"]["risk"] == risk and set(mine["ask"]) >= set(ask), text
        assert nulls(mine) == [], (text, nulls(mine))
        device.answer(s, request["id"], "no")
        turn_ended(device, shared, rid)
    assert set(mine["ask"]) == {"toolCallId", "summary", "risk"}  # no kind: left out, not null


@pytest.mark.rule("phone.its-list-says-what-each-session-does")
def test_the_list_never_holds_a_secret(daemon: Daemon, shared: dict[str, Any]) -> None:
    """The last line is redacted as the session's log is: the list goes to every device around
    and stays in their sealed snapshots.

    If this fails: a secret of yours reaches every device around and its sealed snapshot."""
    device = pair(daemon)
    attach(device, shared)
    turn_ended(device, shared, prompt(device, shared, "leak"))
    assert FAKE_SECRET in device.text(shared["id"])  # the live stream is the agent's own
    last = listed(device, shared)["last"]
    assert FAKE_SECRET not in last and last == "the token is «redacted»"


@pytest.mark.rule(
    "phone.its-list-follows-the-sessions", "device.a-family-member-s-reaches-apps-only"
)
def test_a_turn_and_an_ask_reach_the_devices_unasked(
    daemon: Daemon, shared: dict[str, Any]
) -> None:
    """A device around that never lists again is sent the list when a shared session starts a
    turn, waits on you, and ends its turn; a device for apps only is sent none.

    If this fails: Home says "working" while the agent waits on you, or "needs you" for an ask
    answered on the computer."""
    watcher, driver = pair(daemon, "watcher"), pair(daemon, "driver")
    watcher.request(None, "_handler/remote/list_sessions")  # around
    with daemon.http() as c:
        r = c.post("/v1/remote/devices", json={"name": "kid", "person": "kid", "scope": "apps"})
    kid = Device(r.json()["pairingUrl"])
    kid.request(None, "_handler/remote/list_apps")  # around too
    attach(driver, shared)

    def told(check: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        def match(f: dict[str, Any]) -> bool:
            if f["m"].get("method") != "_handler/remote/sessions_changed":
                return False
            mine = [x for x in f["m"]["params"]["sessions"] if x["id"] == shared["id"]]
            return bool(mine) and check(mine[0])

        frame = watcher.wait_frame(match)
        return next(x for x in frame["m"]["params"]["sessions"] if x["id"] == shared["id"])

    rid = prompt(driver, shared, "permission execute")
    assert told(lambda x: x["busy"] and "ask" not in x)["pendingPermissions"] == 0
    request = asked(driver, shared)
    assert told(lambda x: "ask" in x)["ask"]["toolCallId"] == "t2"
    driver.answer(shared["id"], request["id"], "once")
    told(lambda x: x["busy"] and "ask" not in x)  # answered: no more ask, still working
    turn_ended(driver, shared, rid)
    told(lambda x: not x["busy"])
    kid.poll(wait=1)
    assert kid.notifications(None, "_handler/remote/sessions_changed") == []


@pytest.mark.rule("phone-session.off-until-you-switch-it-on", "phone.only-the-allowed-methods")
def test_only_shared_sessions_and_allowed_methods(daemon: Daemon, shared: dict[str, Any]) -> None:
    device = pair(daemon)
    private = running_session(daemon)
    listed = device.request(None, "_handler/remote/list_sessions")["sessions"]
    assert private["id"] not in [s["id"] for s in listed]
    with pytest.raises(DeviceError, match="-32020"):
        device.request(private["id"], "initialize", {"protocolVersion": 1})
    with pytest.raises(DeviceError, match="-32021"):  # not attached yet
        device.request(shared["id"], "session/prompt", {})
    attach(device, shared)
    with pytest.raises(DeviceError, match="-32022"):
        device.request(shared["id"], "session/new", {"cwd": shared["scope"], "mcpServers": []})
    with pytest.raises(DeviceError, match="-32022"):
        device.request(None, "_handler/remote/share", {"s": private["id"]})


@pytest.mark.rule(
    "phone-session.off-until-you-switch-it-on", "phone-session.off-closes-the-devices-at-once"
)
def test_unsharing_closes_the_device(daemon: Daemon, shared: dict[str, Any]) -> None:
    device = pair(daemon)
    attach(device, shared)
    share(daemon, shared, False)
    closed = device.wait_frame(lambda f: f["m"].get("method") == "_handler/remote/closed")
    assert closed["m"]["params"] == {
        "s": shared["id"],
        "code": 4004,
        "reason": "remote access disabled",
    }
    with pytest.raises(DeviceError, match="-32020"):
        device.request(shared["id"], "initialize", {"protocolVersion": 1})
    # sharing does not survive a stop, and a stopped session cannot be shared
    share(daemon, shared)
    with daemon.http() as c:
        stopped = c.post(f"/v1/sessions/{shared['id']}/stop").json()
    assert stopped["remote"] is False
    assert share(daemon, shared).status_code == 409


@pytest.mark.rule(
    "envelope.bound-to-its-host-device-and-direction", "envelope.taken-once-before-it-expires"
)
def test_hostile_gateway_is_refused(daemon: Daemon, shared: dict[str, Any]) -> None:
    device = pair(daemon)
    frame = {
        "s": None,
        "m": {"jsonrpc": "2.0", "id": 77, "method": "_handler/remote/list_sessions"},
    }

    # replay: the same envelope again is accepted by the gateway, not by handler
    envelope = device.send([frame])
    device.wait_frame(lambda f: f["m"].get("id") == 77)
    assert device.post(envelope).status_code == 202
    # held back: an envelope expired by the time handler gets it is rejected, and the device told
    old = device.send([frame | {"m": frame["m"] | {"id": 78}}], lifetime=-1)
    device.wait_until(lambda: any(r["id"] == old["id"] for r in device.rejected))
    # altered: the ciphertext changed (a byte of the tag)
    altered = device.seal([frame | {"m": frame["m"] | {"id": 79}}])
    ct = altered["ct"]
    altered["ct"] = ct[:-2] + ("A" if ct[-2] != "A" else "B") + ct[-1]
    assert device.post(altered).status_code == 202
    # reflected: an envelope handler sent to the device, sent back as if from the device
    reflected = dict(device.envelopes[-1])
    reflected.pop("cursor")
    reflected.pop("dev")
    assert device.post(reflected).status_code == 202
    # a genuine envelope after all that still works — and was the only other one answered
    assert device.request(None, "_handler/remote/list_sessions")["sessions"]
    time.sleep(1)
    device.poll(wait=0)
    answered = [f["m"]["id"] for f in device.frames if f["m"].get("id") in (77, 78, 79)]
    assert answered == [77]
    assert device.acks.count(envelope["id"]) == 1
    assert altered["id"] not in device.acks and reflected["id"] not in device.acks


@pytest.mark.rule("device.revoked-is-refused")
def test_a_revoked_device_the_gateway_still_relays_gets_no_answer(
    daemon: Daemon, gateway: Gateway, shared: dict[str, Any]
) -> None:
    """Revoked, then registered again at the gateway by hand (a gateway that does not forget
    it): what it sends reaches handlerd, which answers none of it.

    If this fails: a lost phone still reaches your sessions through a gateway that kept it."""
    device = pair(daemon, "kept by the gateway")
    assert device.request(None, "_handler/remote/list_sessions")["sessions"]
    with daemon.http() as c:
        assert c.delete(f"/v1/remote/devices/{device.id}").status_code == 204
    host = httpx.Client(
        base_url=gateway.url, headers={"Authorization": f"Bearer {gateway.host_token}"}
    )
    again = host.put(
        f"/v1/host/devices/{device.id}", json={"tokenHash": rc.gateway_token_hash(device.key)}
    )
    assert again.is_success, again.text
    device.cursor = ""  # its mailbox at the gateway is a new one
    rid = device.call(None, "_handler/remote/list_sessions")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:  # the host polls; an answer would come by now
        with contextlib.suppress(httpx.HTTPStatusError):  # forgotten again by handlerd's sync
            device.poll(wait=0.5)
    print("DBG", rid, device.frames[-3:], device.rejected, device.acks[-3:])
    assert [f for f in device.frames if f["m"].get("id") == rid] == []


@pytest.mark.rule("gateway.each-caller-its-own-mailboxes", "device.revoked-is-refused")
def test_revoked_device_is_locked_out(daemon: Daemon, shared: dict[str, Any]) -> None:
    device = pair(daemon, "lost phone")
    attach(device, shared)
    with daemon.http() as c:
        devices = c.get("/v1/remote").json()["devices"]
        victim = next(d for d in devices if d["id"] == device.id)
        assert victim["attached"] == [shared["id"]]
        assert c.delete(f"/v1/remote/devices/{device.id}").status_code == 204
        assert c.delete(f"/v1/remote/devices/{device.id}").status_code == 404
        assert device.id not in [d["id"] for d in c.get("/v1/remote").json()["devices"]]
    assert device.http.get("/v1/device/poll", params={"wait": 0}).status_code == 401


@pytest.mark.rule(
    "remote.the-light-says-why",
    "remote.the-host-token-over-https",
    "device.paired-from-this-computer-only",
)
def test_pairing_needs_a_gateway_and_a_valid_token(daemon: Daemon, gateway: Gateway) -> None:
    with daemon.http() as c:
        bad = {"gatewayUrl": gateway.url, "hostToken": "not-a-token"}
        assert c.put("/v1/remote/gateway", json=bad).status_code == 422
        # plain http would carry the host token in clear: only to this computer
        clear = {"gatewayUrl": "http://gateway.example.org", "hostToken": gateway.host_token}
        assert c.put("/v1/remote/gateway", json=clear).status_code == 422
        # a well-formed token the gateway does not know: Connect says so at once, and polling
        # once something is shared
        wrong = {"gatewayUrl": gateway.url, "hostToken": "h_0123456789abcdef." + "x" * 43}
        r = c.put("/v1/remote/gateway", json=wrong)
        assert r.status_code == 200 and r.json()["light"] == "unauthorized"
        session = running_session(daemon)
        share(daemon, session)
        wait_light(daemon, "unauthorized")
        assert c.delete("/v1/remote/gateway").json()["light"] == "off"
        assert c.post("/v1/remote/devices", json={"name": "x"}).status_code == 409
        good = {"gatewayUrl": gateway.url, "hostToken": gateway.host_token}
        assert c.put("/v1/remote/gateway", json=good).status_code == 200
        wait_light(daemon, "ok")
        share(daemon, session, False)


def test_the_phone_knows_the_computer_by_its_name(own: tuple[Gateway, Daemon]) -> None:
    """The computer's name (D.7): the hostname until it is named, kept by a Change of gateway,
    and given to each phone paired after, in its pairing fragment."""
    gateway, daemon = own
    hostname = socket.gethostname().split(".")[0]
    with daemon.http() as c:
        assert c.get("/v1/remote").json()["computerName"] == hostname
        named = c.put("/v1/remote/computer-name", json={"computerName": "desk"})
        assert named.status_code == 409  # no gateway yet: nothing to pair with
        good = {"gatewayUrl": gateway.url, "hostToken": gateway.host_token}
        assert c.put("/v1/remote/gateway", json=good).status_code == 200
        assert pair(daemon).computer == hostname
        assert c.put("/v1/remote/computer-name", json={"computerName": ""}).status_code == 422
        named = c.put("/v1/remote/computer-name", json={"computerName": "desk"})
        assert named.status_code == 200 and named.json()["computerName"] == "desk"
        assert c.put("/v1/remote/gateway", json=good).json()["computerName"] == "desk"
        assert pair(daemon).computer == "desk"


@pytest.fixture
def own() -> Iterator[tuple[Gateway, Daemon]]:
    """A gateway and a handlerd of the test's own: what the host polls is the test's alone."""
    for gateway in start_gateway():
        for daemon in start_daemon():
            yield gateway, daemon


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.rule(
    "remote.polls-only-while-something-is-reachable",
    "remote.the-light-says-why",
)
def test_connect_tries_the_gateway_at_once(own: tuple[Gateway, Daemon]) -> None:
    """Connect (D.7) tries the gateway once, with nothing reachable, and answers what it got;
    the light keeps it, and handlerd does not poll after."""
    gateway, daemon = own
    with daemon.http() as c:
        nobody = {"gatewayUrl": f"http://127.0.0.1:{free_port()}", "hostToken": gateway.host_token}
        status = c.put("/v1/remote/gateway", json=nobody).json()
        assert status["light"] == "unreachable" and status["detail"], status
        assert status["gatewayUrl"] == nobody["gatewayUrl"]  # saved all the same

        wrong = {"gatewayUrl": gateway.url, "hostToken": "h_0123456789abcdef." + "x" * 43}
        status = c.put("/v1/remote/gateway", json=wrong).json()
        assert status["light"] == "unauthorized" and status["detail"], status

        good = {"gatewayUrl": gateway.url, "hostToken": gateway.host_token}
        status = c.put("/v1/remote/gateway", json=good).json()
        assert status["light"] == "ok" and status["sharedSessions"] == [], status
        device = pair(daemon)
        time.sleep(1.5)
        # the try is no poll (a phone is not told the computer listens), and none followed it
        assert device.http.get("/v1/device/poll", params={"wait": 0}).json()["hostSeen"] is None
        assert remote(daemon)["light"] == "ok" and remote(daemon)["since"] == status["since"]


@pytest.mark.rule("phone.an-ordinary-attachment")
def test_local_client_is_unaffected(daemon: Daemon, shared: dict[str, Any]) -> None:
    """Sanity: a shared session is still an ordinary session locally."""
    client: AcpClient = daemon.connect(shared["acpUrl"])
    try:
        client.initialize()
        params = {"sessionId": shared["acpSessionId"], "cwd": shared["scope"], "mcpServers": []}
        client.request("session/load", params)
        assert client.prompt(shared["acpSessionId"], "hello")["stopReason"] == "end_turn"
    finally:
        client.close()


@pytest.mark.rule(
    "remote.polls-only-while-something-is-reachable",
    "device.a-family-member-s-reaches-apps-only",
    "phone.starts-only-the-agents-you-marked",
)
def test_device_starts_a_session_of_an_allowed_agent(daemon: Daemon) -> None:
    """D.7: the owner's device lists the agents marked `remoteStart` (the host polls for them,
    nothing else being shared) and starts a session of one, shared with it once it runs."""
    folder = daemon.make_scope()
    agents = [
        {"model": {"account": "fake"}, "name": "coder", "remoteStart": True},
        {"model": {"account": "fake"}, "name": "dev"},
    ]
    with daemon.http() as c:
        body = {"folder": str(folder), "name": "shop", "agents": agents}
        project = c.post("/v1/projects", json=body).json()
    coder, other = project["agents"]
    assert coder["remoteStart"] and not other["remoteStart"]
    wait_light(daemon, "ok")  # an agent may be started: the host polls
    device = pair(daemon, "starter")
    listed = device.request(None, "_handler/remote/list_agents")["projects"]
    shop = next(p for p in listed if p["projectId"] == project["id"])
    assert [a["name"] for a in shop["agents"]] == ["coder"] and shop["agents"][0]["default"]

    started = device.request(
        None, "_handler/remote/start_session", {"agentId": coder["id"], "prompt": "hi"}
    )
    sid = started["session"]
    changed = device.wait_frame(
        lambda f: (
            f["m"].get("method") == "_handler/remote/sessions_changed"
            and sid in [s["id"] for s in f["m"]["params"]["sessions"]]
        )
    )
    session = next(s for s in changed["m"]["params"]["sessions"] if s["id"] == sid)
    assert (session["project"], session["agent"], session["origin"]) == ("shop", "coder", "phone")
    attach(device, session)
    with daemon.http() as c:
        assert c.get(f"/v1/sessions/{sid}").json()["origin"] == "phone"

    with pytest.raises(DeviceError):  # not marked remoteStart
        device.request(None, "_handler/remote/start_session", {"agentId": other["id"]})
    with daemon.http() as c:
        r = c.post("/v1/remote/devices", json={"name": "kid", "person": "kid", "scope": "apps"})
    kid = Device(r.json()["pairingUrl"])
    assert kid.request(None, "_handler/remote/list_agents") == {"projects": [], "chats": []}
    with pytest.raises(DeviceError):  # an apps-only device starts nothing
        kid.request(None, "_handler/remote/start_session", {"agentId": coder["id"]})


@pytest.mark.rule(
    "remote.polls-only-while-something-is-reachable", "phone.starts-only-the-agents-you-marked"
)
def test_device_starts_a_chat(daemon: Daemon) -> None:
    """D.7, D.1: who you talk to in Chat (an agent whose home is Chat) is listed for the owner's
    devices with no `remoteStart`, the one used last the default, and started from them (Ask's
    Start a chat about it); one outside projects is not."""
    with daemon.http() as c:
        made = c.post(
            "/v1/agents", json={"model": {"account": "fake"}, "name": "Claude", "chat": True}
        )
        assert made.status_code == 201, made.text
        chat = made.json()
    other = daemon.create_ad_hoc("fake", daemon.make_scope(), name="Notes keeper")
    with daemon.http() as c:
        assert c.get(f"/v1/agents/{chat['id']}").json()["chat"]
        assert "app" not in c.get(f"/v1/agents/{other['id']}").json()
    wait_light(daemon, "ok")  # someone to talk to: the host polls
    device = pair(daemon, "chatter")
    listed = device.request(None, "_handler/remote/list_agents")
    assert [(a["name"], a["default"]) for a in listed["chats"]] == [("Claude", True)]

    started = device.request(
        None, "_handler/remote/start_session", {"agentId": chat["id"], "prompt": "Lyon?"}
    )
    with daemon.http() as c:
        assert c.get(f"/v1/sessions/{started['session']}").json()["origin"] == "phone"
    with pytest.raises(DeviceError):  # not a chat (a folder) and not marked remoteStart
        device.request(None, "_handler/remote/start_session", {"agentId": other["id"]})


@pytest.mark.rule("phone.starts-only-the-agents-you-marked")
def test_device_starts_an_agent_with_a_form_from_its_form(daemon: Daemon) -> None:
    """D.7, D.18: an agent with a form (a brief, a job) is listed with it and started with it
    filled in, checked as Handler's own start checks it; never as a plain chat with a request.

    If this fails: a job started from a phone chats in bypass and gives no result, or a brief's
    form is never asked."""
    form = {"type": "object", "properties": {"ask": {"type": "string"}}, "required": ["ask"]}
    result = {"type": "object", "properties": {"verdict": {"enum": ["good", "bad"]}}}
    folder = daemon.make_scope()
    agents = [
        {"model": {"account": "fake"}, "name": "briefed", "remoteStart": True}
        | {"interface": {"fields": form}},
        {"model": {"account": "fake"}, "name": "worker", "remoteStart": True}
        | {"interface": {"fields": form, "result": result}},
        {"model": {"account": "fake"}, "name": "talker", "remoteStart": True},
    ]
    with daemon.http() as c:
        body = {"folder": str(folder), "name": "forms", "agents": agents}
        project = c.post("/v1/projects", json=body).json()
    briefed, worker, talker = (
        next(a for a in project["agents"] if a["name"] == n)
        for n in ("briefed", "worker", "talker")
    )
    wait_light(daemon, "ok")
    device = pair(daemon, "former")
    listed = device.request(None, "_handler/remote/list_agents")["projects"]
    shown = {a["name"]: a for a in next(p for p in listed if p["project"] == "forms")["agents"]}
    assert shown["briefed"]["form"] == form and shown["briefed"]["job"] is False
    assert shown["worker"]["form"] == form and shown["worker"]["job"] is True
    assert "form" not in shown["talker"]

    start = "_handler/remote/start_session"
    for params in (
        {"agentId": briefed["id"], "prompt": "hi"},  # a request: its form is not filled
        {"agentId": briefed["id"], "fields": {}},  # its required field missing
        {"agentId": talker["id"], "fields": {"ask": "x"}},  # no form to fill
    ):
        with pytest.raises(DeviceError):
            device.request(None, start, params)
    started = device.request(None, start, {"agentId": briefed["id"], "fields": {"ask": "Do it"}})
    with daemon.http() as c:
        session = c.get(f"/v1/sessions/{started['session']}").json()
    assert session["input"] == {"fields": {"ask": "Do it"}} and session["origin"] == "phone"
    assert session["unattended"] is False  # a brief: a session you then work in
    started = device.request(None, start, {"agentId": worker["id"], "fields": {"ask": "Go"}})
    with daemon.http() as c:
        assert c.get(f"/v1/sessions/{started['session']}").json()["unattended"] is True  # a job


@pytest.mark.rule("phone.starts-only-the-agents-you-marked")
def test_a_start_that_fails_is_told_to_the_device_that_asked(daemon: Daemon) -> None:
    """F.1, D.7: a session started from a device that does not start (its program's image not
    built) is never shared: the device that started it is told why, instead of waiting.

    If this fails: the phone waits for a session that will never open, saying nothing."""
    folder = daemon.make_scope()
    agents = [{"model": {"account": "fake"}, "name": "coder", "remoteStart": True}]
    with daemon.http() as c:
        project = c.post(
            "/v1/projects", json={"folder": str(folder), "name": "unbuilt", "agents": agents}
        ).json()
    wait_light(daemon, "ok")
    device = pair(daemon, "waiter")
    missing = daemon.config_dir.parent / "fake-ran" / "harness-image-missing"
    missing.touch()
    try:
        started = device.request(
            None,
            "_handler/remote/start_session",
            {"agentId": project["agents"][0]["id"], "prompt": "hi"},
        )
        failed = device.wait_frame(
            lambda f: f["m"].get("method") == "_handler/remote/start_failed"
        )["m"]["params"]
    finally:
        missing.unlink()
    assert failed["session"] == started["session"] and failed["missingImage"] == "fake"
    assert failed["error"]


def nulls(value: Any, where: str = "") -> list[str]:
    """Where `value` holds a `null`."""
    if value is None:
        return [where or "."]
    if isinstance(value, dict):
        return [n for k, v in value.items() for n in nulls(v, f"{where}.{k}")]
    if isinstance(value, list):
        return [n for i, v in enumerate(value) for n in nulls(v, f"{where}[{i}]")]
    return []


@pytest.mark.rule("phone.messages-are-contract-documents")
def test_the_device_channel_speaks_its_contract_documents(
    daemon: Daemon, shared: dict[str, Any]
) -> None:
    """A control request whose params do not fit its document gets -32602; a result and a
    notification leave absent fields out, never `null`.

    If this fails: the phone and handlerd drift apart, and a phone reads `null` where its
    document has nothing."""
    device = pair(daemon)
    for params in ({}, {"agentId": 5}, {"agentId": "a", "surprise": True}):
        with pytest.raises(DeviceError) as refused:
            device.request(None, "_handler/remote/start_session", params)
        assert refused.value.code == -32602, params
    for params in ({}, {"id": 5}):
        with pytest.raises(DeviceError) as refused:
            device.request(None, "_handler/remote/inbox_read", params)
        assert refused.value.code == -32602, params
    for method in ("list_sessions", "list_agents", "list_apps", "inbox"):
        result = device.request(None, f"_handler/remote/{method}")
        assert nulls(result) == [], (method, nulls(result))
    share(daemon, running_session(daemon))  # told to the device: sessions_changed
    device.wait_frame(lambda f: f["m"].get("method") == "_handler/remote/sessions_changed")
    for frame in device.frames:
        if "method" in frame["m"]:
            assert nulls(frame["m"].get("params")) == [], frame
