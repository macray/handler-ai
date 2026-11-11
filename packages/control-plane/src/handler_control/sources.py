"""Sources (D.26): git repositories Handler reads to offer apps, agents and tools to install, and
the system packages (B.7) their tools need, installed with them.
The official one is Handler's (Settings.official_source); the person adds others, trusting them.
A source only offers: installing goes through each kind's own path and its page (addons G.5,
apps H.15, agents files D.23), never by itself.

    <config>/sources.toml       the sources added: [[source]] id, url (not the official one)
    <state>/sources/<id>/       what was read of it last:
      fetched.json              url, commit, fetchedAt, error (the last fetch's, when it failed:
                                the tree is then the one read before), skipped (an item → why it
                                cannot be offered)
      tree/                     the commit's handler-source.toml, apps/, agents/, tools/ and
                                system-packages/

A repository is read with dulwich, shallow and bare: nothing of it runs (no hooks, filters,
submodules, LFS). Its files are written out here, never a link: an item holding one, or a
submodule, is not offered.
"""

import contextlib
import io
import json
import re
import shutil
import tempfile
import threading
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import tomlkit
from dulwich import porcelain
from dulwich.config import ConfigDict
from dulwich.index import validate_path_element_default
from dulwich.object_store import iter_tree_contents
from dulwich.objects import Blob, Commit
from pydantic import ValidationError

from handler_contracts import OFFICIAL_SOURCE, SOURCE_MANIFEST, SourceKind, SourceManifest

from . import files
from .settings import Settings

ROOTS: dict[SourceKind, str] = {
    "app": "apps",
    "agents": "agents",
    "addon": "tools",
    "system-package": "system-packages",
}
NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")  # an item's folder
MAX_FILES, MAX_BYTES = 50_000, 1024 * 2**20  # what a source's tree may hold
FETCH_TIMEOUT = 60  # seconds, each HTTP request
FRESH_FOR = timedelta(days=1)  # read again when listed after that
FETCHED, TREE = "fetched.json", "tree"
LINK, GITLINK = 0o120000, 0o160000

# an item: its kind, its name, its folder (None: not offered) and why not
type Found = tuple[SourceKind, str, Path | None, str]


