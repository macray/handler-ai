"""Contract H, A5 on the computer: host files, an automation calling the app (I.3), notifications
(desktop and inbox), with the test app tests/fixtures/miniapp-coach in podman. The desktop is a
fake `notify-send`."""

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from ..support.daemon import Daemon, start_daemon
from .conftest import AppClient, api, call_app, copy_fixture, gnome_env, requires_podman

pytestmark = requires_podman


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
    yield from start_daemon(extra_env=env | gnome_env(data_root))


@pytest.fixture(scope="module")
def agenda(data_root: Path) -> Path:
    path = data_root / "notes" / "agenda.md"  # inside the home (~/.cache/handler-tests/…)
    path.parent.mkdir()
    path.write_text("10:00 dentist\n14:00 call Bob\n")
    return path


def manifest(source: Path, file: Path | str) -> None:
    (source / "app.toml").write_text(
        f"""apiVersion = "handler.miniapp/v1"
name = "coach"
version = "1.0.0"
[needs]
files = [{{ path = "{file}" }}]
notify = true
[routes]
"POST /api/checkin" = "queued"
"""
    )


@pytest.fixture(scope="module")
def source(data_root: Path, agenda: Path) -> Path:
    path = copy_fixture("miniapp-coach", data_root)
    manifest(path, agenda)
    return path


def test_needs_are_shown(daemon: Daemon, source: Path, agenda: Path) -> None:
    app = api(daemon, "POST", "/v1/apps", {"sourceDir": str(source)}).json()
    assert app["source"]["addedNeeds"] == [f"file {agenda} (ro)", "notifications"]


@pytest.mark.parametrize("where", ["outside", "handler"])
def test_files_refused(
    daemon: Daemon, source: Path, agenda: Path, data_root: Path, where: str
) -> None:
    handler_own = data_root / "handler" / "apps"  # handler's data folder: never given to an app
    manifest(source, "/etc/hostname" if where == "outside" else handler_own)
    try:
        r = api(daemon, "POST", "/v1/apps/coach/deploy")
        assert r.status_code == 422
        expected = "inside your home" if where == "outside" else "never given"
        assert expected in r.json()["detail"]
    finally:
        manifest(source, agenda)


def test_an_automation_s_call_reads_the_file_and_notifies(daemon: Daemon, desktop: Path) -> None:
    r = api(daemon, "POST", "/v1/apps/coach/deploy")
    assert r.status_code == 200, api(daemon, "GET", "/v1/apps/coach/log").json()["text"]

    run = call_app(daemon, "morning", "coach", "POST /api/cron/morning")
    assert run["state"] == "succeeded", run

    (note, *_) = api(daemon, "GET", "/v1/inbox").json()
    assert (note["source"], note["name"], note["person"]) == ("app", "coach", "owner")
    assert (note["title"], note["summary"]) == ("Today", "10:00 dentist")
    deadline = time.monotonic() + 10
    while not desktop.exists():
        assert time.monotonic() < deadline
        time.sleep(0.2)
    assert "coach: Today|10:00 dentist|" in desktop.read_text()


def test_file_is_read_only(daemon: Daemon, agenda: Path) -> None:
    log = api(daemon, "GET", "/v1/apps/coach/log").json()["text"]
    assert "automation morning: POST /api/cron/morning: 200" in log
    assert agenda.read_text().startswith("10:00 dentist")


def test_notify_only_persons_it_is_shared_with(daemon: Daemon) -> None:
    browser = AppClient(daemon, "coach")
    browser.login(api(daemon, "POST", "/v1/apps/coach/open").json()["url"])
    r = browser.request_json("POST", "/api/tell-alice", {})
    assert r == {"ok": False, "error": 'Error: notify: {"error": "coach is not shared with alice"}'}
    api(daemon, "PUT", "/v1/apps/coach/persons", {"persons": ["alice"]})
    assert browser.request_json("POST", "/api/tell-alice", {}) == {"ok": True}
    assert api(daemon, "GET", "/v1/inbox").json()[0]["person"] == "alice"


def test_an_automation_of_an_unknown_app(daemon: Daemon) -> None:
    folder = daemon.config_dir / "automations" / "nope"
    folder.mkdir(parents=True)
    (folder / "automation.toml").write_text(
        'apiVersion = "handler.automation/v1"\nwhen = { every = "1h" }\n'
        'run = { app = "nope", call = "POST /api/x" }\n'
    )
    view = api(daemon, "GET", "/v1/automations/nope").json()
    assert view["problems"] == ["run.app: no app named nope"]
