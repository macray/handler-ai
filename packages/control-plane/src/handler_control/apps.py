"""Mini apps (contract H, docs/dev/design/miniapps.md): registry, deploy and rollback, backends
started on demand and stopped when idle. Serving them over HTTP is app_http.py.

    <state>/apps.json                  registry: each app's source folder and deployments
    <data>/apps/<name>/versions/<n>/   the code of deploy n (app.toml, backend dir, built UI)
    <data>/apps/<name>/data/           the app's data (its scope): survives deploys
    <data>/apps/<name>/backups/<n>/    the data as it was just before deploy n (rollback)
    <data>/apps/<name>/app.log         the last deploys and the backend's output
    <runtime>/apps/<name>/             the backend's socket (HANDLER_RUNTIME_DIR, settings.py)

A deploy (H.6) is asked by a person, never by an agent: snapshot the source folder, run the
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
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from handler_contracts import (
    HEALTH_PATH,
    MANIFEST_FILE,
    PERSON_HEADER,
    RUNTIME_IMAGE,
    App,
    AppDeployment,
    AppSecret,
    AppSource,
    AppState,
    MiniAppManifest,
    SharedApp,
    is_within,
)

from . import compose, runtime, sandbox_process, shortcuts
from .app_api import AppApi
from .inbox import Inbox
from .launcher import NETWORK_FILTER_MISSING
from .secrets import SecretStore
from .settings import Settings

log = logging.getLogger("handler.apps")

KEEP_DEPLOYMENTS = 3  # the current one and two to roll back to
MAX_APP_BYTES = 256 * 1024 * 1024
START_TIMEOUT = 60.0  # a first start may wait for podman to set the container up
TEST_TIMEOUT = 300.0
PULL_TIMEOUT = 600.0
LOG_MAX_BYTES = 1024 * 1024
LOG_TAIL_BYTES = 64 * 1024
LINK_TTL = 120.0
LINE_LIMIT = 1024 * 1024
NOTIFY_PER_HOUR = 30
CALL_TIMEOUT = 300.0  # an automation's call (I.3)
# never given to an app, whatever it asks (H.9): keys and password stores (and handler's own dirs)
PRIVATE_HOME = (".ssh", ".gnupg", ".password-store", ".local/share/keyrings", ".pki", ".aws")
COOKIE_NAME = "handler_app"


class AppError(Exception):
    """A request that cannot be done: bad source folder, unknown app, failed deploy…"""


class AppNotFoundError(AppError):
    pass


class DeployError(AppError):
    pass


@dataclass
class Deployment:
    seq: int
    version: str
    deployed_at: datetime


@dataclass
class AppRecord:
    name: str
    source_dir: str
    deployments: list[Deployment] = field(default_factory=list)  # oldest first; last = current
    next_seq: int = 1
    last_used_at: datetime | None = None
    shortcut: str | None = None  # GNOME accelerator, set by the person (H.7)
    persons: list[str] = field(default_factory=list)  # who may use it remotely (H.8)

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
    seq: int
    pump: asyncio.Task[None]  # copies its output to the log
    api: AppApi | None = None  # handler's side for the backend (needs.notify, H.9)
    last_used: float = field(default_factory=time.monotonic)


def read_manifest(folder: Path) -> MiniAppManifest:
    try:
        text = (folder / MANIFEST_FILE).read_text()
    except OSError as e:
        raise AppError(f"cannot read {folder / MANIFEST_FILE}: {e.strerror}") from None
    try:
        return MiniAppManifest.from_toml(text)
    except (ValidationError, ValueError) as e:
        raise AppError(f"{MANIFEST_FILE} is invalid: {e}") from None


def snapshot(source: Path, target: Path, manifest: MiniAppManifest) -> None:
    """Copy what a deploy installs (the manifest, the backend's directory, the built UI) from
    `source` to `target`. Symbolic links are kept, and must stay inside the copy: an agent could
    otherwise publish any host file through the app's UI."""
    if not (source / manifest.server.entry).is_file():
        raise DeployError(f"server.entry {manifest.server.entry} does not exist")
    if not (source / manifest.ui.dir / "index.html").is_file():
        raise DeployError(f"{manifest.ui.dir}/index.html does not exist: build the UI first")
    target.mkdir(parents=True)
    shutil.copy2(source / MANIFEST_FILE, target / MANIFEST_FILE)
    for rel in (manifest.server.dir, manifest.ui.dir):
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source / rel, target / rel, symlinks=True)
    root, total = os.path.realpath(target), 0
    for dirpath, dirnames, filenames in os.walk(target):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path) and not is_within(os.path.realpath(path), root):
                raise DeployError(f"{os.path.relpath(path, target)} is a link to outside the app")
        total += sum(os.lstat(os.path.join(dirpath, n)).st_size for n in filenames)
    if total > MAX_APP_BYTES:
        raise DeployError(f"the app is {total // 2**20} MiB: more than {MAX_APP_BYTES // 2**20}")