class SourceError(ValueError):
    def __init__(self, status: int, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.title = status, title


@dataclass(frozen=True)
class Listed:
    id: str
    url: str
    official: bool = False


@dataclass(frozen=True)
class Fetched:
    """What was read of a source last."""

    commit: str | None = None
    fetched_at: datetime | None = None
    error: str | None = None
    skipped: dict[str, str] | None = None  # "<root>/<name>" → why it is not offered
    manifest: SourceManifest | None = None


# ── the list ────────────────────────────────────────────────────────────


def config_path(settings: Settings) -> Path:
    return settings.config_dir / "sources.toml"


def cache(settings: Settings, source_id: str) -> Path:
    return settings.state_dir / "sources" / source_id


def listed(settings: Settings) -> list[Listed]:
    """The official source first, then the ones added, in the order they were."""
    try:
        data = tomllib.loads(config_path(settings).read_text())
    except FileNotFoundError:
        data = {}
    added = [Listed(s["id"], s["url"]) for s in data.get("source", [])]
    return [Listed(OFFICIAL_SOURCE, settings.official_source, official=True), *added]


def get(settings: Settings, source_id: str) -> Listed:
    for found in listed(settings):
        if found.id == source_id:
            return found
    raise SourceError(404, "unknown source", source_id)


def _write(settings: Settings, added: list[Listed]) -> None:
    doc = tomlkit.document()
    doc.add(tomlkit.comment("Sources added (D.26): written by handlerd, each one trusted by you"))
    sources = tomlkit.aot()
    for s in added:
        row = tomlkit.table()
        row.update({"id": s.id, "url": s.url})
        sources.append(row)
    doc.add("source", sources)
    files.write_private(config_path(settings), tomlkit.dumps(doc))


def new_id(url: str, taken: set[str]) -> str:
    """Its name in Handler: the repository's, made unique."""
    last = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    base = re.sub(r"[^a-z0-9]+", "-", last.lower()).strip("-")[:36] or "source"
    found, n = base, 2
    while found in taken or found == OFFICIAL_SOURCE:
        found, n = f"{base}-{n}", n + 1
    return found


def add(settings: Settings, url: str) -> Listed:
    """Read first: a repository that is no source is not added."""
    known = listed(settings)
    if url.rstrip("/").removesuffix(".git") in {
        k.url.rstrip("/").removesuffix(".git") for k in known
    }:
        raise SourceError(409, "source exists", url)
    source = Listed(new_id(url, {k.id for k in known}), url)
    fetch(settings, source)
    state = read(settings, source.id)
    if state.error is not None:
        shutil.rmtree(cache(settings, source.id), ignore_errors=True)
        raise SourceError(422, "not a source", state.error)
    _write(settings, [*(k for k in known if not k.official), source])
    return source


def remove(settings: Settings, source_id: str) -> None:
    """What was installed from it stays: it is the person's."""
    source = get(settings, source_id)
    if source.official:
        raise SourceError(409, "the official source", "Handler's own source cannot be removed")
    _write(settings, [k for k in listed(settings) if not k.official and k.id != source_id])
    shutil.rmtree(cache(settings, source_id), ignore_errors=True)


# ── reading a repository ────────────────────────────────────────────────

_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _lock(source_id: str) -> threading.Lock:
    with _locks_lock:
        return _locks.setdefault(source_id, threading.Lock())


def read(settings: Settings, source_id: str) -> Fetched:
    """What was read of it last (nothing yet: all None)."""
    folder = cache(settings, source_id)
    try:
        raw = json.loads((folder / FETCHED).read_text())
    except (FileNotFoundError, ValueError):
        return Fetched()
    manifest = None
    with contextlib.suppress(OSError, ValueError, ValidationError):
        manifest = SourceManifest.model_validate(
            tomllib.loads((folder / TREE / SOURCE_MANIFEST).read_text())
        )
    return Fetched(
        commit=raw.get("commit"),
        fetched_at=datetime.fromisoformat(at) if (at := raw.get("fetchedAt")) else None,
        error=raw.get("error"),
        skipped=raw.get("skipped", {}),
        manifest=manifest,
    )


def stale(settings: Settings, source_id: str) -> bool:
    at = read(settings, source_id).fetched_at
    return at is None or datetime.now(UTC) - at > FRESH_FOR


def fetch(settings: Settings, source: Listed) -> None:
    """Read it again. A failure is kept as its error, beside what was read before."""
    folder = cache(settings, source.id)
    with _lock(source.id):
        folder.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder.parent, prefix=f".{source.id}-") as tmp:
            new = Path(tmp) / "new"
            try:
                commit, skipped = _clone(source.url, Path(tmp) / "git", new / TREE)
            except SourceError as e:
                previous = (
                    json.loads((folder / FETCHED).read_text())
                    if (folder / FETCHED).is_file()
                    else {}
                )
                previous |= {
                    "url": source.url,
                    "fetchedAt": datetime.now(UTC).isoformat(),
                    "error": str(e),
                }
                folder.mkdir(parents=True, exist_ok=True)
                files.write_private(folder / FETCHED, json.dumps(previous, indent=2))
                return
            fetched = {
                "url": source.url,
                "commit": commit,
                "fetchedAt": datetime.now(UTC).isoformat(),
                "skipped": skipped,
            }
            files.write_private(new / FETCHED, json.dumps(fetched, indent=2))
            if folder.exists():
                folder.rename(Path(tmp) / "old")
            new.rename(folder)


