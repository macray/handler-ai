"""The gateway's API: authentication, mailboxes, fetched status, limits, cursors."""

import hashlib
import secrets
import threading
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from handler_gateway.app import Limits, State, create_app
from handler_gateway.store import MailboxFullError, Queue, Registry


def envelope(**extra: str) -> dict[str, str]:
    return {
        "id": secrets.token_urlsafe(16),
        "nonce": secrets.token_urlsafe(12),
        "ct": "AAAA",
    } | extra


class Setup:
    def __init__(self, tmp: Path, limits: Limits | None = None, client_dir: Path | None = None):
        self.registry = Registry(tmp / "state.json")
        self.host_token = self.registry.add_host("laptop")
        self.state = State(self.registry, limits or Limits(rate=1000))
        # entered: one event loop for every request (long polls wait on asyncio events)
        self.client = TestClient(create_app(self.state, client_dir)).__enter__()
        self.dev = "d_" + secrets.token_hex(8)
        self.dev_secret = secrets.token_urlsafe(32)

    def host(self, method: str, path: str, **kw: object):
        headers = {"Authorization": f"Bearer {self.host_token}"}
        return self.client.request(method, path, headers=headers, **kw)  # ty: ignore[invalid-argument-type]

    def device(self, method: str, path: str, token: str | None = None, **kw: object):
        headers = {"Authorization": f"Bearer {token or f'{self.dev}.{self.dev_secret}'}"}
        return self.client.request(method, path, headers=headers, **kw)  # ty: ignore[invalid-argument-type]

    def register(self) -> None:
        token_hash = hashlib.sha256(self.dev_secret.encode()).hexdigest()
        r = self.host("PUT", f"/v1/host/devices/{self.dev}", json={"tokenHash": token_hash})
        assert r.status_code == 204, r.text


