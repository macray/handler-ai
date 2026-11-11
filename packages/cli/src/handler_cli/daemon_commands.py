"""`handler daemon …` — handlerd, the daemon that runs your agents, as a user service started with
your session: a systemd user service on Linux, a launchd agent on macOS. `handler setup`
installs it.

handler daemon status                is it up (its version, its address); if not, the service's
                                     state
handler daemon install [--dry-run]   write the service, enable and start it (--dry-run: print it)
handler daemon uninstall             stop and disable it, remove the service (configuration and
                                     state are kept)
handler daemon log [-f]              its log (-f: follow it)
"""

import argparse
import os
import plistlib
import pwd
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from .client import base_url

UNIT_NAME = "handler-ai.service"  # systemd
LABEL = "ai.handler.handlerd"  # launchd
NO_SYSTEMD = "no systemd here: handlerd's log is wherever you started it"


def handlerd_path() -> str:
    sibling = Path(sys.executable).parent / "handlerd"  # same installation as this CLI
    return str(sibling) if sibling.exists() else (shutil.which("handlerd") or "handlerd")


# Linux's, Apple's, Docker's (Desktop, OrbStack)
ENGINES_ON_PATH = ("podman", "container", "docker")
CARRIED = ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "DOCKER_HOST")
NOT_CARRIED = ("HANDLER_URL", "HANDLER_TEST_")  # the CLI's own; the tests' (credentials among them)


def service_path(bin_dir: str) -> str:
    """PATH for handlerd: it finds handler-sandbox-* next to itself; the container engine (podman,
    Apple's `container`, docker) must be on it too, also when only this shell's PATH has it
    (Docker Desktop's own folder)."""
    found = [str(Path(e).parent) for name in ENGINES_ON_PATH if (e := shutil.which(name))]
    folders = [bin_dir, *found, "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    return ":".join(dict.fromkeys(folders))


def service_env(bin_dir: str) -> dict[str, str]:
    """handlerd's environment as a service, which gets none of this shell's: its PATH, then what
    says where Handler keeps its files and listens (`HANDLER_*`, the XDG folders, HOME when it is
    not the account's), and DOCKER_HOST, so that the service is the handlerd this shell's
    `handler` talks to."""
    env = {"PATH": service_path(bin_dir)}
    for name, value in sorted(os.environ.items()):
        handler = name.startswith("HANDLER_") and not name.startswith(NOT_CARRIED)
        if handler or name in CARRIED:
            env[name] = value
    home = os.environ.get("HOME")
    if home and Path(home) != Path(pwd.getpwuid(os.getuid()).pw_dir):
        env["HOME"] = home
    return env


def macos() -> bool:
    return sys.platform == "darwin"


def wsl() -> bool:
    """Is this Windows' WSL (its kernel's release names Microsoft)."""
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError:
        return False


# ── systemd (Linux, WSL) ────────────────────────────────────────────────


def unit_path() -> Path:
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg / "systemd" / "user" / UNIT_NAME


def _environment_line(name: str, value: str) -> str:
    """One systemd `Environment=`, quoted (a value may hold spaces), `%` doubled (a specifier)."""
    quoted = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'Environment="{name}={quoted}"'


def unit_text() -> str:
    handlerd = handlerd_path()
    env = service_env(str(Path(handlerd).parent))
    environment = "\n".join(_environment_line(k, v) for k, v in env.items())
    return f"""[Unit]
Description=Handler control plane

[Service]
ExecStart={handlerd}
{environment}
Restart=on-failure

[Install]
WantedBy=default.target
"""


def _systemctl(*args: str) -> int:
    return subprocess.run(["systemctl", "--user", *args], check=False).returncode


# ── launchd (macOS) ─────────────────────────────────────────────────────


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "handler-ai" / "handlerd.log"


def plist_bytes() -> bytes:
    handlerd = handlerd_path()
    agent = {
        "Label": LABEL,
        "ProgramArguments": [handlerd],
        "EnvironmentVariables": service_env(str(Path(handlerd).parent)),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},  # restarted when it fails, as Restart=on-failure
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
    }
    return plistlib.dumps(agent)


def _launchctl(*args: str) -> int:
    return subprocess.run(["launchctl", *args], check=False).returncode


def _domain() -> str:
    return f"gui/{os.getuid()}"


# ── the commands ────────────────────────────────────────────────────────


def install(dry_run: bool) -> int:
    path, content = (
        (plist_path(), plist_bytes()) if macos() else (unit_path(), unit_text().encode())
    )
    if dry_run:
        print(f"# {path}\n{content.decode()}", end="")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    print(f"wrote {path}")
    if macos():
        log_path().parent.mkdir(parents=True, exist_ok=True)
        bootout = ["launchctl", "bootout", f"{_domain()}/{LABEL}"]  # an older one, if loaded
        subprocess.run(bootout, capture_output=True, check=False)
        return _launchctl("bootstrap", _domain(), str(path))
    return _systemctl("daemon-reload") or _systemctl("enable", "--now", UNIT_NAME)


def uninstall() -> int:
    if macos():
        _launchctl("bootout", f"{_domain()}/{LABEL}")
        plist_path().unlink(missing_ok=True)
        return 0
    _systemctl("disable", "--now", UNIT_NAME)
    unit_path().unlink(missing_ok=True)
    return _systemctl("daemon-reload")


def status() -> int:
    try:
        health = httpx.get(f"{base_url()}/v1/health", timeout=5).json()
    except httpx.HTTPError:
        print(f"handlerd is not reachable at {base_url()}")
        if macos():
            _launchctl("print", f"{_domain()}/{LABEL}")
        elif shutil.which("systemctl"):
            _systemctl("status", "--no-pager", UNIT_NAME)
        else:
            print(NO_SYSTEMD)
        return 1
    print(f"handlerd {health['version']} up at {base_url()}")
    return 0


def log(follow: bool) -> int:
    if macos():
        command = ["tail", "-n", "200", *(["-F"] if follow else []), str(log_path())]
    elif not shutil.which("journalctl"):
        print(NO_SYSTEMD)
        return 1
    else:
        command = ["journalctl", "--user", "-u", UNIT_NAME, "--no-pager", "-n", "200"]
        command += ["-f"] if follow else []
    return subprocess.run(command, check=False).returncode


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
