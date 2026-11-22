"""Contract H, A5 on the computer: needs given (a host file, who works on its job, H.2), an
automation calling the app (I.3), notifications (desktop and inbox), runs of its job (H.11), with
the test app tests/fixtures/app-coach in a real sandbox. The desktop is a fake `notify-send`; who
works is the fake harness."""

import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from handler_control.secrets import SecretStore

from ..support.daemon import FAKE_SECRET, Daemon, start_daemon
from .conftest import (
    AppClient,
    add_app,
    api,
    call_app,
    copy_fixture,
    real_sandbox_env,
    requires_app_runtime,
)

pytestmark = requires_app_runtime


@pytest.fixture(scope="module")
def desktop(data_root: Path) -> Path:
    """A fake notify-send on the daemon's PATH, recording what it shows."""
    bin_dir = data_root / "bin"
    bin_dir.mkdir()
    shown = data_root / "shown.txt"
    fake = bin_dir / "notify-send"
    fake.write_text(f'#!/bin/sh\nprintf "%s|" "$@" >> {shown}\necho >> {shown}\n')
    fake.chmod(0o755)
    return shown


@pytest.fixture(scope="module")
def daemon(data_root: Path, desktop: Path) -> Iterator[Daemon]:
    env = {
        "HANDLER_DATA_DIR": str(data_root / "handler"),
        "PATH": f"{desktop.parent / 'bin'}:{os.environ['PATH']}",
    }
    # its own data folder: the fake account's login goes there too (who runs the app's job)
    SecretStore(data_root / "handler").put("accounts/fake/token", FAKE_SECRET)
    yield from start_daemon(extra_env=env | real_sandbox_env())


@pytest.fixture(scope="module")
def agenda(data_root: Path) -> Path:
    path = data_root / "notes" / "agenda.md"  # inside the home (dev_env.home_env)
    path.parent.mkdir()
    path.write_text("10:00 dentist\n14:00 call Bob\n")
    return path


RESULT = (
    '{ type = "object", required = ["status", "summary"], properties = { status = { enum = '
    '["ok", "attention", "failed"] }, summary = { type = "string" } } }'
)
FAKE = {"program": "fake", "account": "fake"}  # who works on its job: the fake harness


def manifest(source: Path) -> None:
    """The coach's app.toml: it reads the agenda (a file the person gives) and runs its job
    "coach" (H.11, its instructions jobs/coach.md)."""
    (source / "app.toml").write_text(
        f"""apiVersion = "handler.app/v1"
name = "coach"
version = "1.0.0"
[needs]
notify = true
[needs.files.agenda]
description = "Your agenda"
[jobs.coach]
description = "Answers what you ask"
result = {RESULT}
[jobs.coach.fields]
type = "object"
properties = {{ fake = {{ type = "string" }}, answer = {{}} }}
[routes]
"POST /api/checkin" = "queued"
"""
    )


def install(daemon: Daemon, source: Path, agenda: Path) -> None:
    """The coach registered and given what it needs (the agenda, who works), not deployed."""
    add_app(daemon, source)
    r = api(daemon, "PUT", "/v1/apps/coach/files/agenda", {"path": str(agenda)})
    assert r.status_code == 200, r.text
    assert api(daemon, "PUT", "/v1/apps/coach/who-works", FAKE).status_code == 200


@pytest.fixture(scope="module")
def source(data_root: Path) -> Path:
    path = copy_fixture("app-coach", data_root)
    manifest(path)
    return path


@pytest.fixture(scope="module")
def registered(daemon: Daemon, source: Path) -> dict[str, Any]:
    r = add_app(daemon, source)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture(scope="module")
def given(daemon: Daemon, agenda: Path, registered: dict[str, Any]) -> None:
    """The coach given what it needs (the agenda, who works on its job), not deployed."""
    r = api(daemon, "PUT", "/v1/apps/coach/files/agenda", {"path": str(agenda)})
    assert r.status_code == 200, r.text
    r = api(daemon, "PUT", "/v1/apps/coach/who-works", FAKE)
    assert r.status_code == 200, r.text


