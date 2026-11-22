"""D.5's notes history through a real handlerd: a folder given read-write gets its history when
the agent is saved, what changed while handlerd was off is committed at its start, a change is
read and undone through the API; a folder no agent writes has none."""

import shutil
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from ..support import dev_env
from ..support.daemon import Daemon, start_daemon


@pytest.fixture(scope="module")
def root() -> Iterator[Path]:
    base = dev_env.scope_root() / f"notes-history-{uuid.uuid4().hex[:8]}"
    (base / "people").mkdir(parents=True)
    (base / "people" / "ada.md").write_text("# Ada\n")
    (base / "read-only").mkdir()
    yield base
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture(scope="module")
def daemon(root: Path) -> Iterator[Daemon]:
    yield from start_daemon(extra_env={"HANDLER_NOTES_DIR": str(root)})


@pytest.mark.rule(
    "notes.writable-has-a-history",
    "notes.handler-writes-only-what-you-asked",
    "notes.agents-never-reach-the-history",
)
def test_a_read_write_folder_s_history_through_the_api(daemon: Daemon, root: Path) -> None:
    """Saved with the folder read-write: its first state at once, in Handler's data; changed
    while handlerd was off: committed at its start, its lines readable; undone: the file as it
    was, in a commit of its own.

    If this fails: you cannot see or undo what changed in a folder agents may write."""
    daemon.create_ad_hoc(
        "fake", daemon.make_scope(), knowledge=[{"folder": "people", "access": "write"}]
    )
    with daemon.http() as c:
        [first] = c.get("/v1/knowledge/history", params={"folder": "people"}).json()["commits"]
        assert (first["kind"], first["fileCount"]) == ("first", 1)
        assert c.get("/v1/knowledge/history", params={"folder": "read-only"}).status_code == 404
    assert len(list((daemon.data_dir / "notes-history").iterdir())) == 1

    (root / "people" / "ada.md").write_text("# Ada Lovelace\n")
    daemon.restart()
    with daemon.http() as c:
        commits = until_committed(c, "people", 2)  # a look at its start, beside serving
        assert [x["kind"] for x in commits] == ["while-off", "first"]
        change = commits[0]
        assert change["files"] == [
            {"path": "ada.md", "change": "changed", "link": False, "added": 1, "removed": 1}
        ]
        detail = c.get(f"/v1/knowledge/history/{change['id']}", params={"folder": "people"})
        assert detail.json()["files"][0]["diff"] == "@@ -1 +1 @@\n-# Ada\n+# Ada Lovelace\n"

        first_undo = {"folder": "people", "commit": first["id"]}
        assert c.post("/v1/knowledge/history/undo", json=first_undo).status_code == 409
        r = c.post("/v1/knowledge/history/undo", json={"folder": "people", "commit": change["id"]})
        assert r.status_code == 200, r.text
        assert r.json()["commit"]["undoes"] == change["id"] and r.json()["skipped"] == []
        assert (root / "people" / "ada.md").read_text() == "# Ada\n"
        commits = c.get("/v1/knowledge/history", params={"folder": "people"}).json()["commits"]
        assert [x["kind"] for x in commits] == ["undo", "while-off", "first"]
        missing = {"folder": "people", "commit": "0" * 40}
        assert c.post("/v1/knowledge/history/undo", json=missing).status_code == 404


def until_committed(
    c: httpx.Client, folder: str, count: int, timeout: float = 30
) -> list[dict[str, Any]]:
    """The folder's history once it has `count` commits (or after `timeout`)."""
    deadline = time.monotonic() + timeout
    while True:
        commits = c.get("/v1/knowledge/history", params={"folder": folder}).json()["commits"]
        if len(commits) >= count or time.monotonic() > deadline:
            return commits
        time.sleep(0.1)
