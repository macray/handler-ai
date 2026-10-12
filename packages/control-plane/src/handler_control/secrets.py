"""Secrets (contract E2, D.14): handler's store of values, and resolving references into values just
before `render`.

Values are held in memory only for the time of a launch; they are never logged (invariant 4).

The store keeps each value under a path named after what owns it (`providers/openrouter/apiKey`,
`apps/notes/TOKEN`), with a description; deleting or renaming a
path does so for everything under it (what its owner had). This one is a plaintext JSON file
(0600) in the data folder: no weaker than a `file` reference, not a vault. Its methods are the
store's interface: another backend (the OS keyring, injection at the network proxy) replaces the
class, not its callers.
"""

import contextlib
import json
import os
import re
import secrets
import string
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from handler_contracts import (
    CommandSecret,
    EnvSecret,
    FileSecret,
    Injection,
    NetworkMode,
    SecretInfo,
    SecretRef,
    StoreSecret,
)

from .files import write_private

STORE_FILE = "secrets.json"
_lock = threading.Lock()  # one daemon process; its routes run in threads


class SecretError(RuntimeError):
    pass


class SecretStore:
    def __init__(self, data_dir: Path) -> None:
        self.file = data_dir / STORE_FILE

    def get(self, path: str) -> str | None:
        entry = self._read().get(path)
        return entry["value"] if entry else None

    def values(self) -> list[str]:
        """Every value it holds: what must not leave handler (automations redact with them, I.4)."""
        return [e["value"] for e in self._read().values()]

    def list(self) -> list[SecretInfo]:
        """Every secret, described (never its value), by path."""
        return [
            SecretInfo(
                path=path,
                description=e.get("description"),
                created_at=e["createdAt"],
                updated_at=e["updatedAt"],
            )
            for path, e in sorted(self._read().items())
        ]

    def put(self, path: str, value: str, description: str | None = None) -> None:
        now = datetime.now(UTC).isoformat()
        with _lock:
            entries = self._read()
            created = entries.get(path, {}).get("createdAt", now)
            entries[path] = {
                "value": value,
                "description": description,
                "createdAt": created,
                "updatedAt": now,
            }
            self._write(entries)

    def delete(self, path: str) -> bool:
        """Forget `path` and everything under it (`apps/notes` removes the app's secrets)."""
        with _lock:
            entries = self._read()
            gone = [p for p in entries if _within(p, path)]
            for p in gone:
                del entries[p]
            if gone:
                self._write(entries)
        return bool(gone)

    def rename(self, old: str, new: str) -> None:
        """Move `old` and everything under it to `new` (its owner was renamed)."""
        with _lock:
            entries = self._read()
            moved = {new + p.removeprefix(old): e for p, e in entries.items() if _within(p, old)}
            if moved:
                kept = {p: e for p, e in entries.items() if not _within(p, old)}
                self._write(kept | moved)

    def _read(self) -> dict[str, dict]:
        with contextlib.suppress(FileNotFoundError):
            return json.loads(self.file.read_text())
        return {}

    def _write(self, entries: dict[str, dict]) -> None:
        write_private(self.file, json.dumps(entries, indent=2))


def _within(path: str, owner: str) -> bool:
    return path == owner or path.startswith(owner + "/")


def redactor(values: list[str]) -> Callable[[str], str]:
    """Replace secret values (raw and JSON-escaped) in a text: a serialized event (invariant 4),
    a transcript (I.4)."""
    forms = sorted(
        {form for v in values if len(v) >= 4 for form in (v, json.dumps(v)[1:-1])},
        key=len,
        reverse=True,
    )

    def redact(text: str) -> str:
        for form in forms:
            text = text.replace(form, "«redacted»")
        return text

    return redact


def kind(ref: SecretRef) -> Literal["secret", "env", "file", "command"]:
    """Where a referenced value comes from: handler's store, or one of the person's own (E2)."""
    if isinstance(ref, StoreSecret):
        return "secret"
    if isinstance(ref, EnvSecret):
        return "env"
    return "file" if isinstance(ref, FileSecret) else "command"


