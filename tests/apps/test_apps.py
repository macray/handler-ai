"""Contract H conformance: a real handlerd runs the test app (tests/fixtures/miniapp) in podman.

Register, deploy (tests, health check on a copy of the data), open with a one-time link, the
app's origin (cookie, same-origin rule, static files, the backend), a new version keeping the
data, a failed deploy changing nothing, rollback, idle stop, removal.
"""

import os
import shutil
import time
from pathlib import Path

import pytest

from handler_contracts import RUNTIME_IMAGE

from ..support.daemon import Daemon
from .conftest import IDLE_TIMEOUT, AppClient, api, copy_fixture, requires_podman, set_version

FIXTURE = "miniapp"

pytestmark = requires_podman


@pytest.fixture(scope="module")
def source(data_root: Path) -> Path:
    return copy_fixture(FIXTURE, data_root)


def test_register(daemon: Daemon, source: Path) -> None:
    r = api(daemon, "POST", "/v1/apps", json={"sourceDir": str(source)})
    assert r.status_code == 201, r.text
    app = r.json()
    assert app["name"] == "counter"
    assert app["state"] == "stopped"
    assert "current" not in app
    assert app["source"] == {"version": "1.0.0", "description": "Counts clicks", "addedNeeds": []}
    again = api(daemon, "POST", "/v1/apps", json={"sourceDir": str(source)})
    assert again.status_code == 409
    assert AppClient(daemon, "counter").request("GET", "/").status_code == 404  # not deployed
    assert api(daemon, "POST", "/v1/apps/counter/open").status_code == 409


def test_deploy(daemon: Daemon) -> None:
    r = api(daemon, "POST", "/v1/apps/counter/deploy")
    assert r.status_code == 200, api(daemon, "GET", "/v1/apps/counter/log").json()["text"]
    app = r.json()
    assert app["current"]["version"] == "1.0.0"
    assert app["state"] == "stopped"  # the health check ran on a copy; started on first use
    log = api(daemon, "GET", "/v1/apps/counter/log").json()["text"]
    assert "1 passed" in log  # the backend's tests ran


def test_open_and_use(daemon: Daemon) -> None:
    browser = AppClient(daemon, "counter")
    assert browser.request("GET", "/").status_code == 401
    link = api(daemon, "POST", "/v1/apps/counter/open").json()["url"]
    assert browser.login(link).status_code == 200
    assert browser.login(link).status_code == 403  # one-time

    page = browser.request("GET", "/")
    assert page.status_code == 200
    assert "Counter" in page.text
    assert "connect-src 'self'" in page.headers["content-security-policy"]
    assert browser.request("GET", "/some/client/route").text == page.text  # SPA fallback
    assert browser.request("GET", "/missing.js").status_code == 404
    assert browser.request("GET", "/../../app.toml").status_code in (404, 200)
    assert "apiVersion" not in browser.request("GET", "/%2e%2e/%2e%2e/app.toml").text

    assert browser.request("GET", "/api/count").json() == {"n": 0}
    assert api(daemon, "GET", "/v1/apps/counter").json()["state"] == "running"
    assert browser.request("POST", "/api/count").status_code == 403  # no Origin
    other = f"http://other.localhost:{browser.port}"
    assert browser.request("POST", "/api/count", Origin=other).status_code == 403
    assert (
        browser.request("GET", "/api/count", **{"Sec-Fetch-Site": "same-site"}).status_code == 403
    )
    assert browser.request("POST", "/api/count", Origin=browser.origin).json() == {"n": 1}

    who = browser.request("GET", "/api/whoami", **{"X-HANDLER-Person": "mallory"}).json()
    assert who == {"person": "owner", "cookie": "other=1"}  # handler's cookie is not forwarded

    # handler's own API is not on the app's origin, even with the token: /v1/… is one of its pages
    bearer = f"Bearer {daemon.token}"
    assert browser.request("GET", "/v1/apps", Authorization=bearer).text == page.text
    browser.cookie = None
    assert browser.request("GET", "/v1/apps", Authorization=bearer).status_code == 401


