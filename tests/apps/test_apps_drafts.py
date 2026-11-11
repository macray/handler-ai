"""H.15 conformance: drafts of an app's code on a real handlerd. A folderless agent's session works
on a copy of an app's code (one draft per app at a time), or on an empty folder for a new app;
used, the draft becomes the app's next version, or a new app. The App creator, the helper that
writes them, has no folder. No deploy here: no podman needed."""

import shutil
from pathlib import Path
from typing import Any

import pytest

from ..support.daemon import Daemon
from .conftest import add_app, api, copy_fixture


def folderless(daemon: Daemon, **body: Any) -> dict[str, Any]:
    r = api(daemon, "POST", "/v1/agents", {"name": "drafter", "model": {"account": "fake"}} | body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.rule("app.one-name-one-app", "draft.one-at-a-time-on-a-copy")
def test_a_draft_of_an_apps_code_becomes_its_next_version(daemon: Daemon, data_root: Path) -> None:
    source = copy_fixture("app", data_root)
    assert add_app(daemon, source).status_code == 201
    agent = folderless(daemon)

    r = api(
        daemon, "POST", "/v1/sessions", {"agentId": agent["id"], "appDraft": {"app": "counter"}}
    )
    assert r.status_code == 202, r.text
    session = r.json()
    assert session["appDraft"] == {"app": "counter"}
    draft = Path(session["scope"])
    assert draft.name == "work" and (draft / "app.toml").is_file()  # a copy of its code
    again = api(
        daemon, "POST", "/v1/sessions", {"agentId": agent["id"], "appDraft": {"app": "counter"}}
    )
    assert again.status_code == 409 and "waiting" in again.json()["title"]

    manifest = draft / "app.toml"
    manifest.write_text(manifest.read_text().replace('version = "1.0.0"', 'version = "1.1.0"'))
    (draft / "ui" / "node_modules").mkdir(parents=True)  # what is rebuilt is not kept
    used = api(daemon, "POST", f"/v1/apps/from-draft/{session['id']}")
    assert used.status_code == 200, used.text
    assert used.json()["source"]["version"] == "1.1.0"
    assert "current" not in used.json()  # used, not deployed: its page deploys it
    assert api(daemon, "GET", f"/v1/sessions/{session['id']}").status_code == 404  # it went
    kept = data_root / "apps" / "counter" / "source"
    assert (kept / "app.toml").is_file() and not (kept / "ui" / "node_modules").exists()

    other = api(
        daemon, "POST", "/v1/sessions", {"agentId": agent["id"], "appDraft": {"app": "counter"}}
    )
    assert other.status_code == 202  # the draft was used: another may start
    renamed = Path(other.json()["scope"]) / "app.toml"
    renamed.write_text(renamed.read_text().replace('name = "counter"', 'name = "other"'))
    refused = api(daemon, "POST", f"/v1/apps/from-draft/{other.json()['id']}")
    assert refused.status_code == 409 and "names another app" in refused.json()["detail"]
    assert api(daemon, "DELETE", f"/v1/sessions/{other.json()['id']}").status_code == 204


@pytest.mark.rule("draft.one-at-a-time-on-a-copy")
def test_a_draft_of_a_new_app(daemon: Daemon, data_root: Path) -> None:
    agent = folderless(daemon, name="new-drafter")
    r = api(daemon, "POST", "/v1/sessions", {"agentId": agent["id"], "appDraft": {}})
    assert r.status_code == 202, r.text
    draft = Path(r.json()["scope"])
    assert list(draft.iterdir()) == []
    shutil.copytree(copy_fixture("app", data_root / "new"), draft, dirs_exist_ok=True)
    manifest = draft / "app.toml"
    manifest.write_text(manifest.read_text().replace('name = "counter"', 'name = "tally"'))
    used = api(daemon, "POST", f"/v1/apps/from-draft/{r.json()['id']}")
    assert used.status_code == 201, used.text
    assert used.json()["name"] == "tally" and "fromSource" not in used.json()

    scoped = daemon.create_ad_hoc("fake", daemon.make_scope())
    body = {"agentId": scoped["id"], "appDraft": {}}
    assert api(daemon, "POST", "/v1/sessions", body).json()["title"] == "a folderless agent's only"
    missing = {"agentId": agent["id"], "appDraft": {"app": "nope"}}
    assert api(daemon, "POST", "/v1/sessions", missing).status_code == 404


@pytest.mark.rule("draft.one-at-a-time-on-a-copy")
def test_the_app_creator_has_no_folder(daemon: Daemon) -> None:
    """One App creator, given as any helper is; one set up for its need fits only with no
    folder (each session works on a draft)."""
    origin = {"kind": "handler-need", "name": "app-creator", "version": 1}
    loose = folderless(daemon, name="App creator", origin=origin, addons=[])
    scoped = daemon.create_ad_hoc("fake", daemon.make_scope(), name="creator", origin=origin)
    needs = api(daemon, "GET", "/v1/handler-needs").json()
    need = next(n for n in needs if n["name"] == "app-creator")
    assert loose["id"] in need["fits"] and scoped["id"] not in need["fits"]
    refused = api(daemon, "PUT", "/v1/handler-needs/app-creator", {"agentId": scoped["id"]})
    assert refused.status_code == 409 and "no folder" in refused.json()["detail"]
    given = api(daemon, "PUT", "/v1/handler-needs/app-creator", {"agentId": loose["id"]})
    assert given.status_code == 200 and given.json()["agentId"] == loose["id"]
