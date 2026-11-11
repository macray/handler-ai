"""Contract H, A5 on the computer: needs given (a host file, an agent set up from the app's
definition, H.2), an automation calling the app (I.3), notifications (desktop and inbox), runs of
the agent (H.11), with the test app tests/fixtures/app-coach in a real sandbox. The desktop is a fake
`notify-send`; the agent is the fake one."""

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
    # its own data folder: the fake account's login goes there too (the agent the app runs)
    SecretStore(data_root / "handler").put("accounts/fake/token", FAKE_SECRET)
    yield from start_daemon(extra_env=env | real_sandbox_env())


@pytest.fixture(scope="module")
def agenda(data_root: Path) -> Path:
    path = data_root / "notes" / "agenda.md"  # inside the home (dev_env.home_env)
    path.parent.mkdir()
    path.write_text("10:00 dentist\n14:00 call Bob\n")
    return path


def manifest(source: Path) -> None:
    """The coach's app.toml: it reads the agenda (a file the person gives) and runs the agent
    given for its need "coach" (H.11), set up from agent/."""
    (source / "app.toml").write_text(
        """apiVersion = "handler.app/v1"
name = "coach"
version = "1.0.0"
[needs]
notify = true
[needs.files.agenda]
description = "Your agenda"
[needs.agents.coach]
description = "Answers what you ask"
from = "agent"
[routes]
"POST /api/checkin" = "queued"
"""
    )


def set_up_agent(daemon: Daemon, app: dict[str, Any]) -> dict[str, Any]:
    """The agent the coach needs, set up from the app's definition (its origin) on the fake
    harness, as the web UI's set-up page does."""
    (need,) = app["agents"]
    definition = need["definition"]
    body = {
        "name": definition["agentName"],
        "model": {"account": "fake"},
        "permissions": definition["permissions"],
        "interface": definition["interface"],
        "origin": need["origin"],
        "app": need["origin"]["name"],
    }
    r = api(daemon, "POST", "/v1/agents", body)
    assert r.status_code == 201, r.text
    return r.json()


def install(daemon: Daemon, source: Path, agenda: Path) -> None:
    """The coach registered and given what it needs (the agenda, its agent), not deployed."""
    app = add_app(daemon, source).json()
    r = api(daemon, "PUT", "/v1/apps/coach/files/agenda", {"path": str(agenda)})
    assert r.status_code == 200, r.text
    body = {"agentId": set_up_agent(daemon, app)["id"]}
    assert api(daemon, "PUT", "/v1/apps/coach/agents/coach", body).status_code == 200


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
def coach(daemon: Daemon, registered: dict[str, Any]) -> dict[str, Any]:
    """The job the app runs: set up from the app's definition."""
    agent = set_up_agent(daemon, registered)
    assert agent["origin"] == {"kind": "app", "name": "coach", "agent": "coach"}
    return agent


@pytest.mark.rule("deploy.what-it-adds-is-said-first", "deploy.only-with-all-it-needs")
def test_needs_are_shown(daemon: Daemon, registered: dict[str, Any]) -> None:
    added = registered["source"]["addedNeeds"]
    assert added == ["file agenda (ro)", "notifications", "agent coach"]
    (folder,) = registered["files"]
    assert (folder["name"], folder["mode"], folder.get("path")) == ("agenda", "ro", None)
    (need,) = registered["agents"]
    assert (need["name"], need["fits"], need.get("agentId")) == ("coach", [], None)
    assert need["definition"]["agentName"] == "Coach"
    r = api(daemon, "POST", "/v1/apps/coach/deploy")
    assert r.status_code == 422 and "folder agenda not given" in r.json()["detail"]


@pytest.mark.rule("need.a-folder-in-your-home-never-handler-s")
@pytest.mark.parametrize("where", ["outside", "handler"])
def test_files_refused(daemon: Daemon, data_root: Path, where: str) -> None:
    handler_own = data_root / "handler" / "apps"  # handler's data folder: never given to an app
    path = "/etc/hostname" if where == "outside" else str(handler_own)
    r = api(daemon, "PUT", "/v1/apps/coach/files/agenda", {"path": path})
    assert r.status_code == 409
    expected = "inside your home" if where == "outside" else "never given"
    assert expected in r.json()["detail"]


