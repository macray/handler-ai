"""Egress allow-list and secret injections via a per-instance mitmproxy (contract A.3, A.4): its
settings, its secrets, its arguments, and its events reported on stderr. What the proxy decides
is in `proxy/addon.py`."""

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Literal, TextIO

from handler_contracts import Injection

from .proxy import addon

Enforcement = Literal["enforce", "log-only"]
Filtering = Enforcement | Literal["open"]  # open: nothing filtered, its proxy is for its secrets

PROXY_PORT = 8888
ADDON_TARGET = "/handler/addon.py"
SETTINGS_FILE = addon.SETTINGS
EVENTS_FILE = addon.EVENTS
STARTED_FILE = addon.STARTED
CA_BUNDLE_FILE = addon.CA_BUNDLE

EGRESS_EVENT_PREFIX = "handler-egress "
"""stderr line prefix of egress events: `handler-egress {"decision": "denied", "host":
"host:port"}`; decisions: `allowed`, `denied`, `unlisted` (log only: let through, but no entry
allows it)."""


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

    def write(self, allow: list[str], enforcement: Filtering) -> None:
        # replaced whole: the proxy reads it while `set-egress` writes it
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"allow": allow, "enforcement": enforcement}))
        tmp.replace(self.file)

    def read(self) -> tuple[list[str], Filtering]:
        data = json.loads(self.file.read_text())
        return list(data["allow"]), data["enforcement"]


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
