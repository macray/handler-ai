"""Which launcher made a sandbox's resources, and whether it still runs (`sweep` removes what dead
launchers left, never what a live one is still setting up, contract A).

A launcher is its pid and its start time: a pid alone later names another process (pids are
reused, after a reboot from the first ones). The start time comes from /proc where there is one
(Linux: clock ticks since boot), else from `ps` (macOS: to the second).
"""

import os
import subprocess
from pathlib import Path

PROC = Path("/proc")

# the labels every runtime puts on what it creates: Handler's, which sandbox, which launcher
MANAGED_LABEL = "handler.managed"
SANDBOX_LABEL = "handler.sandbox"
LAUNCHER_LABEL = "handler.launcher"


def launcher_label() -> str:
    """This process: `<pid>:<start time>`, to put on what it creates."""
    return f"{os.getpid()}:{start_time(os.getpid())}"


def launcher_alive(label: str) -> bool:
    """The launcher a launcher_label() value names still runs."""
    pid, _, started = label.partition(":")
    return pid.isdigit() and started != "" and start_time(int(pid)) == started


def start_time(pid: int) -> str | None:
    """When process `pid` started, None when there is no such process."""
    if PROC.is_dir():
        try:
            stat = (PROC / str(pid) / "stat").read_text()
        except OSError:
            return None
        return stat.rsplit(")", 1)[1].split()[19]  # field 22, after the name (may hold ")")
    try:
        ps = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return "-".join(ps.stdout.split()) or None  # "Sat Oct 25 19:28:34 2026", one word