def resolve(ref: SecretRef, store: SecretStore) -> str:
    if isinstance(ref, StoreSecret):
        value = store.get(ref.secret)
        if value is None:
            raise SecretError(f"secret {ref.secret} is not set (handler secret set {ref.secret})")
        return value
    if isinstance(ref, EnvSecret):
        value = os.environ.get(ref.env)
        if value is None:
            raise SecretError(f"environment variable {ref.env} is not set")
        return value
    if isinstance(ref, FileSecret):
        try:
            lines = open(ref.file).read().splitlines()  # noqa: SIM115 — one-shot read
        except OSError as e:
            raise SecretError(f"cannot read secret file {ref.file}: {e.strerror}") from None
        if not lines or not lines[0].strip():
            raise SecretError(f"secret file {ref.file} is empty")
        return lines[0].strip()
    if isinstance(ref, CommandSecret):
        proc = subprocess.run(ref.command, capture_output=True, text=True, check=False, timeout=30)
        if proc.returncode != 0 or not proc.stdout.strip():
            raise SecretError(f"secret command {ref.command[0]} failed (exit {proc.returncode})")
        return proc.stdout.strip().splitlines()[0]
    raise SecretError(f"unsupported secret reference {ref!r}")


def resolve_all(refs: dict[str, SecretRef] | None, store: SecretStore) -> dict[str, str]:
    return {slot: resolve(ref, store) for slot, ref in (refs or {}).items()}


# A vendor's prefix ("sk-ant-oat01-", "github_pat_", "shptka_"): words ending with "-" or "_", the
# first of letters only. Kept in a phantom (some clients check a key's form) when what follows
# is long enough to stay secret.
_PREFIX = re.compile(r"^[a-z]+[-_](?:[a-z0-9]+[-_]){0,3}")
_INJECTABLE = re.compile(r"^[!-~]{8,}$")  # printable ASCII, no space (A.1 Injection)


def phantom(value: str) -> str:
    """A stand-in for `value` that a sandbox's proxy swaps back (A.3): as long, with the same
    kind of character at each place (a digit for a digit…), its vendor's prefix kept."""
    prefix = m.group() if (m := _PREFIX.match(value)) and len(value) - m.end() >= 24 else ""
    while True:
        rest = "".join(_like(c) for c in value[len(prefix) :])
        if (made := prefix + rest) != value:
            return made


def _like(c: str) -> str:
    for kind in (string.digits, string.ascii_lowercase, string.ascii_uppercase):
        if c in kind:
            return secrets.choice(kind)
    return c


@dataclass
class Delivery:
    """How a launch's secrets reach its sandbox (A.3): through its proxy, the process holding a
    phantom, wherever the secret has hosts and a network to reach them; the value itself when it
    cannot be injected (no hosts, a value the proxy cannot carry). Without a network, a phantom:
    nothing to reach, and the value never written to its folders."""

    network: NetworkMode
    injections: list[Injection] = field(default_factory=list)

    def give(self, name: str, value: str, hosts: Sequence[str] | None) -> str:
        """What the sandbox gets for the secret `name` (as the store names it, e.g.
        `providers/openrouter/apiKey`, whatever its reference). `hosts` None: the value as it
        is, its owner says so (an addon's slot, G.1)."""
        if hosts is None or not _INJECTABLE.match(value):
            return value
        if self.network != "none" and not hosts:
            return value  # no host to give it to
        made = phantom(value)
        if self.network != "none":
            self.injections.append(
                Injection(name=name, phantom=made, value=value, hosts=sorted(set(hosts)))
            )
        return made


def name_of(ref: SecretRef, own: str) -> str:
    """A secret's name (D.14, A.3 injections): its path in the store, or for a reference elsewhere
    the path its owner's (`own`) would have there."""
    return ref.secret if isinstance(ref, StoreSecret) else own


def visible(value: str | None, hosts: Sequence[str] | None) -> str | None:
    """Why a networked sandbox gets a secret's value itself rather than a phantom (Delivery), in
    words for the person; None when its proxy gives it. `value` None: not known (a command's,
    not run)."""
    if hosts is None:
        return "its addon gives it as it is (it signs with it, or does not speak HTTP)"
    if not hosts:
        return "no host to give it to: its addon reaches none"
    if value is not None and not _INJECTABLE.match(value):
        return "the proxy cannot carry it: under 8 characters, or not printable ASCII"
    return None
