"""Handler's needs (D.18): its own features that need an agent (the skill review needs a
reviewer), each given one by the person as an app's needs are (H.2). Handler ships the definition
an agent is set up from for each; the UI calls the agent given a helper.

    data/handler-needs/<name>/   need.toml (what the agent does for Handler, the definition's
                                 version) + the definition (definitions.py)
    <state>/handler-needs.json   the agent given for each: need name → agent id

An agent set up for one keeps its origin (kind "handler-need", its name and version).
"""

import json
import tomllib
from pathlib import Path

from handler_contracts import AgentInterface, AgentOrigin, HandlerNeed

from . import definitions, interfaces, skills
from .files import write_private

ROOT = Path(__file__).parent / "data" / "handler-needs"
GIVEN_FILE = "handler-needs.json"


class NeedError(ValueError):
    def __init__(self, status: int, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.title = status, title


def read(folder: Path) -> HandlerNeed:
    meta = tomllib.loads((folder / "need.toml").read_text())
    return HandlerNeed(name=folder.name, definition=definitions.read(folder), **meta)


def load_all() -> list[HandlerNeed]:
    """Every need, the agent given for none (the API's view says)."""
    return [read(p) for p in sorted(ROOT.iterdir()) if p.is_dir()]


def get(name: str) -> HandlerNeed | None:
    found = ROOT / name
    return read(found) if skills.NAME.fullmatch(name) and found.is_dir() else None


def origin(need: HandlerNeed) -> AgentOrigin:
    return AgentOrigin(kind="handler-need", name=need.name, version=need.version)


def folder(origin: AgentOrigin) -> Path:
    """The definition an origin sets up (its current version only)."""
    need = get(origin.name)
    if need is None:
        raise NeedError(400, "unknown handler need", origin.name)
    if origin.version != need.version:
        now = f"{need.name} is at version {need.version}, not {origin.version}"
        raise NeedError(409, "handler need changed", now)
    return ROOT / need.name


def given(state_dir: Path) -> dict[str, str]:
    """The agent given for each need: name → agent id."""
    try:
        return dict(json.loads((state_dir / GIVEN_FILE).read_text()))
    except FileNotFoundError:
        return {}


def give(state_dir: Path, name: str, agent_id: str) -> None:
    write_private(state_dir / GIVEN_FILE, json.dumps(given(state_dir) | {name: agent_id}, indent=2))


def forget(state_dir: Path, agent_id: str) -> None:
    """A deleted agent is given for no need any more: Handler uses none until you give another."""
    now = given(state_dir)
    if agent_id in now.values():
        kept = {name: aid for name, aid in now.items() if aid != agent_id}
        write_private(state_dir / GIVEN_FILE, json.dumps(kept, indent=2))


def misfit(
    need: HandlerNeed,
    origin: AgentOrigin | None,
    interface: AgentInterface | None,
    scope: str | None,
) -> str | None:
    """Why an agent (its origin, its interface, its folder) cannot be given for a need, None when
    it fits: a job's form and result fit (interfaces.misfit, as an app's need, H.2); a chat says
    nothing of what it does, so only one set up for that need fits, with no folder (each session
    works on a copy: a skill, an app's draft)."""
    wanted = need.definition.interface
    if wanted is not None and wanted.result is not None:
        return interfaces.misfit(wanted, interface)
    name = need.definition.agent_name
    if origin is None or (origin.kind, origin.name) != ("handler-need", need.name):
        return f"only an agent set up as the {name} fits"
    if scope is not None:
        return f"the {name} has no folder: each session works on a copy"
    return None
