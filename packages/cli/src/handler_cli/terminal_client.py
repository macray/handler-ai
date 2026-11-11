"""`handler terminal`: this terminal attached to a harness's own terminal program in its sandbox
(D.16). handlerd starts the sandbox, then this process runs the sandbox's `attach` command: raw
while it runs (every key goes to the program, Ctrl-C included), resized with this terminal, its
exit code the program's; closing the terminal stops the sandbox. handlerd is not in between, so it
can restart meanwhile. On a terminal, `attach` runs on a terminal of its own relayed to this one,
so that the paste key first puts the clipboard's image where the program reads it (paste.py);
stdin piped, this process becomes `attach`.
"""

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, NoReturn

from handler_contracts import TerminalStart, TerminalStarted, terminal_path

from . import paste
from .client import Daemon
from .on_terminal import on_terminal

_TERM = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
START_TIMEOUT = 600.0  # seconds: handlerd's own limit (a first start may build the proxy's image)


def _start(args: list[str], model: dict[str, Any] | None, folder: str) -> TerminalStart:
    term = os.environ.get("TERM", "")
    colorterm = os.environ.get("COLORTERM", "")
    extra: dict[str, Any] = {"term": term} if _TERM.match(term) else {}
    if _TERM.match(colorterm):
        extra["colorterm"] = colorterm
    if model is not None:
        extra["model"] = model
    return TerminalStart(args=args, folder=folder, **extra)


def run(
    d: Daemon, agent_id: str, args: list[str], folder: str, model: dict[str, Any] | None = None
) -> NoReturn:
    """The agent's terminal in `folder` (the agent's or one inside it, the only one mounted), with
    `model` (the agent's or another; default: the agent's); ClientError when it cannot start."""
    body = _start(args, model, folder).model_dump(mode="json", by_alias=True, exclude_none=True)
    raw = d.call("POST", terminal_path(agent_id), body, timeout=START_TIMEOUT)
    started = TerminalStarted.model_validate(raw)
    if not sys.stdin.isatty():
        os.execvp(started.attach[0], started.attach)
    argv = [shutil.which(started.attach[0]) or started.attach[0], *started.attach[1:]]
    sys.exit(on_terminal(argv, os.environ, os.getcwd(), paste.watcher(Path(started.paste))))
