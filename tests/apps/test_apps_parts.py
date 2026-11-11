"""H.14, an app's parts: the agent set up for an app is the app's, never a project's (not adopted
by the project made on its folder, refused as a project's agent), started only by the app, and
removed with it (with the automation running it). A project lists the apps given its folder."""

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest

from ..support.daemon import Daemon
from .conftest import FIXTURES, add_app, api, copy_fixture


def manifest(source: Path, name: str = "keeper") -> None:
    (source / "app.toml").write_text(
        f"""apiVersion = "handler.app/v1"
name = "{name}"
version = "1.0.0"
[needs.files.data]
description = "Where it keeps your things"
mode = "rw"
[needs.agents.keeper]
description = "Sorts your things"
from = "agent"
works_in = "data"
[routes]
"POST /api/checkin" = "queued"
"""
    )


@pytest.mark.rule(
    "app.uninstalled-leaves-nothing-of-it",
    "part.its-app-s-only",
    "part.started-by-its-app-only",
    "part.removed-with-its-app",
)
def test_an_apps_agent_is_its_part(daemon: Daemon, data_root: Path) -> None:
    source = copy_fixture("app-coach", data_root)
    manifest(source)
    folder = daemon.make_scope()
    app = add_app(daemon, source).json()
    assert api(daemon, "PUT", "/v1/apps/keeper/files/data", {"path": str(folder)}).is_success
    (need,) = app["agents"]
    definition = need["definition"]
    body: dict[str, Any] = {
        "name": definition["agentName"],
        "scope": str(folder),
        "model": {"account": "fake"},
        "permissions": definition["permissions"],
        "interface": definition["interface"],
        "origin": need["origin"],
        "app": need["origin"]["name"],
    }
    agent = api(daemon, "POST", "/v1/agents", body).json()
    assert api(daemon, "PUT", "/v1/apps/keeper/agents/keeper", {"agentId": agent["id"]}).is_success

    project_body: dict[str, Any] = {
        "name": "keeping",
        "folder": str(folder),
        "agents": [{"name": "dev", "model": {"account": "fake"}}],
    }
    project = api(daemon, "POST", "/v1/projects", project_body).json()
    assert project["apps"] == ["keeper"]  # the app given its folder, listed from its side
    assert "projectId" not in api(daemon, "GET", f"/v1/agents/{agent['id']}").json()
    as_project_agent = api(
        daemon,
        "POST",
        "/v1/agents",
        {k: v for k, v in body.items() if k not in ("scope", "app")}
        | {"name": "keeper too", "projectId": project["id"]},
    )
    assert as_project_agent.status_code == 400, as_project_agent.text
    assert "app keeper" in as_project_agent.json()["detail"]

    started = api(daemon, "POST", "/v1/sessions", {"agentId": agent["id"]})
    assert started.status_code == 409 and "ask the app" in started.json()["detail"]

    automation = {
        "name": "keeper-sort",
        "definition": {
            "apiVersion": "handler.automation/v1",
            "when": {"every": "5h"},
            "run": {"agent": definition["agentName"]},
            "app": "keeper",
        },
        "agentId": agent["id"],
        "enable": False,
    }
    made = api(daemon, "POST", "/v1/automations", automation)
    assert made.status_code in (200, 201), made.text

    assert api(daemon, "DELETE", "/v1/apps/keeper").status_code == 204
    assert api(daemon, "GET", f"/v1/agents/{agent['id']}").status_code == 404
    assert api(daemon, "GET", "/v1/automations/keeper-sort").status_code == 404
    assert api(daemon, "GET", f"/v1/projects/{project['id']}").json()["apps"] == []
    assert folder.is_dir()  # your files stay


def _part_of(daemon: Daemon, data_root: Path, app: str) -> dict[str, Any]:
    """The app `app` (the keeper's code under that name), installed, and the agent set up from
    its need."""
    source = data_root / "src" / f"{app}-{uuid.uuid4().hex[:6]}"
    shutil.copytree(FIXTURES / "app-coach", source)
    manifest(source, app)
    (need,) = add_app(daemon, source).json()["agents"]
    folder = daemon.make_scope()
    assert api(daemon, "PUT", f"/v1/apps/{app}/files/data", {"path": str(folder)}).is_success
    definition = need["definition"]
    body = {
        "name": definition["agentName"],
        "scope": str(folder),
        "model": {"account": "fake"},
        "permissions": definition["permissions"],
        "interface": definition["interface"],
        "origin": need["origin"],
        "app": app,
    }
    made = api(daemon, "POST", "/v1/agents", body)
    assert made.status_code == 201, made.text
    return made.json()


@pytest.mark.rule("part.its-app-s-only")
def test_an_apps_part_is_given_for_no_other_app_s_need(daemon: Daemon, data_root: Path) -> None:
    """Two apps with the same need: the agent set up for one is refused for the other's (409,
    naming its app), though it fits; each app takes its own.

    If this fails: an app's agent serves another app, with that app's folder and fields."""
    keeper = _part_of(daemon, data_root, "keeper-a")
    other = _part_of(daemon, data_root, "keeper-b")
    r = api(daemon, "PUT", "/v1/apps/keeper-b/agents/keeper", {"agentId": keeper["id"]})
    assert r.status_code == 409 and "one of the app keeper-a's parts" in r.text, r.text
    r = api(daemon, "PUT", "/v1/apps/keeper-b/agents/keeper", {"agentId": other["id"]})
    assert r.is_success, r.text


@pytest.mark.rule("action.done-by-its-code-or-its-agent")
def test_a_deploy_fails_when_an_agent_s_action_does_not_say_how_it_went(
    daemon: Daemon, data_root: Path
) -> None:
    """If this fails: Ask says an action was done when its agent failed, or shows nothing."""
    source = data_root / "src" / f"asker-{uuid.uuid4().hex[:6]}"
    shutil.copytree(FIXTURES / "app-coach", source)
    interface = json.loads((source / "agent" / "interface.json").read_text())
    interface["result"]["required"] = ["status"]  # no summary
    (source / "agent" / "interface.json").write_text(json.dumps(interface))
    (source / "app.toml").write_text(
        'apiVersion = "handler.app/v1"\nname = "asker"\nversion = "1.0.0"\n'
        '[needs.agents.coach]\ndescription = "Answers"\nfrom = "agent"\n'
        '[actions.ask]\ndescription = "Ask the coach"\nagent = "coach"\n'
    )
    added = add_app(daemon, source)
    assert added.status_code == 201, added.text
    (need,) = added.json()["agents"]
    definition = need["definition"]
    body = {
        "name": definition["agentName"],
        "scope": str(daemon.make_scope()),
        "model": {"account": "fake"},
        "permissions": definition["permissions"],
        "interface": definition["interface"],
        "origin": need["origin"],
        "app": "asker",
    }
    agent = api(daemon, "POST", "/v1/agents", body)
    assert agent.status_code == 201, agent.text
    given = api(daemon, "PUT", "/v1/apps/asker/agents/coach", {"agentId": agent.json()["id"]})
    assert given.is_success, given.text
    r = api(daemon, "POST", "/v1/apps/asker/deploy")
    assert r.status_code == 422, r.text
    assert "actions.ask: the agent coach: its result has no required 'summary'" in r.text
