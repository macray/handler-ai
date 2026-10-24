"""Apps from paired devices (contract H.8, docs/dev/design/apps.md §5.2): a real gateway,
devices in Python, the test app in podman. Persons and scopes: the owner's phone and a family
member's (apps only); an app reaches the persons it is shared with, and nobody else."""

import base64
import json
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from ..apps.conftest import add_app, api, copy_fixture, requires_podman
from ..support import dev_env
from ..support.daemon import Daemon, start_daemon
from ..support.remote import Device, DeviceError, Gateway, start_gateway

pytestmark = requires_podman
S = "app:counter"


@pytest.fixture(scope="module")
def gateway() -> Iterator[Gateway]:
    yield from start_gateway()


@pytest.fixture(scope="module")
def data_root() -> Iterator[Path]:
    path = dev_env.scope_root() / f"remote-apps-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    yield path
    dev_env.remove_scope(path)


@pytest.fixture(scope="module")
def daemon(gateway: Gateway, data_root: Path) -> Iterator[Daemon]:
    for d in start_daemon(extra_env={"HANDLER_DATA_DIR": str(data_root)}):
        body = {"gatewayUrl": gateway.url, "hostToken": gateway.host_token}
        assert api(d, "PUT", "/v1/remote/gateway", body).status_code == 200
        source = copy_fixture("app", data_root)
        assert add_app(d, source).status_code == 201
        r = api(d, "POST", "/v1/apps/counter/deploy")
        assert r.status_code == 200, r.text
        yield d


def pair(daemon: Daemon, **body: str) -> Device:
    r = api(daemon, "POST", "/v1/remote/devices", {"name": "phone"} | body)
    assert r.status_code == 201, r.text
    return Device(r.json()["pairingUrl"])


def share(daemon: Daemon, *persons: str) -> dict[str, Any]:
    r = api(daemon, "PUT", "/v1/apps/counter/persons", {"persons": list(persons)})
    assert r.status_code == 200, r.text
    return r.json()


def light(daemon: Daemon) -> str:
    return api(daemon, "GET", "/v1/remote").json()["light"]


def wait_light(daemon: Daemon, wanted: str) -> None:
    deadline = time.monotonic() + 20
    while light(daemon) != wanted:
        assert time.monotonic() < deadline, light(daemon)
        time.sleep(0.1)


def http(device: Device, method: str, path: str, body: Any = None) -> tuple[int, Any]:
    params: dict[str, Any] = {"method": method, "path": path}
    if body is not None:
        params["body"] = base64.b64encode(json.dumps(body).encode()).decode()
        params["headers"] = {"Content-Type": "application/json"}
    result = device.request(S, "_handler/app/http", params, timeout=90)
    raw = base64.b64decode(result["body"])
    kind = result["headers"].get("content-type", "")
    return result["status"], json.loads(raw) if "json" in kind else raw.decode()


def test_sharing_an_app_starts_polling(daemon: Daemon) -> None:
    wait_light(daemon, "idle")  # nothing shared
    assert share(daemon, "owner")["persons"] == ["owner"]
    wait_light(daemon, "ok")


def test_owner_uses_the_app(daemon: Daemon) -> None:
    phone = pair(daemon)
    listed = phone.request(None, "_handler/remote/list_apps")
    assert listed["person"] == "owner" and listed["scope"] == "all"
    assert [a["name"] for a in listed["apps"]] == ["counter"]

    ui = phone.request(S, "_handler/app/ui")
    assert "Counter" in ui["html"]
    assert 'src="/app.js"' not in ui["html"]  # inlined: the frame fetches nothing
    assert "getElementById" in ui["html"]
    assert phone.request(S, "_handler/app/ui", {"have": ui["version"]}) == {
        "version": ui["version"],
        "unchanged": True,
    }

    assert http(phone, "GET", "/api/count") == (200, {"n": 0})
    assert http(phone, "POST", "/api/count", {}) == (200, {"n": 1})
    status, who = http(phone, "GET", "/api/whoami")
    assert status == 200 and who["person"] == "owner"
    with pytest.raises(DeviceError) as e:
        phone.request(S, "_handler/app/http", {"method": "GET", "path": "/app.toml"})
    assert e.value.code == -32602


def test_family_member_gets_only_what_is_shared_with_them(daemon: Daemon) -> None:
    r = api(daemon, "POST", "/v1/remote/devices", {"name": "x", "person": "alice"})
    assert r.status_code == 409  # a family member's device reaches apps only
    alice = pair(daemon, person="alice", scope="apps")
    devices = api(daemon, "GET", "/v1/remote").json()["devices"]
    assert {(d["person"], d["scope"]) for d in devices} >= {("alice", "apps"), ("owner", "all")}

    assert alice.request(None, "_handler/remote/list_sessions") == {"sessions": []}
    assert alice.request(None, "_handler/remote/list_apps")["apps"] == []
    with pytest.raises(DeviceError) as e:
        alice.request(S, "_handler/app/ui")
    assert e.value.code == -32020
    with pytest.raises(DeviceError) as e:  # any session: refused before looking it up
        alice.request("s_0123456789abcdef", "initialize", {"protocolVersion": 1})
    assert e.value.code == -32022

    share(daemon, "owner", "alice")
    notice = alice.wait_frame(lambda f: f["m"].get("method") == "_handler/remote/apps_changed")
    assert [a["name"] for a in notice["m"]["params"]["apps"]] == ["counter"]
    status, who = http(alice, "GET", "/api/whoami")
    assert status == 200 and who["person"] == "alice"

    share(daemon, "owner")
    with pytest.raises(DeviceError):
        alice.request(S, "_handler/app/ui")


def test_unshared_app_stops_polling(daemon: Daemon) -> None:
    share(daemon)
    wait_light(daemon, "idle")
    with httpx.Client() as c:  # the local app is untouched
        assert c.get(f"{daemon.base_url}/v1/health").status_code == 200
