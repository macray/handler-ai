"""The notes history (D.5): what keeps a folder others write recoverable. Each notes folder an
agent may write, and each folder given to an app's files need in `rw` (in the notes or not), has
a git history, kept by handlerd out of every sandbox's reach:

    <data>/notes-history/<key>.git     a bare repository per folder (its real path's digest);
                                       its `description` names the folder

committed every LAPSE when something changed, and at handlerd's start (what changed while it
was off). A commit names the agents and apps that could write the folder and ran in its lapse.
The person sees a folder's changes,
by commit, and undoes one: its files put back as they were before it. A folder is named by its
path relative to the notes root when it is in the notes, else by its full path.

Nothing of a folder is ever followed: it is read and written through directory descriptors, a
link kept as a link (its target never read), a file or folder replaced by a link on the way
left as it is. Each folder's own `.git` (a vault's history) is left out, at any depth.

After each commit, the documents it changed that name a schema are checked against the
Library's (`handler_smd`, the pure core, on the committed text): a broken one is a warning in
the inbox, never a refused write.
"""

import asyncio
import contextlib
import difflib
import hashlib
import logging
import os
import re
import stat
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast, get_args

from dulwich.diff_tree import TreeChange, tree_changes
from dulwich.objects import Blob, Commit, ObjectID, ShaFile, Tree, TreeEntry
from dulwich.refs import HEADREF
from dulwich.repo import Repo

from handler_contracts import (
    KnowledgeFolderUse,
    NotesChange,
    NotesCommit,
    NotesCommitDiff,
    NotesCommitKind,
    NotesFileChange,
    NotesFileDiff,
    NotesHistory,
    NotesUndo,
    NotesWriter,
    is_within,
)
from handler_smd.parser import parse
from handler_smd.resolver import resolve_schema
from handler_smd.scanner import load_schemas
from handler_smd.validator import validate

from . import knowledge
from .agents import AgentRecord, AgentRegistry
from .apps import WrittenFolder
from .inbox import Inbox
from .settings import Settings

log = logging.getLogger("handler.notes_history")

LAPSE = 300.0  # seconds between two looks at the folders
MAX_FILE_BYTES = 64 * 1024 * 1024  # a larger file is left out of the history (logged)
MAX_DIFF_BYTES = 1024 * 1024  # a larger text is shown as changed, without its lines
LISTED_COMMITS = 100
FILES_SAID = 3  # a listed commit says what changed in its first files only (the web UI's rows)
GIT = b".git"
KINDS = get_args(NotesCommitKind)
AUTHOR = b"Handler <handler@localhost>"

FILE, EXECUTABLE, LINK, DIR = 0o100644, 0o100755, 0o120000, 0o040000
NOFOLLOW_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
NOFOLLOW_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class NotesHistoryError(ValueError):
    """A notes folder that cannot be used (outside the root, missing…)."""


class NotesHistoryMissingError(NotesHistoryError):
    """No history for that folder, or no such change in it."""


class NotesHistoryConflictError(NotesHistoryError):
    """A change that cannot be undone now."""


@dataclass
class Writers:
    """Who may write a folder: agents (given it read-write) and apps (given it for a files need in
    `rw`)."""

    agents: list[AgentRecord] = field(default_factory=list)
    apps: list[WrittenFolder] = field(default_factory=list)


@dataclass(frozen=True)
class _Stat:
    """What tells a file unchanged since its blob was made, without reading it."""

    dev: int
    ino: int
    size: int
    mtime_ns: int
    ctime_ns: int
    mode: int


