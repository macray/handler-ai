"""Apps (contract H, apps design): registry, deploy and rollback, backends
started on demand and stopped when idle. Serving them over HTTP is app_http.py.

    <state>/apps.json                  registry: each app's deployments, the source its code came
                                       from (D.26), and what the person gave its needs
                                       (bindings: a folder's path by the need's name, H.2) and
                                       who works on its jobs (its own, a job's)
    <data>/apps/<name>/versions/<n>/   the code of deploy n (app.toml, backend dir, built UI, its
                                       jobs' instructions, its schemas)
    <data>/apps/<name>/data/           the app's data (its scope): survives deploys
    <data>/apps/<name>/backups/<n>/    the data as it was just before deploy n (rollback)
    <data>/apps/<name>/app.log         the last deploys and the backend's output
    <data>/apps/<name>/source/         its code, kept by Handler (H.15): what an app file, a
                                       draft or a source (D.26) gave; what a deploy installs and
                                       an export holds
    <runtime>/apps/<name>/             the backend's socket (HANDLER_RUNTIME_DIR, settings.py)

A deploy (H.6) is asked by a person, never by an agent: snapshot its code (source/), run the
backend's tests, stop the backend, back the data up, start the new version on a copy of the data
(its migrations run there) until it answers its health check, then switch. Any failure leaves the
installed version and the data as they were.
"""

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import TypeAdapter, ValidationError

from handler_contracts import (
    ACTION_HEADER,
    HEALTH_PATH,
    JOB_INSTRUCTIONS_DIR,
    MANIFEST_FILE,
    NUDGE_HEADER,
    PERSON_HEADER,
    RUNTIME_IMAGE,
    START_HEADER,
    VIA_HEADER,
    ActionResult,
    ActionRun,
    AgentInterface,
    App,
    AppAction,
    AppDeployment,
    AppFileNeed,
    AppJob,
    AppJobCanDo,
    AppManifest,
    AppManifestJob,
    AppManifestNudge,
    AppNudge,
    AppOffered,
    AppRun,
    AppRunRequest,
    AppRunStartedBy,
    AppSecret,
    AppSource,
    AppState,
    DraftCopy,
    DraftPreview,
    InboxMessage,
    NotesCommitDiff,
    NotesHistory,
    NudgeSetting,
    PreparedNudge,
    Schedule,
    SharedApp,
    StartedByAction,
    StartedByCode,
    WhoWorks,
    is_within,
)

from . import (
    app_jobs,
    app_smd,
    compose,
    definitions,
    files,
    interfaces,
    knowledge_schemas,
    pins,
    runtime,
    sandbox_process,
    sources,
)
from .agents import RunsAs
from .app_api import AppApi
from .app_api import Handler as AppApiHandler
from .app_runs import AppRunError, AppRuns
from .inbox import Inbox, told_result
from .launcher import NETWORK_FILTER, missing
from .nudges import NudgeError, Nudges, slot_key
from .secrets import SecretStore
from .settings import Settings

log = logging.getLogger("handler.apps")

KEEP_DEPLOYMENTS = 3  # the current one and two to roll back to
MAX_APP_BYTES = 256 * 1024 * 1024
START_TIMEOUT = 60.0  # a first start may wait for podman to set the container up
TEST_TIMEOUT = 300.0
PULL_TIMEOUT = 600.0
MAX_APP_FILES = 20_000  # in an app file (H.15)
LOG_MAX_BYTES = 1024 * 1024
LOG_TAIL_BYTES = 64 * 1024
LINK_TTL = 120.0
LINE_LIMIT = 1024 * 1024
NOTIFY_PER_HOUR = 30
CALL_TIMEOUT = 300.0  # an automation's call (I.3), a nudge's `prepare` (H.17)
MAX_PREPARED = 10  # nudges a `prepare` answers at one slot (H.17)
PREPARED: TypeAdapter[PreparedNudge | list[PreparedNudge]] = TypeAdapter(
    PreparedNudge | list[PreparedNudge]
)
ACTION_TIMEOUT = 30.0  # an action done by the app's code answers at once (H.12)
ACTION_WAIT = 20.0  # an action done by its job: answered with its result if it ends by then
ACTION_POLL = 0.5
# never given to an app, whatever it asks (H.9): keys and password stores (and handler's own dirs)
PRIVATE_HOME = (".ssh", ".gnupg", ".password-store", ".local/share/keyrings", ".pki", ".aws")
COOKIE_NAME = "handler_app"
DRAFT = "--draft"  # an opened draft's name: `<app>--draft`, its own origin and folder (H.16)
SMALL_FOLDER = 64 * 1024 * 1024  # a folder given to an app copied for its opened draft


CHAT = "chat"  # Chat is no app, but it is listed with them (D.1): no app takes its name


class AppError(Exception):
    """A request that cannot be done: bad source folder, unknown app, failed deploy…"""


class AppNotFoundError(AppError):
    pass


class DeployError(AppError):
    pass


class InputError(AppError):
    """An action's fields that do not fit its form (H.12)."""


@dataclass
class Deployment:
    seq: int
    version: str
    deployed_at: datetime


@dataclass
class AppRecord:
    name: str
    from_source: str | None = None  # the source its code came from (D.26); None: a file, a draft
    deployments: list[Deployment] = field(default_factory=list)  # oldest first; last = current
    next_seq: int = 1
    last_used_at: datetime | None = None
    persons: list[str] = field(default_factory=list)  # who may use it remotely (H.8)
    files: dict[str, str] = field(default_factory=dict)  # need → the folder given (H.2)
    not_in_ask: list[str] = field(default_factory=list)  # its actions you took out of Ask (D.24)
    who_works: WhoWorks | None = None  # who runs its jobs (H.2)
    jobs_who_works: dict[str, WhoWorks] = field(default_factory=dict)  # a job's own, by name

    @property
    def current(self) -> Deployment | None:
        return self.deployments[-1] if self.deployments else None

    @property
    def previous(self) -> Deployment | None:
        return self.deployments[-2] if len(self.deployments) > 1 else None


@dataclass(frozen=True)
class WrittenFolder:
    """A folder given to a files need in `rw` of an installed app (H.2), written by the app (D.5,
    the notes history)."""

    app: str
    title: str  # the app's display name, its name without one
    path: str  # real, a folder
    running: bool  # its backend, now
    last_used_at: datetime | None


@dataclass
class Backend:
    """A running backend: the sandbox launcher and a client on its socket."""

    process: asyncio.subprocess.Process
    client: httpx.AsyncClient
    pump: asyncio.Task[None]  # copies its output to the log
    api: AppApi | None = None  # handler's side for the backend (H.9, H.11)
    last_used: float = field(default_factory=time.monotonic)


@dataclass
class Preview:
    """A draft opened (H.16): its backend, on copies, and what it works on."""

    session: str  # the draft's session
    backend: Backend
    copies: list[DraftCopy]


def read_manifest(folder: Path) -> AppManifest:
    try:
        text = (folder / MANIFEST_FILE).read_text()
    except OSError as e:
        raise AppError(f"cannot read {folder / MANIFEST_FILE}: {e.strerror}") from None
    try:
        manifest = AppManifest.from_toml(text)
    except ValidationError as e:
        raise AppError(f"{MANIFEST_FILE} is invalid: {files.describe(e)}") from None
    except ValueError as e:  # TOML syntax
        raise AppError(f"{MANIFEST_FILE} is invalid: {e}") from None
    return manifest


def jobs_problem(folder: Path, jobs: list[str]) -> str | None:
    """Why the app's `jobs/` does not hold exactly its jobs' instructions, a file `<name>.md` for
    each (H.1); None when it does."""
    shipped = folder / JOB_INSTRUCTIONS_DIR
    found = sorted(p.name for p in shipped.iterdir()) if shipped.is_dir() else []
    for name in sorted(jobs):
        if not (shipped / f"{name}.md").is_file():
            return f"jobs.{name}: its instructions {JOB_INSTRUCTIONS_DIR}/{name}.md do not exist"
    if extra := [f for f in found if f.removesuffix(".md") not in jobs or not f.endswith(".md")]:
        return f"{JOB_INSTRUCTIONS_DIR}/{extra[0]} is no job's instructions"
    return None


def snapshot(source: Path, target: Path, manifest: AppManifest) -> None:
    """Copy what a deploy installs (the manifest, the backend's directory, the built UI, its
    `schemas/`, its jobs' instructions `jobs/`) from `source` to
    `target`, its jobs checked there. Symbolic links are kept, and must stay inside the copy: an
    agent could otherwise publish any host file through the app's UI."""
    if not (source / manifest.server.entry).is_file():
        raise DeployError(f"server.entry {manifest.server.entry} does not exist")
    if not (source / manifest.ui.dir / "index.html").is_file():
        raise DeployError(f"{manifest.ui.dir}/index.html does not exist: build the UI first")
    if problem := app_smd.shipped_problem(source, manifest.schemas):
        raise DeployError(problem)
    if problem := jobs_problem(source, list(manifest.jobs)):
        raise DeployError(problem)
    target.mkdir(parents=True)
    shutil.copy2(source / MANIFEST_FILE, target / MANIFEST_FILE)
    formats = [app_smd.SCHEMAS_DIR] if manifest.schemas else []
    instructions = [JOB_INSTRUCTIONS_DIR] if manifest.jobs else []
    for rel in (manifest.server.dir, manifest.ui.dir, *formats, *instructions):
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source / rel, target / rel, symlinks=True, dirs_exist_ok=True)
    root, total = os.path.realpath(target), 0
    for dirpath, dirnames, filenames in os.walk(target):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path) and not is_within(os.path.realpath(path), root):
                raise DeployError(f"{os.path.relpath(path, target)} is a link to outside the app")
        total += sum(os.lstat(os.path.join(dirpath, n)).st_size for n in filenames)
    if total > MAX_APP_BYTES:
        raise DeployError(f"the app is {total // 2**20} MiB: more than {MAX_APP_BYTES // 2**20}")
    check_jobs(manifest, target)  # the copy: no link leads out of it


def check_jobs(manifest: AppManifest, folder: Path) -> None:
    """Each job's form and result are JSON Schemas (D.18), its result says how it went (`status`,
    `summary`: I.3's rule), and its instructions (in `folder`, a snapshot: every one there, no
    link leading out) name only fields of its form."""
    for name, job in manifest.jobs.items():
        interface = AgentInterface(
            fields=job.fields, result=job.result, timeout_sec=job.timeout_sec
        )
        try:
            interfaces.check(interface)
            path = folder / JOB_INSTRUCTIONS_DIR / f"{name}.md"
            interfaces.check_instructions(path.read_text(errors="replace"), interface)
        except interfaces.InterfaceError as e:
            raise DeployError(f"jobs.{name}.{e}") from None
        if found := interfaces.result_problems(job.result):
            raise DeployError(f"jobs.{name}: {'; '.join(found)}")