def copy_data(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        target.mkdir(parents=True)


class AppStore:
    def __init__(self, settings: Settings, token: str, inbox: Inbox) -> None:
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
        self._load()

    # ── registry ────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            raw = json.loads(self.file.read_text())
        except FileNotFoundError:
            return
        for name, r in raw.get("apps", {}).items():
            self.records[name] = AppRecord(
                name=name,
                source_dir=r["sourceDir"],
                deployments=[
                    Deployment(d["seq"], d["version"], datetime.fromisoformat(d["deployedAt"]))
                    for d in r.get("deployments", [])
                ],
                next_seq=r.get("nextSeq", 1),
                last_used_at=datetime.fromisoformat(u) if (u := r.get("lastUsedAt")) else None,
                shortcut=r.get("shortcut"),
                persons=list(r.get("persons", [])),
            )

    def _save(self) -> None:
        apps = {
            r.name: {
                "sourceDir": r.source_dir,
                "deployments": [
                    {"seq": d.seq, "version": d.version, "deployedAt": d.deployed_at.isoformat()}
                    for d in r.deployments
                ],
                "nextSeq": r.next_seq,
                "lastUsedAt": r.last_used_at.isoformat() if r.last_used_at else None,
                "shortcut": r.shortcut,
                "persons": r.persons,
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

    def add(self, source_dir: str) -> AppRecord:
        source = Path(os.path.realpath(source_dir))
        manifest = read_manifest(source)
        if manifest.name in self.records:
            raise AppError(f"an app named {manifest.name} is already registered")
        record = AppRecord(name=manifest.name, source_dir=str(source))
        self.records[record.name] = record
        self.data_dir(record.name).mkdir(parents=True, exist_ok=True)
        self._save()
        return record

    async def remove(self, name: str) -> None:
        """Unregister the app and delete its versions and backups. Its data folder is kept:
        registering the app again finds it."""
        self.get(name)
        async with self.lock(name):
            await self._stop(name)
            record = self.records.pop(name)
            self._save()
            self.changed()
            if record.shortcut:
                with contextlib.suppress(shortcuts.ShortcutError):
                    await asyncio.to_thread(shortcuts.remove, name)
            self.secrets.delete(f"apps/{name}")
            for sub in ("versions", "backups"):
                shutil.rmtree(self.app_dir(name) / sub, ignore_errors=True)

    def manifest(self, name: str, seq: int) -> MiniAppManifest:
        return read_manifest(self.version_dir(name, seq))

    # ── secrets (H.2) ───────────────────────────────────────────────────

    def declared_secrets(self, name: str) -> list[str]:
        """What the installed version and the source folder declare."""
        record = self.get(name)
        declared: set[str] = set()
        if record.current:
            with contextlib.suppress(AppError):
                declared |= set(self.manifest(name, record.current.seq).needs.secrets)
        with contextlib.suppress(AppError):
            source = read_manifest(Path(record.source_dir))
            if source.name == name:
                declared |= set(source.needs.secrets)
        return sorted(declared)

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

    def secrets_for(self, name: str, manifest: MiniAppManifest) -> dict[str, str]:
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
            description = None
            with contextlib.suppress(AppError):
                description = self.manifest(record.name, record.current.seq).description
            queued: list[str] = []
            with contextlib.suppress(AppError):
                queued = self.manifest(record.name, record.current.seq).queued_routes
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

    # ── keyboard shortcuts (H.7) ────────────────────────────────────────

    async def set_shortcut(self, name: str, keys: str | None) -> App:
        record = self.get(name)
        taken = [r.name for r in self.records.values() if keys and r.shortcut == keys]
        if taken and taken != [name]:
            raise AppError(f"{keys} already opens {taken[0]}")
        try:
            if keys:
                await asyncio.to_thread(shortcuts.install, name, keys)
            elif record.shortcut:
                await asyncio.to_thread(shortcuts.remove, name)
        except shortcuts.ShortcutError as e:
            raise AppError(f"cannot set the shortcut: {e}") from None
        record.shortcut = keys
        self._save()
        return self.view(name)

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
            manifest = read_manifest(Path(record.source_dir))
        except AppError as e:
            return AppSource(error=str(e))
        if manifest.name != record.name:
            return AppSource(error=f"{MANIFEST_FILE} now names another app: {manifest.name}")
        current = self.deployment_view(record.name, record.current)
        return AppSource(
            version=manifest.version,
            description=manifest.description,
            added_needs=manifest.added_needs(current.needs if current else None),
        )

    def view(self, name: str) -> App:
        record = self.get(name)
        current = self.deployment_view(name, record.current)
        description = None
        if record.current:
            with contextlib.suppress(AppError):
                description = self.manifest(name, record.current.seq).description
        return App(
            name=name,
            description=description,
            source_dir=record.source_dir,
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
            shortcut=record.shortcut,
            persons=record.persons,
            last_used_at=record.last_used_at,
        )

    def views(self) -> list[App]:
        return [self.view(n) for n in sorted(self.records)]

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
                manifest = read_manifest(Path(record.source_dir))
                self._log(name, f"== deploy {manifest.version} (#{seq}) from {record.source_dir}")
                if manifest.name != name:
                    raise DeployError(f"{MANIFEST_FILE} names another app: {manifest.name}")
                app_secrets = self.secrets_for(name, manifest)
                self.check_files(manifest)
                await asyncio.to_thread(snapshot, Path(record.source_dir), staging, manifest)
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

    async def _run_tests(
        self, name: str, manifest: MiniAppManifest, code: Path, data: Path
    ) -> None:
        """`deno test` on the backend's directory, with an empty data folder, in the sandbox."""
        data.mkdir(parents=True)
        run = self.run_root / f"{name}-test"
        run.mkdir(parents=True, exist_ok=True)
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
            raise DeployError(NETWORK_FILTER_MISSING)
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
        manifest: MiniAppManifest,
        code: Path,
        data: Path,
        *,
        app_secrets: dict[str, str],
        check: bool = False,
    ) -> Backend:
        """Start the backend and wait until its health check answers 200 (H.3). `check`: a
        deploy's trial run, on a copy of the data."""
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
            files=self.check_files(manifest),
        )
        api: AppApi | None = None
        if manifest.needs.notify:  # a trial run's notifications go nowhere
            api = AppApi(name, run / "handler.sock", self.dropped if check else self.from_app)
            await api.start()
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
                raise AppError(NETWORK_FILTER_MISSING)
            proc = await sandbox_process.start_piped(spec, line_limit=LINE_LIMIT)
            pump = asyncio.get_running_loop().create_task(self._pump(name, proc, app_secrets))
            backend = Backend(proc, client, seq, pump, api)
            deadline = time.monotonic() + START_TIMEOUT
            while True:
                if proc.returncode is not None:
                    raise AppError(f"the backend exited ({proc.returncode}); see the log")
                if time.monotonic() > deadline:
                    raise AppError(f"the backend did not answer {HEALTH_PATH} in time")
                if socket.exists():
                    with contextlib.suppress(httpx.TransportError):
                        r = await client.get(HEALTH_PATH, timeout=2.0)
                        if r.status_code == 200:
                            return backend
                        raise AppError(f"{HEALTH_PATH} answered {r.status_code}")
                await asyncio.sleep(0.2)
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

    # ── host files (H.9) ────────────────────────────────────────────────

    def check_files(self, manifest: MiniAppManifest) -> list[tuple[str, bool]]:
        """The manifest's files, resolved: existing, in the home, not handler's own nor keys."""
        home = os.path.realpath(Path.home())
        private = [os.path.realpath(Path(home) / p) for p in PRIVATE_HOME]
        private += [
            os.path.realpath(d)
            for d in (self.settings.config_dir, self.settings.state_dir, self.settings.data_dir)
        ]
        out: list[tuple[str, bool]] = []
        for f in manifest.needs.files:
            path = os.path.realpath(f.path)
            if not os.path.exists(path):
                raise DeployError(f"file {f.path} does not exist")
            if not is_within(path, home) or path == home:
                raise DeployError(f"file {f.path}: only files and folders inside your home")
            if any(is_within(path, p) or is_within(p, path) for p in private):
                raise DeployError(f"file {f.path}: handler's own files and keys are never given")
            if "," in path or any(path == p for p, _ in out):
                raise DeployError(f"file {f.path}: listed twice, or has a ','")
            out.append((path, f.mode == "rw"))
        return out

    # ── notifications (H.9) ─────────────────────────────────────────────

    async def dropped(self, _name: str, _payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return 200, {"id": None}  # a deploy's trial run: nobody is told

    async def from_app(self, name: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
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
        return 200, {"id": self.notify(name, person, title, body)}

    def notify(self, name: str, person: str, title: str, body: str | None) -> str:
        """Into the person's inbox (H.9); its id."""
        self._log(name, f"notification for {person}: {title}")
        message = self.inbox.add(source="app", name=name, person=person, title=title, summary=body)
        return message.id

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
        self.reaper = asyncio.get_running_loop().create_task(self._reap())

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
            with contextlib.suppress(OSError):
                self._save()  # last-used times

    async def close(self) -> None:
        if self.reaper:
            self.reaper.cancel()
        for name in list(self.live):
            await self._stop(name)
        with contextlib.suppress(OSError):
            self._save()