@pytest.fixture
def g(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


def test_round_trip_and_fetched_status(g: Setup) -> None:
    g.register()
    down = envelope()
    assert g.device("POST", "/v1/device/down", json=down).json() == {"id": down["id"]}
    polled = g.host("GET", "/v1/host/poll", params={"wait": 0}).json()
    assert [(e["dev"], e["id"], e["ct"]) for e in polled["envelopes"]] == [
        (g.dev, down["id"], "AAAA")
    ]
    # the next host poll starts after it
    assert (
        g.host("GET", "/v1/host/poll", params={"wait": 0, "after": polled["cursor"]}).json()[
            "envelopes"
        ]
        == []
    )

    up = envelope(dev=g.dev)
    assert g.host("POST", "/v1/host/up", json={"envelopes": [up]}).status_code == 204
    got = g.device("GET", "/v1/device/poll", params={"wait": 0}).json()
    assert [e["id"] for e in got["envelopes"]] == [up["id"]]
    assert got["fetched"] == [down["id"]]  # reported once
    assert got["hostSeen"] is not None
    again = g.device("GET", "/v1/device/poll", params={"wait": 0, "after": got["cursor"]}).json()
    assert again["envelopes"] == [] and again["fetched"] == []


def test_authentication(g: Setup) -> None:
    assert g.client.get("/v1/host/poll").status_code == 401
    assert (
        g.client.get("/v1/host/poll", headers={"Authorization": "Bearer h_x.y"}).status_code == 401
    )
    wrong = g.host_token.split(".")[0] + ".nope"
    assert (
        g.client.get("/v1/host/poll", headers={"Authorization": f"Bearer {wrong}"}).status_code
        == 401
    )
    assert g.device("GET", "/v1/device/poll").status_code == 401  # not registered yet
    g.register()
    assert g.device("GET", "/v1/device/poll", params={"wait": 0}).status_code == 200
    assert g.device("GET", "/v1/device/poll", token=f"{g.dev}.wrong").status_code == 401
    # a device token is not a host token, and the other way round
    assert g.host("GET", "/v1/device/poll").status_code == 401


def test_devices_belong_to_their_host(g: Setup) -> None:
    g.register()
    other = g.registry.add_host("other")
    headers = {"Authorization": f"Bearer {other}"}
    r = g.client.put(f"/v1/host/devices/{g.dev}", headers=headers, json={"tokenHash": "0" * 64})
    assert r.status_code == 409
    # the other host can neither send to it nor revoke it
    r = g.client.post("/v1/host/up", headers=headers, json={"envelopes": [envelope(dev=g.dev)]})
    assert r.status_code == 404
    assert g.client.delete(f"/v1/host/devices/{g.dev}", headers=headers).status_code == 204
    assert g.host("GET", "/v1/host/devices").json() == {"devices": [g.dev]}
    # revoked by its host: gone
    assert g.host("DELETE", f"/v1/host/devices/{g.dev}").status_code == 204
    assert g.device("GET", "/v1/device/poll").status_code == 401


def test_invalid_input(g: Setup) -> None:
    g.register()
    for bad in [{"id": "short", "nonce": "x" * 16, "ct": "AA"}, envelope(ct="not base64!"), [1]]:
        assert g.device("POST", "/v1/device/down", json=bad).status_code == 400
    big = envelope(ct="A" * 300_000)
    assert g.device("POST", "/v1/device/down", json=big).status_code == 413
    r = g.host("PUT", "/v1/host/devices/nope", json={"tokenHash": "0" * 64})
    assert r.status_code == 400


def test_full_down_mailbox_refuses_but_up_drops_oldest(tmp_path: Path) -> None:
    g = Setup(tmp_path, Limits(down_count=2, up_count=2, rate=1000))
    g.register()
    assert g.device("POST", "/v1/device/down", json=envelope()).status_code == 202
    assert g.device("POST", "/v1/device/down", json=envelope()).status_code == 202
    assert g.device("POST", "/v1/device/down", json=envelope()).status_code == 503
    ups = [envelope(dev=g.dev) for _ in range(3)]
    g.host("POST", "/v1/host/up", json={"envelopes": ups})
    got = g.device("GET", "/v1/device/poll", params={"wait": 0}).json()["envelopes"]
    assert [e["id"] for e in got] == [ups[1]["id"], ups[2]["id"]]


def test_envelopes_expire(tmp_path: Path) -> None:
    g = Setup(tmp_path, Limits(ttl=0.2, rate=1000))
    g.register()
    g.device("POST", "/v1/device/down", json=envelope())
    time.sleep(0.3)
    assert g.host("GET", "/v1/host/poll", params={"wait": 0}).json()["envelopes"] == []


def test_cursor_of_another_epoch_starts_over(g: Setup) -> None:
    g.register()
    first = envelope()
    g.device("POST", "/v1/device/down", json=first)
    stale = "deadbeef-99"  # from before a gateway restart
    got = g.host("GET", "/v1/host/poll", params={"wait": 0, "after": stale}).json()
    assert [e["id"] for e in got["envelopes"]] == [first["id"]]


def test_long_poll_wakes_on_put(g: Setup) -> None:
    g.register()
    down = envelope()
    timer = threading.Timer(0.3, lambda: g.device("POST", "/v1/device/down", json=down))
    timer.start()
    started = time.monotonic()
    got = g.host("GET", "/v1/host/poll", params={"wait": 10}).json()
    assert [e["id"] for e in got["envelopes"]] == [down["id"]]
    assert time.monotonic() - started < 5


def test_rate_limit(tmp_path: Path) -> None:
    g = Setup(tmp_path, Limits(rate=2))
    codes = [g.host("GET", "/v1/host/devices").status_code for _ in range(10)]
    assert 429 in codes


def test_registry_is_private_and_reloaded(tmp_path: Path) -> None:
    g = Setup(tmp_path)
    assert (tmp_path / "state.json").stat().st_mode & 0o777 == 0o600
    token = Registry(tmp_path / "state.json").add_host("added by the CLI")
    time.sleep(0.01)
    r = g.client.get("/v1/host/devices", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_the_server_never_undoes_what_the_cli_did(tmp_path: Path) -> None:
    """The server read the registry, the CLI adds a host, then the server registers a device
    (without a host request in between): the new host stays."""
    g = Setup(tmp_path)
    host = g.host_token.split(".")[0]
    token = Registry(tmp_path / "state.json").add_host("added by the CLI")
    g.registry.put_device(host, "d_" + "1" * 16, "0" * 64)
    assert token.split(".")[0] in Registry(tmp_path / "state.json").hosts


def test_a_host_removed_by_the_cli_takes_its_devices_at_once(tmp_path: Path) -> None:
    """No host request needs to come first (the removed host's handlerd may be off)."""
    g = Setup(tmp_path)
    g.register()
    assert g.device("GET", "/v1/device/poll", params={"wait": 0}).status_code == 200
    assert Registry(tmp_path / "state.json").remove_host(g.host_token.split(".")[0])
    assert g.device("GET", "/v1/device/poll", params={"wait": 0}).status_code == 401


def test_changes_from_two_processes_are_all_kept(tmp_path: Path) -> None:
    """Two writers at once (the CLI and the server): each change kept, the file always whole."""
    path = tmp_path / "state.json"
    host = Registry(path).add_host("laptop").split(".")[0]

    def register(prefix: str) -> None:
        registry = Registry(path)  # its own file descriptors: its own locks, as a process
        for i in range(100):
            registry.put_device(host, f"d_{prefix}{i:015x}", "0" * 64)

    writers = [threading.Thread(target=register, args=(p,)) for p in "ab"]
    for w in writers:
        w.start()
    for w in writers:
        w.join()
    assert len(Registry(path).devices_of(host)) == 200
    assert not list(tmp_path.glob("*.tmp")) and not list(tmp_path.glob(".state.json-*"))


def test_app_frame_reaches_nothing(tmp_path: Path) -> None:
    client_dir = tmp_path / "client"
    client_dir.mkdir()
    (client_dir / "index.html").write_text("<html>client</html>")
    (client_dir / "appframe.html").write_text("<html>frame</html>")
    g = Setup(tmp_path, client_dir=client_dir)
    policy = g.client.get("/appframe.html").headers["content-security-policy"]
    assert "connect-src 'none'" in policy and "default-src 'none'" in policy
    assert "frame-ancestors 'self'" in policy  # only the client may show it
    # an opaque origin even opened alone: never the client's, which holds the device's keys
    assert "sandbox allow-scripts allow-forms allow-modals" in policy
    client = g.client.get("/").headers["content-security-policy"]
    assert "frame-ancestors 'none'" in client
    assert "frame-src 'self'" in client  # an app's frame is not navigated out of the gateway


def test_serves_the_client_with_a_strict_policy(tmp_path: Path) -> None:
    client_dir = tmp_path / "client"
    client_dir.mkdir()
    (client_dir / "index.html").write_text("<html>client</html>")
    g = Setup(tmp_path, client_dir=client_dir)
    r = g.client.get("/")
    assert r.status_code == 200 and "client" in r.text
    assert "connect-src 'self'" in r.headers["content-security-policy"]
    assert g.client.get("/v1/health").json() == {"ok": True}


def test_queue_survives_a_restart_until_the_host_takes_it(tmp_path: Path) -> None:
    g = Setup(tmp_path)
    g.state.queue = Queue(tmp_path / "state.queue")
    g.register()
    host = g.host_token.split(".")[0]
    e = envelope()
    assert g.device("POST", "/v1/device/queue", json=e).status_code == 202
    assert g.device("POST", "/v1/device/queue", json=e).status_code == 202  # the same: once
    assert g.device("GET", "/v1/device/poll", params={"wait": 0}).json()["queued"] == [e["id"]]
    file = tmp_path / "state.queue" / host / f"{e['id']}.json"
    assert file.stat().st_mode & 0o777 == 0o600

    again = Queue(tmp_path / "state.queue")  # a gateway restart
    assert [x["id"] for x in again.pending(host, 1 << 20)] == [e["id"]]
    listed = g.host("GET", "/v1/host/queue").json()["envelopes"]
    assert listed == [e | {"dev": g.dev}]
    assert g.host("DELETE", f"/v1/host/queue/{e['id']}").status_code == 204
    assert not file.exists()
    assert g.host("DELETE", f"/v1/host/queue/{e['id']}").status_code == 404
    assert g.host("GET", "/v1/host/queue").json()["envelopes"] == []
    assert g.device("GET", "/v1/device/poll", params={"wait": 0}).json()["queued"] == []


def test_queueing_writes_that_envelope_only(tmp_path: Path) -> None:
    """A put costs its own envelope, not every queue again (a device could otherwise make the
    gateway rewrite megabytes on each call); a removal never names a file from the host's word."""
    q = Queue(tmp_path / "q")
    q.put("h_a", "d", "a" * 16, "n" * 16, "A" * 100_000)
    first = (tmp_path / "q" / "h_a" / f"{'a' * 16}.json").stat().st_mtime_ns
    time.sleep(0.01)
    q.put("h_b", "d", "b" * 16, "n" * 16, "AAAA")
    assert (tmp_path / "q" / "h_a" / f"{'a' * 16}.json").stat().st_mtime_ns == first
    (tmp_path / "outside.json").write_text("{}")
    assert not q.remove("h_a", "../../outside")
    assert (tmp_path / "outside.json").exists()


def test_queue_is_bounded_and_expires(tmp_path: Path) -> None:
    q = Queue(None, max_count=2, ttl=0.2)
    q.put("h", "d", "a" * 16, "n" * 16, "AAAA")
    q.put("h", "d", "b" * 16, "n" * 16, "AAAA")
    with pytest.raises(MailboxFullError):
        q.put("h", "d", "c" * 16, "n" * 16, "AAAA")
    time.sleep(0.3)
    assert q.pending("h", 1 << 20) == []
    q.put("h", "d", "c" * 16, "n" * 16, "AAAA")


def test_queue_needs_a_device_and_belongs_to_its_host(g: Setup) -> None:
    assert g.device("POST", "/v1/device/queue", json=envelope()).status_code == 401
    token = g.registry.add_host("other")
    g.register()
    e = envelope()
    g.device("POST", "/v1/device/queue", json=e)
    r = g.client.get("/v1/host/queue", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["envelopes"] == []


def test_queueing_wakes_the_host(g: Setup) -> None:
    g.register()
    result: dict[str, object] = {}

    def poll() -> None:
        result.update(g.host("GET", "/v1/host/poll", params={"wait": 10}).json())

    waiting = threading.Thread(target=poll)
    started = time.monotonic()
    waiting.start()
    time.sleep(0.3)
    assert g.device("POST", "/v1/device/queue", json=envelope()).status_code == 202
    waiting.join(timeout=10)
    assert time.monotonic() - started < 5
    assert result["queued"] == 1 and result["envelopes"] == []