def test_new_version_keeps_data(daemon: Daemon, source: Path) -> None:
    set_version(source, "1.1.0")
    (source / "server" / "migrations" / "002_label.sql").write_text(
        "ALTER TABLE counter ADD COLUMN label TEXT;\n"
    )
    assert api(daemon, "GET", "/v1/apps/counter").json()["source"]["version"] == "1.1.0"
    r = api(daemon, "POST", "/v1/apps/counter/deploy")
    assert r.status_code == 200, r.text
    assert r.json()["current"]["version"] == "1.1.0"
    assert r.json()["previous"]["version"] == "1.0.0"
    browser = AppClient(daemon, "counter")
    browser.login(api(daemon, "POST", "/v1/apps/counter/open").json()["url"])
    assert browser.request("GET", "/api/count").json() == {"n": 1}
    assert browser.request("POST", "/api/count", Origin=browser.origin).json() == {"n": 2}


def test_failed_deploy_changes_nothing(daemon: Daemon, source: Path) -> None:
    test_file = source / "server" / "main_test.ts"
    good = test_file.read_text()
    set_version(source, "1.2.0")
    test_file.write_text(good.replace("body.n !== 1", "body.n !== 42"))
    try:
        r = api(daemon, "POST", "/v1/apps/counter/deploy")
        assert r.status_code == 422
        assert "tests failed" in r.json()["detail"]
    finally:
        test_file.write_text(good)

    link = source / "ui" / "dist" / "secret.txt"
    link.symlink_to("/etc/hostname")
    try:
        r = api(daemon, "POST", "/v1/apps/counter/deploy")
        assert r.status_code == 422
        assert "link to outside the app" in r.json()["detail"]
    finally:
        link.unlink()

    app = api(daemon, "GET", "/v1/apps/counter").json()
    assert app["current"]["version"] == "1.1.0"
    browser = AppClient(daemon, "counter")
    browser.login(api(daemon, "POST", "/v1/apps/counter/open").json()["url"])
    assert browser.request("GET", "/api/count").json() == {"n": 2}


def test_rollback(daemon: Daemon) -> None:
    r = api(daemon, "POST", "/v1/apps/counter/rollback")
    assert r.status_code == 200, r.text
    assert r.json()["current"]["version"] == "1.0.0"
    assert "previous" not in r.json()
    browser = AppClient(daemon, "counter")
    browser.login(api(daemon, "POST", "/v1/apps/counter/open").json()["url"])
    # the data as it was before 1.1.0 was deployed: the click made under 1.1.0 is gone
    assert browser.request("GET", "/api/count").json() == {"n": 1}
    assert api(daemon, "POST", "/v1/apps/counter/rollback").status_code == 409


def test_idle_stop(daemon: Daemon) -> None:
    assert api(daemon, "GET", "/v1/apps/counter").json()["state"] == "running"
    deadline = time.monotonic() + IDLE_TIMEOUT + 15
    while api(daemon, "GET", "/v1/apps/counter").json()["state"] == "running":
        assert time.monotonic() < deadline, "the idle backend was not stopped"
        time.sleep(1)
    assert "idle for" in api(daemon, "GET", "/v1/apps/counter/log").json()["text"]


@pytest.mark.skipif(not shutil.which("gsettings"), reason="gsettings not installed")
def test_keyboard_shortcut(daemon: Daemon, data_root: Path) -> None:
    keyfile = data_root / "gnome" / "config" / "glib-2.0" / "settings" / "keyfile"
    r = api(daemon, "PUT", "/v1/apps/counter/shortcut", {"shortcut": "<Super>k"})
    assert r.status_code == 200, r.text
    assert r.json()["shortcut"] == "<Super>k"
    assert "binding='<Super>k'" in keyfile.read_text()
    assert "app open counter" in keyfile.read_text()
    bad = api(daemon, "PUT", "/v1/apps/counter/shortcut", {"shortcut": "k"})
    assert bad.status_code == 422  # a modifier is required


def test_remove_keeps_data(daemon: Daemon, data_root: Path) -> None:
    assert api(daemon, "DELETE", "/v1/apps/counter").status_code == 204
    assert api(daemon, "GET", "/v1/apps/counter").status_code == 404
    assert (data_root / "apps" / "counter" / "data" / "app.db").exists()
    assert not (data_root / "apps" / "counter" / "versions").exists()
    keyfile = data_root / "gnome" / "config" / "glib-2.0" / "settings" / "keyfile"
    if keyfile.exists():  # its shortcut is gone from GNOME's list
        listed = [ln for ln in keyfile.read_text().splitlines() if "custom-keybindings=" in ln]
        assert listed and "handler-counter" not in listed[0]


def test_runtime_image_is_pinned() -> None:
    assert RUNTIME_IMAGE.rsplit(":", 1)[1][0].isalpha()  # a tag, not latest by default
    assert os.path.basename(RUNTIME_IMAGE).startswith("deno:distroless-")
