"""`handler terminal`: this terminal attached to a harness's own terminal program in its sandbox
(D.16). handlerd starts the sandbox, then this process becomes the sandbox's `attach` command: raw
while it runs (every key goes to the program, Ctrl-C included), resized with this terminal, its
exit code the program's; closing the terminal stops the sandbox. handlerd is not in between, so it
can restart meanwhile.
"""

import os
import re
from typing import Any, NoReturn

from handler_contracts import TerminalStart, TerminalStarted, terminal_path

from .client import Daemon

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
    os.execvp(started.attach[0], started.attach)