class NotesHistories:
    """The history of every folder others write: the timer, the commits, their listing, undo."""

    def __init__(
        self,
        settings: Settings,
        registry: AgentRegistry,
        inbox: Inbox,
        label: Callable[[AgentRecord], str],
        app_folders: Callable[[], list[WrittenFolder]],
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.inbox = inbox
        self.label = label
        self.app_folders = app_folders  # AppStore.written_folders
        self.dir = settings.data_dir / "notes-history"
        self.lock = threading.Lock()  # one commit or undo at a time
        self.blobs: dict[str, dict[bytes, tuple[_Stat, ObjectID]]] = {}  # per folder: unchanged
        self.lapse_start = datetime.now(UTC)
        self.connected: set[str] = set()  # agents with a sandbox at the previous look
        self.running: set[str] = set()  # apps with a backend at the previous look
        self.task: asyncio.Task[None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None  # where the inbox is told

    # ── the timer ───────────────────────────────────────────────────────

    def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.task = self.loop.create_task(self._run())

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    async def _run(self) -> None:
        await asyncio.to_thread(self.commit_all, started=True)
        while True:
            await asyncio.sleep(LAPSE)
            await asyncio.to_thread(self.commit_all)

    # ── committing ──────────────────────────────────────────────────────

    def commit_all(self, *, started: bool = False) -> list[NotesCommit]:
        """Commit each folder others write that changed; `started`: at handlerd's start, what
        changed while it was off (no agent nor app could write through Handler then)."""
        made: list[NotesCommit] = []
        with self.lock:
            now = datetime.now(UTC)
            for folder, writers in self.writable().items():
                could = [] if started else self.ran(writers)
                try:
                    commit = self._commit(folder, "while-off" if started else "changes", could)
                except OSError as e:
                    log.warning("notes history of %s: %s", folder, e)
                    continue
                if commit is not None:
                    made.append(commit)
            self.lapse_start = now
            self.connected = {a.id for a in self.registry.agents.values() if a.connections}
            self.running = {f.app for f in self.app_folders() if f.running}
        return made

    def begin_new(self) -> None:
        """After an agent is saved, or an app given a folder or deployed: a folder given
        read-write that has no history yet gets its first state now, before anything writes
        there. Waits for a look under way only when
        there is such a folder; never fails the save (a problem is logged)."""
        try:
            new = [f for f in self.writable() if not self._git_dir(self._path(f)).is_dir()]
            if not new:
                return
            with self.lock:
                for folder in new:
                    if not self._git_dir(self._path(folder)).is_dir():
                        self._commit(folder, "first", [])
        except (OSError, NotesHistoryError) as e:
            log.warning("notes history: a new folder's first state: %s", e)

    def writable(self) -> dict[str, Writers]:
        """Each folder some agent or app may write (named as `_key` says) → who; a notes folder
        no longer usable (removed, made a link) is left out, and so is an app's folder no longer
        given (or gone)."""
        root = knowledge.root(self.settings)[0]
        found: dict[str, list[AgentRecord]] = {}
        for agent in self.registry.agents.values():
            for use in agent.knowledge:
                if use.access == "write":
                    found.setdefault(use.folder, []).append(agent)
        usable: dict[str, Writers] = {}
        for folder, agents in found.items():
            try:
                knowledge.check(root, [KnowledgeFolderUse(folder=folder, access="write")])
            except knowledge.KnowledgeError:
                continue
            usable[folder] = Writers(agents=agents)
        for given in self.app_folders():
            writers = usable.setdefault(self._key(given.path), Writers())
            writers.apps.append(given)
        return dict(sorted(usable.items()))

    def ran(self, writers: Writers) -> list[NotesWriter]:
        """Those of `writers` that ran in the lapse: an app with its backend running now or at
        the previous look, or used since; an agent with a sandbox so, or one started since."""
        apps = [
            NotesWriter(app=f.app, name=f.title)
            for f in writers.apps
            if f.running
            or f.app in self.running
            or (f.last_used_at is not None and f.last_used_at >= self.lapse_start)
        ]
        agents = [
            NotesWriter(agent_id=a.id, name=self.label(a))
            for a in writers.agents
            if a.connections
            or a.id in self.connected
            or (a.last_used_at is not None and a.last_used_at >= self.lapse_start)
        ]
        return apps + agents

    def _commit(
        self,
        folder: str,
        kind: NotesCommitKind,
        could: list[NotesWriter],
        undoes: str | None = None,
    ) -> NotesCommit | None:
        path = self._path(folder)
        repo = self._repo(path, create=True)
        try:
            tree = self._snapshot(repo, path)
            head = _head(repo)
            if head is not None and _get(repo, head, Commit).tree == tree:
                return None
            commit = Commit()
            commit.tree = tree
            commit.parents = [head] if head is not None else []
            commit.author = commit.committer = AUTHOR
            commit.author_time = commit.commit_time = int(time.time())
            commit.author_timezone = commit.commit_timezone = 0
            commit.message = _message("first" if head is None else kind, could, undoes)
            repo.object_store.add_object(commit)
            repo.refs[HEADREF] = commit.id
            made = self._described(repo, commit)
        finally:
            repo.close()
        if made.kind != "first":
            self._check(folder, path, made)
        return made

    def _snapshot(self, repo: Repo, folder: str) -> ObjectID:
        """The folder's tree, every file a blob in `repo`, read through directory descriptors:
        a link is stored as a link, never followed. A file unchanged since the last look (its
        stat) is not read again."""
        walk = _Walk(repo, self.blobs.get(folder, {}))
        fd = os.open(folder, NOFOLLOW_DIR)
        try:
            tree = walk.tree(fd, b"").id
        finally:
            os.close(fd)
        self.blobs[folder] = walk.seen
        return tree

    # ── the check after a commit (knowledge.history-check-only-warns) ──────────────

    def _check(self, folder: str, path: str, commit: NotesCommit) -> None:
        """The documents `commit` added or changed that name a schema, checked against the
        Library's: a broken one is a warning in the inbox, never more."""
        broken: list[str] = []
        with self._open(path) as repo:
            tree = _commit_of(repo, commit.id).tree
            index = None
            for change in commit.files:
                if change.change == "deleted" or change.link or not change.path.endswith(".md"):
                    continue
                data = _blob_at(repo, tree, change.path)
                if data is None or len(data) > MAX_DIFF_BYTES:
                    continue
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                parsed = parse(text, change.path)
                if "schema" not in parsed.document.meta:
                    continue  # a plain note
                if index is None:
                    index, _ = load_schemas(self.settings.schemas_dir)
                typedef, found = resolve_schema(parsed.document, index, change.path)
                if typedef is not None:
                    found += validate(parsed.document, typedef, change.path)[1]
                errors = [d for d in [*parsed.diagnostics, *found] if d.severity == "error"]
                if errors:
                    first = errors[0]
                    broken.append(f"{change.path}:{first.line}: {first.message}")
        if broken:
            # A folder outside the notes is an app's (its history is on the app's page): the
            # warning comes from the app, never as a notes folder the inbox cannot open.
            apps = [f.app for f in self.app_folders() if self._key(f.path) == folder]
            outside = os.path.isabs(folder) and apps
            self._tell(
                source="app" if outside else "notes",
                name=apps[0] if outside else folder,
                person="owner",
                title=f"{len(broken)} document{'s' if len(broken) > 1 else ''} "
                "not as their schema says",
                status="attention",
                summary="\n".join(broken[:20]),
            )

    def _tell(self, **fields: Any) -> None:
        """An inbox message, added from the loop (commits are made in a thread; the inbox
        tells the desktop from the loop)."""
        if self.loop is None:
            self.inbox.add(**fields)
        else:
            self.loop.call_soon_threadsafe(lambda: self.inbox.add(**fields))

    # ── reading ─────────────────────────────────────────────────────────

    def history(self, folder: str) -> NotesHistory:
        """A folder's commits, newest first."""
        with self._open(self._path(folder, existing=True)) as repo:
            head = _head(repo)
            commits: list[NotesCommit] = []
            if head is not None:
                for entry in repo.get_walker(include=[head], max_entries=LISTED_COMMITS):
                    commits.append(self._described(repo, entry.commit))
        return NotesHistory(folder=folder, commits=commits)

    def commit(self, folder: str, commit_id: str) -> NotesCommitDiff:
        """One commit's files, each with what changed in its lines when it is text."""
        with self._open(self._path(folder, existing=True)) as repo:
            commit = _commit_of(repo, commit_id)
            files = [_file_diff(repo, change) for change in _changes(repo, commit)]
            return NotesCommitDiff(commit=self._described(repo, commit), files=files)

    # ── undo ────────────────────────────────────────────────────────────

    def undo(self, folder: str, commit_id: str) -> NotesUndo:
        """Put the files `commit_id` changed back as they were before it. What the folder holds
        now is committed first, so the undo itself can be undone; a file whose way passes
        through a link is left as it is (`skipped`)."""
        with self.lock:
            path = self._path(folder, existing=True)
            with self._open(path) as repo:
                if not _commit_of(repo, commit_id).parents:
                    raise NotesHistoryConflictError("the history's first state cannot be undone")
            key = self._key(folder)
            writers = self.writable().get(key)
            if writers is None:
                raise NotesHistoryConflictError(
                    f"no agent nor app may write {folder} now: nothing to undo there"
                )
            self._commit(key, "changes", self.ran(writers))
            with self._open(path) as repo:
                commit = _commit_of(repo, commit_id)
                skipped = [c for c in _changes(repo, commit) if not _put_back(repo, path, c)]
            made = self._commit(key, "undo", [], undoes=commit.id.decode())
            return NotesUndo(commit=made, skipped=[_path_of(c) for c in skipped])

    # ── where the histories are ─────────────────────────────────────────

    def _key(self, folder: str) -> str:
        """A folder's name in the histories: relative to the notes root for a notes folder (a
        full path inside the root too, K1), else its full real path (an app's folder)."""
        if not os.path.isabs(folder):
            return folder
        path = os.path.realpath(folder)
        root = os.path.realpath(knowledge.root(self.settings)[0])
        if not is_within(path, root):
            return path
        try:
            use = KnowledgeFolderUse(folder=os.path.relpath(path, root))
            return knowledge.check(Path(root), [use])[0].folder
        except knowledge.KnowledgeError:
            return path  # a hidden folder of the notes: no notes folder

    def _path(self, folder: str, *, existing: bool = False) -> str:
        """The folder's real path, a notes folder's as the root is now; `existing`: one with a
        history."""
        key = self._key(folder)
        if os.path.isabs(key):
            path = key
        else:
            root = os.path.realpath(knowledge.root(self.settings)[0])
            try:
                used = knowledge.check(Path(root), [KnowledgeFolderUse(folder=key)])[0].folder
            except knowledge.KnowledgeError as e:
                raise NotesHistoryError(str(e)) from None
            path = root if used == "." else os.path.join(root, used)
        if existing and not self._git_dir(path).is_dir():
            raise NotesHistoryMissingError(
                f"{folder} has no history: no agent nor app was given it read-write"
            )
        return path

    def _git_dir(self, path: str) -> Path:
        return self.dir / f"{hashlib.sha256(os.fsencode(path)).hexdigest()[:16]}.git"

    def _repo(self, path: str, *, create: bool = False) -> Repo:
        git_dir = self._git_dir(path)
        if git_dir.is_dir():
            return Repo(git_dir)
        if not create:
            raise NotesHistoryMissingError(f"{path} has no history")
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        repo = Repo.init_bare(git_dir, mkdir=True)
        (git_dir / "description").write_text(f"{path}\n")
        return repo

    @contextlib.contextmanager
    def _open(self, path: str) -> Iterator[Repo]:
        repo = self._repo(path)
        try:
            yield repo
        finally:
            repo.close()

    def _described(self, repo: Repo, commit: Commit) -> NotesCommit:
        kind, could, undoes = _parsed(commit.message)
        changes = _changes(repo, commit)
        files = [
            NotesFileChange.model_validate(_file_diff(repo, c).model_dump(include=SAID))
            if i < FILES_SAID and kind != "first"
            else NotesFileChange(path=_path_of(c), change=_change(c), link=_is_link(c))
            for i, c in enumerate(changes)
        ]
        return NotesCommit(
            id=commit.id.decode(),
            at=datetime.fromtimestamp(commit.commit_time, UTC),
            kind=kind,
            could_write=could,
            undoes=undoes,
            files=files if kind != "first" else [],
            file_count=len(files),
        )


class _Walk:
    """One look at a folder: its tree built into `repo`."""

    def __init__(self, repo: Repo, known: dict[bytes, tuple[_Stat, ObjectID]]) -> None:
        self.repo = repo
        self.known = known
        self.seen: dict[bytes, tuple[_Stat, ObjectID]] = {}

    def tree(self, fd: int, prefix: bytes) -> Tree:
        """The tree of the folder open at `fd`. An entry gone since it was listed, or that
        cannot be read, is left out (logged); one changed into a link while it was read stops
        the look (OSError: the next one sees it as it is then)."""
        tree = Tree()
        with os.scandir(fd) as entries:
            names = sorted(os.fsencode(e.name) for e in entries)
        for name in names:
            if name == GIT:
                continue
            rel = prefix + name
            try:
                self.add(tree, fd, name, rel)
            except (FileNotFoundError, PermissionError) as e:
                log.warning("notes history: %s left out: %s", os.fsdecode(rel), e)
        self.repo.object_store.add_object(tree)
        return tree

    def add(self, tree: Tree, fd: int, name: bytes, rel: bytes) -> None:
        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISLNK(st.st_mode):
            target = os.fsencode(os.readlink(name, dir_fd=fd))
            tree.add(name, LINK, _store(self.repo, target))
        elif stat.S_ISDIR(st.st_mode):
            child = os.open(name, NOFOLLOW_DIR, dir_fd=fd)
            try:
                sub = self.tree(child, rel + b"/")
            finally:
                os.close(child)
            if len(sub):  # git keeps no empty folder
                tree.add(name, DIR, sub.id)
        elif stat.S_ISREG(st.st_mode):
            if st.st_size > MAX_FILE_BYTES:
                log.warning("notes history: %s is too large to keep", os.fsdecode(rel))
                return
            blob = self.blob(fd, name, rel, _stat(st))
            self.seen[rel] = (_stat(st), blob)
            tree.add(name, EXECUTABLE if st.st_mode & 0o111 else FILE, blob)

    def blob(self, fd: int, name: bytes, rel: bytes, st: _Stat) -> ObjectID:
        cached = self.known.get(rel)
        if cached is not None and cached[0] == st:
            return cached[1]
        file = os.open(name, NOFOLLOW_FILE, dir_fd=fd)
        with os.fdopen(file, "rb") as f:
            return _store(self.repo, f.read(MAX_FILE_BYTES))


# ── commits as text ─────────────────────────────────────────────────────


def _message(kind: NotesCommitKind, could: list[NotesWriter], undoes: str | None) -> bytes:
    lines = [f"Kind: {kind}"]
    if undoes:
        lines.append(f"Undoes: {undoes}")
    lines += [
        f"Could-write-app: {w.app} {w.name}" if w.app else f"Could-write: {w.agent_id} {w.name}"
        for w in could
    ]
    return ("\n".join(lines) + "\n").encode()


def _parsed(message: bytes) -> tuple[NotesCommitKind, list[NotesWriter], str | None]:
    kind: NotesCommitKind = "changes"
    could: list[NotesWriter] = []
    undoes: str | None = None
    for line in message.decode(errors="replace").splitlines():
        key, _, value = line.partition(": ")
        if key == "Kind" and value in KINDS:
            kind = cast("NotesCommitKind", value)
        elif key == "Undoes":
            undoes = value
        elif key == "Could-write":
            agent_id, _, name = value.partition(" ")
            could.append(NotesWriter(agent_id=agent_id, name=name))
        elif key == "Could-write-app":
            app, _, name = value.partition(" ")
            could.append(NotesWriter(app=app, name=name))
    return kind, could, undoes


# ── objects ─────────────────────────────────────────────────────────────


def _stat(st: os.stat_result) -> _Stat:
    return _Stat(st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_mode)


def _store(repo: Repo, data: bytes) -> ObjectID:
    blob = Blob.from_string(data)
    repo.object_store.add_object(blob)
    return blob.id


def _head(repo: Repo) -> ObjectID | None:
    try:
        return repo.head()
    except KeyError:
        return None


def _get[T: ShaFile](repo: Repo, sha: ObjectID, kind: type[T]) -> T:
    obj = repo[sha]
    if not isinstance(obj, kind):
        raise NotesHistoryMissingError(f"{sha.decode()} is not a {kind.__name__.lower()}")
    return obj


def _commit_of(repo: Repo, commit_id: str) -> Commit:
    try:
        return _get(repo, ObjectID(commit_id.encode()), Commit)
    except (KeyError, ValueError):
        raise NotesHistoryMissingError(f"no change {commit_id} in this folder's history") from None


def _changes(repo: Repo, commit: Commit) -> list[TreeChange]:
    """What `commit` changed from its first parent (from nothing, the first)."""
    parent = _get(repo, commit.parents[0], Commit).tree if commit.parents else None
    return list(tree_changes(repo.object_store, parent, commit.tree))


def _blob_at(repo: Repo, tree: ObjectID, path: str) -> bytes | None:
    """A file's content in `tree`; None: not there, or a link on its way."""
    obj: ShaFile = _get(repo, tree, Tree)
    for part in path.encode().split(b"/"):
        if not isinstance(obj, Tree) or part not in obj:
            return None
        mode, sha = obj[part]
        if mode == LINK:
            return None
        obj = repo[sha]
    return obj.data if isinstance(obj, Blob) else None


def _side(change: TreeChange) -> TreeEntry:
    """The entry a change is about: its new one, the old one of a deletion."""
    entry = change.new if change.new is not None else change.old
    assert entry is not None  # a change has a side
    return entry


def _path_of(change: TreeChange) -> str:
    return os.fsdecode(_side(change).path)  # no renames: both sides have one path


def _change(change: TreeChange) -> NotesChange:
    if change.old is None:
        return "added"
    return "deleted" if change.new is None else "changed"


def _is_link(change: TreeChange) -> bool:
    return any(e is not None and e.mode == LINK for e in (change.old, change.new))


def _data(repo: Repo, entry: TreeEntry | None) -> bytes:
    return _get(repo, entry.sha, Blob).data if entry is not None else b""


def _file_diff(repo: Repo, change: TreeChange) -> NotesFileDiff:
    """A file's change, with its lines when both sides are text (not links, not too large)."""
    link, diff, target = _is_link(change), None, None
    if link:
        side = _side(change)
        target = os.fsdecode(_data(repo, side)) if side.mode == LINK else None
    else:
        old, new = _data(repo, change.old), _data(repo, change.new)
        if len(old) <= MAX_DIFF_BYTES and len(new) <= MAX_DIFF_BYTES:
            with contextlib.suppress(UnicodeDecodeError):
                a, b = old.decode("utf-8"), new.decode("utf-8")
                lines = difflib.unified_diff(
                    a.splitlines(keepends=True), b.splitlines(keepends=True), n=3
                )
                diff = "".join(list(lines)[2:])  # without the ---/+++ header
    added, removed, under = _said(diff) if diff is not None else (None, None, None)
    return NotesFileDiff(
        path=_path_of(change),
        change=_change(change),
        link=link,
        diff=diff,
        link_target=target,
        added=added,
        removed=removed,
        under=under,
    )


SAID = {"path", "change", "link", "added", "removed", "under"}  # NotesFileChange's fields
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")


def _said(diff: str) -> tuple[int, int, str | None]:
    """A diff's lines added and removed, and the heading they are all under: the nearest above
    each changed line within its hunk (a removed heading is not one); None when they differ or
    some have none."""
    added = removed = 0
    unders: set[str | None] = set()
    near: str | None = None
    for line in diff.splitlines():
        if line.startswith("@@"):
            near = None
            continue
        sign, text = line[:1], line[1:]
        if sign in "+-" and line:
            if sign == "+":
                added += 1
            else:
                removed += 1
            unders.add(near)
        if sign != "-" and (m := HEADING.match(text)):
            near = m.group(1)
    under = next(iter(unders)) if len(unders) == 1 else None
    return added, removed, under


# ── putting a file back (undo), never through a link ────────────────────


def _put_back(repo: Repo, folder: str, change: TreeChange) -> bool:
    """`change` undone in `folder`: the file as it was before it (absent if it was added).
    False when its way passes through a link, or is not a folder: left as it is."""
    old = change.old
    parts = _path_of(change).split("/")
    try:
        fd = _walk_to(folder, parts[:-1], create=old is not None)
    except OSError:
        return False
    if fd is None:
        return True  # its folder is gone: the added file is gone with it
    try:
        return _replace(repo, fd, parts[-1], old)
    except OSError:
        return False
    finally:
        os.close(fd)


def _replace(repo: Repo, fd: int, name: str, entry: TreeEntry | None) -> bool:
    """`name` in the folder open at `fd` made `entry` (None: removed); a link there is removed
    itself, never followed; a folder there is left (False)."""
    with contextlib.suppress(FileNotFoundError):
        if stat.S_ISDIR(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
            return False  # a folder where the file was: left to the person
        os.unlink(name, dir_fd=fd)
    if entry is None:
        return True
    data = _data(repo, entry)
    if entry.mode == LINK:
        os.symlink(os.fsdecode(data), name, dir_fd=fd)
        return True
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    file = os.open(name, flags, 0o755 if entry.mode == EXECUTABLE else 0o644, dir_fd=fd)
    with os.fdopen(file, "wb") as f:
        f.write(data)
    return True


def _walk_to(folder: str, parts: list[str], *, create: bool) -> int | None:
    """A descriptor of `folder`/`parts`, each step refusing a link; missing folders made when
    `create`, else None."""
    fd = os.open(folder, NOFOLLOW_DIR)
    try:
        for part in parts:
            try:
                child = os.open(part, NOFOLLOW_DIR, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    os.close(fd)
                    return None
                os.mkdir(part, 0o755, dir_fd=fd)
                child = os.open(part, NOFOLLOW_DIR, dir_fd=fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd
