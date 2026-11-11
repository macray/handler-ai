"""The network filter (contract A.3, A.4): an allow-list and secret injections via a per-instance
mitmproxy. Here, its host side: its settings, its secrets, its arguments, and its events reported
on stderr. In `proxy/` (`proxy_dir()`), what runs in the filter's own container: its image's
recipe, what it decides (`addon.py`), Apple's socket front (`front.py`)."""

import contextlib
import json
import os
import sys
import threading
import time
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Literal, TextIO

from handler_contracts import Injection

from .proxy import addon

Enforcement = Literal["enforce", "log-only"]
Filtering = Enforcement | Literal["open"]  # open: nothing filtered, its proxy is for its secrets

PROXY_PORT = 8888
ADDON_SOURCE = Path(addon.__file__)  # mounted into the proxy at ADDON_TARGET
ADDON_TARGET = "/handler/addon.py"
SETTINGS_FILE = addon.SETTINGS
APPLIED_FILE = addon.APPLIED
EVENTS_FILE = addon.EVENTS
STARTED_FILE = addon.STARTED
CA_BUNDLE_FILE = addon.CA_BUNDLE

EGRESS_EVENT_PREFIX = "handler-egress "
"""stderr line prefix of egress events: `handler-egress {"decision": "denied", "host":
"host:port"}`; decisions: `allowed`, `denied`, `unlisted` (log only: let through, but no entry
allows it)."""


def proxy_dir() -> Traversable:
    """The filter's own files, shipped here: its image's recipe (`Containerfile`, built by
    `image build-proxy`, A.7) and what runs in it (`addon.py`, `front.py`)."""
    return resources.files(__name__) / "proxy"


def upstream_proxy() -> str | None:
    """HANDLER_SANDBOX_DEV_UPSTREAM_PROXY (an http:// proxy URL) is for development environments
    that reach the internet only through a proxy (a handler agent running the conformance tests):
    the sandbox's proxy then reaches every destination through it, local ones included, which it
    cannot reach. Never set it on a real host."""
    return os.environ.get("HANDLER_SANDBOX_DEV_UPSTREAM_PROXY") or None


def proxy_args(listen_ip: str, secret_hosts: list[str]) -> list[str]:
    """mitmdump's arguments: listen on the sandbox's network; decrypt only the tunnels to
    `secret_hosts` (allow-list entries), relay every other one as it is; the addon decides; its
    CA (made per instance at start) in /cfg."""
    upstream = upstream_proxy()
    mode = ["--mode", f"upstream:{upstream}"] if upstream else []
    # matched against "host:port" (the CONNECT target, the TLS server name)
    decrypted = [f"^(?:{addon.entry_pattern(e).pattern})$" for e in sorted(set(secret_hosts))]
    hosts = [a for p in decrypted for a in ("--allow-hosts", p)] or ["--ignore-hosts", ".*"]
    return [
        "--listen-host", listen_ip, "--listen-port", str(PROXY_PORT), *mode, *hosts,
        "--set", "confdir=/cfg/ca", "--scripts", ADDON_TARGET, "--quiet",
    ]  # fmt: skip


def write_secrets(directory: Path, injections: list[Injection]) -> None:
    """The proxy's secrets, readable by the launcher's user only (the proxy runs as it)."""
    path = directory / addon.SECRETS
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump([i.model_dump(mode="json") for i in injections], f)


class EgressState:
    """Persisted per-instance egress settings: the addon reads them, `set-egress` rewrites them."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.file = directory / SETTINGS_FILE

    def write(
        self,
        allow: list[str],
        blocked: list[str],
        enforcement: Filtering,
        watched: str | None = None,
    ) -> int:
        """Replaced whole (the proxy reads it while `set-egress` writes it); its version.
        `watched`: the turn someone watches the session in (`set-watched`), None when nobody
        does: the filter holds a request a while for the person's answer only then."""
        version = json.loads(self.file.read_text())["version"] + 1 if self.file.exists() else 1
        tmp = self.file.with_suffix(".tmp")
        settings = {
            "allow": allow,
            "blocked": blocked,
            "enforcement": enforcement,
            "watched": watched,
        }
        tmp.write_text(json.dumps(settings | {"version": version}))
        tmp.replace(self.file)
        return version

    def read(self) -> tuple[list[str], list[str], Filtering, str | None]:
        data = json.loads(self.file.read_text())
        return list(data["allow"]), list(data["blocked"]), data["enforcement"], data["watched"]

    def wait_applied(self, version: int, timeout: float) -> bool:
        """Until the proxy says the settings of `version` (or later) are in force."""
        deadline = time.monotonic() + timeout
        while True:
            with contextlib.suppress(OSError, ValueError):
                if int((self.directory / APPLIED_FILE).read_text()) >= version:
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)


class EventWatcher(threading.Thread):
    """Tails the proxy's events and reports them on stderr (A.3: denials observable)."""

    def __init__(self, events_file: Path, out: TextIO = sys.stderr) -> None:
        super().__init__(daemon=True, name="handler-egress-events")
        self.events_file = events_file
        self.out = out
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        pos = 0
        while True:
            stopping = self._stop_event.is_set()  # one last full read after stop() before exiting
            try:
                with self.events_file.open() as f:
                    f.seek(pos)
                    while (line := f.readline()).endswith("\n"):  # a line being written waits
                        self.out.write(EGRESS_EVENT_PREFIX + line)
                        pos = f.tell()
                    self.out.flush()
            except FileNotFoundError:
                pass
            if stopping:
                return
            self._stop_event.wait(0.2)


def wait_until_ready(directory: Path, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (directory / STARTED_FILE).exists():
            return True
        time.sleep(0.05)
    return False
