"""Unit tests: a session's folder read without following links nor leaving it, and what changed
in it since the session started (F.8)."""

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import SessionMount
from handler_control import session_files
from handler_control.session_files import PathError

SINCE = datetime(2026, 10, 7, tzinfo=UTC)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "work"
    (base / "src").mkdir(parents=True)
    (base / "src" / "app.py").write_text("print('hi')\n")
    (base / "README.md").write_text("# Shop\n")
    return base


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def touch_later(path: Path) -> None:
    """A modification time the baseline cannot have, whatever the clock's resolution."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


@pytest.mark.rule("files.no-link-leads-out")
def test_folder_lists_folders_first_links_unfollowed_and_no_git(root: Path) -> None:
    (root / ".git").mkdir()
    (root / "key").symlink_to(Path.home() / ".ssh" / "id_ed25519")
    os.mkfifo(root / "pipe")
    listing = session_files.folder(root, "")
    assert [(e.name, e.kind) for e in listing.entries] == [
        ("src", "folder"),
        ("key", "link"),
        ("README.md", "file"),
    ]
    assert listing.entries[1].target == str(Path.home() / ".ssh" / "id_ed25519")
    assert listing.entries[2].size == 7
    assert session_files.folder(root, "src/").path == "src"


@pytest.mark.rule("files.no-link-leads-out")
def test_links_are_never_followed(root: Path, tmp_path: Path) -> None:
    (tmp_path / "secret").write_text("s3cret")
    (root / "secret").symlink_to(tmp_path / "secret")
    (root / "out").symlink_to(tmp_path)
    with pytest.raises(PathError, match="is a link"):
        session_files.read(root, "secret", tmp_path / "none.json")
    with pytest.raises(PathError, match="out is a link"):
        session_files.read(root, "out/secret", tmp_path / "none.json")
    with pytest.raises(PathError, match="out is a link"):
        session_files.folder(root, "out")


@pytest.mark.rule("files.no-link-leads-out")
@pytest.mark.parametrize(
    "path", ["../work/README.md", "/etc/passwd", "src/../README.md", ".git/config"]
)
def test_paths_stay_in_the_folder(root: Path, tmp_path: Path, path: str) -> None:
    with pytest.raises(PathError) as e:
        session_files.read(root, path, tmp_path / "none.json")
    assert not e.value.missing


def test_read_shows_text_images_and_only_the_size_of_the_rest(root: Path, tmp_path: Path) -> None:
    none = tmp_path / "none.json"
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 8)
    (root / "blob.bin").write_bytes(b"\0\1\2")
    (root / "big.txt").write_text("x" * (session_files.MAX_READ + 1))
    os.mkfifo(root / "pipe")  # would block a plain open
    assert session_files.read(root, "README.md", none).text == "# Shop\n"
    assert (session_files.read(root, "logo.png", none).image or "").startswith(
        "data:image/png;base64,"
    )
    binary = session_files.read(root, "blob.bin", none)
    assert (binary.size, binary.text, binary.image) == (3, None, None)
    assert session_files.read(root, "big.txt", none).text is None
    with pytest.raises(PathError, match="not a file"):
        session_files.read(root, "pipe", none)
    with pytest.raises(PathError) as e:
        session_files.read(root, "nope.txt", none)
    assert e.value.missing


@pytest.mark.rule("files.changes-are-since-the-session-started")
def test_changes_since_the_baseline(root: Path, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    (root / ".gitignore").write_text("node_modules/\n*.log\n")
    (root / "src" / ".gitignore").write_text("!keep.log\n")
    session_files.record_baseline(root, baseline)
    assert baseline.stat().st_mode & 0o777 == 0o600

    touch_later(root / "src" / "app.py")
    (root / "src" / "new.py").write_text("")
    (root / "README.md").unlink()
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "node_modules" / "x" / "index.js").write_text("")
    (root / "debug.log").write_text("")
    (root / "src" / "keep.log").write_text("")
    (root / "link").symlink_to("/etc/passwd")
    found = session_files.changes(root, baseline, SINCE)
    assert not found.git
    assert found.not_followed is None
    assert sorted((c.path, c.change) for c in found.files) == [
        ("README.md", "deleted"),
        ("link", "added"),
        ("src/app.py", "modified"),
        ("src/keep.log", "added"),
        ("src/new.py", "added"),
    ]
    assert found.files[-1].at is None  # deleted ones last
    assert session_files.read(root, "src/app.py", baseline).change == "modified"
    assert session_files.read(root, "src/new.py", baseline).change == "added"
    gone = session_files.read(root, "README.md", baseline)
    assert (gone.change, gone.size, gone.before) == ("deleted", None, None)


@pytest.mark.rule("files.changes-are-since-the-session-started")
def test_changes_not_followed(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = session_files.changes(root, tmp_path / "none.json", SINCE)
    assert missing.not_followed == "its folder was not recorded when it started"
    assert session_files.read(root, "README.md", tmp_path / "none.json").change is None
    monkeypatch.setattr(session_files, "MAX_FILES", 1)
    session_files.record_baseline(root, tmp_path / "baseline.json")
    found = session_files.changes(root, tmp_path / "baseline.json", SINCE)
    assert found.not_followed == "its folder has more than 1 files"
    assert found.files == []


@pytest.mark.rule("files.git-never-runs-on-the-host")
@pytest.mark.skipif(shutil.which("git") is None, reason="needs git to make a repository")
def test_git_gives_the_earlier_versions(root: Path, tmp_path: Path) -> None:
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-qm", "start")
    baseline = tmp_path / "baseline.json"
    session_files.record_baseline(root, baseline)

    (root / "src" / "app.py").write_text("print('bye')\n")
    touch_later(root / "src" / "app.py")
    (root / "README.md").unlink()
    git(root, "commit", "-qam", "the agent commits")  # still compared with the start
    found = session_files.changes(root, baseline, SINCE)
    assert found.git
    assert sorted((c.path, c.change) for c in found.files) == [
        ("README.md", "deleted"),
        ("src/app.py", "modified"),
    ]
    changed = session_files.read(root, "src/app.py", baseline)
    assert (changed.before, changed.text) == ("print('hi')\n", "print('bye')\n")
    assert session_files.read(root, "README.md", baseline).before == "# Shop\n"


@pytest.mark.rule("files.git-never-runs-on-the-host")
@pytest.mark.skipif(shutil.which("git") is None, reason="needs git to make a repository")
def test_a_hostile_repository_only_costs_the_child(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repository is read in a child process: handlerd never runs what its config names, and one
    that would block the reader gives no earlier version once handlerd stops waiting."""
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-qm", "start")
    marker = tmp_path / "ran"
    with (root / ".git" / "config").open("a") as f:
        f.write(f"[core]\n\tfsmonitor = touch {marker}\n")
    baseline = tmp_path / "baseline.json"
    session_files.record_baseline(root, baseline)
    (root / "README.md").write_text("changed\n")
    touch_later(root / "README.md")
    assert session_files.read(root, "README.md", baseline).before == "# Shop\n"
    assert not marker.exists()

    monkeypatch.setattr(session_files, "GIT_TIMEOUT", 1.0)
    (root / ".git" / "config").unlink()
    os.mkfifo(root / ".git" / "config")  # opening it waits for a writer
    assert session_files.read(root, "README.md", baseline).before is None


