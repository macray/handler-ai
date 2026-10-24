"""D.16 — a harness's own terminal program in a sandbox (`handler terminal`): the request that
starts it and what the client then runs to attach its terminal to it."""

from typing import Annotated
from urllib.parse import quote

from pydantic import Field

from .common import AbsolutePath, Document
from .control import ModelAccess


class TerminalStart(Document):
    """The client's terminal type, arguments for the harness's program, the folder it works in."""

    term: Annotated[str, Field(pattern=r"^[A-Za-z0-9._+-]{1,64}$")] = "xterm-256color"
    colorterm: Annotated[str, Field(pattern=r"^[A-Za-z0-9._+-]{1,64}$")] | None = None
    args: list[str] = []
    # any model its project's area allows (D.19), the agent's or not; default: the agent's
    model: ModelAccess | None = None
    # the client's directory, inside the agent's folder: the only one mounted, instead of the
    # agent's (a project's sub-folder); default: the agent's folder
    folder: AbsolutePath | None = None


class TerminalStarted(Document):
    """The sandbox is ready: the client runs `attach` on its own terminal (A.7, `attach`)."""

    sandbox: str
    attach: list[str]  # the sandbox's executable and its arguments


def terminal_path(agent_id: str) -> str:
    """URL path of an agent's terminal endpoint."""
    return f"/v1/agents/{quote(agent_id, safe='')}/terminal"
