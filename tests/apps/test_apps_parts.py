"""H.14, an app's parts: the agent set up for an app is the app's, never a project's (not adopted
by the project made on its folder, refused as a project's agent), started only by the app, and
removed with it (with the automation running it). A project lists the apps given its folder."""

from pathlib import Path
from typing import Any

from ..support.daemon import Daemon
from .conftest import add_app, api, copy_fixture


def manifest(source: Path) -> None:
    (source / "app.toml").write_text(
        """apiVersion = "handler.app/v1"
name = "keeper"
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