def unpack(data: bytes, target: Path) -> Path:
    """An app file (a zip, H.15) unpacked into `target`: the folder holding its app.toml (the
    zip's root, or the one folder it holds). Refused: no zip, a path leaving the folder, a link
    (an export has none), more than MAX_APP_FILES files or MAX_APP_BYTES bytes."""
    try:
        files.unzip(data, target, MAX_APP_FILES, MAX_APP_BYTES)
    except ValueError as e:
        raise AppError(f"not an app file: {e}") from None
    if (target / MANIFEST_FILE).is_file():
        return target
    inside = list(target.iterdir())
    if len(inside) == 1 and (inside[0] / MANIFEST_FILE).is_file():
        return inside[0]
    raise AppError(f"no {MANIFEST_FILE} in this file")


def link_out(root: Path, path: Path) -> str | None:
    """The first of `path` and what it holds that is a symbolic link leading outside `root` (an
    app's folder, which an agent writes): reading through it would give handler's reach to the
    agent. None when there is none."""
    inside = os.path.realpath(root)
    for p in [path, *(path.rglob("*") if path.is_dir() and not path.is_symlink() else [])]:
        if p.is_symlink() and not is_within(os.path.realpath(p), inside):
            return os.path.relpath(p, root)
    return None


def copy_data(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        target.mkdir(parents=True)


def folder_size(folder: Path) -> int:
    return sum(p.lstat().st_size for p in folder.rglob("*") if p.is_file() or p.is_symlink())


def _dump(who: WhoWorks) -> dict[str, Any]:
    return who.model_dump(mode="json", by_alias=True, exclude_none=True)


def _answer_error(r: httpx.Response) -> str:
    """What a backend's answer that is no success says: its `error`, else its status."""
    with contextlib.suppress(ValueError, AttributeError):
        if isinstance(error := r.json().get("error"), str):
            return error[:300]
    return f"answered {r.status_code}"


async def healthy(
    proc: asyncio.subprocess.Process, client: httpx.AsyncClient, socket: Path
) -> None:
    """Until the backend answers its health check (H.3); its exit, another answer or
    START_TIMEOUT: an AppError saying which. A connection refused or closed: not listening yet
    (on Apple container the launcher's socket answers first, A.10)."""
    deadline = time.monotonic() + START_TIMEOUT
    while True:
        if proc.returncode is not None:
            raise AppError(f"the backend exited ({proc.returncode}); its log says why")
        if time.monotonic() > deadline:
            raise AppError(f"the backend did not answer {HEALTH_PATH} in time")
        if socket.exists():
            try:
                r = await client.get(HEALTH_PATH, timeout=2.0)
            except httpx.TransportError:
                pass
            else:
                if r.status_code == 200:
                    return
                raise AppError(f"{HEALTH_PATH} answered {r.status_code}")
        await asyncio.sleep(0.2)


class FolderHistory(Protocol):
    """The notes history (D.5, notes_history.py, a layer above): a folder's commits, and one's
    files with their lines. Read only: an app never undoes."""

    def history(self, folder: str) -> NotesHistory: ...

    def commit(self, folder: str, commit_id: str) -> NotesCommitDiff: ...


class AppStore:
    def __init__(self, settings: Settings, token: str, inbox: Inbox, runs: AppRuns) -> None:
        self.settings = settings
        self.token = token
        self.file = settings.state_dir / "apps.json"
        self.root = settings.data_dir / "apps"
        self.run_root = settings.runtime_dir / "apps"
        self.records: dict[str, AppRecord] = {}
        self.live: dict[str, Backend] = {}
        self.errors: dict[str, str] = {}  # why a backend failed, until it starts again
        self.starting: set[str] = set()
        self.locks: dict[str, asyncio.Lock] = {}
        # one-time code → (app, the path it opens, expiry)
        self.links: dict[str, tuple[str, str, float]] = {}
        self.reaper: asyncio.Task[None] | None = None
        self.secrets = SecretStore(settings.data_dir)  # an app's are apps/<app>/<secret> (H.2)
        self.listeners: list[Callable[[], None]] = []  # the remote connector: what is shared
        self.inbox = inbox
        self.nudges = Nudges(settings, inbox)  # what its apps ask a person to do (H.17)
        self.sending: set[asyncio.Task[list[InboxMessage]]] = set()  # nudges at their slots
        self.sent: dict[str, list[float]] = {}  # app → recent notification times (rate limit)
        self.runs = runs  # runs of the jobs the apps start (H.11)
        # told after each change saved, and when a backend starts or stops (the web UI, D.30)
        self.watchers: list[Callable[[], None]] = []
        runs.call_then = self.call_then  # a job's `then`, when one of its runs ends
        self.starts: dict[str, str] = {}  # start token of an owner's request in progress → app
        self.previews: dict[str, Preview] = {}  # an app's name → its draft, opened (H.16)
        # its read-write folders' history, for its code (H.9): set by the daemon once made
        self.history: FolderHistory | None = None
        runs.sessions.delete_listeners.append(self._session_deleted)
        self._load()

    # ── registry ────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            raw = json.loads(self.file.read_text())
        except FileNotFoundError:
            return
        for name, r in raw["apps"].items():
            self.records[name] = AppRecord(
                name=name,
                from_source=r["fromSource"],
                deployments=[
                    Deployment(
                        d["seq"],
                        d["version"],
                        datetime.fromisoformat(d["deployedAt"]),
                    )
                    for d in r["deployments"]
                ],
                next_seq=r["nextSeq"],
                last_used_at=datetime.fromisoformat(u) if (u := r["lastUsedAt"]) else None,
                persons=r["persons"],
                files=r["files"],
                not_in_ask=r["notInAsk"],
                who_works=WhoWorks.model_validate(w) if (w := r["whoWorks"]) else None,
                jobs_who_works={
                    j: WhoWorks.model_validate(w) for j, w in r["jobsWhoWorks"].items()
                },
            )

    def _tell(self) -> None:
        for watcher in self.watchers:
            watcher()

    def _save(self) -> None:
        apps = {
            r.name: {
                "fromSource": r.from_source,
                "deployments": [
                    {
                        "seq": d.seq,
                        "version": d.version,
                        "deployedAt": d.deployed_at.isoformat(),
                    }
                    for d in r.deployments
                ],
                "nextSeq": r.next_seq,
                "lastUsedAt": r.last_used_at.isoformat() if r.last_used_at else None,
                "persons": r.persons,
                "files": r.files,
                "notInAsk": r.not_in_ask,
                "whoWorks": _dump(r.who_works) if r.who_works else None,
                "jobsWhoWorks": {j: _dump(w) for j, w in r.jobs_who_works.items()},
            }
            for r in self.records.values()
        }
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"apps": apps}, indent=2))
        tmp.replace(self.file)
        self._tell()

    def get(self, name: str) -> AppRecord:
        record = self.records.get(name)
        if record is None:
            raise AppNotFoundError(f"no app named {name}")
        return record

    def lock(self, name: str) -> asyncio.Lock:
        return self.locks.setdefault(name, asyncio.Lock())

    def app_dir(self, name: str) -> Path:
        return self.root / name

    def data_dir(self, name: str) -> Path:
        return self.app_dir(name) / "data"

    def version_dir(self, name: str, seq: int) -> Path:
        return self.app_dir(name) / "versions" / str(seq)

    def log_path(self, name: str) -> Path:
        return self.app_dir(name) / "app.log"

    def source(self, name: str) -> Path:
        """Its code, kept by Handler (H.15)."""
        return self.app_dir(name) / "source"

    def add_file(self, data: bytes) -> tuple[AppRecord, bool]:
        """Install an app file (an export, H.15): its code becomes Handler's copy. A new name is
        a new app (True), not installed yet; the name of one you have gives it its next version,
        which its page offers to deploy (False). An app from a source given so is yours from
        then on: its source no longer offers it a next version."""
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root, prefix=".incoming-") as tmp:
            return self._install(unpack(data, Path(tmp) / "app"), "from a file")

    def add_draft(self, draft: Path, app: str | None) -> tuple[AppRecord, bool]:
        """A draft of an app's code used (H.15: an App creator's session's folder): as an app
        file is, the next version of `app`, or a new app (None). Not its `.git` nor
        `node_modules`; a link leading outside it is refused (the folder is an agent's)."""
        if (out := link_out(draft, draft)) is not None:
            raise AppError(f"{out} is a link to outside the draft")
        manifest = read_manifest(draft)
        if app is not None and manifest.name != app:
            raise AppError(f"the draft of {app} now names another app: {manifest.name}")
        if app is None and manifest.name in self.records:
            raise AppError(f"an app named {manifest.name} is already installed: rename it")
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root, prefix=".incoming-") as tmp:
            folder = Path(tmp) / "app"
            ignore = shutil.ignore_patterns(".git", "node_modules")
            shutil.copytree(draft, folder, symlinks=True, ignore=ignore)
            return self._install(folder, "from a draft")

    def add_from_source(self, source: str, folder: Path) -> tuple[AppRecord, bool]:
        """An app a source offers (D.26, `folder`: its item as read last), its code copied as an
        app file's is: a new app (True), or the next version of one you have from that source
        (False). It keeps which source it came from: a later commit of that source offers its next
        version. Never over an app of that name from elsewhere (yours, or another source's): its
        code would be replaced by a stranger's."""
        if (name := read_manifest(folder).name) != folder.name:
            raise AppError(f"{folder.name}: its {MANIFEST_FILE} names another app, {name}")
        known = self.records.get(name)
        if known is not None and known.from_source != source:
            whose = f"from the source {known.from_source}" if known.from_source else "yours"
            raise AppError(f"you already have an app named {name}, {whose}: remove it first")
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root, prefix=".incoming-") as tmp:
            copy = Path(tmp) / "app"
            shutil.copytree(folder, copy)  # a source's tree holds no link
            return self._install(copy, f"from the source {source}", source)

    def _install(self, folder: Path, how: str, source: str | None = None) -> tuple[AppRecord, bool]:
        """`folder` (the app's code, on the same file system) becomes its code kept by Handler."""
        manifest = read_manifest(folder)
        name = manifest.name
        if name.endswith(DRAFT):
            raise AppError(f"{name}: a name ending in {DRAFT} is an opened draft's (H.16)")
        if name == CHAT:
            raise AppError(f"{name}: the name of Chat, listed with the apps (D.1)")
        known = self.records.get(name)
        target = self.source(name)
        shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        folder.replace(target)
        if known is None:
            self.records[name] = AppRecord(name=name, from_source=source)
            self.data_dir(name).mkdir(parents=True, exist_ok=True)
        else:
            known.from_source = source
        self._save()
        self._log(name, f"its code {manifest.version} installed {how}")
        self.changed()
        return self.records[name], known is None

    def export(self, name: str) -> tuple[str, bytes]:
        """Its code as one file (H.15): the name to save it as, and the zip. Never its data,
        what you gave it, its secrets or its runs: those are not in its code."""
        self.get(name)
        folder = self.source(name)
        version = read_manifest(folder).version
        if (out := link_out(folder, folder)) is not None:
            raise AppError(f"{out} is a link to outside the app: it cannot be exported")
        return f"{name}-{version}.zip", files.zipped(folder)

    async def remove(self, name: str) -> None:
        """Uninstall it (H.6): its code, versions, backups, its own data and its pin deleted (the
        folders given to it are the person's: they stay), so nothing of it is found by an app
        installed later under its name."""
        self.get(name)
        async with self.lock(name):
            await self._stop(name)
            self.records.pop(name)
            self._save()
            self.changed()
            self.secrets.delete(f"apps/{name}")
            await self.runs.forget(name)
            self.nudges.forget(name)
            pins.forget(self.settings.state_dir, "app", name)
            shutil.rmtree(self.app_dir(name), ignore_errors=True)

    def manifest(self, name: str, seq: int) -> AppManifest:
        return read_manifest(self.version_dir(name, seq))

    # ── secrets (H.2) ───────────────────────────────────────────────────

    def declared_secrets(self, name: str) -> list[str]:
        """What the installed version and the source folder declare."""
        return sorted({s for m, _ in self.declared(name) for s in m.needs.secrets})

    async def set_secret(self, name: str, secret: str, value: str | None) -> App:
        """Set (or, with None, forget) a secret's value. A running backend is stopped: it starts
        again, with the new value, on its next request."""
        if secret not in self.declared_secrets(name):
            raise AppError(f"{name} declares no secret {secret}")
        if value is None:
            self.secrets.delete(f"apps/{name}/{secret}")
        else:
            self.secrets.put(f"apps/{name}/{secret}", value, f"{secret} of the app {name}")
        async with self.lock(name):
            await self._stop(name)
        return self.view(name)

    def secrets_for(self, name: str, manifest: AppManifest) -> dict[str, str]:
        values = {
            n: v for n in manifest.needs.secrets if (v := self.secrets.get(f"apps/{name}/{n}"))
        }
        if missing := [n for n in manifest.needs.secrets if n not in values]:
            raise AppError(
                f"secret {', '.join(missing)} not set (Apps page, or handler app secret)"
            )
        return {n: values[n] for n in manifest.needs.secrets}

    # ── remote use (H.8) ────────────────────────────────────────────────

    def set_persons(self, name: str, persons: list[str]) -> App:
        record = self.get(name)
        record.persons = sorted(set(persons))
        self._save()
        self.changed()
        return self.view(name)

    def remote_apps(self, person: str | None = None) -> list[SharedApp]:
        """Deployed apps shared with `person` (with anyone: None), as a device lists them."""
        out: list[SharedApp] = []
        for record in sorted(self.records.values(), key=lambda r: r.name):
            if record.current is None or not record.persons:
                continue
            if person is not None and person not in record.persons:
                continue
            description, queued = None, []
            with contextlib.suppress(AppError):
                manifest = self.manifest(record.name, record.current.seq)
                description, queued = manifest.description, manifest.queued_routes
            out.append(
                SharedApp(
                    name=record.name,
                    description=description,
                    version=record.current.version,
                    queued=queued,
                )
            )
        return out

    def changed(self) -> None:
        for listener in self.listeners:
            listener()

    # ── views ───────────────────────────────────────────────────────────

    def origin(self, name: str) -> str:
        return f"http://{name}.localhost:{self.settings.port}"

    def state(self, name: str) -> AppState:
        if name in self.starting:
            return "starting"
        if name in self.live:
            return "running"
        return "failed" if name in self.errors else "stopped"

    def deployment_view(self, name: str, d: Deployment | None) -> AppDeployment | None:
        if d is None:
            return None
        try:
            needs = self.manifest(name, d.seq).needs
        except AppError:
            return None
        return AppDeployment(version=d.version, deployed_at=d.deployed_at, needs=needs)

    def source_view(self, record: AppRecord) -> AppSource:
        try:
            manifest = read_manifest(self.source(record.name))
        except AppError as e:
            return AppSource(error=str(e))
        if manifest.name != record.name:
            return AppSource(error=f"{MANIFEST_FILE} now names another app: {manifest.name}")
        installed = None
        if record.current:
            with contextlib.suppress(AppError):
                installed = self.manifest(record.name, record.current.seq)
        return AppSource(
            version=manifest.version,
            description=manifest.description,
            changes=manifest.changes,
            added_needs=manifest.added_needs(installed),
            needs=manifest.needs,
        )

    def offered_folder(self, record: AppRecord) -> Path | None:
        """The folder of the version its source offers, as read last (D.26), while it differs
        from its kept code's (rule app.update-takes-then-deploys); None: no source, an unreadable
        one, none offered, or the same version."""
        if record.from_source is None:
            return None
        try:
            folder = sources.item(self.settings, record.from_source, "app", record.name)
            manifest = read_manifest(folder)
        except (sources.SourceError, AppError, OSError):
            return None
        with contextlib.suppress(AppError):
            if read_manifest(self.source(record.name)).version == manifest.version:
                return None
        return folder if manifest.name == record.name else None

    def offered_view(self, record: AppRecord) -> AppOffered | None:
        """What Update would take: the version its source offers, what it changes and what it
        adds to the installed one (rule deploy.what-it-adds-is-said-first)."""
        if record.from_source is None or (folder := self.offered_folder(record)) is None:
            return None
        manifest = read_manifest(folder)
        installed = None
        if record.current:
            with contextlib.suppress(AppError):
                installed = self.manifest(record.name, record.current.seq)
        return AppOffered(
            source=record.from_source,
            version=manifest.version,
            changes=manifest.changes,
            added_needs=manifest.added_needs(installed),
        )

    async def update(self, name: str) -> App:
        """Update (H.6): the version its source offers taken (as Get it takes it), then deployed.
        A deploy that fails leaves that version kept, ready to deploy, and the installed one
        running (rule deploy.a-failure-changes-nothing)."""
        record = self.get(name)
        folder = self.offered_folder(record)
        if record.from_source is None or folder is None:
            raise AppError(f"{name}: its source offers no other version")
        self.add_from_source(record.from_source, folder)
        return await self.deploy(name)

    def view(self, name: str) -> App:
        record = self.get(name)
        files = self.needs_view(name)
        next_version = self.declared(name)[:1]
        suggests = next_version[0][0].automations if next_version else []
        current = self.deployment_view(name, record.current)
        description, title = None, None
        if record.current:
            with contextlib.suppress(AppError):
                installed = self.manifest(name, record.current.seq)
                description, title = installed.description, installed.title
        else:
            with contextlib.suppress(AppError):
                title = read_manifest(self.source(name)).title
        return App(
            name=name,
            title=title,
            description=description,
            url=f"{self.origin(name)}/",
            state=self.state(name),
            error=self.errors.get(name),
            current=current,
            previous=self.deployment_view(name, record.previous),
            source=self.source_view(record),
            offered=self.offered_view(record),
            secrets=[
                AppSecret(name=n, set=self.secrets.get(f"apps/{name}/{n}") is not None)
                for n in self.declared_secrets(name)
            ],
            files=files,
            suggests=suggests,
            persons=record.persons,
            last_used_at=record.last_used_at,
            from_source=record.from_source,
            actions=self.actions_view(name),
            nudges=self.nudges_view(name),
            who_works=record.who_works,
            jobs=self.jobs_view(name),
        )

    def views(self) -> list[App]:
        return [self.view(n) for n in sorted(self.records)]

    def folder_apps(self, folder: str) -> list[str]:
        """The names of the apps given that folder, or one inside it, for one of their files
        needs (H.14): a project lists them, from its folder's side."""
        return [
            n
            for n, record in sorted(self.records.items())
            if any(is_within(path, folder) for path in record.files.values())
        ]

    def written_folders(self) -> list[WrittenFolder]:
        """Each folder given to a files need in `rw` of an app's installed version, with who
        writes it (rule notes.writable-has-a-history); a file given, or a folder gone, is not."""
        found: list[WrittenFolder] = []
        for name, record in sorted(self.records.items()):
            if record.current is None:
                continue
            try:
                manifest = self.manifest(name, record.current.seq)
            except AppError:
                continue
            for need, wanted in manifest.needs.files.items():
                given = record.files.get(need)
                if wanted.mode != "rw" or given is None or not os.path.isdir(given):
                    continue
                found.append(
                    WrittenFolder(
                        app=name,
                        title=manifest.title or name,
                        path=os.path.realpath(given),
                        running=name in self.live,
                        last_used_at=record.last_used_at,
                    )
                )
        return found

    def log_tail(self, name: str) -> str:
        self.get(name)
        try:
            with self.log_path(name).open("rb") as f:
                f.seek(max(0, f.seek(0, os.SEEK_END) - LOG_TAIL_BYTES))
                return f.read().decode(errors="replace")
        except FileNotFoundError:
            return ""

    def _log(self, name: str, text: str) -> None:
        path = self.log_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            tail = path.read_bytes()[-LOG_MAX_BYTES // 4 :]
            path.write_bytes(tail)
        with path.open("a") as f:
            f.write(f"[{datetime.now(UTC):%Y-%m-%d %H:%M:%S}] {text}\n")

    # ── opening an app in a browser (H.4) ───────────────────────────────

    def open_link(self, name: str, path: str = "/") -> str:
        """A one-time link opening the app at `path`: `/`, or the page a nudge names (H.17)."""
        record = self.get(name)
        if record.current is None:
            raise AppError(f"{name} is not deployed yet")
        now = time.monotonic()
        self.links = {c: v for c, v in self.links.items() if v[2] > now}
        code = secrets.token_urlsafe(24)
        self.links[code] = (name, path, now + LINK_TTL)
        return f"{self.origin(name)}/_handler/login?code={code}"

    def redeem(self, name: str, code: str) -> str | None:
        """One-time: a link opens the app once, within LINK_TTL; the path it opens."""
        entry = self.links.pop(code, None)
        if entry is None or entry[0] != name or entry[2] <= time.monotonic():
            return None
        return entry[1]

    def cookie(self, name: str) -> str:
        """The app's cookie: bound to the app and the daemon's token (changing it logs out)."""
        return hmac.new(
            self.token.encode(), f"handler-app/{name}".encode(), hashlib.sha256
        ).hexdigest()

    def cookie_matches(self, name: str, presented: str | None) -> bool:
        return presented is not None and hmac.compare_digest(presented, self.cookie(name))

    # ── deploy and rollback (H.6) ───────────────────────────────────────

    async def deploy(self, name: str) -> App:
        record = self.get(name)
        async with self.lock(name):
            seq = record.next_seq
            record.next_seq += 1
            self._save()
            staging = self.app_dir(name) / "staging" / str(seq)
            check = self.app_dir(name) / "check-data"
            backup = self.app_dir(name) / "backups" / str(seq)
            # what a deploy of this number left, here or in a state since lost (a new state
            # numbers from 1 again): no deployment recorded owns them
            target = self.version_dir(name, seq)
            for leftover in (staging, check, backup, target):
                shutil.rmtree(leftover, ignore_errors=True)
            try:
                source = self.source(name)
                manifest = read_manifest(source)
                self._log(name, f"== deploy {manifest.version} (#{seq})")
                if manifest.name != name:
                    raise DeployError(f"{MANIFEST_FILE} names another app: {manifest.name}")
                app_secrets = self.secrets_for(name, manifest)
                self.check_files(name, manifest)
                self.check_actions(manifest)
                await asyncio.to_thread(snapshot, source, staging, manifest)
                await self._pull_runtime(name)
                await self._run_tests(name, manifest, staging, check)
                await self._stop(name)
                await asyncio.to_thread(copy_data, self.data_dir(name), backup)
                await asyncio.to_thread(copy_data, self.data_dir(name), check)
                backend = await self._start(
                    name, seq, manifest, staging, check, app_secrets=app_secrets, check=True
                )
                await self._stop_backend(backend)
                self.library_schemas(name, staging)  # the last step that may fail
            except BaseException as e:
                shutil.rmtree(backup, ignore_errors=True)
                shutil.rmtree(staging, ignore_errors=True)
                detail = str(e) if isinstance(e, AppError) else f"{type(e).__name__}: {e}"
                self._log(name, f"deploy failed: {detail}")
                if isinstance(e, (AppError, OSError)):
                    raise DeployError(detail) from None
                raise
            finally:
                shutil.rmtree(check, ignore_errors=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(target)
            record.deployments.append(Deployment(seq, manifest.version, datetime.now(UTC)))
            for old in record.deployments[:-KEEP_DEPLOYMENTS]:
                shutil.rmtree(self.version_dir(name, old.seq), ignore_errors=True)
                shutil.rmtree(self.app_dir(name) / "backups" / str(old.seq), ignore_errors=True)
            record.deployments = record.deployments[-KEEP_DEPLOYMENTS:]
            self.errors.pop(name, None)
            self._save()
            self._log(name, f"deployed {manifest.version} (#{seq})")
        self.changed()
        return self.view(name)

    def library_schemas(self, name: str, folder: Path) -> None:
        """The schemas an app brings (its `schemas/`, D.29) into the Library, those not there
        yet: the person's from then on, as an agent definition's. A different one of an `$id`
        there refuses the deploy, said, adding none."""
        differs = f"{name} brings: it reads its documents with its own; replace yours in "
        differs += "Library → Schemas to install it"
        try:
            definitions.install_schemas(folder, self.settings.schemas_dir, differs)
        except knowledge_schemas.SchemaError as e:
            raise DeployError(str(e)) from None

    async def rollback(self, name: str) -> App:
        """Back to the previous version, with the data as it was just before the current one was
        deployed: what changed since is lost (the migrations may not run backwards)."""
        record = self.get(name)
        async with self.lock(name):
            current, previous = record.current, record.previous
            if current is None or previous is None:
                raise AppError(f"{name} has no previous version")
            backup = self.app_dir(name) / "backups" / str(current.seq)
            if not backup.is_dir():
                raise AppError(f"the data backup of deploy #{current.seq} is missing")
            await self._stop(name)
            data = self.data_dir(name)
            await asyncio.to_thread(shutil.rmtree, data)
            backup.replace(data)
            record.deployments.pop()
            shutil.rmtree(self.version_dir(name, current.seq), ignore_errors=True)
            self.errors.pop(name, None)
            self._save()
            self._log(name, f"rolled back from {current.version} to {previous.version}")
        self.changed()
        return self.view(name)

    async def _pull_runtime(self, name: str) -> None:
        if await asyncio.to_thread(runtime.exists, RUNTIME_IMAGE):
            return
        self._log(name, f"pulling {RUNTIME_IMAGE}")
        with self.log_path(name).open("ab") as out:
            pull = await asyncio.create_subprocess_exec(
                *runtime.pull_argv(RUNTIME_IMAGE), stdout=out, stderr=out
            )
            try:
                code = await asyncio.wait_for(pull.wait(), PULL_TIMEOUT)
            except TimeoutError:
                pull.kill()
                raise DeployError(f"pulling {RUNTIME_IMAGE} took too long") from None
        if code:
            raise DeployError(f"cannot pull {RUNTIME_IMAGE}; its log says why")

    async def _run_tests(self, name: str, manifest: AppManifest, code: Path, data: Path) -> None:
        """`bun test` on the backend's directory, with an empty data folder, in the sandbox."""
        data.mkdir(parents=True)
        run = self.run_root / f"{name}-test"
        run.mkdir(parents=True, exist_ok=True)
        sandbox_process.give_dev_agent(data, run)
        spec = compose.app_sandbox_spec(
            name=f"handler-app-{name}-test-{secrets.token_hex(3)}",
            manifest=manifest,
            code=str(code),
            data=str(data),
            run=str(run),
            test=True,
        )
        self._log(name, "running the backend's tests")
        if await asyncio.to_thread(runtime.missing_proxy, spec):
            raise DeployError(str(missing(NETWORK_FILTER)))
        try:
            proc = await sandbox_process.start_piped(spec, line_limit=LINE_LIMIT)
            pump = asyncio.get_running_loop().create_task(self._pump(name, proc, {}))
            try:
                code_ = await asyncio.wait_for(proc.wait(), TEST_TIMEOUT)
            except TimeoutError:
                await sandbox_process.stop(proc)
                raise DeployError(f"the tests took more than {TEST_TIMEOUT:.0f} s") from None
            except BaseException:
                await sandbox_process.stop(proc)
                raise
            finally:
                await pump
        finally:
            shutil.rmtree(run, ignore_errors=True)
            shutil.rmtree(data, ignore_errors=True)
        if code_:
            raise DeployError(f"the tests failed (exit {code_}); its log says why")

    # ── backends (H.5) ──────────────────────────────────────────────────

    async def ensure_running(self, name: str) -> Backend:
        record = self.get(name)
        backend = self.live.get(name)
        if backend is None:
            async with self.lock(name):  # a deploy or rollback in progress finishes first
                backend = self.live.get(name)
                if backend is None:
                    current = record.current
                    if current is None:
                        raise AppError(f"{name} is not deployed")
                    manifest = self.manifest(name, current.seq)
                    code = self.version_dir(name, current.seq)
                    data = self.data_dir(name)
                    data.mkdir(parents=True, exist_ok=True)
                    try:
                        app_secrets = self.secrets_for(name, manifest)
                        backend = await self._start(
                            name, current.seq, manifest, code, data, app_secrets=app_secrets
                        )
                    except AppError as e:
                        self.errors[name] = str(e)
                        self._tell()
                        raise
                    self.errors.pop(name, None)
                    self.live[name] = backend
                    self._tell()
                    asyncio.get_running_loop().create_task(self._watch(name, backend))
        backend.last_used = time.monotonic()
        record.last_used_at = datetime.now(UTC)
        return backend

    async def _start(
        self,
        name: str,
        seq: int,
        manifest: AppManifest,
        code: Path,
        data: Path,
        *,
        app_secrets: dict[str, str],
        check: bool = False,
        files: list[tuple[str, str, bool]] | None = None,
    ) -> Backend:
        """Start the backend and wait until its health check answers 200 (H.3). `check`: a
        deploy's trial run, on a copy of the data (an opened draft's too, with its `files`)."""
        run = self.run_root / name
        run.mkdir(parents=True, exist_ok=True)
        socket = run / "app.sock"
        socket.unlink(missing_ok=True)
        given = self.check_files(name, manifest) if files is None else files
        spec = compose.app_sandbox_spec(
            name=f"handler-app-{name}-{secrets.token_hex(3)}",
            manifest=manifest,
            code=str(code),
            data=str(data),
            run=str(run),
            secrets=app_secrets,
            files=given,
        )
        api: AppApi | None = None
        if manifest.handler_api:  # a trial run's notifications go nowhere, starts nothing
            smd = app_smd.AppSmd(code / app_smd.SCHEMAS_DIR, given) if manifest.schemas else None
            handle = self.with_smd(smd, self.trial if check else self.from_app)
            api = AppApi(name, run / "handler.sock", handle)
            await api.start()
        sandbox_process.give_dev_agent(data, run)  # with its socket
        version = f"{manifest.version} (#{seq})"
        where = " on a copy of the data" if check else ""
        self._log(name, f"{'trying' if check else 'starting'} {version}{where}")
        self.starting.add(name)
        self._tell()
        client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(socket)),
            base_url="http://app",
            timeout=httpx.Timeout(60.0, connect=5.0),
        )
        backend: Backend | None = None
        try:
            if await asyncio.to_thread(runtime.missing_proxy, spec):
                raise AppError(str(missing(NETWORK_FILTER)))
            proc = await sandbox_process.start_piped(spec, line_limit=LINE_LIMIT)
            pump = asyncio.get_running_loop().create_task(self._pump(name, proc, app_secrets))
            backend = Backend(proc, client, pump, api)
            await healthy(proc, client, socket)
            return backend
        except BaseException:
            if backend is not None:
                await self._stop_backend(backend)
            else:
                await client.aclose()
                if api is not None:
                    await api.close()
            raise
        finally:
            self.starting.discard(name)
            self._tell()

    async def _watch(self, name: str, backend: Backend) -> None:
        code = await backend.process.wait()
        if self.live.get(name) is backend:  # exited by itself, not stopped by us
            self.live.pop(name)
            self.errors[name] = f"the backend exited ({code}); its log says why"
            self._tell()
            self._log(name, f"backend exited ({code})")
            await self._close(backend)

    async def _stop_backend(self, backend: Backend) -> None:
        await sandbox_process.stop(backend.process)
        await self._close(backend)

    @staticmethod
    async def _close(backend: Backend) -> None:
        await backend.client.aclose()
        if backend.api is not None:
            await backend.api.close()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(backend.pump), 5.0)

    async def _pump(
        self, name: str, proc: asyncio.subprocess.Process, hide: dict[str, str]
    ) -> None:
        """Copy a sandbox's output to the app's log, secret values replaced by their names
        (invariant 4: a backend printing its API key does not put it in the log)."""
        assert proc.stdout is not None
        values = [(v.encode(), f"[secret {n}]".encode()) for n, v in hide.items() if len(v) >= 4]
        with self.log_path(name).open("ab") as out:
            while True:
                try:
                    line = await proc.stdout.readline()
                except ValueError:  # longer than LINE_LIMIT: what is buffered
                    line = await proc.stdout.read(LINE_LIMIT)
                if not line:
                    return
                for value, label in values:
                    line = line.replace(value, label)
                out.write(line)
                out.flush()

    async def _stop(self, name: str) -> None:
        backend = self.live.pop(name, None)
        if backend is not None:
            self._tell()
            self._log(name, "stopping the backend")
            await self._stop_backend(backend)

    async def stop(self, name: str) -> App:
        self.get(name)
        async with self.lock(name):
            await self._stop(name)
            self.errors.pop(name, None)
        return self.view(name)

    def touch(self, name: str) -> None:
        if backend := self.live.get(name):
            backend.last_used = time.monotonic()

    # ── a draft opened (H.16) ───────────────────────────────────────────

    async def open_draft(self, session: str, folder: Path, app: str | None) -> DraftPreview:
        """A session's draft of an app's code started at its own address, `<app>--draft`, as a
        deploy's trial is: on copies taken now (its data; each folder given to it when small,
        else that folder read-only; nothing for a new app), its calls to Handler going nowhere.
        Opened again, it starts again on new copies."""
        manifest = read_manifest(folder)
        name = manifest.name
        if app is not None and name != app:
            raise AppError(f"the draft's {MANIFEST_FILE} names another app: {name}")
        if app is None and name in self.records:
            raise AppError(f"{name} is an app you have: change it from its page")
        preview = name + DRAFT
        async with self.lock(preview):
            await self._close_draft(name)
            root = self.app_dir(preview)
            shutil.rmtree(root, ignore_errors=True)
            await asyncio.to_thread(snapshot, folder, root / "code", manifest)
            copies, files = await asyncio.to_thread(self._draft_copies, name, manifest, root)
            app_secrets = self.secrets_for(name, manifest) if name in self.records else {}
            await self._pull_runtime(name)
            backend = await self._start(
                preview, 0, manifest, root / "code", root / "data",
                app_secrets=app_secrets, check=True, files=files,
            )  # fmt: skip
            self.previews[name] = Preview(session, backend, copies)
        return DraftPreview(app=name, url=self.preview_link(name), copies=copies)

    def _draft_copies(
        self, name: str, manifest: AppManifest, root: Path
    ) -> tuple[list[DraftCopy], list[tuple[str, str, bool]]]:
        record = self.records.get(name)
        data = root / "data"
        if record is not None and self.data_dir(name).is_dir():
            copy_data(self.data_dir(name), data)
            size = folder_size(data)
            copies = [DraftCopy(what="its data", how="copy", size=size)]
        else:
            data.mkdir(parents=True)
            copies = [DraftCopy(what="its data", how="empty")]
        files: list[tuple[str, str, bool]] = []
        for need, wanted in manifest.needs.files.items():
            given = (record.files if record else {}).get(need)
            path = os.path.realpath(given) if given else None
            copy = root / "files" / need
            if path is None or not os.path.isdir(path):
                copy.mkdir(parents=True)
                copies.append(DraftCopy(what=f"folder {need}", how="empty"))
                files.append((need, str(copy), True))
            elif (size := folder_size(Path(path))) <= SMALL_FOLDER:
                shutil.copytree(path, copy, symlinks=True)
                copies.append(DraftCopy(what=f"folder {need}", path=path, how="copy", size=size))
                files.append((need, str(copy), wanted.mode == "rw"))
            else:
                copies.append(DraftCopy(what=f"folder {need}", path=path, how="read-only"))
                files.append((need, path, False))
        sandbox_process.give_dev_agent(
            data, *(Path(p) for _, p, rw in files if rw and is_within(p, str(root)))
        )
        return copies, files

    def preview_link(self, name: str) -> str:
        """A one-time link that opens the app's draft (H.4)."""
        now = time.monotonic()
        self.links = {c: v for c, v in self.links.items() if v[2] > now}
        code = secrets.token_urlsafe(24)
        self.links[code] = (name + DRAFT, "/", now + LINK_TTL)
        return f"{self.origin(name + DRAFT)}/_handler/login?code={code}"

    async def _session_deleted(self, session: str) -> None:
        """A draft's session deleted (thrown away, used, or with its agent): its opened copy too."""
        if (opened := self.preview_of(session)) is not None:
            await self.close_draft(opened)

    def preview_of(self, session: str) -> str | None:
        """The app whose draft that session has open."""
        return next((n for n, p in self.previews.items() if p.session == session), None)

    async def close_draft(self, name: str, only: Preview | None = None) -> None:
        """Its opened draft stopped and its copies removed (used, thrown away, idle): `only`
        that one (the reaper's), not one opened again since."""
        async with self.lock(name + DRAFT):
            if only is None or self.previews.get(name) is only:
                await self._close_draft(name)

    async def _close_draft(self, name: str) -> None:
        preview = self.previews.pop(name, None)
        if preview is not None:
            await self._stop_backend(preview.backend)
        shutil.rmtree(self.app_dir(name + DRAFT), ignore_errors=True)

    # ── what the person gives its needs (H.2, H.9, H.11) ───────────────

    def declared(self, name: str) -> list[tuple[AppManifest, Path]]:
        """The source folder's manifest (when it is this app's) and the installed version's,
        each with the folder its definitions are in: the needs a person gives, before a deploy
        and after."""
        record = self.get(name)
        found: list[tuple[AppManifest, Path]] = []
        with contextlib.suppress(AppError):
            source = read_manifest(self.source(name))
            if source.name == name:
                found.append((source, self.source(name)))
        if record.current:
            with contextlib.suppress(AppError):
                seq = record.current.seq
                found.append((self.manifest(name, seq), self.version_dir(name, seq)))
        return found

    def check_folder(self, path: str) -> str:
        """A folder (or file) a person gives an app, resolved: in the home, not the home, not
        handler's own folders nor keys (H.9). It may not exist yet."""
        home = os.path.realpath(Path.home())
        private = [os.path.realpath(Path(home) / p) for p in PRIVATE_HOME]
        private += [
            os.path.realpath(d)
            for d in (self.settings.config_dir, self.settings.state_dir, self.settings.data_dir)
        ]
        resolved = os.path.realpath(path)
        if not is_within(resolved, home) or resolved == home:
            raise AppError(f"{path}: only files and folders inside your home")
        if any(is_within(resolved, p) or is_within(p, resolved) for p in private):
            raise AppError(f"{path}: handler's own files and keys are never given")
        if "," in resolved:
            raise AppError(f"{path}: a path with a ','")
        return resolved

    async def set_file(self, name: str, need: str, path: str, create: bool) -> App:
        """Give a files need its folder: made when `create` (else it must exist), the need's
        `init` files copied in when it has none of those names. A running backend is stopped:
        it starts again with that folder."""
        found = [(m, d) for m, d in self.declared(name) if need in m.needs.files]
        if not found:
            raise AppError(f"{name} needs no folder {need}")
        resolved = self.check_folder(path)
        if not os.path.exists(resolved):
            if not create:
                raise AppError(f"{path} does not exist")
            os.makedirs(resolved)
        manifest, folder = found[0]
        init = manifest.needs.files[need].init
        if bad := next((b for rel in init if (b := link_out(folder, folder / rel))), None):
            raise AppError(f"files.{need}.init: {bad} is a link to outside the app")
        if os.path.isdir(resolved):
            for rel in init:
                target = Path(resolved) / Path(rel).name
                if (folder / rel).is_file() and not target.exists():
                    shutil.copy2(folder / rel, target)
        record = self.get(name)
        record.files[need] = resolved
        self._save()
        self.changed()  # a folder given rw: its history's first state (D.5)
        async with self.lock(name):
            await self._stop(name)
        return self.view(name)

    # ── its jobs, run by its Who works (H.1, H.2) ───────────────────────

    def set_who_works(self, name: str, who: WhoWorks) -> App:
        """Who runs its jobs (a job's own aside): a program on an account or provider, or the
        model alone on a provider, that can run here (rule app-job.runs-as-its-who-works)."""
        record = self.get(name)
        try:
            app_jobs.runs_as(self.settings, who)
        except AppRunError as e:
            raise AppError(str(e)) from None
        record.who_works = who
        self._save()
        return self.view(name)

    def set_job_who_works(self, name: str, job: str, who: WhoWorks | None) -> App:
        """Who runs that job, instead of the app's Who works; None: the app's again. One that
        cannot run it (the model alone for a job reaching folders, schemas or hosts) is refused
        (rule app-job.runs-as-its-who-works)."""
        record = self.get(name)
        declared = self.declared_jobs(name)
        if job not in declared:
            raise AppError(f"{name} has no job {job}")
        if who is None:
            record.jobs_who_works.pop(job, None)
        else:
            if why := app_jobs.cannot_run(declared[job], who):
                raise AppError(f"job {job}: {why}")
            try:
                app_jobs.runs_as(self.settings, who)
            except AppRunError as e:
                raise AppError(str(e)) from None
            record.jobs_who_works[job] = who
        self._save()
        return self.view(name)

    def declared_jobs(self, name: str) -> dict[str, AppManifestJob]:
        """The jobs of the version a deploy would install, then the installed one's (as its
        needs, `needs_view`)."""
        found: dict[str, AppManifestJob] = {}
        for manifest, _ in self.declared(name):
            for job_name, job in manifest.jobs.items():
                found.setdefault(job_name, job)
        return found

    def job_problems(self, name: str, job_name: str) -> list[str]:
        """Why an automation cannot run that job of that app (I.1): no such app or job (its
        source's or its installed version's), nobody to run it, one who cannot (rule
        app-job.runs-as-its-who-works); the terms of who runs it are the automation's to read
        (`job_runs_as`)."""
        if name not in self.records:
            return [f"run.app: no app named {name}"]
        job = self.declared_jobs(name).get(job_name)
        if job is None:
            return [f"run.job: {name} has no job {job_name}"]
        record = self.get(name)
        who = record.jobs_who_works.get(job_name) or record.who_works
        if why := app_jobs.cannot_run(job, who):
            return [f"run.job: {why}"]
        try:
            self.job_runs_as(name, job_name)
        except AppRunError as e:
            return [f"run.job: {e}"]
        return []

    def job_runs_as(self, name: str, job_name: str) -> RunsAs:
        """The model that job runs with now: its own Who works, else the app's (AppRunError when
        none, or when it cannot run here)."""
        record = self.get(name)
        who = record.jobs_who_works.get(job_name) or record.who_works
        if who is None:
            raise AppRunError(409, "nobody is chosen to run it")
        return app_jobs.runs_as(self.settings, who)

    def jobs_view(self, name: str) -> list[AppJob]:
        """Its jobs, each with what it reaches, who runs it (its own, else the app's) and why
        that one cannot run it now."""
        record = self.get(name)
        out: list[AppJob] = []
        for job_name, job in self.declared_jobs(name).items():
            own = record.jobs_who_works.get(job_name)
            who = own or record.who_works
            problem = app_jobs.cannot_run(job, who)
            if problem is None:
                assert who is not None  # else a reason above
                try:
                    app_jobs.runs_as(self.settings, who)
                except AppRunError as e:
                    problem = str(e)
            can_do = AppJobCanDo(
                files=job.files, works_in=job.works_in, schemas=job.schemas, egress=job.egress
            )
            out.append(
                AppJob(
                    name=job_name,
                    description=job.description,
                    can_do=can_do,
                    who_works=who,
                    own=own is not None,
                    problem=problem,
                )
            )
        return out

    def job_run(
        self, name: str, job_name: str, fields: dict[str, Any], started_by: AppRunStartedBy
    ) -> AppRun:
        """A run of a job of the installed version, by its Who works, in the folders given to
        the app (H.1, H.11): AppRunError 403 a job it does not declare, 409 nobody chosen to run
        it, one that cannot (rule app-job.runs-as-its-who-works), a folder not given or that
        cannot be mounted as it says, 400 an input its form refuses."""
        record = self.get(name)
        assert record.current is not None
        seq = record.current.seq
        job = self.manifest(name, seq).jobs.get(job_name)
        if job is None:
            raise AppRunError(403, f"{name} has no job {job_name}: not in its [jobs]")
        who = record.jobs_who_works.get(job_name) or record.who_works
        if why := app_jobs.cannot_run(job, who):
            raise AppRunError(409, f"job {job_name}: {why}")
        assert who is not None  # else a reason above
        runs = app_jobs.runs_as(self.settings, who)
        given: dict[str, str] = {}
        for need in job.files:
            path = record.files.get(need)
            if path is None:
                raise AppRunError(409, f"folder {need} not given (Apps page)")
            try:
                given[need] = self.check_folder(path)
            except AppError as e:
                raise AppRunError(409, f"folder {need}: {e}") from None
            if not os.path.exists(given[need]):
                raise AppRunError(409, f"folder {need}: {path} does not exist")
        place = app_jobs.place(job, given)
        instructions = self.version_dir(name, seq) / JOB_INSTRUCTIONS_DIR / f"{job_name}.md"
        stand_in = app_jobs.stand_in(name, job_name, job, runs, instructions.read_text())
        run = self.runs.start_job(
            name,
            job_name,
            stand_in=stand_in,
            runs=runs,
            place=place,
            fields=fields,
            started_by=started_by,
            then=job.then,
        )
        self._log(name, f"run {run.id} of job {job_name} started")
        return run

    def check_files(self, name: str, manifest: AppManifest) -> list[tuple[str, str, bool]]:
        """The folders given for the manifest's files needs, checked now: (need, path, writable)."""
        given = self.get(name).files
        out: list[tuple[str, str, bool]] = []
        for need, wanted in manifest.needs.files.items():
            if need not in given:
                raise DeployError(f"folder {need} not given (Apps page, or handler app folder)")
            try:
                path = self.check_folder(given[need])
            except AppError as e:
                raise DeployError(f"folder {need}: {e}") from None
            if not os.path.exists(path):
                raise DeployError(f"folder {need}: {given[need]} does not exist")
            if other := next((n for n, p, _ in out if p == path), None):
                raise DeployError(f"folder {need}: {path} is also given for {other}")
            git = os.path.join(path, ".git")
            if wanted.mode == "rw" and os.path.lexists(git) and not compose.real_folder(git):
                raise DeployError(
                    f"folder {need}: its .git is not a folder (a link or a worktree's file),"
                    " so it cannot be kept read-only: give another folder"
                )
            out.append((need, path, wanted.mode == "rw"))
        return out

    def needs_view(self, name: str) -> list[AppFileNeed]:
        """The files needs of the version a deploy would install (the source's; the installed
        one's when the source cannot be read), with what was given. A need only the installed
        version has is not asked for: the next deploy drops it (its binding stays, for a
        rollback)."""
        record = self.get(name)
        files: dict[str, AppFileNeed] = {}
        for manifest, _ in self.declared(name)[:1]:
            for need, f in manifest.needs.files.items():
                files.setdefault(
                    need,
                    AppFileNeed(
                        name=need,
                        description=f.description,
                        mode=f.mode,
                        path=(path := record.files.get(need)),
                        file=path is not None and Path(path).is_file(),
                    ),
                )
        return list(files.values())

    # ── its actions, what the person can ask it (H.12) ──────────────────

    def check_actions(self, manifest: AppManifest) -> None:
        """A route's form is a form's JSON Schema (D.18); a job's action takes its job's form and
        result, checked with its job (`check_jobs`)."""
        for name, action in manifest.actions.items():
            if action.fields is not None:
                try:
                    interfaces.check(AgentInterface(fields=action.fields))
                except interfaces.InterfaceError as e:
                    raise DeployError(f"actions.{name}.{e}") from None

    def actions_view(self, name: str) -> list[AppAction]:
        """The actions of the installed version (before a first deploy, its source's), each with
        its form: the route's or its job's."""
        record = self.get(name)
        declared = self.declared(name)
        found = declared[-1:] if record.current else declared[:1]
        out: list[AppAction] = []
        for manifest, _ in found:
            for action_name, action in manifest.actions.items():
                fields = action.fields
                if action.job is not None:
                    fields = manifest.jobs[action.job].fields
                by = "code" if action.route else "job"
                out.append(
                    AppAction(
                        name=action_name,
                        description=action.description,
                        examples=action.examples,
                        by=by,
                        fields=fields,
                        in_ask=action_name not in record.not_in_ask,
                    )
                )
        return out

    def askable(self) -> bool:
        """An installed app offers an action to Ask (cheap: read while the host decides to poll)."""
        for record in self.records.values():
            if record.current:
                with contextlib.suppress(AppError):
                    actions = self.manifest(record.name, record.current.seq).actions
                    if set(actions) - set(record.not_in_ask):
                        return True
        return False

    def set_ask(self, name: str, not_in_ask: list[str]) -> App:
        """The actions you take out of Ask (D.24), the others offered: one out is still tried on
        its page and opened by a nudge. An action the app does not have: InputError."""
        record = self.get(name)
        unknown = set(not_in_ask) - {a.name for a in self.actions_view(name)}
        if unknown:
            raise InputError(f"{name} has no action {', '.join(sorted(unknown))}")
        record.not_in_ask = sorted(set(not_in_ask))
        self._save()
        self.changed()  # the host may poll for the owner's phone, or stop (D.24)
        return self.view(name)

    async def act(
        self,
        name: str,
        action_name: str,
        fields: dict[str, Any],
        nudge: str | None = None,
        *,
        asked: bool = False,
    ) -> ActionRun:
        """One action of the installed version, the owner's: its code answers it now; its job's
        run is answered with its result if it ends within ACTION_WAIT, else as running (read it again with `action_run`; its end reaches the inbox, H.11). From an open nudge pointing at
        it (H.17): the nudge is done once it succeeds, its code told which (NUDGE_HEADER).
        `asked`: Ask's pick (D.24); otherwise its form was filled by the person (its run started
        "via" a nudge, or "try")."""
        record = self.get(name)
        if record.current is None:
            raise AppError(f"{name} is not installed")
        manifest = self.manifest(name, record.current.seq)
        action = manifest.actions.get(action_name)
        if action is None:
            raise AppNotFoundError(f"{name} has no action {action_name}")
        answered = self.nudge_of(name, nudge, action_name) if nudge is not None else None
        via = "nudge" if nudge is not None else "ask" if asked else "try"
        if action.route is not None:
            if action.fields is not None and (found := interfaces.errors(action.fields, fields)):
                raise InputError(f"input invalid: {'; '.join(found)}")
            done = await self._act_by_code(
                name, action_name, action.route, fields, answered, via=via
            )
            if nudge is not None:
                self.nudges.action_ended(nudge, done.result.status if done.result else "failed")
            return done
        try:
            started_by = StartedByAction(action=action_name, via=via)
            assert action.job is not None
            run = self.job_run(name, action.job, fields, started_by)
        except AppRunError as e:
            raise (InputError if e.status == 400 else AppError)(str(e)) from None
        self._log(name, f"action {action_name}: run {run.id} of {action.job} started")
        if nudge is not None:
            self.nudges.running(nudge, run.id)
        deadline = time.monotonic() + ACTION_WAIT
        view = self.action_run(name, action_name, run.id)
        while view.state == "running" and time.monotonic() < deadline:
            await asyncio.sleep(ACTION_POLL)
            view = self.action_run(name, action_name, run.id)
        return view

    def action_run(self, name: str, action_name: str, run_id: str) -> ActionRun:
        """A job's action, as its run is now: its result's `status` and `summary`, the whole
        result as `data`."""
        self.get(name)
        try:
            run = self.runs.get(name, run_id)
        except AppRunError as e:
            raise AppNotFoundError(str(e)) from None
        base: dict[str, Any] = {"app": name, "action": action_name, "run_id": run.id}
        base["session_id"] = run.session_id
        if run.state in ("waiting", "running"):
            return ActionRun(**base, state="running")
        for m in self.nudges.open(name):  # a nudge it was done from (H.17)
            if m.nudge is not None and m.nudge.run_id == run.id:
                self.nudges.action_ended(m.id, self.run_state(name, run.id))
        if run.state == "succeeded" and isinstance(run.result, dict):
            told = told_result(run.result)
            summary = told["summary"] or "Done."
            result = ActionResult(status=told["status"], summary=summary[:500], data=run.result)
            return ActionRun(**base, state="succeeded", result=result)
        return ActionRun(**base, state="failed", error=run.error or run.state)

    def run_state(self, name: str, run_id: str) -> str:
        """How an action's job run went, for its nudge (H.17): "running", its result's status,
        or "failed"."""
        try:
            run = self.runs.get(name, run_id)
        except AppRunError:
            return "failed"
        if run.state in ("waiting", "running"):
            return "running"
        if run.state == "succeeded" and isinstance(run.result, dict):
            return str(told_result(run.result)["status"])
        return "failed"

    # ── its nudges, what it asks a person to do (H.17) ──────────────────

    def nudges_view(self, name: str) -> list[AppNudge]:
        """The nudges of the installed version (before a first deploy, its source's), each with
        how often it alerts you and when handlerd sends it (the app's, yours, the next slot)."""
        record = self.get(name)
        declared = self.declared(name)
        found = declared[-1:] if record.current else declared[:1]
        now = datetime.now(UTC)
        views = []
        for manifest, _ in found:
            for n, d in manifest.nudges.items():
                own = self.nudges.own_when(name, n) if d.when is not None else None
                when = own or d.when
                views.append(
                    AppNudge(
                        name=n,
                        description=d.description,
                        action=d.action,
                        open=d.open,
                        remind=d.remind,
                        if_ignored=d.if_ignored,
                        setting=self.nudges.setting(name, n),
                        when=d.when,
                        own_when=own,
                        next_at=self.nudges.next_at(name, n, when, now)
                        if when is not None and record.current
                        else None,
                        prepared=d.prepare is not None,
                        off=self.nudges.is_off(name, n),
                    )
                )
        return views

    def set_nudge_setting(self, name: str, nudge: str, setting: NudgeSetting) -> App:
        if nudge not in {n.name for n in self.nudges_view(name)}:
            raise AppNotFoundError(f"{name} has no nudge {nudge}")
        self.nudges.set_setting(name, nudge, setting)
        return self.view(name)

    def set_nudge_off(self, name: str, nudge: str, off: bool) -> App:
        """That nudge off (none sent, its `prepare` not called, its open ones reminding no more)
        or on again, from its next slot: none missed while off is sent."""
        if nudge not in {n.name for n in self.nudges_view(name)}:
            raise AppNotFoundError(f"{name} has no nudge {nudge}")
        self.nudges.set_off(name, nudge, off)
        self._log(name, f"nudge {nudge}: turned {'off' if off else 'on'} by you")
        return self.view(name)

    def set_nudge_when(self, name: str, nudge: str, when: Schedule | None) -> App:
        """When handlerd sends that nudge: yours replacing the app's, or the app's again (None).
        Only a nudge the app gives a `when`: the others its code sends."""
        found = next((n for n in self.nudges_view(name) if n.name == nudge), None)
        if found is None:
            raise AppNotFoundError(f"{name} has no nudge {nudge}")
        if found.when is None:
            raise AppError(f"{nudge} is sent by {name}'s code: it has no time to change")
        self.nudges.set_when(name, nudge, when)
        return self.view(name)

    # ── its nudges sent at their `when` (H.17) ──────────────────────────

    def send_due_nudges(self, now: datetime | None = None) -> None:
        """Each installed app's nudge whose slot came (its `when`, or yours): its slot taken now,
        its open ones expired with `until = "next"` (whatever its `prepare` answers: the slot
        came), then sent (after its `prepare`) in the background. A slot missed while handlerd
        was off: the latest one, once."""
        now = now or datetime.now(UTC)
        for name, record in list(self.records.items()):
            if record.current is None:
                continue
            for nudge, declared in self.manifest(name, record.current.seq).nudges.items():
                if declared.when is None:
                    continue
                when = self.nudges.own_when(name, nudge) or declared.when
                slot = self.nudges.due(name, nudge, when, now)  # taken even while off
                if slot is not None and not self.nudges.is_off(name, nudge):
                    if declared.until == "next" and (expired := self.nudges.expire(name, nudge)):
                        self._log(name, f"nudge {nudge}: {len(expired)} expired, its next slot")
                    task = asyncio.get_running_loop().create_task(
                        self.send_at_slot(name, nudge, declared, slot_key(when, slot))
                    )
                    self.sending.add(task)
                    task.add_done_callback(self.sending.discard)

    async def send_at_slot(
        self, name: str, nudge: str, declared: AppManifestNudge, key: str
    ) -> list[InboxMessage]:
        """One slot of a scheduled nudge: without `prepare`, its `description` as title, the slot
        as key; with it, what its route answers (none: 204). To the owner. A failure (no answer,
        a bad one) is told in the app's log and the owner's inbox; never retried."""
        try:
            if declared.prepare is None:
                prepared = [PreparedNudge(title=declared.description)]
            else:
                prepared = await self.prepare_nudge(name, nudge, declared.prepare)
            form = None
            if declared.action is not None:
                form = next(
                    (a.fields for a in self.actions_view(name) if a.name == declared.action), None
                )
            sent = []
            for p in prepared:
                payload = p.model_dump(exclude_none=True) | {"key": p.key or key}
                sent.append(self.nudges.send(name, nudge, declared, payload, persons=[], form=form))
        except (AppError, NudgeError) as e:
            self._log(name, f"nudge {nudge} at {key}: not sent: {e}")
            self.inbox.add(
                source="app",
                name=name,
                person="owner",
                title=f"{declared.description}: not sent",
                summary=f"Its nudge {nudge} for {key} was not sent: {e}",
                status="failed",
                app=name,
            )
            return []
        self._log(name, f"nudge {nudge} at {key}: sent {len(sent)}")
        return sent

    async def prepare_nudge(self, name: str, nudge: str, route: str) -> list[PreparedNudge]:
        """Its `prepare` route called as the owner, with no start token (it cannot start a run):
        the nudges it answers, of this name, each with its own key when several; none for 204.
        AppError when it cannot be called or answers something else."""
        method, path = route.split(" ", 1)
        backend = await self.ensure_running(name)
        try:
            r = await backend.client.request(
                method, path, headers={PERSON_HEADER: "owner"}, timeout=CALL_TIMEOUT
            )
        except httpx.HTTPError as e:
            raise AppError(f"{route}: {str(e) or type(e).__name__}") from None
        self.touch(name)
        self._log(name, f"nudge {nudge}: {route}: {r.status_code}")
        if r.status_code == 204:
            return []
        if not r.is_success:
            raise AppError(f"{route}: {_answer_error(r)}")
        try:
            answer = PREPARED.validate_json(r.content)
        except ValidationError as e:
            where = ".".join(str(x) for x in e.errors()[0]["loc"]) or "(top)"
            raise AppError(f"{route} answered no nudge: {where}: {e.errors()[0]['msg']}") from None
        if not isinstance(answer, list):
            return [answer]
        keys = [p.key for p in answer]
        if len(answer) > MAX_PREPARED or None in keys or len(set(keys)) < len(keys):
            raise AppError(
                f"{route} answered several nudges: at most {MAX_PREPARED}, each with its own key"
            )
        return answer

    async def call_then(self, name: str, route: str, payload: dict[str, Any]) -> str | None:
        """A job's `then` route called once a run of it ended (H.11, rule
        app-job.then-called-once): as the owner, with no start token (it cannot start a run: no
        loop), the backend started if needed, as a nudge's `prepare` is; its answer's body
        ignored (2xx: done). None when it was done, else why it failed (no backend, no answer,
        an error), said on the run, never retried."""
        method, path = route.split(" ", 1)
        try:
            backend = await self.ensure_running(name)
            r = await backend.client.request(
                method, path, headers={PERSON_HEADER: "owner"}, json=payload, timeout=CALL_TIMEOUT
            )
        except AppError as e:
            return str(e)
        except httpx.HTTPError as e:
            return str(e) or type(e).__name__
        self.touch(name)
        self._log(name, f"run {payload['runId']}: then {route}: {r.status_code}")
        return None if r.is_success else _answer_error(r)

    def nudge_of(self, name: str, message_id: str, action: str) -> InboxMessage:
        """The open nudge an action is done from: of this app, pointing at this action."""
        try:
            m = self.nudges.get(message_id, name)
        except NudgeError as e:
            raise (AppNotFoundError if e.status == 404 else AppError)(str(e)) from None
        assert m.nudge is not None
        if m.nudge.action != action:
            raise AppError(f"this nudge opens {m.nudge.action or 'a page'}, not {action}")
        return m

    def nudge_link(self, message_id: str) -> str:
        """A one-time link to the page an open nudge opens."""
        try:
            m = self.nudges.get(message_id)
        except NudgeError as e:
            raise (AppNotFoundError if e.status == 404 else AppError)(str(e)) from None
        assert m.nudge is not None and m.app is not None
        if m.nudge.open is None:
            raise AppError("this nudge opens an action's form, not a page")
        return self.open_link(m.app, m.nudge.open)

    async def nudge_call(
        self, name: str, method: str, path: str, payload: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        """`POST /nudge`, `POST /nudge/{id}/done`, `DELETE /nudge/{id}` from its backend; or
        `POST /nudge/done`, `DELETE /nudge` with `{name, key}`: the open ones of that name and key
        (whoever they went to), `{ids}` those ended, none an empty list."""
        record = self.get(name)
        assert record.current is not None
        manifest = self.manifest(name, record.current.seq)
        parts = path.split("/")[2:]  # "/nudge/abc/done" → ["abc", "done"]
        try:
            if method == "POST" and not parts:
                return self.send_nudge(name, manifest, payload or {}, record.persons)
            if (method, parts) in (("POST", ["done"]), ("DELETE", [])):
                ended = self.nudges.keyed(name, payload or {}, list(manifest.nudges))
                for m in ended:
                    assert m.nudge is not None
                    if method == "POST":
                        self.nudges.end(m.id, "done")
                        self._log(name, f"nudge {m.id} ({m.nudge.key}): done, said the app")
                    else:
                        self.nudges.withdraw(name, m.id)
                        self._log(name, f"nudge {m.id} ({m.nudge.key}): withdrawn")
                return 200, {"ids": [m.id for m in ended]}
            if method == "POST" and len(parts) == 2 and parts[1] == "done":
                self.nudges.get(parts[0], name)
                self.nudges.end(parts[0], "done")
                self._log(name, f"nudge {parts[0]}: done, said the app")
                return 200, {}
            if method == "DELETE" and len(parts) == 1:
                self.nudges.withdraw(name, parts[0])
                self._log(name, f"nudge {parts[0]}: withdrawn")
                return 200, {}
        except NudgeError as e:
            return e.status, {"error": str(e)}
        return 404, {
            "error": "POST /nudge, POST /nudge/{id}/done, DELETE /nudge/{id}, "
            "POST /nudge/done {name, key}, DELETE /nudge {name, key}"
        }

    def send_nudge(
        self, name: str, manifest: AppManifest, payload: dict[str, Any], persons: list[str]
    ) -> tuple[int, dict[str, Any]]:
        nudge = payload.get("name")
        declared = manifest.nudges.get(nudge) if isinstance(nudge, str) else None
        if declared is None:
            raise NudgeError(403, f"name: one of its nudges ({', '.join(manifest.nudges)})")
        assert isinstance(nudge, str)
        if self.nudges.is_off(name, nudge):  # the person turned it off: not sent, as a trial's
            self._log(name, f"nudge {nudge}: not sent, turned off by you")
            return 200, {"id": None}
        if not self.rate_ok(name):
            raise NudgeError(429, f"at most {NOTIFY_PER_HOUR} notifications an hour")
        form = None
        if declared.action is not None:
            form = next(
                (a.fields for a in self.actions_view(name) if a.name == declared.action), None
            )
        message = self.nudges.send(name, nudge, declared, payload, persons=persons, form=form)
        self._log(name, f"nudge {nudge} for {message.person}: {message.title}")
        return 200, {"id": message.id}

    def rate_ok(self, name: str) -> bool:
        """Its notifications and nudges sent in the last hour are fewer than NOTIFY_PER_HOUR (its
        reminders are Handler's, not counted); counts this one when it is."""
        now = time.monotonic()
        recent = [t for t in self.sent.get(name, []) if now - t < 3600]
        if len(recent) >= NOTIFY_PER_HOUR:
            self.sent[name] = recent
            return False
        self.sent[name] = [*recent, now]
        return True

    async def _act_by_code(
        self,
        name: str,
        action_name: str,
        route: str,
        fields: dict[str, Any],
        nudge: InboxMessage | None,
        *,
        via: Literal["ask", "nudge", "try"],
    ) -> ActionRun:
        """`POST /api/…` with the fields, as the owner (who may start runs meanwhile, H.11): its
        answer is the ActionResult. The call says where it was asked (`via`, as a job's run's
        `startedBy`); answering a nudge (H.17), which one: its id, and its key when it has one
        (as is: NudgeKey holds only what a header value may)."""
        method, path = route.split(" ", 1)
        backend = await self.ensure_running(name)
        start = self.issue_start(name, "owner")
        headers = {PERSON_HEADER: "owner", START_HEADER: start or "", ACTION_HEADER: action_name}
        headers[VIA_HEADER] = via
        if nudge is not None:
            assert nudge.nudge is not None
            key = nudge.nudge.key
            headers[NUDGE_HEADER] = nudge.id + (f"; key={key}" if key else "")
        try:
            r = await backend.client.request(
                method, path, headers=headers, json=fields, timeout=ACTION_TIMEOUT
            )
        except httpx.HTTPError as e:
            raise AppError(f"{route}: {str(e) or type(e).__name__}") from None
        finally:
            self.end_start(start)
        self.touch(name)
        self._log(name, f"action {action_name}: {route}: {r.status_code}")
        if not r.is_success:
            return ActionRun(app=name, action=action_name, state="failed", error=_answer_error(r))
        try:
            result = ActionResult.model_validate_json(r.content)
        except ValidationError as e:
            where = ".".join(str(x) for x in e.errors()[0]["loc"]) or "(top)"
            why = f"{route} answered no action's result: {where}: {e.errors()[0]['msg']}"
            return ActionRun(app=name, action=action_name, state="failed", error=why)
        return ActionRun(app=name, action=action_name, state="succeeded", result=result)

    # ── what the backend asks handler (H.9, H.11) ───────────────────────

    @staticmethod
    def with_smd(smd: app_smd.AppSmd | None, handle: AppApiHandler) -> AppApiHandler:
        """`/smd/*` answered on the folders that backend was given, a trial's and a draft's
        too (their copies), when its version declares `schemas`; the rest by `handle`."""

        async def answer(
            name: str, method: str, path: str, payload: dict[str, Any] | None
        ) -> tuple[int, dict[str, Any]]:
            if not path.startswith("/smd/"):
                return await handle(name, method, path, payload)
            if smd is None:
                return 403, {"error": "declare the formats it reads in `schemas` in app.toml"}
            return await smd.answer(method, path, payload)

        return answer

    async def trial(
        self, _name: str, method: str, path: str, _payload: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        """A deploy's trial run: its notifications go nowhere, it starts no run."""
        if (method, path) in (("POST", "/notify"), ("POST", "/nudge")):
            return 200, {"id": None}
        return 403, {"error": "a deploy's trial run starts nothing"}

    async def from_app(
        self, name: str, method: str, path: str, payload: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        record = self.records.get(name)
        if record is None or record.current is None:
            return 404, {"error": f"no app named {name}"}
        manifest = self.manifest(name, record.current.seq)
        needs = manifest.needs
        call: Awaitable[tuple[int, dict[str, Any]]] | None = None
        try:
            if urlsplit(path).path == "/history" or path.startswith("/history/"):
                call = self.history_call(record, manifest, method, path)
            elif path == "/nudge" or path.startswith("/nudge/"):
                if not manifest.nudges:
                    raise AppRunError(403, "declare it in [nudges.<name>] in app.toml")
                call = self.nudge_call(name, method, path, payload)
            elif (method, path) == ("POST", "/notify"):
                if not needs.notify:
                    raise AppRunError(403, "add `notify = true` to [needs] in app.toml")
                call = self.notification(name, payload or {})
            elif path == "/runs" or path.startswith("/runs/"):
                if not manifest.jobs:
                    raise AppRunError(403, "declare the jobs it runs in [jobs.<name>]")
                call = self.run_call(name, method, path, payload)
            if call is not None:
                return await call
        except AppRunError as e:
            return e.status, {"error": str(e)}
        return 404, {
            "error": "POST /notify, POST /nudge, POST /runs, GET /runs, GET /runs/{id}, "
            "POST /runs/{id}/cancel, POST /smd/parse, POST /smd/check, POST /smd/write, "
            "GET /history, GET /history/{id}"
        }

    async def history_call(
        self, record: AppRecord, manifest: AppManifest, method: str, path: str
    ) -> tuple[int, dict[str, Any]]:
        """`GET /history?files=<need>`, `GET /history/{id}?files=<need>`: the changes of a
        folder given to one of its own read-write files needs, read only (rule
        `app-sock.history-read-only`): no undo, no other folder."""
        url = urlsplit(path)
        parts = url.path.split("/")[2:]  # "/history/abc" → ["abc"]
        if method != "GET" or len(parts) > 1 or (parts and not parts[0]):
            return 404, {"error": "GET /history?files=<need>, GET /history/{id}?files=<need>"}
        need = (parse_qs(url.query).get("files") or [""])[0]
        wanted = manifest.needs.files.get(need)
        if wanted is None or wanted.mode != "rw":
            raise AppRunError(403, 'files: one of its read-write files needs (mode = "rw")')
        given = record.files.get(need)
        if given is None or self.history is None:
            return 404, {"error": f"no folder given for {need}"}
        folder = os.path.realpath(given)
        history = self.history
        try:
            if parts:
                diff = await asyncio.to_thread(history.commit, folder, parts[0])
                return 200, diff.model_dump(mode="json", by_alias=True, exclude_none=True)
            listed = await asyncio.to_thread(history.history, folder)
            return 200, listed.model_dump(mode="json", by_alias=True, exclude_none=True)
        except ValueError as e:  # no history yet, no such change in it
            return 404, {"error": str(e)}

    async def run_call(
        self,
        name: str,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> tuple[int, dict[str, Any]]:
        parts = path.split("/")[2:]  # "/runs/r_1/cancel" → ["r_1", "cancel"]
        if method == "POST" and not parts:
            try:
                request = AppRunRequest.model_validate(payload or {})
            except ValidationError as e:
                where = ".".join(str(x) for x in e.errors()[0]["loc"])
                return 400, {"error": f"body: {where}: {e.errors()[0]['msg']}"}
            if self.starts.get(request.start) != name:
                raise AppRunError(
                    403, "start: a run starts only while answering a request of the owner's"
                )
            run = self.job_run(name, request.job, request.fields, StartedByCode())
            return 202, run.model_dump(mode="json", by_alias=True, exclude_none=True)
        if method == "GET" and not parts:
            runs = self.runs.recent(name)
            return 200, {
                "runs": [r.model_dump(mode="json", by_alias=True, exclude_none=True) for r in runs]
            }
        if method == "GET" and len(parts) == 1:
            run = self.runs.get(name, parts[0])
        elif method == "POST" and len(parts) == 2 and parts[1] == "cancel":
            run = await self.runs.cancel(name, parts[0])
        else:
            return 404, {"error": "POST /runs, GET /runs, GET /runs/{id}, POST /runs/{id}/cancel"}
        return 200, run.model_dump(mode="json", by_alias=True, exclude_none=True)

    def issue_start(self, name: str, person: str) -> str | None:
        """The START_HEADER of a request to the app (H.11): an owner's only, None otherwise.
        Valid until `end_start`, once the request is answered."""
        if person != "owner":
            return None
        token = secrets.token_urlsafe(24)
        self.starts[token] = name
        return token

    def end_start(self, token: str | None) -> None:
        if token is not None:
            self.starts.pop(token, None)

    async def notification(self, name: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        title, body, person = payload.get("title"), payload.get("body"), payload.get("person")
        if not isinstance(title, str) or not 0 < len(title) <= 120:
            return 400, {"error": "title: 1 to 120 characters"}
        if body is not None and (not isinstance(body, str) or len(body) > 1000):
            return 400, {"error": "body: at most 1000 characters"}
        person = person or "owner"
        record = self.records.get(name)
        if record is None or not isinstance(person, str):
            return 400, {"error": "unknown app or person"}
        if person != "owner" and person not in record.persons:
            return 403, {"error": f"{name} is not shared with {person}"}
        if not self.rate_ok(name):
            return 429, {"error": f"at most {NOTIFY_PER_HOUR} notifications an hour"}
        self._log(name, f"notification for {person}: {title}")  # into the person's inbox (H.9)
        message = self.inbox.add(
            source="app", name=name, person=person, title=title, summary=body, app=name
        )
        return 200, {"id": message.id}

    # ── calls of automations (I.3) ──────────────────────────────────────

    async def call(self, name: str, call: str, automation: str) -> int:
        """`POST /api/…` of the installed version, as the owner: its HTTP status. AppError when it
        cannot be called (not deployed, its backend does not start, no answer)."""
        record = self.get(name)
        if record.current is None:
            raise AppError(f"{name} is not deployed")
        method, path = call.split(" ", 1)
        backend = await self.ensure_running(name)
        headers = {PERSON_HEADER: "owner", "X-HANDLER-Automation": automation}
        try:
            r = await backend.client.request(method, path, headers=headers, timeout=CALL_TIMEOUT)
        except httpx.HTTPError as e:
            raise AppError(f"{call}: {str(e) or type(e).__name__}") from None
        self._log(name, f"automation {automation}: {call}: {r.status_code}")
        return r.status_code

    # ── lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        for leftover in self.root.glob(f"*{DRAFT}") if self.root.is_dir() else []:
            shutil.rmtree(leftover, ignore_errors=True)  # drafts opened before a restart
        self.reaper = asyncio.get_running_loop().create_task(self._reap())
        self.runs.start_watching(list(self.records))
        self.nudges.tick(self.run_state)  # a reminder missed while off: once, now (H.17)
        self.send_due_nudges()  # a slot missed while off: the latest, once, now (H.17)

    async def _reap(self) -> None:
        interval = max(1.0, min(30.0, self.settings.app_idle_timeout / 4))
        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()
            for name, backend in list(self.live.items()):
                idle = now - backend.last_used
                if idle > self.settings.app_idle_timeout and not self.lock(name).locked():
                    async with self.lock(name):
                        if self.live.get(name) is backend:
                            self._log(name, f"idle for {idle:.0f} s")
                            await self._stop(name)
            for name, preview in list(self.previews.items()):
                idle = now - preview.backend.last_used > self.settings.app_idle_timeout
                if idle and not self.lock(name + DRAFT).locked():
                    await self.close_draft(name, only=preview)
            self.nudges.tick(self.run_state)
            self.send_due_nudges()
            with contextlib.suppress(OSError):
                self._save()  # last-used times

    async def close(self) -> None:
        if self.reaper:
            self.reaper.cancel()
        for name in list(self.live):
            await self._stop(name)
        for name in list(self.previews):
            await self.close_draft(name)
        await self.runs.close()
        with contextlib.suppress(OSError):
            self._save()
