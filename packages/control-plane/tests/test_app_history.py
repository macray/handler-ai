"""Unit tests: an app's code reads the history of the folders it writes on handler.sock (H.9),
`GET /history?files=<need>` and `GET /history/{id}?files=<need>`: its own read-write folders
only, read only. The history itself (commits, undo): test_notes_history.py."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import AppManifest
from handler_control import desktop
from handler_control.agents import AgentRegistry
from handler_control.app_runs import AppRuns
from handler_control.apps import AppRecord, AppStore, Deployment
from handler_control.inbox import Inbox
from handler_control.notes_history import NotesHistories
from handler_control.sessions import SessionStore
from handler_control.settings import Settings

MANIFEST = """apiVersion = "handler.app/v1"
name = "planner"
version = "1.0.0"
[needs.files.tasks]
description = "Your calendar"
mode = "rw"
[needs.files.refs]
description = "What it reads"
"""


class Fixture:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop, "notify", lambda *_: None)
        self.settings = Settings(
            port=0,
            config_dir=tmp_path / "config",
            state_dir=tmp_path / "state",
            bindings_dir=tmp_path / "config",
            data_dir=tmp_path / "data",
            knowledge_dir=tmp_path / "notes",
            allowed_origins=frozenset(),
            web_ui_dir=tmp_path,
        )
        registry = AgentRegistry(self.settings.state_dir)
        inbox = Inbox(self.settings)
        runs = AppRuns(self.settings, SessionStore(self.settings, registry), inbox)
        self.store = AppStore(self.settings, "t0ken", inbox, runs)
        self.notes = NotesHistories(
            self.settings, registry, inbox, lambda a: a.name or "", self.store.written_folders
        )
        self.store.history = self.notes
        self.tasks = tmp_path / "planner"
        self.refs = tmp_path / "refs"
        for folder in (self.tasks, self.refs):
            folder.mkdir()
        (self.tasks / "calendar.md").write_text("# Calendar\n")
        version = self.store.version_dir("planner", 1)
        version.mkdir(parents=True)
        (version / "app.toml").write_text(MANIFEST)
        self.store.records["planner"] = AppRecord(
            name="planner",
            deployments=[Deployment(1, "1.0.0", datetime.now(UTC))],
            files={"tasks": str(self.tasks), "refs": str(self.refs)},
        )

    def call(self, method: str, path: str) -> tuple[int, dict[str, Any]]:
        return asyncio.run(self.store.from_app("planner", method, path, None))


@pytest.fixture
def f(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fixture:
    return Fixture(tmp_path, monkeypatch)


def test_a_read_write_files_need_is_enough_to_reach_handler() -> None:
    """An app whose only Handler need is a folder it writes still gets handler.sock: its
    history is read there.

    If this fails: such an app's code gets no socket, and its history calls fail to connect."""
    manifest = AppManifest.model_validate(
        {
            "apiVersion": "handler.app/v1",
            "name": "x",
            "version": "1.0.0",
            "needs": {"files": {"tasks": {"description": "d", "mode": "rw"}}},
        }
    )
    assert manifest.handler_api
    read_only = manifest.model_copy(
        update={"needs": manifest.needs.model_copy(update={"files": {}})}
    )
    assert not read_only.handler_api


@pytest.mark.rule("app-sock.history-read-only", "app-sock.answers-only-what-the-app-declares")
def test_its_code_reads_the_changes_of_the_folder_it_writes(f: Fixture) -> None:
    """The commits of its read-write folder, newest first, and one's files with their lines.

    If this fails: the app cannot show what its job or you changed in its files."""
    f.notes.commit_all(started=True)
    (f.tasks / "calendar.md").write_text("# Calendar\n\n## To do\n- [ ] Buy milk\n")
    f.notes.commit_all()
    status, history = f.call("GET", "/history?files=tasks")
    assert status == 200, history
    assert history["folder"] == str(f.tasks.resolve())
    assert [c["kind"] for c in history["commits"]] == ["changes", "first"]
    latest = history["commits"][0]
    status, diff = f.call("GET", f"/history/{latest['id']}?files=tasks")
    assert status == 200, diff
    [file] = diff["files"]
    assert (file["path"], file["change"]) == ("calendar.md", "changed")
    assert "+- [ ] Buy milk" in file["diff"]


@pytest.mark.rule("app-sock.history-read-only")
def test_only_its_own_read_write_folders_and_never_an_undo(f: Fixture) -> None:
    """A read-only need, a need it does not declare, another path, a write: refused.

    If this fails: an app reads what it was never given to write, or rewrites the history
    meant to undo what it did."""
    f.notes.commit_all(started=True)
    assert f.call("GET", "/history?files=refs")[0] == 403  # read only: no history of its own
    assert f.call("GET", "/history?files=other")[0] == 403
    assert f.call("GET", "/history")[0] == 403
    assert f.call("POST", "/history/undo?files=tasks")[0] == 404
    assert f.call("DELETE", "/history?files=tasks")[0] == 404
    status, answer = f.call("GET", "/history/0123456789abcdef0123456789abcdef01234567?files=tasks")
    assert status == 404 and "no change" in answer["error"]


def test_a_folder_with_no_history_yet_is_404(f: Fixture) -> None:
    """Before handlerd's first look at the folder, there is nothing to read: said, not a
    failure of Handler's."""
    status, answer = f.call("GET", "/history?files=tasks")
    assert status == 404 and "has no history" in answer["error"]
