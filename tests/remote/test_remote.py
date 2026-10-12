"""Remote control conformance (docs/dev/design/remote.md, contract D.7): a real handlerd, a real
gateway, a device in Python. The gateway is treated as hostile where it matters: envelopes replayed,
held back, altered, or sent back to their sender are refused by handlerd.
"""

import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from ..support.acp_client import AcpClient
from ..support.daemon import Daemon, start_daemon
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


def test_light_follows_sharing(daemon: Daemon) -> None:
    wait_light(daemon, "idle")  # nothing shared: no polling
    session = running_session(daemon)
    share(daemon, session)
    status = wait_light(daemon, "ok")
    assert session["id"] in status["sharedSessions"] and status["hostId"].startswith("h_")
    share(daemon, session, False)
    wait_light(daemon, "idle")


def test_device_drives_a_shared_session(daemon: Daemon, shared: dict[str, Any]) -> None:
    device = pair(daemon)
    listed = device.request(None, "_handler/remote/list_sessions")["sessions"]
    assert shared["id"] in [s["id"] for s in listed]
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
    # held back: an envelope 10 minutes old is rejected, and the device is told
    old = device.send(
        [frame | {"m": frame["m"] | {"id": 78}}], ts=int(time.time() * 1000) - 600_000
    )
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


def test_pairing_needs_a_gateway_and_a_valid_token(daemon: Daemon, gateway: Gateway) -> None:
    with daemon.http() as c:
        bad = {"gatewayUrl": gateway.url, "hostToken": "not-a-token"}
        assert c.put("/v1/remote/gateway", json=bad).status_code == 422
        # a well-formed token the gateway does not know: unauthorized once something is shared
        wrong = {"gatewayUrl": gateway.url, "hostToken": "h_0123456789abcdef." + "x" * 43}
        assert c.put("/v1/remote/gateway", json=wrong).status_code == 200
        session = running_session(daemon)
        share(daemon, session)
        wait_light(daemon, "unauthorized")
        assert c.delete("/v1/remote/gateway").json()["light"] == "off"
        assert c.post("/v1/remote/devices", json={"name": "x"}).status_code == 409
        good = {"gatewayUrl": gateway.url, "hostToken": gateway.host_token}
        assert c.put("/v1/remote/gateway", json=good).status_code == 200
        wait_light(daemon, "ok")
        share(daemon, session, False)


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


def test_device_starts_a_session_of_an_allowed_agent(daemon: Daemon) -> None:
    """D.7: the owner's device lists the agents marked `remoteStart` (the host polls for them,
    nothing else being shared) and starts a session of one, shared with it once it runs."""
    folder = daemon.make_scope()
    agents = [
        {"models": [{"account": "fake"}], "name": "coder", "remoteStart": True},
        {"models": [{"account": "fake"}], "name": "dev"},
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
    assert kid.request(None, "_handler/remote/list_agents") == {"projects": []}
    with pytest.raises(DeviceError):  # an apps-only device starts nothing
        kid.request(None, "_handler/remote/start_session", {"agentId": coder["id"]})
