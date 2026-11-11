"""Opening a terminal window on the desktop (an account's login, D.9): the person gets their own
terminal (its copy and paste, its clickable links), running a `handler` command.

The terminal is `$HANDLER_TERMINAL` (a command line, the command to run appended to it), else on
a Mac Terminal.app, else the first of TERMINALS found on PATH. handlerd runs as a systemd user
service, which may lack WAYLAND_DISPLAY: it is given the display handlerd finds (display.py).
Terminal.app, opened by `open`, gets none of handlerd's environment: the command and its
variables go in a `.command` file it runs, which removes itself first.
"""

import contextlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
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


def _macos() -> bool:
    return sys.platform == "darwin"


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
    if _macos() and not os.environ.get("HANDLER_TERMINAL"):
        return _terminal_app(argv, env)
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


def _terminal_app(argv: list[str], env: Mapping[str, str]) -> str:
    """Run `argv` in a new Terminal.app window: a `.command` file of handlerd's user only, which
    sets `env`, removes itself, then runs `argv` (the window is the user's login shell's)."""
    exports = "".join(f"export {k}={shlex.quote(v)}\n" for k, v in env.items())
    script = f'#!/bin/sh\nrm -f "$0"\n{exports}exec {shlex.join(argv)}\n'
    fd, path = tempfile.mkstemp(prefix="handler-login-", suffix=".command")  # mode 0600
    with os.fdopen(fd, "w") as f:
        f.write(script)
    os.chmod(path, 0o700)
    try:
        opened = subprocess.run(["open", "-a", "Terminal", path], capture_output=True, check=False)
    except OSError as e:
        opened = None
        error = e.strerror
    if opened is None or opened.returncode:
        Path(path).unlink(missing_ok=True)
        error = error if opened is None else opened.stderr.decode(errors="replace").strip()
        raise TerminalError(f"cannot open Terminal: {error}")
    return "Terminal"