def runs(daemon: Daemon) -> list[dict[str, Any]]:
    """The coach's runs handlerd keeps (D: `GET /v1/apps/{name}/runs`)."""
    r = api(daemon, "GET", "/v1/apps/coach/runs")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def deployed(daemon: Daemon, given: None) -> None:
    r = api(daemon, "POST", "/v1/apps/coach/deploy")
    assert r.status_code == 200, api(daemon, "GET", "/v1/apps/coach/log").json()["text"]


@pytest.fixture(scope="module")
def morning(daemon: Daemon, deployed: None) -> dict[str, object]:
    """The run of an automation that called the coach's morning route (I.3), once it ended."""
    return call_app(daemon, "morning", "coach", "POST /api/cron/morning")


@pytest.mark.rule("deploy.what-it-adds-is-said-first", "deploy.only-with-all-it-needs")
def test_needs_are_shown(daemon: Daemon, registered: dict[str, Any]) -> None:
    added = registered["source"]["addedNeeds"]
    assert added == ["file agenda (ro)", "notifications", "job coach"]
    (folder,) = registered["files"]
    assert (folder["name"], folder["mode"], folder.get("path")) == ("agenda", "ro", None)
    assert "agents" not in registered and registered["jobs"][0]["name"] == "coach"
    r = api(daemon, "POST", "/v1/apps/coach/deploy")
    assert r.status_code == 422 and "folder agenda not given" in r.json()["detail"]


@pytest.mark.rule("app-need.a-folder-in-your-home-never-handler-s")
@pytest.mark.parametrize("where", ["outside", "handler"])
def test_files_refused(
    daemon: Daemon, registered: dict[str, Any], data_root: Path, where: str
) -> None:
    handler_own = data_root / "handler" / "apps"  # handler's data folder: never given to an app
    path = "/etc/hostname" if where == "outside" else str(handler_own)
    r = api(daemon, "PUT", "/v1/apps/coach/files/agenda", {"path": path})
    assert r.status_code == 409
    expected = "inside your home" if where == "outside" else "never given"
    assert expected in r.json()["detail"]


@pytest.mark.rule("app-need.yours-kept-by-handler")
def test_needs_given(daemon: Daemon, agenda: Path, registered: dict[str, Any]) -> None:
    r = api(daemon, "PUT", "/v1/apps/coach/files/agenda", {"path": str(agenda)})
    assert r.status_code == 200, r.text
    assert r.json()["files"][0]["path"] == str(agenda)
    r = api(daemon, "PUT", "/v1/apps/coach/who-works", FAKE)
    assert r.status_code == 200, r.text
    assert api(daemon, "GET", "/v1/apps/coach").json()["whoWorks"] == FAKE


@pytest.mark.rule(
    "app-notify.only-to-whom-it-is-shared-with",
    "automation.calls-an-app-s-route-as-the-owner",
    "inbox.told-by-handlerd-alone",
)
def test_an_automation_s_call_reads_the_file_and_notifies(
    daemon: Daemon, morning: dict[str, object], desktop: Path
) -> None:
    assert morning["state"] == "succeeded", morning.get("error")

    (note, *_) = api(daemon, "GET", "/v1/inbox").json()
    assert (note["source"], note["name"], note["person"]) == ("app", "coach", "owner")
    assert (note["title"], note["summary"]) == ("Today", "10:00 dentist")
    deadline = time.monotonic() + 10
    while not desktop.exists():
        assert time.monotonic() < deadline
        time.sleep(0.2)
    assert "coach: Today|10:00 dentist|" in desktop.read_text()


@pytest.mark.rule(
    "app-need.a-folder-in-your-home-never-handler-s", "automation.calls-an-app-s-route-as-the-owner"
)
def test_file_is_read_only(daemon: Daemon, morning: dict[str, object], agenda: Path) -> None:
    log = api(daemon, "GET", "/v1/apps/coach/log").json()["text"]
    assert "automation morning: POST /api/cron/morning: 200" in log
    assert agenda.read_text().startswith("10:00 dentist")


@pytest.mark.rule("app-notify.only-to-whom-it-is-shared-with")
def test_notify_only_persons_it_is_shared_with(daemon: Daemon, deployed: None) -> None:
    browser = AppClient(daemon, "coach")
    browser.login(api(daemon, "POST", "/v1/apps/coach/open").json()["url"])
    r = browser.request_json("POST", "/api/tell-alice", {})
    assert r == {"ok": False, "error": "Error: notify: coach is not shared with alice"}
    api(daemon, "PUT", "/v1/apps/coach/persons", {"persons": ["alice"]})
    assert browser.request_json("POST", "/api/tell-alice", {}) == {"ok": True}
    assert api(daemon, "GET", "/v1/inbox").json()[0]["person"] == "alice"


