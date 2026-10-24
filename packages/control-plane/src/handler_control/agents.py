"""Agents — an agent is a model, a harness on an account or a provider (what; a session may run
with another, for that session only) working in a folder (where), with its own settings: network
(mode, enforcement, extra allowed hosts), confinement, permission mode, bindings (G.3), knowledge
folders (D.5) and a display (A.6). A registered endpoint that starts nothing; editable, with a
stable id.

Its home, given at creation and never changed: a project (`project_id`, projects.py: what it
gets from its project, folder, caches, skills, is resolved into its record, so what launches
sessions and sandboxes never needs to know about projects), an app (`app`: one of its parts,
H.14), Chat (`chat`: someone you talk to, D.1), or none: outside projects (D.1: `handler
run`, `handler acp`, `handler terminal`, or made on the Other folders page). An agent of no
project may have no folder: each of its sessions then works in a folder of its own (D.18).

Each ACP connection to an agent gets its own sandbox (see launcher.py). The registry persists the
definitions (agents.json) and keeps, in memory, the live connections and recent egress events.
"""

import asyncio
import json
import secrets
import subprocess
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import AwareDatetime, ConfigDict, Field

from handler_contracts import (
    AbsolutePath,
    AgentOrigin,
    AgentSettings,
    CacheSharing,
    Enforcement,
    HarnessName,
    ModelAccess,
)

from . import sandbox_process

MAX_EVENTS = 500
# a connection this young whose launcher runs may not have made its instance yet (A.4)
LAUNCHER_START_SECONDS = 10.0


@dataclass
class LiveConnection:
    id: str
    sandbox: str  # sandbox (container) name, used for set-egress / set-allow
    since: datetime
    process: Any  # asyncio.subprocess.Process of handler-sandbox-<impl>
    egress_base: list[str] | None = None  # filtered sandboxes: see StartedAgent.egress_base
    terminal: "RunsAs | None" = None  # a terminal's (D.16): the model it runs with


class RunsAs(ModelAccess):
    """A model an agent runs with, checked (E1): its harness resolved (None: the model alone,
    D.18)."""

    harness: HarnessName | None

    def same_access(self, harness: str | None, account: str | None, provider: str | None) -> bool:
        return (self.harness, self.account, self.provider) == (harness, account, provider)


class NotAgentsModelError(ValueError):
    """Another model than the agent's (a session or a terminal may still run with it, D.19)."""


class CheckedSettings(AgentSettings):
    """An agent's settings once checked (E1, D.13, G3, D.5, A.6, D.18): its model's harness
    resolved, the folder it works in known (an ad-hoc agent's scope, its project's folder; None:
    a folderless agent's sessions each get their own)."""

    model: RunsAs
    scope: AbsolutePath | None

    def runs_as(self, given: ModelAccess | None = None) -> RunsAs:
        """The model a session runs with: `given` (its harness may be left out, an account's),
        else the agent's. NotAgentsModelError when `given` is not the agent's."""
        m = self.model
        if given is None:
            return m
        same = (given.account, given.provider, given.model) == (m.account, m.provider, m.model)
        if same and given.harness in (None, m.harness):
            return m
        raise NotAgentsModelError(f"the agent's model is not {describe(given)}")

    def resumes_as(
        self,
        harness: str | None,
        account: str | None,
        provider: str | None,
        model: str | None,
        *,
        agents_model: bool,
    ) -> RunsAs:
        """The model a session started with that harness, account or provider and model starts
        or resumes with: the same, when it is still the agent's or when it was picked for the
        session alone (D.19); else, started with the agent's model since changed, the agent's
        new one when on the same harness and access (else the session's own)."""
        own = RunsAs(harness=harness, account=account, provider=provider, model=model)
        if own == self.model or not agents_model:
            return own
        return self.model if self.model.same_access(harness, account, provider) else own


def describe(m: ModelAccess) -> str:
    """`claude-code on account claude-pro (opus)`, for messages."""
    access = f"account {m.account}" if m.account else f"provider {m.provider}"
    harness = f"{m.harness} on " if m.harness else ""
    return f"{harness}{access}" + (f" ({m.model})" if m.model else "")


class AgentRecord(CheckedSettings):
    """A registered agent: its settings, who it is, and its live state (not persisted)."""

    model_config = ConfigDict(frozen=False)

    id: str = ""
    name: str | None = None  # its name (of no project: optional)
    project_id: str | None = None  # its home: the project it is an agent of (projects.py)
    app: str | None = None  # its home: the app it is one of the parts of (H.14)
    chat: bool = False  # its home: Chat, someone you talk to (D.1)
    description: str | None = None  # an agent's: what it is for
    instructions: str | None = None  # an agent's: sent before the request starting a session
    remote_start: bool = False  # an agent's: paired devices may start sessions with it
    caches: CacheSharing = "global"  # resolved: its project's choice (caches.py)
    area: str | None = None  # resolved: its project's area (areas.py, D.19)
    skills: list[str] = []  # the skills it picked (D.17)
    origin: AgentOrigin | None = None  # what it is set up from (D.23, H.2)
    project_skills: list[str] = []  # resolved: its project's (D.17)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    last_used_at: AwareDatetime | None = None
    connections: dict[str, LiveConnection] = Field(default_factory=dict, exclude=True)
    events: deque[dict[str, Any]] = Field(
        default_factory=lambda: deque(maxlen=MAX_EVENTS), exclude=True
    )

    @property
    def settings(self) -> CheckedSettings:
        return CheckedSettings.model_validate(self.model_dump(include=_SETTINGS))

    def set_settings(self, settings: CheckedSettings) -> None:
        for key in _SETTINGS:
            setattr(self, key, getattr(settings, key))