@pytest.mark.rule("files.access-lists-what-the-sandbox-sees")
def test_what_the_sandbox_sees(root: Path, tmp_path: Path) -> None:
    recorded = tmp_path / "mounts.json"
    only_folder = session_files.mounts(recorded, str(root))  # not started yet
    assert [(m.kind, m.browsable) for m in only_folder.mounts] == [("scope", True)]
    assert session_files.mount_root(recorded, str(root), None) == (root, True)

    notes = tmp_path / "notes"
    notes.mkdir()

    def seen_as(kind: Any, target: str, source: str, browsable: bool) -> SessionMount:
        return SessionMount(target=target, kind=kind, read_only=kind != "state", source=source,
                            browsable=browsable)  # fmt: skip

    sees = [
        seen_as("scope", str(root), str(root), True),
        seen_as("knowledge", "/notes/notes", str(notes), True),
        seen_as("state", "/home/agent/.claude", str(tmp_path), False),
        seen_as("tools", "/opt/shopify", "handler-ai-tool-shopify", False),
    ]
    session_files.record_mounts(recorded, sees, SINCE)
    seen = session_files.mounts(recorded, str(root))
    assert seen.started_at == SINCE
    assert [(m.kind, m.target, m.browsable) for m in seen.mounts] == [
        ("scope", str(root), True),
        ("knowledge", "/notes/notes", True),
        ("state", "/home/agent/.claude", False),
        ("tools", "/opt/shopify", False),
    ]
    assert session_files.mount_root(recorded, str(root), "/notes/notes") == (notes, False)
    for hidden in ("/home/agent/.claude", "/opt/shopify", "/etc"):
        with pytest.raises(PathError) as e:
            session_files.mount_root(recorded, str(root), hidden)
        assert e.value.missing


@pytest.mark.rule("files.no-link-leads-out")
def test_host_path_is_checked_like_a_read(root: Path, tmp_path: Path) -> None:
    (root / "out").symlink_to(tmp_path)
    assert session_files.host_path(root, "") == (root, True)
    assert session_files.host_path(root, "src") == (root / "src", True)
    assert session_files.host_path(root, "src/app.py") == (root / "src" / "app.py", False)
    assert session_files.host_path(root, "out") == (root / "out", False)  # the link, not followed
    with pytest.raises(PathError, match="out is a link"):
        session_files.host_path(root, "out/anything")
    with pytest.raises(PathError) as e:
        session_files.host_path(root, "nope")
    assert e.value.missing


def test_find_ranks_names_then_paths_then_scattered_letters(root: Path) -> None:
    (root / "src" / "mapping.py").write_text("")
    (root / "docs").mkdir()
    (root / "docs" / "apps.md").write_text("")
    (root / ".gitignore").write_text("build/\n")
    (root / "build").mkdir()
    (root / "build" / "app.js").write_text("")  # ignored: never offered
    found = session_files.find(root, "APP").paths
    assert found == ["src/app.py", "docs/apps.md", "src/mapping.py"]
    assert session_files.find(root, "src/ap").paths == ["src/app.py", "src/mapping.py"]
    assert session_files.find(root, "sapy").paths == ["src/app.py", "src/mapping.py"]  # s…a…p…y
    assert session_files.find(root, "zzz").paths == []
    touch_later(root / "README.md")
    assert session_files.find(root, "").paths[0] == "README.md"
