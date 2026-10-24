"""What the gateway keeps: who may call it (persisted), and the envelopes in transit (memory).

    Registry   hosts (token hash) and the devices each host registered (token hash), in one JSON
               file (0600). `handler-gateway add-host` writes it while the server runs: each one
               re-reads it before using or changing it, and changes it under a lock (`.lock` next
               to it), so neither undoes the other's change.
    Mailbox    envelopes for one reader, in order, with a cursor; bounded (count, bytes) and
               expiring (TTL). Long-poll readers wait for the next put.
    Queue      envelopes a device leaves for when its host is back (on disk, a file each, 7 days).

The gateway never sees a key: tokens are compared by hash, envelopes are opaque.
"""

import asyncio
import contextlib
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class ConflictError(ValueError):
    """The device id belongs to another host."""


class Registry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.hosts: dict[str, dict[str, Any]] = {}
        self.devices: dict[str, dict[str, Any]] = {}
        self.mtime = -1.0
        self.reload()

    def reload(self) -> None:
        """Re-read the file if it changed (another process — the CLI — may have written it)."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime == self.mtime:
            return
        data = json.loads(self.path.read_text())
        self.hosts, self.devices, self.mtime = data.get("hosts", {}), data.get("devices", {}), mtime

    def save(self) -> None:
        """Written whole then renamed (a reader never sees half of it), from a file of its own
        (the CLI and the server never write the same one)."""
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}-")  # 0600
        with os.fdopen(fd, "w") as f:
            json.dump({"hosts": self.hosts, "devices": self.devices}, f, indent=2)
        os.replace(tmp, self.path)
        self.mtime = self.path.stat().st_mtime

    @contextlib.contextmanager
    def change(self) -> Iterator[None]:
        """Read the file again, change it, save it: one process at a time (the CLI's change and
        the server's are never lost to each other)."""
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.path.with_suffix(".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self.reload()
            yield
            self.save()
        finally:
            os.close(fd)  # and its lock

    # ── hosts ───────────────────────────────────────────────────────────

    def add_host(self, name: str) -> str:
        """A new host; returns its token `<hostId>.<secret>` (shown once, stored hashed)."""
        host_id = "h_" + secrets.token_hex(8)
        secret = secrets.token_urlsafe(32)
        with self.change():
            self.hosts[host_id] = {
                "name": name,
                "secretHash": sha256_hex(secret),
                "at": time.time(),
            }
        return f"{host_id}.{secret}"

    def remove_host(self, host_id: str) -> bool:
        with self.change():
            if self.hosts.pop(host_id, None) is None:
                return False
            self.devices = {d: v for d, v in self.devices.items() if v["host"] != host_id}
        return True

    def host_for(self, token: str | None) -> str | None:
        host_id, _, secret = (token or "").partition(".")
        self.reload()
        host = self.hosts.get(host_id)
        if host is None or not secret:
            return None
        return host_id if hmac.compare_digest(host["secretHash"], sha256_hex(secret)) else None

    # ── devices (registered by their host) ─────────────────────────────

    def put_device(self, host_id: str, device_id: str, token_hash: str) -> None:
        with self.change():
            owner = self.devices.get(device_id)
            if owner is not None and owner["host"] != host_id:
                raise ConflictError(device_id)
            self.devices[device_id] = {"host": host_id, "tokenHash": token_hash, "at": time.time()}

    def delete_device(self, host_id: str, device_id: str) -> bool:
        with self.change():
            owner = self.devices.get(device_id)
            if owner is None or owner["host"] != host_id:
                return False
            del self.devices[device_id]
        return True

    def devices_of(self, host_id: str) -> list[str]:
        return sorted(d for d, v in self.devices.items() if v["host"] == host_id)

    def device_for(self, token: str | None) -> tuple[str, str] | None:
        """`<deviceId>.<token>` → (device id, its host id)."""
        device_id, _, secret = (token or "").partition(".")
        self.reload()  # a host removed by the CLI: its devices with it, at once
        device = self.devices.get(device_id)
        if device is None or not secret:
            return None
        if not hmac.compare_digest(device["tokenHash"], sha256_hex(secret)):
            return None
        return device_id, device["host"]


@dataclass
class Envelope:
    cursor: int
    id: str
    nonce: str
    ct: str
    dev: str  # the device it comes from (down) or goes to (up)
    at: float = field(default_factory=time.monotonic)

    @property
    def size(self) -> int:
        return len(self.ct) + len(self.nonce) + len(self.id)

    def to_json(self) -> dict[str, Any]:
        return {"cursor": self.cursor, "dev": self.dev, "id": self.id, "nonce": self.nonce,
                "ct": self.ct}  # fmt: skip


class MailboxFullError(RuntimeError):
    pass


class Mailbox:
    def __init__(self, max_count: int, max_bytes: int, ttl: float) -> None:
        self.max_count, self.max_bytes, self.ttl = max_count, max_bytes, ttl
        self.items: deque[Envelope] = deque()
        self.bytes = 0
        self.cursor = 0
        self.changed = asyncio.Event()

    def _expire(self) -> None:
        deadline = time.monotonic() - self.ttl
        while self.items and self.items[0].at < deadline:
            self._pop()

    def _pop(self) -> None:
        self.bytes -= self.items.popleft().size

    def put(self, id: str, nonce: str, ct: str, dev: str, *, drop_oldest: bool) -> Envelope:
        """Queue an envelope. Full: drop the oldest (up: the device re-syncs from the host's log)
        or refuse (down: a command is never silently lost)."""
        self._expire()
        env = Envelope(self.cursor + 1, id, nonce, ct, dev)
        while self.items and (
            len(self.items) >= self.max_count or self.bytes + env.size > self.max_bytes
        ):
            if not drop_oldest:
                raise MailboxFullError()
            self._pop()
        self.cursor = env.cursor
        self.items.append(env)
        self.bytes += env.size
        self.poke()
        return env

    def poke(self) -> None:
        """Wake the readers waiting on this mailbox."""
        self.changed.set()
        self.changed = asyncio.Event()

    def after(self, cursor: int, limit_bytes: int) -> list[Envelope]:
        self._expire()
        out, size = [], 0
        for env in self.items:
            if env.cursor > cursor:
                if out and size + env.size > limit_bytes:
                    break
                out.append(env)
                size += env.size
        return out

    async def wait_after(
        self,
        cursor: int,
        wait: float,
        limit_bytes: int,
        done: Callable[[], bool] = lambda: False,
    ) -> list[Envelope]:
        """Long poll: what is after `cursor`, waiting up to `wait` seconds for something (or
        for `done()`, checked when the mailbox is poked)."""
        deadline = time.monotonic() + wait
        while not (found := self.after(cursor, limit_bytes)):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or done():
                return []
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.changed.wait(), remaining)
        return found


class Queue:
    """Envelopes a device queued for when its host is back (handler's "queued" routes): kept on disk
    (a gateway restart keeps them), bounded per host, expiring. The host lists them, then deletes
    each one it has processed: nothing is lost if it stops halfway (it dedups by id).

    On disk, one file per envelope, `<path>/<host id>/<envelope id>.json` (0600): queueing writes
    that envelope only, taking it deletes its file, whatever the queues hold. Ids are the
    gateway's checked ones (base64url); a file is only ever named from one already queued."""

    def __init__(
        self,
        path: Path | None,
        max_count: int = 500,
        max_bytes: int = 32 * 1024 * 1024,
        ttl: float = 7 * 24 * 3600.0,
    ) -> None:
        self.path = path
        self.max_count, self.max_bytes, self.ttl = max_count, max_bytes, ttl
        self.items: dict[str, list[dict[str, Any]]] = {}  # host id → envelopes, oldest first
        if path is not None:
            for file in path.glob("*/*.json"):
                with contextlib.suppress(OSError, ValueError):
                    self.items.setdefault(file.parent.name, []).append(json.loads(file.read_text()))
            for box in self.items.values():
                box.sort(key=lambda e: e["at"])

    def _file(self, host: str, id: str) -> Path | None:
        return None if self.path is None else self.path / host / f"{id}.json"

    def _write(self, host: str, envelope: dict[str, Any]) -> None:
        if (file := self._file(host, envelope["id"])) is None:
            return
        file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = file.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(envelope, f)
        tmp.replace(file)

    def _forget(self, host: str, id: str) -> None:
        if (file := self._file(host, id)) is not None:
            file.unlink(missing_ok=True)

    def _expire(self, host: str) -> list[dict[str, Any]]:
        now = time.time()
        box = self.items.get(host, [])
        kept = [e for e in box if now - e["at"] < self.ttl]
        for e in box:
            if now - e["at"] >= self.ttl:
                self._forget(host, e["id"])
        self.items[host] = kept
        return kept

    def put(self, host: str, dev: str, id: str, nonce: str, ct: str) -> None:
        box = self._expire(host)
        if any(e["id"] == id for e in box):
            return
        size = sum(len(e["ct"]) for e in box) + len(ct)
        if len(box) >= self.max_count or size > self.max_bytes:
            raise MailboxFullError()
        envelope = {"id": id, "nonce": nonce, "ct": ct, "dev": dev, "at": time.time()}
        box.append(envelope)
        self._write(host, envelope)

    def pending(self, host: str, limit_bytes: int) -> list[dict[str, Any]]:
        out, size = [], 0
        for e in self._expire(host):
            if out and size + len(e["ct"]) > limit_bytes:
                break
            out.append({k: e[k] for k in ("id", "nonce", "ct", "dev")})
            size += len(e["ct"])
        return out

    def waiting_any(self, host: str) -> int:
        return len(self._expire(host))

    def waiting(self, host: str, dev: str) -> list[str]:
        return [e["id"] for e in self._expire(host) if e["dev"] == dev]

    def remove(self, host: str, id: str) -> bool:
        box = self.items.get(host, [])
        kept = [e for e in box if e["id"] != id]
        if len(kept) == len(box):
            return False  # never queued: no file is named from it
        self.items[host] = kept
        self._forget(host, id)
        return True