_SETTINGS = set(CheckedSettings.model_fields)


class AgentRegistry:
    def __init__(self, state_dir: Path) -> None:
        self.file = state_dir / "agents.json"
        self.agents: dict[str, AgentRecord] = {}
        self.listeners: list[Callable[[], None]] = []  # told after each save (image_updates)
        self._load()

    def _load(self) -> None:
        if not self.file.exists():
            return
        for r in json.loads(self.file.read_text()):
            record = AgentRecord.model_validate(r)
            self.agents[record.id] = record

    def save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        records = [r.model_dump(mode="json", by_alias=True) for r in self.agents.values()]
        tmp.write_text(json.dumps(records, indent=2))
        tmp.replace(self.file)
        for listener in self.listeners:
            listener()

    def outside(self, scope: str | None, name: str | None) -> AgentRecord | None:
        """The agent of no home working in `scope` under `name` (None: the unnamed one; names
        compared without case): outside projects, an agent is its folder and its name (D.1)."""
        key = (name or "").strip().lower()
        for record in self.agents.values():
            same = (record.scope, (record.name or "").lower()) == (scope, key)
            if record.project_id is None and record.app is None and not record.chat and same:
                return record
        return None

    def add(self, record: AgentRecord) -> AgentRecord:
        """Register it under a new id; its settings already checked (agent_service.py)."""
        aid = secrets.token_hex(6)
        while aid in self.agents:
            aid = secrets.token_hex(6)
        record.id = aid
        self.agents[aid] = record
        self.save()
        return record

    def set_instructions(self, record: AgentRecord, instructions: str | None) -> None:
        """Only its instructions changed (an improvement's attempt kept, D.21), already checked
        against its form (save_rules.check_instructions)."""
        record.instructions = instructions
        self.save()

    def get(self, aid: str) -> AgentRecord | None:
        return self.agents.get(aid)

    def delete(self, aid: str) -> AgentRecord | None:
        record = self.agents.pop(aid, None)
        if record:
            self.save()
        return record

    def set_egress(self, record: AgentRecord, egress: Enforcement) -> None:
        record.egress = egress
        self.save()

    def touch(self, record: AgentRecord) -> None:
        """It is being used now: lists show the most recently used first."""
        record.last_used_at = datetime.now(UTC)
        self.save()

    def add_event(self, record: AgentRecord, connection: str, event: dict[str, str]) -> None:
        record.events.append({"t": datetime.now(UTC), "connection": connection} | event)


# ── live connections (A.4) ──────────────────────────────────────────────


def chats(agents: Iterable[AgentRecord]) -> list[AgentRecord]:
    """Who you talk to in Chat (D.1), the one used last first."""
    found = [a for a in agents if a.chat]
    return sorted(found, key=lambda a: a.last_used_at or a.created_at, reverse=True)


async def apply_network(record: AgentRecord, egress: Enforcement | None = None) -> list[str]:
    """On an agent's running filtered sandboxes: the allow-list as now set (the required
    hosts as they started, its own as now), and `egress` if given (A.4). Other changes (mode,
    bindings…) apply to new connections only. Returns failures."""
    failures = []
    for conn in list(record.connections.values()):
        if conn.egress_base is None:
            continue  # not a filtered sandbox
        allow = sorted(set(conn.egress_base) | set(record.allow))
        error = await _on_sandbox(conn, sandbox_process.set_allow, allow)
        if error is None and egress:
            error = await sandbox_process.set_egress(conn.sandbox, egress)
        if error:
            failures.append(f"{conn.id}: {error}")
    return failures


async def switch_egress(record: AgentRecord, egress: Enforcement) -> list[str]:
    """The enforcement of every live connection of the agent switched (A.4); returns failures."""
    failures = []
    for conn in list(record.connections.values()):
        if error := await _on_sandbox(conn, sandbox_process.set_egress, egress):
            failures.append(f"{conn.id}: {error}")
    return failures


async def _on_sandbox[T](
    conn: LiveConnection, verb: Callable[[str, T], Awaitable[str | None]], arg: T
) -> str | None:
    """A live verb on a connection's sandbox (A.4). The sandbox waits for an instance still
    starting once its launcher has made its folder; before that (the launcher's own start), it
    is tried again while the launcher runs."""
    while True:
        error = await verb(conn.sandbox, arg)
        young = (datetime.now(UTC) - conn.since).total_seconds() < LAUNCHER_START_SECONDS
        if error is None or not young or not _launcher_runs(conn.process):
            return error
        await asyncio.sleep(0.1)


def _launcher_runs(process: Any) -> bool:
    """A session's or connection's launcher (asyncio), or a terminal's (subprocess.Popen)."""
    return (process.poll() if isinstance(process, subprocess.Popen) else process.returncode) is None
