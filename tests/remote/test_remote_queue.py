"""A5 from paired devices: calls queued at the gateway while the host is off (taken once, only
for routes the app declares queued, until they expire: 7 days), notifications listed for the
device's person, Web Push subscriptions. A real gateway, a Python device, the coach test app in
podman."""

import base64
import json
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ..apps.conftest import api, call_app, copy_fixture, requires_podman
from ..apps.test_apps_coach import install, manifest
from ..support import dev_env
from ..support.daemon import Daemon, start_daemon
from ..support.remote import Device, DeviceError, Gateway, start_gateway

pytestmark = requires_podman
S = "app:coach"


@pytest.fixture(scope="module")
def gateway() -> Iterator[Gateway]:
    yield from start_gateway()


@pytest.fixture(scope="module")
def data_root() -> Iterator[Path]:
    path = dev_env.scope_root() / f"remote-queue-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    yield path
    dev_env.remove_scope(path)


@pytest.fixture(scope="module")
def daemon(gateway: Gateway, data_root: Path) -> Iterator[Daemon]:
    env = {"HANDLER_DATA_DIR": str(data_root / "handler")} | dev_env.home_env()  # its agenda.md
    for d in start_daemon(extra_env=env):
        body = {"gatewayUrl": gateway.url, "hostToken": gateway.host_token}
        assert api(d, "PUT", "/v1/remote/gateway", body).status_code == 200
        agenda = data_root / "agenda.md"
        agenda.write_text("09:00 standup\n")
        source = copy_fixture("app-coach", data_root)
        manifest(source)
        install(d, source, agenda)
        r = api(d, "POST", "/v1/apps/coach/deploy")
        assert r.status_code == 200, r.text
        api(d, "PUT", "/v1/apps/coach/persons", {"persons": ["owner"]})
        yield d


@pytest.fixture(scope="module")
def phone(daemon: Daemon) -> Device:
    r = api(daemon, "POST", "/v1/remote/devices", {"name": "phone"})
    return Device(r.json()["pairingUrl"])


def checkin(text: str, request_id: str, route: str = "/api/checkin") -> dict[str, Any]:
    body = base64.b64encode(json.dumps({"text": text}).encode()).decode()
    params = {
        "method": "POST",
        "path": route,
        "headers": {"content-type": "application/json", "idempotency-key": request_id},
        "body": body,
    }
    return {
        "s": S,
        "m": {"jsonrpc": "2.0", "id": request_id, "method": "_handler/app/http", "params": params},
    }


def answer(phone: Device, request_id: str) -> dict[str, Any]:
    return phone.wait_frame(lambda f: f["s"] == S and f["m"].get("id") == request_id, 60)["m"]


def checkins(phone: Device) -> list[str]:
    params = {"method": "GET", "path": "/api/checkins"}
    result = phone.request(S, "_handler/app/http", params, timeout=60)
    return json.loads(base64.b64decode(result["body"]))


def test_queued_call_runs_once(phone: Device) -> None:
    assert [a["queued"] for a in phone.request(None, "_handler/remote/list_apps")["apps"]] == [
        ["POST /api/checkin"]
    ]
    envelope = phone.queue([checkin("done", "q-1")])
    m = answer(phone, "q-1")
    assert m["result"]["status"] == 200
    phone.wait_until(lambda: envelope["id"] in phone.acks)
    assert checkins(phone) == ["owner:done:q-1"]

    # the same envelope again (a gateway replaying it): taken once only, by either path
    assert phone.http.post("/v1/device/queue", json=envelope).status_code == 202
    phone.post(envelope)
    time.sleep(3)
    phone.poll()
    assert checkins(phone) == ["owner:done:q-1"]


def test_old_or_unqueued_calls_are_refused(phone: Device) -> None:
    old = phone.queue([checkin("late", "q-old")], lifetime=-1)  # its 7 days are over
    phone.wait_until(lambda: any(r["id"] == old["id"] for r in phone.rejected))
    phone.queue([checkin("x", "q-2", route="/api/tell-alice")])
    assert answer(phone, "q-2")["error"]["code"] == -32022
    assert checkins(phone) == ["owner:done:q-1"]


def test_a_live_call_handed_over_again_as_queued_is_refused(phone: Device) -> None:
    """A hostile gateway keeps a live call and puts it in the queue later: it expired with its
    own (short) lifetime, so it does not run again, however long handler remembers ids."""
    before = checkins(phone)
    envelope = phone.send([checkin("live", "q-live")], lifetime=3)
    assert answer(phone, "q-live")["result"]["status"] == 200
    time.sleep(4)
    assert phone.http.post("/v1/device/queue", json=envelope).status_code == 202
    expired = {"id": envelope["id"], "reason": "expired"}
    phone.wait_until(lambda: expired in phone.rejected, timeout=60)
    assert checkins(phone) == [*before, "owner:live:q-live"]


def test_inbox_and_push(daemon: Daemon, phone: Device) -> None:
    assert call_app(daemon, "morning", "coach", "POST /api/cron/morning")["state"] == "succeeded"
    messages = phone.request(None, "_handler/remote/inbox")["messages"]
    assert (messages[0]["title"], messages[0]["summary"]) == ("Today", "09:00 standup")

    public = phone.request(None, "_handler/remote/push_key")["publicKey"]
    assert len(base64.urlsafe_b64decode(public + "==")) == 65  # an uncompressed P-256 point
    with pytest.raises(DeviceError):
        phone.request(None, "_handler/remote/push_subscribe", {"endpoint": "http://push.test/x"})
    with pytest.raises(DeviceError):  # not a push service: an address of your network, say
        phone.request(None, "_handler/remote/push_subscribe", {"endpoint": "https://10.0.0.1/x"})
    endpoint = {"endpoint": "https://updates.push.services.mozilla.com/wpush/v2/test"}
    ok = phone.request(None, "_handler/remote/push_subscribe", endpoint)
    assert ok == {"subscribed": True}
    assert phone.request(None, "_handler/remote/push_subscribe", {}) == {"subscribed": False}
