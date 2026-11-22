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
from typing import Any

import httpx
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


@pytest.fixture(scope="module")
def registered(daemon: Daemon, source: Path) -> httpx.Response:
    """The counter's file installed (1.0.0), not deployed: Handler's answer."""
    return add_app(daemon, source)


@pytest.fixture(scope="module")
def deployed(daemon: Daemon, registered: httpx.Response) -> httpx.Response:
    """The counter's first deploy (1.0.0): Handler's answer."""
    assert registered.status_code == 201, registered.text
    return api(daemon, "POST", "/v1/apps/counter/deploy")


def opened(daemon: Daemon) -> AppClient:
    """A browser on the counter, signed in with a one-time link."""
    browser = AppClient(daemon, "counter")
    assert browser.login(api(daemon, "POST", "/v1/apps/counter/open").json()["url"]).is_success
    return browser


def click(browser: AppClient) -> int:
    return browser.request("POST", "/api/count", Origin=browser.origin).json()["n"]


def count(browser: AppClient) -> int:
    return browser.request("GET", "/api/count").json()["n"]


@pytest.fixture(scope="module")
def second_version(daemon: Daemon, source: Path, deployed: httpx.Response) -> dict[str, Any]:
    """1.1.0 (a migration more) installed and deployed over 1.0.0 and its data, then one click
    under it: the count before the deploy, what the source said before and after its install,
    the deploy's answer, the count after the click."""
    assert deployed.status_code == 200, deployed.text
    before = click(opened(daemon))
    set_version(source, "1.1.0")
    (source / "server" / "migrations" / "002_label.sql").write_text(
        "ALTER TABLE counter ADD COLUMN label TEXT;\n"
    )
    kept = api(daemon, "GET", "/v1/apps/counter").json()["source"]["version"]
    installed = add_app(daemon, source).json()["source"]["version"]
    r = api(daemon, "POST", "/v1/apps/counter/deploy")
    assert r.status_code == 200, r.text
    browser = opened(daemon)
    found = count(browser)
    return {
        "before": before,
        "kept": kept,
        "installed": installed,
        "deploy": r.json(),
        "found": found,
        "after": click(browser),
    }


@pytest.mark.rule("app.its-code-is-kept-by-handler", "app.nothing-is-read-through-a-link-out")
def test_register(daemon: Daemon, source: Path, registered: httpx.Response) -> None:
    r = registered
    assert r.status_code == 201, r.text
    app = r.json()
    assert app["name"] == "counter"
    assert app["state"] == "stopped"
    assert "current" not in app
    needs = app["source"].pop("needs")  # what it may reach, said before its first deploy
    assert app["source"] == {"version": "1.0.0", "description": "Counts clicks", "addedNeeds": []}
    assert needs["files"] == {} and "agents" not in needs
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


@pytest.mark.rule("deploy.a-failure-changes-nothing", "app-backend.runs-only-while-used")
def test_deploy(daemon: Daemon, deployed: httpx.Response) -> None:
    r = deployed
    assert r.status_code == 200, api(daemon, "GET", "/v1/apps/counter/log").json()["text"]
    app = r.json()
    assert app["current"]["version"] == "1.0.0"
    assert app["state"] == "stopped"  # the health check ran on a copy; started on first use
    log = api(daemon, "GET", "/v1/apps/counter/log").json()["text"]
    assert "1 pass" in log  # the backend's tests ran


@pytest.mark.rule(
    "app-backend.runs-only-while-used",
    "app-origin.its-own-never-handler-s",
    "app-origin.opened-by-a-one-time-link",
    "app-origin.its-api-from-its-own-pages-only",
    "app-origin.its-pages-reach-only-it",
    "app-origin.handlerd-says-who-asks",
)
def test_open_and_use(daemon: Daemon, deployed: httpx.Response) -> None:
    assert deployed.status_code == 200, deployed.text
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
    # an id holding a `/`, sent encoded as one segment, reaches the backend encoded
    sent = browser.request("GET", "/api/path/2026-11-19%2Fcall-the-bank/done?a=b%2Fc").json()
    assert sent == {"path": "/api/path/2026-11-19%2Fcall-the-bank/done", "query": "?a=b%2Fc"}
    assert api(daemon, "GET", "/v1/apps/counter").json()["state"] == "running"
    assert browser.request("POST", "/api/count").status_code == 403  # no Origin
    other = f"http://other.localhost:{browser.port}"
    assert browser.request("POST", "/api/count", Origin=other).status_code == 403
    assert (
        browser.request("GET", "/api/count", **{"Sec-Fetch-Site": "same-site"}).status_code == 403
    )
    assert browser.request("POST", "/api/count", Origin=browser.origin).json() == {"n": 1}

    forged = {"X-HANDLER-Person": "mallory", "X-HANDLER-Automation": "x", "X-Handler-Action": "y"}
    who = browser.request("GET", "/api/whoami", **forged).json()
    # handler's cookie is not forwarded; no x-handler-* of the client's reaches the backend
    assert who == {"person": "owner", "cookie": "other=1", "handler": ["x-handler-person"]}

    # handler's own API is not on the app's origin, even with the token: /v1/… is one of its pages
    bearer = f"Bearer {daemon.token}"
    assert browser.request("GET", "/v1/apps", Authorization=bearer).text == page.text
    browser.cookie = None
    assert browser.request("GET", "/v1/apps", Authorization=bearer).status_code == 401


