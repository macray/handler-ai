"""Apps (contract H, apps design): registry, deploy and rollback, backends
started on demand and stopped when idle. Serving them over HTTP is app_http.py.

    <state>/apps.json                  registry: each app's deployments, the source its code came
                                       from (D.26), and what the person gave its needs
                                       (bindings: a folder's path, an agent's id, by the need's
                                       name, H.2)
    <data>/apps/<name>/versions/<n>/   the code of deploy n (app.toml, backend dir, built UI, the
                                       definitions of the agents it needs)
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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from handler_contracts import (
    ACTION_HEADER,
    HEALTH_PATH,
    MANIFEST_FILE,
    PERSON_HEADER,
    RUNTIME_IMAGE,
    START_HEADER,
    ActionResult,
    ActionRun,
    AgentDefinition,
    AgentInterface,
    AgentOrigin,
    App,
    AppAction,
    AppAgentNeed,
    AppDeployment,
    AppFileNeed,
    AppManifest,
    AppManifestAgentNeed,
    AppRunRequest,
    AppSecret,
    AppSource,
    AppState,
    DraftCopy,
    DraftPreview,
    SharedApp,
    is_within,
)

from . import compose, definitions, files, interfaces, pins, runtime, sandbox_process
from .agents import AgentRecord
from .app_api import AppApi
from .app_runs import AppRunError, AppRuns
from .inbox import Inbox, told_result
from .launcher import NETWORK_FILTER, missing
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
CALL_TIMEOUT = 300.0  # an automation's call (I.3)
ACTION_TIMEOUT = 30.0  # an action done by the app's code answers at once (H.12)
ACTION_WAIT = 20.0  # an action done by its agent: answered with its result if it ends by then
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
    agents: dict[str, str] = field(default_factory=dict)  # need → the agent given, its id
    askable: bool = True  # its actions are offered to Ask (D.24)

    @property
    def current(self) -> Deployment | None:
        return self.deployments[-1] if self.deployments else None

    @property
    def previous(self) -> Deployment | None:
        return self.deployments[-2] if len(self.deployments) > 1 else None


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
        return AppManifest.from_toml(text)
    except ValidationError as e:
        raise AppError(f"{MANIFEST_FILE} is invalid: {files.describe(e)}") from None
    except ValueError as e:  # TOML syntax
        raise AppError(f"{MANIFEST_FILE} is invalid: {e}") from None


def snapshot(source: Path, target: Path, manifest: AppManifest) -> None:
    """Copy what a deploy installs (the manifest, the backend's directory, the built UI) from
    `source` to `target`. Symbolic links are kept, and must stay inside the copy: an agent could
    otherwise publish any host file through the app's UI."""
    if not (source / manifest.server.entry).is_file():
        raise DeployError(f"server.entry {manifest.server.entry} does not exist")
    if not (source / manifest.ui.dir / "index.html").is_file():
        raise DeployError(f"{manifest.ui.dir}/index.html does not exist: build the UI first")
    for need, agent in manifest.needs.agents.items():
        if not (source / agent.from_ / "agent.toml").is_file():
            raise DeployError(f"agents.{need}.from: {agent.from_}/agent.toml does not exist")
    target.mkdir(parents=True)
    shutil.copy2(source / MANIFEST_FILE, target / MANIFEST_FILE)
    definitions = [a.from_ for a in manifest.needs.agents.values()]
    for rel in (manifest.server.dir, manifest.ui.dir, *definitions):
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
            raise AppError(f"the backend exited ({proc.returncode}); see the log")
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
        self.links: dict[str, tuple[str, float]] = {}  # one-time code → (app, expiry)
        self.reaper: asyncio.Task[None] | None = None
        self.secrets = SecretStore(settings.data_dir)  # an app's are apps/<app>/<secret> (H.2)
        self.listeners: list[Callable[[], None]] = []  # the remote connector: what is shared
        self.inbox = inbox
        self.sent: dict[str, list[float]] = {}  # app → recent notification times (rate limit)
        self.runs = runs  # runs of agents the apps start (H.11)
        self.starts: dict[str, str] = {}  # start token of an owner's request in progress → app
        self.previews: dict[str, Preview] = {}  # an app's name → its draft, opened (H.16)
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
                    Deployment(d["seq"], d["version"], datetime.fromisoformat(d["deployedAt"]))
                    for d in r["deployments"]
                ],
                next_seq=r["nextSeq"],
                last_used_at=datetime.fromisoformat(u) if (u := r["lastUsedAt"]) else None,
                persons=r["persons"],
                files=r["files"],
                agents=r["agents"],
                askable=r["askable"],
            )

    def _save(self) -> None:
        apps = {
            r.name: {
                "fromSource": r.from_source,
                "deployments": [
                    {"seq": d.seq, "version": d.version, "deployedAt": d.deployed_at.isoformat()}
                    for d in r.deployments
                ],
                "nextSeq": r.next_seq,
                "lastUsedAt": r.last_used_at.isoformat() if r.last_used_at else None,
                "persons": r.persons,
                "files": r.files,
                "agents": r.agents,
                "askable": r.askable,
            }
            for r in self.records.values()
        }
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"apps": apps}, indent=2))
        tmp.replace(self.file)

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
            self.runs.forget(name)
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
        current = self.deployment_view(record.name, record.current)
        return AppSource(
            version=manifest.version,
            description=manifest.description,
            added_needs=manifest.added_needs(current.needs if current else None),
            needs=manifest.needs,
        )

    def view(self, name: str) -> App:
        record = self.get(name)
        files, agents = self.needs_view(name)
        next_version = self.declared(name)[:1]
        suggests = next_version[0][0].automations if next_version else []
        current = self.deployment_view(name, record.current)
        description = None
        if record.current:
            with contextlib.suppress(AppError):
                description = self.manifest(name, record.current.seq).description
        return App(
            name=name,
            description=description,
            url=f"{self.origin(name)}/",
            state=self.state(name),
            error=self.errors.get(name),
            current=current,
            previous=self.deployment_view(name, record.previous),
            source=self.source_view(record),
            secrets=[
                AppSecret(name=n, set=self.secrets.get(f"apps/{name}/{n}") is not None)
                for n in self.declared_secrets(name)
            ],
            files=files,
            agents=agents,
            suggests=suggests,
            persons=record.persons,
            last_used_at=record.last_used_at,
            from_source=record.from_source,
            actions=self.actions_view(name),
            askable=record.askable,
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

    def open_link(self, name: str) -> str:
        record = self.get(name)
        if record.current is None:
            raise AppError(f"{name} is not deployed yet")
        now = time.monotonic()
        self.links = {c: v for c, v in self.links.items() if v[1] > now}
        code = secrets.token_urlsafe(24)
        self.links[code] = (name, now + LINK_TTL)
        return f"{self.origin(name)}/_handler/login?code={code}"

    def redeem(self, name: str, code: str) -> bool:
        """One-time: a link opens the app once, within LINK_TTL."""
        entry = self.links.pop(code, None)
        return entry is not None and entry[0] == name and entry[1] > time.monotonic()

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
            for leftover in (staging, check, backup):
                shutil.rmtree(leftover, ignore_errors=True)
            try:
                source = self.source(name)
                manifest = read_manifest(source)
                self._log(name, f"== deploy {manifest.version} (#{seq})")
                if manifest.name != name:
                    raise DeployError(f"{MANIFEST_FILE} names another app: {manifest.name}")
                app_secrets = self.secrets_for(name, manifest)
                self.check_files(name, manifest)
                self.check_agents(name, manifest, source)
                self.check_actions(manifest, source)
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
            target = self.version_dir(name, seq)
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
            raise DeployError(f"cannot pull {RUNTIME_IMAGE}; see the log")

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
            raise DeployError(f"the tests failed (exit {code_}); see the log")

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
                        raise
                    self.errors.pop(name, None)
                    self.live[name] = backend
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
        spec = compose.app_sandbox_spec(
            name=f"handler-app-{name}-{secrets.token_hex(3)}",
            manifest=manifest,
            code=str(code),
            data=str(data),
            run=str(run),
            secrets=app_secrets,
            files=self.check_files(name, manifest) if files is None else files,
        )
        api: AppApi | None = None
        if manifest.needs.handler_api:  # a trial run's notifications go nowhere, starts nothing
            api = AppApi(name, run / "handler.sock", self.trial if check else self.from_app)
            await api.start()
        sandbox_process.give_dev_agent(data, run)  # with its socket
        version = f"{manifest.version} (#{seq})"
        where = " on a copy of the data" if check else ""
        self._log(name, f"{'trying' if check else 'starting'} {version}{where}")
        self.starting.add(name)
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

    async def _watch(self, name: str, backend: Backend) -> None:
        code = await backend.process.wait()
        if self.live.get(name) is backend:  # exited by itself, not stopped by us
            self.live.pop(name)
            self.errors[name] = f"the backend exited ({code}); see the log"
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
            await self.close_draft(name)
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
        self.links = {c: v for c, v in self.links.items() if v[1] > now}
        code = secrets.token_urlsafe(24)
        self.links[code] = (name + DRAFT, now + LINK_TTL)
        return f"{self.origin(name + DRAFT)}/_handler/login?code={code}"

    def preview_of(self, session: str) -> str | None:
        """The app whose draft that session has open."""
        return next((n for n, p in self.previews.items() if p.session == session), None)

    async def close_draft(self, name: str) -> None:
        """Its opened draft stopped and its copies removed (used, thrown away, idle)."""
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
        async with self.lock(name):
            await self._stop(name)
        return self.view(name)

    def set_agent(self, name: str, need: str, agent_id: str) -> App:
        """Give an agents need one of the person's agents: one that fits (H.2)."""
        found = [(m, d) for m, d in self.declared(name) if need in m.needs.agents]
        if not found:
            raise AppError(f"{name} needs no agent {need}")
        manifest, folder = found[0]
        if problem := self.agent_problem(name, manifest.needs.agents[need], folder, agent_id):
            raise AppError(f"{need}: {problem}")
        record = self.get(name)
        record.agents[need] = agent_id
        self._save()
        return self.view(name)

    def definition(self, need: AppManifestAgentNeed, folder: Path) -> AgentDefinition:
        """The definition an agents need ships (in `folder`, the app's): a job's (H.2)."""
        if bad := link_out(folder, folder / need.from_):
            raise AppError(f"{need.from_}: {bad} is a link to outside the app")
        try:
            definition = definitions.read(folder / need.from_)
        except definitions.DefinitionError as e:
            raise AppError(f"{need.from_}: {e}") from None
        if definition.interface is None or definition.interface.result is None:
            raise AppError(f"{need.from_}: interface.json: a job's, with a result (D.18)")
        try:
            interfaces.check(definition.interface)
            interfaces.check_instructions(definition.instructions, definition.interface)
        except interfaces.InterfaceError as e:
            raise AppError(f"{need.from_}: {e}") from None
        return definition

    def definition_dir(self, origin: AgentOrigin) -> Path:
        """The folder of the definition an agent set up from an app's need comes from: the
        source folder's (its skills go to the library)."""
        name, need = origin.name, origin.agent or ""  # an app's origin names its need
        found = [(m, d) for m, d in self.declared(name) if need in m.needs.agents]
        if not found:
            raise AppError(f"no app {name} needing an agent {need}")
        manifest, folder = found[0]
        self.definition(manifest.needs.agents[need], folder)
        return folder / manifest.needs.agents[need].from_

    def agent_problem(
        self, name: str, need: AppManifestAgentNeed, folder: Path, agent_id: str
    ) -> str | None:
        """Why that agent cannot be given for the need, None when it fits: a job whose form and
        result fit the definition's (interfaces.misfit), in the folder given for `worksIn`."""
        try:
            wanted = self.definition(need, folder).interface
        except AppError as e:
            return str(e)
        assert wanted is not None
        return self.misfit(name, need, wanted, agent_id)

    def misfit(
        self, name: str, need: AppManifestAgentNeed, wanted: AgentInterface, agent_id: str
    ) -> str | None:
        agent = self.runs.projects.registry.get(agent_id)
        if agent is None:
            return "the agent given was deleted"
        if agent.app is not None and agent.app != name:
            return f"it is one of the app {agent.app}'s parts"
        if why := interfaces.misfit(wanted, agent.interface):
            return why
        if need.works_in is not None:
            given = self.get(name).files.get(need.works_in)
            works = os.path.realpath(agent.scope) if agent.scope else None
            if given is not None and works != given:
                where = agent.scope or "a folder of its own per session"
                return f"it works in {where}, not in {given} ({need.works_in})"
        return None

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
            out.append((need, path, wanted.mode == "rw"))
        return out

    def check_agents(self, name: str, manifest: AppManifest, folder: Path) -> None:
        """Each agents need has a definition, and an agent given that fits it (H.2, H.11)."""
        given = self.get(name).agents
        for need, wanted in manifest.needs.agents.items():
            self.definition(wanted, folder)
            if need not in given:
                raise DeployError(f"agent {need} not given (Apps page, or handler app agent)")
            if problem := self.agent_problem(name, wanted, folder, given[need]):
                raise DeployError(f"agent {need}: {problem}")

    def given_agent(self, name: str, need: str) -> AgentRecord:
        """The agent given for a need of the installed version, fitting it now: AppRunError 403
        for a need it does not declare, 409 when it no longer fits."""
        record = self.get(name)
        assert record.current is not None
        manifest = self.manifest(name, record.current.seq)
        wanted = manifest.needs.agents.get(need)
        if wanted is None:
            raise AppRunError(403, f"{name} needs no agent {need}: not in its needs.agents")
        folder = self.version_dir(name, record.current.seq)
        agent_id = record.agents.get(need)
        if agent_id is None:
            raise AppRunError(409, f"agent {need} not given (Apps page)")
        if problem := self.agent_problem(name, wanted, folder, agent_id):
            raise AppRunError(409, f"agent {need}: {problem}")
        agent = self.runs.projects.registry.get(agent_id)
        assert agent is not None
        return agent

    def needs_view(self, name: str) -> tuple[list[AppFileNeed], list[AppAgentNeed]]:
        """The files and agents needs of the version a deploy would install (the source's; the
        installed one's when the source cannot be read), with what was given and, for an agent,
        those of the person's that fit. A need only the installed version has is not asked for:
        the next deploy drops it (its binding stays, for a rollback)."""
        record = self.get(name)
        files: dict[str, AppFileNeed] = {}
        agents: dict[str, AppAgentNeed] = {}
        for manifest, folder in self.declared(name)[:1]:
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
            for need, a in manifest.needs.agents.items():
                if need in agents:
                    continue
                given = record.agents.get(need)
                try:
                    definition = self.definition(a, folder)
                except AppError as e:
                    agents[need] = AppAgentNeed(
                        name=need,
                        description=a.description,
                        works_in=a.works_in,
                        origin=AgentOrigin(kind="app", name=name, agent=need),
                        agent_id=given,
                        problem=str(e),
                    )
                    continue
                wanted = definition.interface
                assert wanted is not None
                agents[need] = AppAgentNeed(
                    name=need,
                    description=a.description,
                    works_in=a.works_in,
                    definition=definition,
                    origin=AgentOrigin(kind="app", name=name, agent=need),
                    agent_id=given,
                    problem=self.misfit(name, a, wanted, given) if given else None,
                    fits=[
                        agent.id
                        for agent in self.runs.projects.registry.agents.values()
                        if self.misfit(name, a, wanted, agent.id) is None
                    ],
                )
        return list(files.values()), list(agents.values())

    # ── its actions, what the person can ask it (H.12) ──────────────────

    def check_actions(self, manifest: AppManifest, folder: Path) -> None:
        """A route's form is a form's JSON Schema (D.18); an agent's action runs a job whose result
        says how it went (`status`, `summary`: I.3's rule)."""
        for name, action in manifest.actions.items():
            if action.fields is not None:
                try:
                    interfaces.check(AgentInterface(fields=action.fields))
                except interfaces.InterfaceError as e:
                    raise DeployError(f"actions.{name}.{e}") from None
            if action.agent is not None:
                wanted = self.definition(manifest.needs.agents[action.agent], folder).interface
                assert wanted is not None and wanted.result is not None
                if found := interfaces.result_problems(wanted.result):
                    raise DeployError(
                        f"actions.{name}: the agent {action.agent}: {'; '.join(found)}"
                    )

    def actions_view(self, name: str) -> list[AppAction]:
        """The actions of the installed version (before a first deploy, its source's), each with
        its form: the route's, or its agent's definition's."""
        record = self.get(name)
        declared = self.declared(name)
        found = declared[-1:] if record.current else declared[:1]
        out: list[AppAction] = []
        for manifest, folder in found:
            for action_name, action in manifest.actions.items():
                fields = action.fields
                if action.agent is not None:
                    with contextlib.suppress(AppError):
                        need = manifest.needs.agents[action.agent]
                        interface = self.definition(need, folder).interface
                        fields = interface.fields if interface else None
                out.append(
                    AppAction(
                        name=action_name,
                        description=action.description,
                        examples=action.examples,
                        by="code" if action.route else "agent",
                        fields=fields,
                    )
                )
        return out

    def askable(self) -> bool:
        """An installed app offers an action to Ask (cheap: read while the host decides to poll)."""
        for record in self.records.values():
            if record.askable and record.current:
                with contextlib.suppress(AppError):
                    if self.manifest(record.name, record.current.seq).actions:
                        return True
        return False

    def set_askable(self, name: str, askable: bool) -> App:
        """Whether its actions are offered to Ask (D.24): off, they are tried from its page only."""
        self.get(name).askable = askable
        self._save()
        self.changed()  # the host may poll for the owner's phone, or stop (D.24)
        return self.view(name)

    async def act(self, name: str, action_name: str, fields: dict[str, Any]) -> ActionRun:
        """One action of the installed version, the owner's: its code answers it now; its agent's
        run is answered with its result if it ends within ACTION_WAIT, else as running (read it
        again with `action_run`; its end reaches the inbox, H.11)."""
        record = self.get(name)
        if record.current is None:
            raise AppError(f"{name} is not installed")
        manifest = self.manifest(name, record.current.seq)
        action = manifest.actions.get(action_name)
        if action is None:
            raise AppNotFoundError(f"{name} has no action {action_name}")
        if action.route is not None:
            if action.fields is not None and (found := interfaces.errors(action.fields, fields)):
                raise InputError(f"input invalid: {'; '.join(found)}")
            return await self._act_by_code(name, action_name, action.route, fields)
        assert action.agent is not None
        try:
            run = self.runs.start(name, action.agent, self.given_agent(name, action.agent), fields)
        except AppRunError as e:
            raise (InputError if e.status == 400 else AppError)(str(e)) from None
        self._log(name, f"action {action_name}: run {run.id} of {action.agent} started")
        deadline = time.monotonic() + ACTION_WAIT
        view = self.action_run(name, action_name, run.id)
        while view.state == "running" and time.monotonic() < deadline:
            await asyncio.sleep(ACTION_POLL)
            view = self.action_run(name, action_name, run.id)
        return view

    def action_run(self, name: str, action_name: str, run_id: str) -> ActionRun:
        """An agent's action, as its run is now: its result's `status` and `summary`, the whole
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
        if run.state == "succeeded" and isinstance(run.result, dict):
            told = told_result(run.result)
            summary = told["summary"] or "Done."
            result = ActionResult(status=told["status"], summary=summary[:500], data=run.result)
            return ActionRun(**base, state="succeeded", result=result)
        return ActionRun(**base, state="failed", error=run.error or run.state)

    async def _act_by_code(
        self, name: str, action_name: str, route: str, fields: dict[str, Any]
    ) -> ActionRun:
        """`POST /api/…` with the fields, as the owner (who may start runs meanwhile, H.11): its
        answer is the ActionResult."""
        method, path = route.split(" ", 1)
        backend = await self.ensure_running(name)
        start = self.issue_start(name, "owner")
        headers = {PERSON_HEADER: "owner", START_HEADER: start or "", ACTION_HEADER: action_name}
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

    async def trial(
        self, _name: str, method: str, path: str, _payload: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        """A deploy's trial run: its notifications go nowhere, it starts no run."""
        if (method, path) == ("POST", "/notify"):
            return 200, {"id": None}
        return 403, {"error": "a deploy's trial run starts nothing"}

    async def from_app(
        self, name: str, method: str, path: str, payload: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        record = self.records.get(name)
        if record is None or record.current is None:
            return 404, {"error": f"no app named {name}"}
        needs = self.manifest(name, record.current.seq).needs
        try:
            if (method, path) == ("POST", "/notify"):
                if not needs.notify:
                    raise AppRunError(403, "add `notify = true` to [needs] in app.toml")
                return await self.notification(name, payload or {})
            if path == "/runs" or path.startswith("/runs/"):
                if not needs.agents:
                    raise AppRunError(403, "add the jobs it runs to [needs.agents.<name>]")
                return await self.run_call(name, method, path, payload)
        except AppRunError as e:
            return e.status, {"error": str(e)}
        return 404, {"error": "POST /notify, POST /runs, GET /runs/{id}, POST /runs/{id}/cancel"}

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
            agent = self.given_agent(name, request.agent)
            run = self.runs.start(name, request.agent, agent, request.fields)
            self._log(name, f"run {run.id} of {run.agent} started")
            return 202, run.model_dump(mode="json", by_alias=True, exclude_none=True)
        if method == "GET" and len(parts) == 1:
            run = self.runs.get(name, parts[0])
        elif method == "POST" and len(parts) == 2 and parts[1] == "cancel":
            run = await self.runs.cancel(name, parts[0])
        else:
            return 404, {"error": "POST /runs, GET /runs/{id}, POST /runs/{id}/cancel"}
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
        now = time.monotonic()
        recent = [t for t in self.sent.get(name, []) if now - t < 3600]
        if len(recent) >= NOTIFY_PER_HOUR:
            return 429, {"error": f"at most {NOTIFY_PER_HOUR} notifications an hour"}
        self.sent[name] = [*recent, now]
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
                if now - preview.backend.last_used > self.settings.app_idle_timeout:
                    await self.close_draft(name)
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
