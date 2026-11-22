"""H.17 from a paired phone (D.7): an action done from a nudge, its form filled from speech, an
app's nudge toned: the owner's devices only, as Ask; a nudge dismissed: its person's only."""

from collections.abc import Iterator

import pytest

from ..support.daemon import Daemon, start_daemon
from ..support.remote import Device, DeviceError, Gateway, start_gateway
from .test_remote import pair, wait_light


@pytest.fixture(scope="module")
def gateway() -> Iterator[Gateway]:
    yield from start_gateway()


@pytest.fixture(scope="module")
def daemon(gateway: Gateway) -> Iterator[Daemon]:
    for d in start_daemon():
        with d.http() as c:
            body = {"gatewayUrl": gateway.url, "hostToken": gateway.host_token}
            assert c.put("/v1/remote/gateway", json=body).status_code == 200
            made = c.post(
                "/v1/agents", json={"model": {"account": "fake"}, "name": "Claude", "chat": True}
            )
            assert made.status_code == 201, made.text  # someone to talk to: the host polls
        yield d


@pytest.mark.rule("nudge.action-ones-to-the-owner", "nudge.voice-fills-never-sends")
def test_a_family_member_s_phone_neither_acts_nor_fills_nor_tones(daemon: Daemon) -> None:
    wait_light(daemon, "ok")
    owner = pair(daemon, "phone")
    with daemon.http() as c:
        r = c.post("/v1/remote/devices", json={"name": "kid", "person": "kid", "scope": "apps"})
    kid = Device(r.json()["pairingUrl"])
    asks = [
        ("_handler/remote/act", {"app": "worklog", "action": "log", "fields": {}}),
        ("_handler/remote/nudge_fill", {"id": "n1", "said": "I did it"}),
        ("_handler/remote/nudge_setting", {"app": "worklog", "nudge": "d", "setting": "once"}),
    ]
    for method, params in asks:
        with pytest.raises(DeviceError, match="owner's devices"):
            kid.request(None, method, params)
        with pytest.raises(DeviceError) as e:  # the owner's: asked, but nothing of that name
            owner.request(None, method, params)
        assert "owner's devices" not in str(e.value)
    for device in (owner, kid):
        with pytest.raises(DeviceError, match="no nudge"):
            device.request(None, "_handler/remote/nudge_dismiss", {"id": "n1"})
