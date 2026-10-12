"""Opening a terminal window on the desktop (an account's login, D.9): the person gets their own
terminal (its copy and paste, its clickable links), running a `handler` command.

The terminal is `$HANDLER_TERMINAL` (a command line, the command to run appended to it), else
the first of TERMINALS found on PATH. handlerd runs as a systemd user service, which may lack
WAYLAND_DISPLAY: it is given the display handlerd finds (display.py).
"""

import contextlib
import os
import shlex
import shutil
import subprocess
import sys
import threading
from collections.abc import Mapping
from pathlib import Path

from . import display

# each terminal and what precedes the command it runs
TERMINALS: list[tuple[str, list[str]]] = [
    ("ghostty", ["-e"]),
    ("xdg-terminal-exec", []),
    ("ptyxis", ["--new-window", "--"]),
    ("kgx", ["--"]),
    ("gnome-terminal", ["--"]),
    ("konsole", ["-e"]),
    ("xfce4-terminal", ["-x"]),
    ("alacritty", ["-e"]),
    ("kitty", []),
    ("foot", []),
    ("wezterm", ["start", "--"]),
    ("xterm", ["-e"]),
]


class TerminalError(RuntimeError):
    pass


def command(env: Mapping[str, str] | None = None) -> list[str]:
    """The terminal's command line, the command to run then appended; TerminalError if none."""
    env = os.environ if env is None else env
    if configured := env.get("HANDLER_TERMINAL"):
        return shlex.split(configured)
    for name, before in TERMINALS:
        if found := shutil.which(name, path=env.get("PATH")):
            return [found, *before]
    raise TerminalError("no terminal found: set HANDLER_TERMINAL for handlerd (e.g. 'kgx --')")


def handler() -> str:
    """The `handler` next to handlerd's interpreter (same install), else the one on PATH."""
    sibling = Path(sys.executable).parent / "handler"
    return str(sibling) if sibling.exists() else shutil.which("handler") or "handler"


def open_window(argv: list[str], env: Mapping[str, str]) -> str:
    """Run `argv` in a new terminal window, detached; `env` is added to handlerd's. The terminal's
    name, for saying which one opened."""
    terminal = command()
    full = dict(os.environ) | dict(env)
    if "WAYLAND_DISPLAY" not in full:  # else: an X11 session, or the terminal finds it (D-Bus)
        with contextlib.suppress(display.DisplayError):
            full["WAYLAND_DISPLAY"] = display.wayland_socket(full)
    try:
        proc = subprocess.Popen(
            [*terminal, *argv],
            env=full,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # outlives the request, and handlerd's restarts
        )
    except OSError as e:
        raise TerminalError(f"cannot start {terminal[0]}: {e.strerror}") from None
    threading.Thread(target=proc.wait, daemon=True).start()  # reaped when it exits
    return Path(terminal[0]).name
