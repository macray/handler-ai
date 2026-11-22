"""An app's job's folders (H.1), as `app_jobs.place` gives them to its run's sandbox, on each real
runtime: what it reads stays unchanged, what it writes is written, its `.git` never."""

from pathlib import Path

import pytest

from handler_contracts import AppManifest
from handler_control import app_jobs

from ..support.runtimes import Runtime
from .conftest import run, spec

MANIFEST = """apiVersion = "handler.app/v1"
name = "cv"
version = "1.0.0"
[needs.files.cv]
mode = "rw"
[needs.files.notes]
mode = "rw"
[jobs.write]
description = "Writes your CV"
files = { cv = "write", notes = "read" }
worksIn = ["cv"]
result = { type = "object", required = ["status", "summary"], properties = { status = { enum = ["ok"] }, summary = { type = "string" } } }
"""


@pytest.mark.rule("app-job.reads-are-read-only")
def test_a_job_cannot_write_what_it_reads(runtime: Runtime, scope: Path) -> None:
    """The job reads "notes", which its app may write (its need is rw): its run writes "cv",
    its folder, but neither "notes" nor the .git of "cv".

    If this fails: a job meant to read your notes changes them, or rewrites your history."""
    cv, notes = scope / "cv", scope / "notes"
    (cv / ".git").mkdir(parents=True)
    notes.mkdir()
    (notes / "today.md").write_text("Met Bob.\n")
    job = AppManifest.from_toml(MANIFEST).jobs["write"]
    place, _ = app_jobs.place(job, {"cv": str(cv), "notes": str(notes)})
    assert place.work == str(cv)
    folders = [f.model_dump(mode="json") for f in place.folders]
    script = (
        f"echo cv > {cv}/cv.md; "
        f"echo changed > {notes}/today.md 2>/dev/null || echo notes-ro; "
        f"touch {notes}/new.md 2>/dev/null || echo notes-ro; "
        f"touch {cv}/.git/hook 2>/dev/null || echo git-ro"
    )
    doc = spec(cv, ["sh", "-c", script], folders=folders)
    r = run(runtime.binary, doc)
    assert r.stdout.decode().split() == ["notes-ro", "notes-ro", "git-ro"], r.stderr.decode()
    assert (cv / "cv.md").read_text() == "cv\n"
    assert (notes / "today.md").read_text() == "Met Bob.\n"
    assert not (notes / "new.md").exists() and not (cv / ".git" / "hook").exists()
