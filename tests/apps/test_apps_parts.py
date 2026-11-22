"""H.14, an app's parts: its jobs (their runs and harness state) and the automations running
them or calling its routes, removed with the app; your folders stay. A project lists the apps
given its folder."""

from pathlib import Path
from typing import Any

import pytest

from ..support.daemon import Daemon
from .conftest import add_app, api, copy_fixture

RESULT = (
    '{ type = "object", required = ["status", "summary"], properties = { status = { enum = '
    '["ok", "attention", "failed"] }, summary = { type = "string" } } }'
)


def manifest(source: Path, name: str = "keeper") -> None:
    (source / "app.toml").write_text(
        f"""apiVersion = "handler.app/v1"
name = "{name}"
version = "1.0.0"
[needs.files.data]
description = "Where it keeps your things"
mode = "rw"
[jobs.coach]
description = "Sorts your things"
files = {{ data = "write" }}
worksIn = ["data"]
result = {RESULT}
[routes]
"POST /api/checkin" = "queued"
"""
    )


def automation(name: str, run: dict[str, Any]) -> dict[str, Any]:
    definition = {"apiVersion": "handler.automation/v1", "when": {"every": "5h"}, "run": run}
    return {"name": name, "definition": definition, "enable": False}


@pytest.mark.rule("app.uninstalled-leaves-nothing-of-it", "app-part.removed-with-its-app")
def test_an_app_s_parts_go_with_it(daemon: Daemon, data_root: Path) -> None:
    """Uninstalled, an app takes the automations running its jobs or calling its routes along;
    an automation of yours running an agent stays; the project on its folder no longer lists it,
    and the folder stays.

    If this fails: an uninstalled app leaves schedules running, failing at each slot, or an app
    installed later under its name runs them."""
    source = copy_fixture("app-coach", data_root)
    manifest(source)
    folder = daemon.make_scope()
    add_app(daemon, source)
    assert api(daemon, "PUT", "/v1/apps/keeper/files/data", {"path": str(folder)}).is_success
    who = {"program": "fake", "account": "fake"}
    assert api(daemon, "PUT", "/v1/apps/keeper/who-works", who).is_success

    project_body: dict[str, Any] = {
        "name": "keeping",
        "folder": str(folder),
        "agents": [{"name": "dev", "model": {"account": "fake"}}],
    }
    project = api(daemon, "POST", "/v1/projects", project_body).json()
    assert project["apps"] == ["keeper"]  # the app given its folder, listed from its side

    for body in [
        automation("keeper-sort", {"app": "keeper", "job": "coach"}),
        automation("keeper-call", {"app": "keeper", "call": "POST /api/checkin"}),
        automation("mine", {"agent": "dev", "project": "keeping"}),
    ]:
        made = api(daemon, "POST", "/v1/automations", body)
        assert made.status_code in (200, 201), made.text

    assert api(daemon, "DELETE", "/v1/apps/keeper").status_code == 204
    assert api(daemon, "GET", "/v1/automations/keeper-sort").status_code == 404
    assert api(daemon, "GET", "/v1/automations/keeper-call").status_code == 404
    assert api(daemon, "GET", "/v1/automations/mine").status_code == 200
    assert api(daemon, "GET", f"/v1/projects/{project['id']}").json()["apps"] == []
    assert folder.is_dir()  # your files stay