@pytest.mark.rule("app.its-code-is-kept-by-handler", "deploy.a-failure-changes-nothing")
def test_new_version_keeps_data(second_version: dict[str, Any]) -> None:
    v = second_version
    assert (v["kept"], v["installed"]) == ("1.0.0", "1.1.0")  # its code is Handler's
    assert v["deploy"]["current"]["version"] == "1.1.0"
    assert v["deploy"]["previous"]["version"] == "1.0.0"
    assert v["before"] >= 1 and v["found"] == v["before"]
    assert v["after"] == v["before"] + 1


@pytest.mark.rule("deploy.a-failure-changes-nothing")
def test_failed_deploy_changes_nothing(
    daemon: Daemon, source: Path, deployed: httpx.Response
) -> None:
    assert deployed.status_code == 200, deployed.text
    app = api(daemon, "GET", "/v1/apps/counter").json()
    current, installed = app["current"]["version"], app["source"]["version"]
    n = click(opened(daemon))
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
        set_version(source, installed)
        add_app(daemon, source)

    app = api(daemon, "GET", "/v1/apps/counter").json()
    assert app["current"]["version"] == current
    assert count(opened(daemon)) == n


@pytest.mark.rule("deploy.a-rollback-takes-its-data-back")
def test_rollback(daemon: Daemon, second_version: dict[str, Any]) -> None:
    r = api(daemon, "POST", "/v1/apps/counter/rollback")
    assert r.status_code == 200, r.text
    assert r.json()["current"]["version"] == "1.0.0"
    assert "previous" not in r.json()
    # the data as it was before 1.1.0 was deployed: the click made under 1.1.0 is gone
    assert count(opened(daemon)) == second_version["before"]
    assert api(daemon, "POST", "/v1/apps/counter/rollback").status_code == 409


@pytest.mark.rule("app.its-code-is-kept-by-handler")
def test_export(daemon: Daemon, registered: httpx.Response) -> None:
    """Its code as one file: what was installed, nothing of its data."""
    assert registered.status_code == 201, registered.text
    installed = api(daemon, "GET", "/v1/apps/counter").json()["source"]["version"]
    with daemon.http() as c:
        r = c.get("/v1/apps/counter/export")
    assert r.status_code == 200, r.text
    assert f'filename="counter-{installed}.zip"' in r.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "app.toml" in names and "server/main.ts" in names
    assert not any(n.startswith("data/") or n.endswith("app.db") for n in names)
    assert api(daemon, "GET", "/v1/apps/nothing/export").status_code == 404


@pytest.mark.rule("app-backend.runs-only-while-used")
def test_idle_stop(daemon: Daemon, deployed: httpx.Response) -> None:
    assert deployed.status_code == 200, deployed.text
    count(opened(daemon))  # used: its backend runs
    assert api(daemon, "GET", "/v1/apps/counter").json()["state"] == "running"
    deadline = time.monotonic() + IDLE_TIMEOUT + 15
    while api(daemon, "GET", "/v1/apps/counter").json()["state"] == "running":
        assert time.monotonic() < deadline, "the idle backend was not stopped"
        time.sleep(1)
    assert "idle for" in api(daemon, "GET", "/v1/apps/counter/log").json()["text"]


@pytest.mark.rule("app.uninstalled-leaves-nothing-of-it")
def test_uninstall_deletes_its_data(
    daemon: Daemon, data_root: Path, deployed: httpx.Response
) -> None:
    """Uninstalled, nothing of it is left (H.6): another app of that name never finds its data."""
    assert deployed.status_code == 200, deployed.text
    count(opened(daemon))  # used: it has data
    assert (data_root / "apps" / "counter" / "data" / "app.db").exists()
    assert api(daemon, "DELETE", "/v1/apps/counter").status_code == 204
    assert api(daemon, "GET", "/v1/apps/counter").status_code == 404
    assert not (data_root / "apps" / "counter").exists()


@pytest.mark.rule("app-backend.in-a-strict-sandbox")
def test_runtime_image_is_pinned() -> None:
    assert re.fullmatch(r"docker\.io/oven/bun:\d+\.\d+\.\d+-distroless", RUNTIME_IMAGE)
