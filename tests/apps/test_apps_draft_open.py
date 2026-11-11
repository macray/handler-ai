"""H.16 conformance: a draft of an app's code opened at its own address, in a real sandbox: on copies
taken when opened (what is done there leaves the app and its data as they were), each page with
the draft's banner, closed when the draft is thrown away."""

from pathlib import Path

import pytest

from ..support.daemon import Daemon
from .conftest import AppClient, add_app, api, copy_fixture, requires_app_runtime

pytestmark = requires_app_runtime


@pytest.mark.rule("origin.opened-by-a-one-time-link", "draft.opened-on-copies")
def test_an_opened_draft_works_on_copies(daemon: Daemon, data_root: Path) -> None:
    assert add_app(daemon, copy_fixture("app", data_root)).status_code == 201
    r = api(daemon, "POST", "/v1/apps/counter/deploy")
    assert r.status_code == 200, api(daemon, "GET", "/v1/apps/counter/log").json()["text"]
    app = AppClient(daemon, "counter")
    app.login(api(daemon, "POST", "/v1/apps/counter/open").json()["url"])
    assert app.request("POST", "/api/count", Origin=app.origin).json() == {"n": 1}

    body = {"name": "drafter", "model": {"account": "fake"}}
    agent = api(daemon, "POST", "/v1/agents", body).json()
    body = {"agentId": agent["id"], "appDraft": {"app": "counter"}}
    session = api(daemon, "POST", "/v1/sessions", body).json()
    page = Path(session["scope"]) / "ui" / "dist" / "index.html"
    page.write_text(page.read_text().replace("Counter", "Counter, drafted"))

    r = api(daemon, "POST", f"/v1/apps/from-draft/{session['id']}/open")
    assert r.status_code == 200, r.text
    opened = r.json()
    assert opened["app"] == "counter"
    assert opened["copies"][0]["what"] == "its data" and opened["copies"][0]["how"] == "copy"
    draft = AppClient(daemon, "counter--draft")
    assert draft.request("GET", "/").status_code == 401  # its own cookie
    assert draft.login(opened["url"]).status_code == 200
    shown = draft.request("GET", "/")
    assert "Counter, drafted" in shown.text and "Draft of counter" in shown.text
    assert draft.request("POST", "/api/count", Origin=draft.origin).json() == {"n": 2}
    assert app.request("GET", "/api/count").json() == {"n": 1}  # the app's own data untouched
    assert "Draft of" not in app.request("GET", "/").text

    assert api(daemon, "DELETE", f"/v1/sessions/{session['id']}").status_code == 204
    closed = draft.request("GET", "/")
    assert closed.status_code == 404 and "closed" in closed.text
    assert not (data_root / "apps" / "counter--draft").exists()