def _clone(url: str, git: Path, tree: Path) -> tuple[str, dict[str, str]]:
    """The default branch's last commit written out in `tree`: its id, and the items skipped."""
    config = ConfigDict()
    config.set((b"http",), b"timeout", str(FETCH_TIMEOUT).encode())
    try:
        repo = porcelain.clone(
            url, str(git), bare=True, depth=1, checkout=False, errstream=io.BytesIO(), config=config
        )
    except Exception as e:  # dulwich's errors: network, HTTP, protocol, not a repository
        raise SourceError(422, "cannot read the source", f"cannot read {url}: {e}") from None
    with repo:
        try:
            commit = repo[repo.head()]
        except KeyError:
            raise SourceError(422, "not a source", f"{url} has no commit") from None
        assert isinstance(commit, Commit)
        skipped: dict[str, str] = {}
        count = size = 0
        tree.mkdir(parents=True)
        for entry in iter_tree_contents(repo.object_store, commit.tree):
            path = entry.path.decode("utf-8", "replace")
            parts = path.split("/")
            # git refuses "..", "." and ".git" in a tree, a crafted repository need not: written
            # out, "apps/../../x" would land outside the tree
            if not all(validate_path_element_default(p) for p in entry.path.split(b"/")):
                raise SourceError(422, "not a source", f"{url} holds an unsafe path: {path!r}")
            if path != SOURCE_MANIFEST and (len(parts) < 3 or parts[0] not in ROOTS.values()):
                continue  # not something offered: its README, CI, …
            item = "/".join(parts[:2])
            if entry.mode in (LINK, GITLINK):
                kind = "a link" if entry.mode == LINK else "a submodule"
                skipped[item] = f"it holds {kind}: {'/'.join(parts[2:])}"
                continue
            blob = repo[entry.sha]
            assert isinstance(blob, Blob)
            count, size = count + 1, size + blob.raw_length()
            if count > MAX_FILES or size > MAX_BYTES:
                raise SourceError(
                    422, "source too large", f"more than {MAX_FILES} files or {MAX_BYTES >> 20} MiB"
                )
            target = tree.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob.as_raw_string())
            if entry.mode & 0o111:
                target.chmod(0o755)
        for item in skipped:
            shutil.rmtree(tree / item, ignore_errors=True)
    if not (tree / SOURCE_MANIFEST).is_file():
        raise SourceError(422, "not a source", f"{url} has no {SOURCE_MANIFEST} at its root")
    try:
        SourceManifest.model_validate(tomllib.loads((tree / SOURCE_MANIFEST).read_text()))
    except (ValueError, ValidationError) as e:
        detail = files.describe(e) if isinstance(e, ValidationError) else str(e)
        raise SourceError(422, "not a source", f"{SOURCE_MANIFEST}: {detail}") from None
    return commit.id.decode(), skipped


# ── what it offers ──────────────────────────────────────────────────────


def items(settings: Settings, source_id: str) -> list[Found]:
    """Each item read last: its kind, name, folder (None: not offered) and why not."""
    tree = cache(settings, source_id) / TREE
    skipped = read(settings, source_id).skipped or {}
    found: list[Found] = []
    for kind, root in ROOTS.items():
        names = (
            {p.name for p in (tree / root).iterdir() if p.is_dir()}
            if (tree / root).is_dir()
            else set()
        )
        names |= {item.split("/", 1)[1] for item in skipped if item.startswith(f"{root}/")}
        for name in sorted(names):
            if (why := skipped.get(f"{root}/{name}")) is not None:
                found.append((kind, name, None, why))
            elif not NAME.fullmatch(name):
                found.append((kind, name, None, "not a name (lowercase letters, digits, -)"))
            else:
                found.append((kind, name, tree / root / name, ""))
    return found


def item(settings: Settings, source_id: str, kind: SourceKind, name: str) -> Path:
    """The folder of one it offers, as read last."""
    get(settings, source_id)
    for k, n, folder, why in items(settings, source_id):
        if k == kind and n == name:
            if folder is None:
                raise SourceError(409, "not offered", f"{name}: {why}")
            return folder
    raise SourceError(404, "unknown item", f"{source_id} offers no {kind} named {name}")
