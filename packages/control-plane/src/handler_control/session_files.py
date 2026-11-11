"""A session's folder as its people see it (F.8): its folders and files, read without following a
link nor leaving the folder, and what changed in it since the session started.

The agent writes in that folder, so nothing in it is trusted: every path is opened one name at a
time from the folder itself, never following a link; only regular files are read, up to a size;
`.gitignore` files are read the same way. Git objects are read by `git_read` in a child process
(a repository is the agent's too: handlerd never runs git nor reads `.git` itself).

The baseline, recorded when the session first starts (`baseline.json` in its folder, F.2): each
file's size and modification time, and the commit HEAD was at when the folder is a git repository
(the earlier versions of the files are that commit's). Files ignored by the folder's `.gitignore`
files (and `.git/info/exclude`) are left out, `.git` folders always.

What else of the host its sandbox sees is recorded at each start (`mounts.json`): knowledge
folders, skills and a run's subject are read here like its folder (the agent cannot change them);
the agent's own state (it holds the account's sign-in) and caches are only listed."""

import base64
import errno
import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from dulwich.ignore import IgnoreFilter

from handler_contracts import (
    SessionChanges,
    SessionFile,
    SessionFileChange,
    SessionFolder,
    SessionFolderEntry,
    SessionFound,
    SessionMount,
    SessionMounts,
)

from .files import write_private

MAX_FILES = 50_000  # beyond, changes are not followed
FOUND = 20  # paths a search returns
MAX_READ = 1 << 20  # a file shown, a .gitignore read
GIT_TIMEOUT = 10.0
IMAGES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}
DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC  # a FIFO does not block

Stats = dict[str, list[int]]  # path → [size, mtime_ns]
Chain = list[tuple[str, IgnoreFilter]]  # (folder, its ignore rules), deepest first


class PathError(Exception):
    """A path that cannot be shown: `missing` (404) or not one to show (400)."""

    def __init__(self, message: str, missing: bool = False) -> None:
        super().__init__(message)
        self.missing = missing


class TooManyFilesError(Exception):
    pass


# ── what the sandbox sees ───────────────────────────────────────────────


def record_mounts(recorded: Path, seen: list[SessionMount], at: datetime) -> None:
    """What the session's sandbox sees (compose.seen), as of its start `at`."""
    found = SessionMounts(started_at=at, mounts=seen)
    write_private(recorded, found.model_dump_json(by_alias=True, exclude_none=True))


def mounts(recorded: Path, scope: str) -> SessionMounts:
    try:
        return SessionMounts.model_validate_json(recorded.read_text())
    except FileNotFoundError:  # never started yet
        folder = SessionMount(
            target=scope, kind="scope", read_only=False, source=scope, browsable=True
        )
        return SessionMounts(mounts=[folder])


def mount_root(recorded: Path, scope: str, target: str | None) -> tuple[Path, bool]:
    """(its folder on the host, whether it is the session's folder) of the browsable mount the
    agent sees at `target`; the session's folder without one."""
    if target is None:
        return Path(scope), True
    for m in mounts(recorded, scope).mounts:
        if m.target == target and m.browsable:
            return Path(m.source), m.kind == "scope"
    raise PathError(f"the agent sees nothing to show at {target}", missing=True)


# ── reading ─────────────────────────────────────────────────────────────


def folder(root: Path, relative: str) -> SessionFolder:
    parts = _parts(relative)
    fd = _open_folder(root, parts)
    try:
        with os.scandir(fd) as found:
            scanned = list(found)
        entries: list[SessionFolderEntry] = []
        for entry in scanned:
            if entry.name == ".git":
                continue
            try:
                st = entry.stat(follow_symlinks=False)
                target = os.readlink(entry.name, dir_fd=fd) if entry.is_symlink() else None
            except FileNotFoundError:  # gone meanwhile
                continue
            if stat.S_ISDIR(st.st_mode):
                entries.append(SessionFolderEntry(name=entry.name, kind="folder"))
            elif stat.S_ISREG(st.st_mode):
                entries.append(SessionFolderEntry(name=entry.name, kind="file", size=st.st_size))
            elif target is not None:
                entries.append(SessionFolderEntry(name=entry.name, kind="link", target=target))
    finally:
        os.close(fd)
    entries.sort(key=lambda e: (e.kind != "folder", e.name.lower(), e.name))
    return SessionFolder(path="/".join(parts), entries=entries)


def read(root: Path, relative: str, baseline: Path | None) -> SessionFile:
    """A file, with what changed in it since the session started (with its `baseline`, for the
    session's folder); a deleted one is shown with its earlier version when there is one."""
    parts = _parts(relative)
    if not parts:
        raise PathError("not a file")
    path = "/".join(parts)
    recorded = _load(baseline) if baseline else {}
    before_stats = recorded.get("files", {}).get(path)
    commit = recorded.get("commit")
    try:
        data, size, mtime = _read_file(root, parts)
    except PathError as e:
        if not (e.missing and before_stats):
            raise
        before = git_text(root, commit, path) if commit else None
        return SessionFile(path=path, change="deleted", before=before)
    change = None
    if "files" in recorded:
        change = "added" if before_stats is None else None
        if before_stats is not None and before_stats != [size, mtime]:
            change = "modified"
    view = SessionFile(path=path, size=size, change=change, **_shown(data, size))
    if change == "modified" and commit:
        view = view.model_copy(update={"before": git_text(root, commit, path)})
    return view


def read_bytes(root: Path, relative: str) -> tuple[bytes, int]:
    """(its first MAX_READ + 1 bytes, its size): a file read as `read` reads it, inside the
    folder and through no link on the way (a plan file, D.27)."""
    parts = _parts(relative)
    if not parts:
        raise PathError("not a file")
    data, size, _ = _read_file(root, parts)
    return data, size


def host_path(root: Path, relative: str) -> tuple[Path, bool]:
    """(where it is on the host, whether it is a folder): checked like a read, inside the folder
    and through no link on the way."""
    parts = _parts(relative)
    if not parts:
        return root, True
    fd = _open_folder(root, parts[:-1])
    try:
        st = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        raise PathError(f"no file {'/'.join(parts)}", missing=True) from None
    finally:
        os.close(fd)
    return root.joinpath(*parts), stat.S_ISDIR(st.st_mode)


def _shown(data: bytes, size: int) -> dict[str, str]:
    if size > MAX_READ:
        return {}
    for magic, mime in IMAGES.items():
        if data.startswith(magic):
            return {"image": f"data:{mime};base64,{base64.b64encode(data).decode()}"}
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return {"image": f"data:image/webp;base64,{base64.b64encode(data).decode()}"}
    return {"text": text} if (text := _text(data)) is not None else {}


def _text(data: bytes) -> str | None:
    if b"\0" in data:
        return None
    try:
        return data.decode()
    except UnicodeDecodeError:
        return None


def _parts(relative: str) -> list[str]:
    parts = [p for p in relative.split("/") if p]
    if relative.startswith("/") or "\0" in relative or any(p in (".", "..") for p in parts):
        raise PathError("path invalid: relative to the session's folder, without . or ..")
    if ".git" in parts:
        raise PathError("a .git folder is not shown")
    return parts


def _open_folder(root: Path, parts: list[str]) -> int:
    """The folder at `parts`, opened one name at a time from `root`, never through a link."""
    fd = os.open(root, DIR & ~os.O_NOFOLLOW)  # the session's folder itself: handlerd's to trust
    opened: list[str] = []
    try:
        for name in parts:
            opened.append(name)
            sub = os.open(name, DIR, dir_fd=fd)
            os.close(fd)
            fd = sub
    except OSError as e:
        link = e.errno in (errno.ELOOP, errno.ENOTDIR) and _is_link(fd, opened[-1])
        os.close(fd)
        path = "/".join(opened)
        if link:
            raise PathError(f"{path} is a link: links are not followed") from None
        if e.errno in (errno.ENOENT, errno.ENOTDIR):
            raise PathError(f"no folder {path}", missing=True) from None
        raise
    return fd


def _is_link(fd: int, name: str) -> bool:
    try:
        return stat.S_ISLNK(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode)
    except OSError:
        return False


def _read_file(root: Path, parts: list[str]) -> tuple[bytes, int, int]:
    """(its first MAX_READ + 1 bytes, size, mtime_ns) of a regular file."""
    path = "/".join(parts)
    fd = _open_folder(root, parts[:-1])
    try:
        file = os.open(parts[-1], FILE, dir_fd=fd)
    except OSError as e:
        if e.errno == errno.ENOENT:
            raise PathError(f"no file {path}", missing=True) from None
        if e.errno == errno.ELOOP:
            raise PathError(f"{path} is a link: links are not followed") from None
        raise
    finally:
        os.close(fd)
    with os.fdopen(file, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise PathError(f"{path} is not a file")
        return f.read(MAX_READ + 1), st.st_size, st.st_mtime_ns


# ── changes ─────────────────────────────────────────────────────────────


def record_baseline(root: Path, baseline: Path) -> None:
    """The folder as the session starts (see above)."""
    try:
        recorded: dict[str, object] = {"files": _walk(root), "commit": git_head(root)}
    except TooManyFilesError:
        recorded = {"notFollowed": f"its folder has more than {MAX_FILES} files"}
    write_private(baseline, json.dumps(recorded))


def changes(root: Path, baseline: Path, since: datetime) -> SessionChanges:
    recorded = _load(baseline)
    git = bool(recorded.get("commit"))
    if "files" not in recorded:
        reason = recorded.get("notFollowed", "its folder was not recorded when it started")
        return SessionChanges(since=since, git=git, not_followed=reason)
    try:
        now = _walk(root)
    except TooManyFilesError:
        reason = f"its folder has more than {MAX_FILES} files"
        return SessionChanges(since=since, git=git, not_followed=reason)
    before: Stats = recorded["files"]
    found = [
        SessionFileChange(
            path=path,
            change="added" if path not in before else "modified",
            at=datetime.fromtimestamp(stats[1] / 1e9, UTC),
        )
        for path, stats in now.items()
        if before.get(path) != stats
    ]
    found.sort(key=lambda c: c.at or since, reverse=True)
    deleted = [SessionFileChange(path=p, change="deleted") for p in sorted(before) if p not in now]
    return SessionChanges(since=since, git=git, files=found + deleted)


def find(root: Path, query: str) -> SessionFound:
    """The files whose path holds the query's letters in order, case aside: those whose name
    starts with it first, then whose name, then whose path holds it, then the others; the shorter
    path first. No query: the most recently modified. Ignored files and `.git` are not searched."""
    try:
        files = _walk(root)
    except TooManyFilesError:
        return SessionFound(paths=[], not_followed=f"its folder has more than {MAX_FILES} files")
    q = query.lower()
    if not q:
        recent = sorted(files, key=lambda p: files[p][1], reverse=True)
        return SessionFound(paths=recent[:FOUND])
    ranked = [(rank, len(p), p) for p in files if (rank := _rank(p.lower(), q)) is not None]
    return SessionFound(paths=[p for _, _, p in sorted(ranked)[:FOUND]])


def _rank(path: str, q: str) -> int | None:
    name = path.rsplit("/", 1)[-1]
    if name.startswith(q):
        return 0
    if q in name:
        return 1
    if q in path:
        return 2
    letters = iter(path)
    return 3 if all(c in letters for c in q) else None


def _load(baseline: Path) -> dict:
    try:
        return json.loads(baseline.read_text())
    except FileNotFoundError:
        return {}


def _walk(root: Path) -> Stats:
    """Every regular file and link (not followed) of the folder, but ignored ones and `.git`."""
    found: Stats = {}
    exclude = _rules(root, [".git", "info"], "exclude")
    pending: list[tuple[list[str], Chain]] = [([], [("", exclude)] if exclude else [])]
    while pending:
        parts, chain = pending.pop()
        try:
            fd = _open_folder(root, parts)
        except PathError:  # replaced meanwhile
            continue
        try:
            if own := _rules(root, parts, ".gitignore"):
                chain = [("/".join(parts), own), *chain]
            with os.scandir(fd) as entries:
                for entry in entries:
                    if entry.name == ".git":
                        continue
                    path = "/".join([*parts, entry.name])
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        if not _ignored(chain, path + "/"):
                            pending.append(([*parts, entry.name], chain))
                    elif _followed(st.st_mode) and not _ignored(chain, path):
                        found[path] = [st.st_size, st.st_mtime_ns]
                        if len(found) > MAX_FILES:
                            raise TooManyFilesError
        finally:
            os.close(fd)
    return found


def _followed(mode: int) -> bool:
    return stat.S_ISREG(mode) or stat.S_ISLNK(mode)


def _rules(root: Path, parts: list[str], name: str) -> IgnoreFilter | None:
    try:
        data, size, _ = _read_file(root, [*parts, name])
    except (PathError, OSError):
        return None
    if size > MAX_READ:
        return None
    return IgnoreFilter(data.splitlines())


def _ignored(chain: Chain, path: str) -> bool:
    """git's rules: the deepest `.gitignore` that has a say decides."""
    for base, rules in chain:
        verdict = rules.is_ignored(path[len(base) + 1 :] if base else path)
        if verdict is not None:
            return verdict
    return False


# ── git, in a child process ─────────────────────────────────────────────


def git_head(root: Path) -> str | None:
    """The commit the folder's repository is at; None outside a repository or before a
    commit."""
    if not (root / ".git").is_dir():
        return None
    out = _git_read("head", str(root))
    return out.decode() if out else None


def git_text(root: Path, commit: str, path: str) -> str | None:
    """`path`'s text at `commit`; None when it was not there, or not text."""
    out = _git_read("show", str(root), commit, path)
    return _text(out) if out is not None and len(out) <= MAX_READ else None


def _git_read(*args: str) -> bytes | None:
    try:
        done = subprocess.run(
            [sys.executable, "-m", "handler_control.git_read", *args],
            capture_output=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    return done.stdout if done.returncode == 0 else None
