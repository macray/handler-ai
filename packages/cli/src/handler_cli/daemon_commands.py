"""`handler daemon …` — handlerd, the daemon that runs your agents, as a systemd user service
(started with your session). `handler setup` installs it.

handler daemon status                is it up (its version, its address); if not, the service's
                                     state
handler daemon install [--dry-run]   write the unit, enable and start it (--dry-run: print it)
handler daemon uninstall             stop and disable it, remove the unit (configuration and state
                                     are kept)
handler daemon log [-f]              its log (journalctl; -f: follow it)
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from .client import base_url

UNIT_NAME = "handler-ai.service"


def unit_path() -> Path:
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg / "systemd" / "user" / UNIT_NAME


def handlerd_path() -> str:
    sibling = Path(sys.executable).parent / "handlerd"  # same installation as this CLI
    return str(sibling) if sibling.exists() else (shutil.which("handlerd") or "handlerd")


def unit_text() -> str:
    handlerd = handlerd_path()
    bin_dir = str(Path(handlerd).parent)
    return f"""[Unit]
Description=Handler control plane

[Service]
ExecStart={handlerd}
# handlerd finds handler-sandbox-* next to itself; podman must be on PATH.
Environment=PATH={bin_dir}:/usr/local/bin:/usr/bin:/bin
Restart=on-failure

[Install]
WantedBy=default.target
"""


def _systemctl(*args: str) -> int:
    return subprocess.run(["systemctl", "--user", *args], check=False).returncode


def install(dry_run: bool) -> int:
    if dry_run:
        print(f"# {unit_path()}\n{unit_text()}", end="")
        return 0
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit_text())
    print(f"wrote {path}")
    return _systemctl("daemon-reload") or _systemctl("enable", "--now", UNIT_NAME)


def uninstall() -> int:
    _systemctl("disable", "--now", UNIT_NAME)
    unit_path().unlink(missing_ok=True)
    return _systemctl("daemon-reload")


def status() -> int:
    try:
        health = httpx.get(f"{base_url()}/v1/health", timeout=5).json()
    except httpx.HTTPError:
        print(f"handlerd is not reachable at {base_url()}")
        _systemctl("status", "--no-pager", UNIT_NAME)
        return 1
    print(f"handlerd {health['version']} up at {base_url()}")
    return 0


def log(follow: bool) -> int:
    command = ["journalctl", "--user", "-u", UNIT_NAME, "--no-pager", "-n", "200"]
    return subprocess.run([*command, *(["-f"] if follow else [])], check=False).returncode


def add_parser(sub: Any) -> None:
    daemon = sub.add_parser("daemon", help="handlerd as a user service", description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    a = daemon.add_subparsers(dest="daemon_cmd", required=True)
    a.add_parser("status")
    a.add_parser("install").add_argument("--dry-run", action="store_true")
    a.add_parser("uninstall")
    a.add_parser("log").add_argument("-f", "--follow", action="store_true")


def dispatch(args: argparse.Namespace) -> int:
    if args.daemon_cmd == "install":
        return install(args.dry_run)
    if args.daemon_cmd == "uninstall":
        return uninstall()
    if args.daemon_cmd == "log":
        return log(args.follow)
    return status()
