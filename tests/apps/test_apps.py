"""Contract H conformance: a real handlerd runs the test app (tests/fixtures/app) in a real
sandbox (Podman; Apple container on a Mac).

Install its file, deploy (tests, health check on a copy of the data), open with a one-time link,
the app's origin (cookie, same-origin rule, static files, the backend), a new version keeping the
data (its next file), a failed deploy changing nothing, rollback, idle stop, export, removal.
"""

import io
import re
import time
import zipfile
from pathlib import Path

import pytest

from handler_contracts import RUNTIME_IMAGE

from ..support.daemon import Daemon
from .conftest import (
    IDLE_TIMEOUT,
    AppClient,
    add_app,
    api,
    copy_fixture,
    requires_app_runtime,
    set_version,
)

FIXTURE = "app"

pytestmark = requires_app_runtime


@pytest.fixture(scope="module")
def source(data_root: Path) -> Path:
    return copy_fixture(FIXTURE, data_root)


@pytest.mark.rule("app.its-code-is-kept-by-handler", "app.nothing-is-read-through-a-link-out")
def test_register(daemon: Daemon, source: Path) -> None:
    r = add_app(daemon, source)
    assert r.status_code == 201, r.text
    app = r.json()
    assert app["name"] == "counter"
    assert app["state"] == "stopped"
    assert "current" not in app
    needs = app["source"].pop("needs")  # what it may reach, said before its first deploy
    assert app["source"] == {"version": "1.0.0", "description": "Counts clicks", "addedNeeds": []}
    assert needs["files"] == {} and needs["agents"] == {}
    again = add_app(daemon, source)  # the same app's file again: its next version, not another app
    assert again.status_code == 200 and again.json()["source"]["version"] == "1.0.0"
    with daemon.http() as c:
        bad = c.post("/v1/apps", content=b"not a zip")
        assert bad.status_code == 409 and "not an app file" in bad.json()["detail"]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("app.toml", (source / "app.toml").read_text())
            link = zipfile.ZipInfo("ui/dist/secret.txt")
            link.external_attr = 0o120777 << 16
            zf.writestr(link, "/etc/hostname")
        refused = c.post("/v1/apps", content=buffer.getvalue())
        assert refused.status_code == 409 and "is a link" in refused.json()["detail"]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("../app.toml", "")
        assert "leaving" in c.post("/v1/apps", content=buffer.getvalue()).json()["detail"]
    assert AppClient(daemon, "counter").request("GET", "/").status_code == 404  # not deployed
    assert api(daemon, "POST", "/v1/apps/counter/open").status_code == 409


@pytest.mark.rule("deploy.a-failure-changes-nothing", "backend.runs-only-while-used")
def test_deploy(daemon: Daemon) -> None:
    r = api(daemon, "POST", "/v1/apps/counter/deploy")
    assert r.status_code == 200, api(daemon, "GET", "/v1/apps/counter/log").json()["text"]
    app = r.json()
    assert app["current"]["version"] == "1.0.0"
    assert app["state"] == "stopped"  # the health check ran on a copy; started on first use
    log = api(daemon, "GET", "/v1/apps/counter/log").json()["text"]
    assert "1 pass" in log  # the backend's tests ran


@pytest.mark.rule(
    "backend.runs-only-while-used",
    "origin.its-own-never-handler-s",
    "origin.opened-by-a-one-time-link",
    "origin.its-api-from-its-own-pages-only",
    "origin.its-pages-reach-only-it",
    "origin.handlerd-says-who-asks",
)
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


@pytest.mark.rule("app.its-code-is-kept-by-handler", "deploy.a-failure-changes-nothing")
def test_new_version_keeps_data(daemon: Daemon, source: Path) -> None:
    set_version(source, "1.1.0")
    (source / "server" / "migrations" / "002_label.sql").write_text(
        "ALTER TABLE counter ADD COLUMN label TEXT;\n"
    )
    assert api(daemon, "GET", "/v1/apps/counter").json()["source"]["version"] == "1.0.0"
    assert add_app(daemon, source).json()["source"]["version"] == "1.1.0"  # its code is Handler's
    r = api(daemon, "POST", "/v1/apps/counter/deploy")
    assert r.status_code == 200, r.text
    assert r.json()["current"]["version"] == "1.1.0"
    assert r.json()["previous"]["version"] == "1.0.0"
    browser = AppClient(daemon, "counter")
    browser.login(api(daemon, "POST", "/v1/apps/counter/open").json()["url"])
    assert browser.request("GET", "/api/count").json() == {"n": 1}
    assert browser.request("POST", "/api/count", Origin=browser.origin).json() == {"n": 2}


@pytest.mark.rule("deploy.a-failure-changes-nothing")
def test_failed_deploy_changes_nothing(daemon: Daemon, source: Path) -> None:
    test_file = source / "server" / "main_test.ts"
    good = test_file.read_text()
    set_version(source, "1.2.0")
    test_file.write_text(good.replace("body.n !== 1", "body.n !== 42"))
    try:
        add_app(daemon, source)
        r = api(daemon, "POST", "/v1/apps/counter/deploy")
        assert r.status_code == 422
        assert "tests failed" in r.json()["detail"]
    finally:
        test_file.write_text(good)
        set_version(source, "1.1.0")
        add_app(daemon, source)

    app = api(daemon, "GET", "/v1/apps/counter").json()
    assert app["current"]["version"] == "1.1.0"
    browser = AppClient(daemon, "counter")
    browser.login(api(daemon, "POST", "/v1/apps/counter/open").json()["url"])
    assert browser.request("GET", "/api/count").json() == {"n": 2}


@pytest.mark.rule("deploy.a-rollback-takes-its-data-back")
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


@pytest.mark.rule("app.its-code-is-kept-by-handler")
def test_export(daemon: Daemon, source: Path) -> None:
    """Its code as one file: what was installed, nothing of its data."""
    with daemon.http() as c:
        r = c.get("/v1/apps/counter/export")
    assert r.status_code == 200, r.text
    assert 'filename="counter-1.1.0.zip"' in r.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "app.toml" in names and "server/main.ts" in names
    assert not any(n.startswith("data/") or n.endswith("app.db") for n in names)
    assert api(daemon, "GET", "/v1/apps/nothing/export").status_code == 404


@pytest.mark.rule("backend.runs-only-while-used")
def test_idle_stop(daemon: Daemon) -> None:
    assert api(daemon, "GET", "/v1/apps/counter").json()["state"] == "running"
    deadline = time.monotonic() + IDLE_TIMEOUT + 15
    while api(daemon, "GET", "/v1/apps/counter").json()["state"] == "running":
        assert time.monotonic() < deadline, "the idle backend was not stopped"
        time.sleep(1)
    assert "idle for" in api(daemon, "GET", "/v1/apps/counter/log").json()["text"]


@pytest.mark.rule("app.uninstalled-leaves-nothing-of-it")
def test_uninstall_deletes_its_data(daemon: Daemon, data_root: Path) -> None:
    """Uninstalled, nothing of it is left (H.6): another app of that name never finds its data."""
    assert (data_root / "apps" / "counter" / "data" / "app.db").exists()
    assert api(daemon, "DELETE", "/v1/apps/counter").status_code == 204
    assert api(daemon, "GET", "/v1/apps/counter").status_code == 404
    assert not (data_root / "apps" / "counter").exists()


@pytest.mark.rule("backend.in-a-strict-sandbox")
def test_runtime_image_is_pinned() -> None:
    assert re.fullmatch(r"docker\.io/oven/bun:\d+\.\d+\.\d+-distroless", RUNTIME_IMAGE)