@pytest.mark.rule("automation.with-problems-never-runs")
def test_an_automation_of_an_unknown_app(daemon: Daemon) -> None:
    folder = daemon.config_dir / "automations" / "nope"
    folder.mkdir(parents=True)
    (folder / "automation.toml").write_text(
        'apiVersion = "handler.automation/v1"\nwhen = { every = "1h" }\n'
        'run = { app = "nope", call = "POST /api/x" }\n'
    )
    view = api(daemon, "GET", "/v1/automations/nope").json()
    assert view["problems"] == ["run.app: no app named nope"]


@pytest.mark.rule(
    "app-job.its-code-starts-one-only-while-answering-the-owner",
    "app-run.its-end-reaches-the-inbox",
)
def test_an_app_runs_its_job_for_the_owner(daemon: Daemon, deployed: None) -> None:
    browser = AppClient(daemon, "coach")
    browser.login(api(daemon, "POST", "/v1/apps/coach/open").json()["url"])
    asked = browser.request_json("POST", "/api/ask", {"request": "Call the bank before 10."})
    assert isinstance(asked, dict) and asked["ok"] is True, asked
    run = asked["run"]
    assert (run["job"], run["state"]) in {("coach", "waiting"), ("coach", "running")}
    deadline = time.monotonic() + 60
    while run["state"] in ("waiting", "running"):
        assert time.monotonic() < deadline
        time.sleep(0.5)
        run = browser.request_json("GET", f"/api/run?id={run['id']}", None)
        assert isinstance(run, dict)
    assert run["state"] == "succeeded", run.get("error")
    assert run["result"] == {"status": "attention", "summary": "Call the bank before 10."}
    session = api(daemon, "GET", f"/v1/sessions/{run['sessionId']}").json()
    assert (session["origin"], session["app"], session["job"]) == ("app", "coach", "coach")
    assert session.get("agentId") is None
    deadline = time.monotonic() + 10
    while not (notes := [n for n in api(daemon, "GET", "/v1/inbox").json() if n.get("status")]):
        assert time.monotonic() < deadline
        time.sleep(0.2)
    note = notes[0]
    assert note["source"] == "app"
    assert (note["name"], note["title"], note["app"], note["status"]) == (
        "coach",
        "coach",
        "coach",
        "attention",
    )
    assert note["summary"] == "Call the bank before 10." and note["sessionId"] == session["id"]


@pytest.mark.rule("app-job.its-code-starts-one-only-while-answering-the-owner")
def test_an_automation_s_call_runs_no_job(daemon: Daemon, deployed: None) -> None:
    before = runs(daemon)
    run = call_app(daemon, "asker", "coach", "POST /api/cron/ask")
    assert run["state"] == "succeeded", run  # the route answered: without a run
    assert runs(daemon) == before


@pytest.mark.rule("app-job.its-code-starts-one-only-while-answering-the-owner")
def test_an_opened_draft_runs_no_job(daemon: Daemon, given: None) -> None:
    """The app's draft opened, asked what makes the app run its job: the run is refused (a
    draft, as a deploy's trial, starts nothing) and no run starts.

    If this fails: trying a draft runs its jobs on your subscription, on the draft's say."""
    before = runs(daemon)
    drafter = api(daemon, "POST", "/v1/agents", {"name": "drafter", "model": {"account": "fake"}})
    body = {"agentId": drafter.json()["id"], "appDraft": {"app": "coach"}}
    session = api(daemon, "POST", "/v1/sessions", body).json()
    opened = api(daemon, "POST", f"/v1/apps/from-draft/{session['id']}/open")
    assert opened.status_code == 200, opened.text
    draft = AppClient(daemon, "coach--draft")
    assert draft.login(opened.json()["url"]).status_code == 200
    asked = draft.request_json("POST", "/api/ask", {"request": "Call the bank."})
    assert isinstance(asked, dict) and asked["ok"] is False, asked  # no start token given
    assert runs(daemon) == before
    assert api(daemon, "DELETE", f"/v1/sessions/{session['id']}").status_code == 204