@pytest.mark.rule("need.yours-kept-by-handler", "need.an-agent-that-fits")
def test_needs_given(daemon: Daemon, agenda: Path, coach: dict[str, Any]) -> None:
    r = api(daemon, "PUT", "/v1/apps/coach/files/agenda", {"path": str(agenda)})
    assert r.status_code == 200, r.text
    assert r.json()["files"][0]["path"] == str(agenda)
    (need,) = api(daemon, "GET", "/v1/apps/coach").json()["agents"]
    assert need["fits"] == [coach["id"]]  # set up from its definition: it fits
    r = api(daemon, "PUT", "/v1/apps/coach/agents/coach", {"agentId": "nope"})
    assert r.status_code == 409 and "deleted" in r.json()["detail"]
    r = api(daemon, "PUT", "/v1/apps/coach/agents/coach", {"agentId": coach["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["agents"][0]["agentId"] == coach["id"]


@pytest.mark.rule(
    "notify.only-to-whom-it-is-shared-with", "call.an-app-s-route-as-you", "inbox.what-it-is-told"
)
def test_an_automation_s_call_reads_the_file_and_notifies(daemon: Daemon, desktop: Path) -> None:
    r = api(daemon, "POST", "/v1/apps/coach/deploy")
    assert r.status_code == 200, api(daemon, "GET", "/v1/apps/coach/log").json()["text"]

    run = call_app(daemon, "morning", "coach", "POST /api/cron/morning")
    assert run["state"] == "succeeded", run.get("error")

    (note, *_) = api(daemon, "GET", "/v1/inbox").json()
    assert (note["source"], note["name"], note["person"]) == ("app", "coach", "owner")
    assert (note["title"], note["summary"]) == ("Today", "10:00 dentist")
    deadline = time.monotonic() + 10
    while not desktop.exists():
        assert time.monotonic() < deadline
        time.sleep(0.2)
    assert "coach: Today|10:00 dentist|" in desktop.read_text()


@pytest.mark.rule("need.a-folder-in-your-home-never-handler-s", "call.an-app-s-route-as-you")
def test_file_is_read_only(daemon: Daemon, agenda: Path) -> None:
    log = api(daemon, "GET", "/v1/apps/coach/log").json()["text"]
    assert "automation morning: POST /api/cron/morning: 200" in log
    assert agenda.read_text().startswith("10:00 dentist")


@pytest.mark.rule("notify.only-to-whom-it-is-shared-with")
def test_notify_only_persons_it_is_shared_with(daemon: Daemon) -> None:
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


@pytest.mark.rule("run.only-while-it-answers-the-owner", "run.its-end-reaches-the-inbox")
def test_an_app_runs_an_agent_for_the_owner(daemon: Daemon, coach: dict[str, Any]) -> None:
    browser = AppClient(daemon, "coach")
    browser.login(api(daemon, "POST", "/v1/apps/coach/open").json()["url"])
    asked = browser.request_json("POST", "/api/ask", {"request": "Call the bank before 10."})
    assert isinstance(asked, dict) and asked["ok"] is True, asked
    run = asked["run"]
    assert (run["agent"], run["state"]) in {("coach", "waiting"), ("coach", "running")}
    deadline = time.monotonic() + 60
    while run["state"] in ("waiting", "running"):
        assert time.monotonic() < deadline
        time.sleep(0.5)
        run = browser.request_json("GET", f"/api/run?id={run['id']}", None)
        assert isinstance(run, dict)
    assert run["state"] == "succeeded", run.get("error")
    assert run["result"] == {"status": "attention", "summary": "Call the bank before 10."}
    session = api(daemon, "GET", f"/v1/sessions/{run['sessionId']}").json()
    assert (session["origin"], session["app"], session["agentId"]) == ("app", "coach", coach["id"])
    deadline = time.monotonic() + 10
    while (note := api(daemon, "GET", "/v1/inbox").json()[0])["source"] != "app" or not note.get(
        "agent"
    ):
        assert time.monotonic() < deadline
        time.sleep(0.2)
    assert (note["name"], note["agent"], note["app"], note["status"]) == (
        "coach",
        "Coach",
        "coach",
        "attention",
    )
    assert note["summary"] == "Call the bank before 10." and note["sessionId"] == session["id"]


@pytest.mark.rule("run.only-while-it-answers-the-owner")
def test_an_automation_s_call_runs_no_agent(daemon: Daemon, coach: dict[str, Any]) -> None:
    before = api(daemon, "GET", f"/v1/sessions?agentId={coach['id']}").json()
    run = call_app(daemon, "asker", "coach", "POST /api/cron/ask")
    assert run["state"] == "succeeded", run  # the route answered: without a run
    assert api(daemon, "GET", f"/v1/sessions?agentId={coach['id']}").json() == before


@pytest.mark.rule("run.only-while-it-answers-the-owner")
def test_an_opened_draft_runs_no_agent(daemon: Daemon, coach: dict[str, Any]) -> None:
    """The app's draft opened, asked what makes the app run its agent: the run is refused (a
    draft, as a deploy's trial, starts nothing) and no session of the agent starts.

    If this fails: trying a draft runs your agents on your subscription, on the draft's say."""
    before = api(daemon, "GET", f"/v1/sessions?agentId={coach['id']}").json()
    drafter = api(daemon, "POST", "/v1/agents", {"name": "drafter", "model": {"account": "fake"}})
    body = {"agentId": drafter.json()["id"], "appDraft": {"app": "coach"}}
    session = api(daemon, "POST", "/v1/sessions", body).json()
    opened = api(daemon, "POST", f"/v1/apps/from-draft/{session['id']}/open")
    assert opened.status_code == 200, opened.text
    draft = AppClient(daemon, "coach--draft")
    assert draft.login(opened.json()["url"]).status_code == 200
    asked = draft.request_json("POST", "/api/ask", {"request": "Call the bank."})
    assert isinstance(asked, dict) and asked["ok"] is False, asked  # no start token given
    assert api(daemon, "GET", f"/v1/sessions?agentId={coach['id']}").json() == before
    assert api(daemon, "DELETE", f"/v1/sessions/{session['id']}").status_code == 204
