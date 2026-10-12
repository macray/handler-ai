"""Agents — an agent is a list of models, each a harness on an account or a provider (what, one
per session) working in a folder (where), with its own settings: network (mode, enforcement,
extra allowed hosts), confinement, permission mode, bindings (G.3), knowledge folders (D.5) and a
display (A.6). A registered endpoint that starts nothing; editable, with a stable id.

An agent of a project (projects.py) has a `project_id`: what it gets from its project (folder,
caches, skills) is resolved into its record, so what launches sessions and sandboxes never needs
to know about projects. An ad-hoc agent has none (D.1: `handler run`, `handler acp`, `handler
terminal` outside projects, or made in the web UI); it may have no folder either: each of its
sessions then works in a folder of its own (D.18).

Each ACP connection to an agent gets its own sandbox (see launcher.py). The registry persists the
definitions (agents.json) and keeps, in memory, the live connections and recent egress events.
"""

import json
import secrets
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from pydantic import AwareDatetime, ConfigDict, Field

from handler_contracts import (
    AbsolutePath,
    AgentSettings,
    CacheSharing,
    Enforcement,
    HarnessName,
    ModelAccess,
)

from . import sandbox_process

MAX_EVENTS = 500


@dataclass
class LiveConnection:
    id: str
    sandbox: str  # sandbox (container) name, used for set-egress / set-allow
    since: datetime
    process: Any  # asyncio.subprocess.Process of handler-sandbox-<impl>
    egress_base: list[str] | None = None  # filtered sandboxes: see StartedAgent.egress_base
    terminal: "RunsAs | None" = None  # a terminal's (D.16): the model it runs with


class RunsAs(ModelAccess):
    """One of an agent's models, checked (E1): its harness resolved."""

    harness: HarnessName

    def same_access(self, harness: str, account: str | None, provider: str | None) -> bool:
        return (self.harness, self.account, self.provider) == (harness, account, provider)


class ModelNotListedError(ValueError):
    """A model the agent does not list (a session or a terminal may still run with it, D.19)."""


class CheckedSettings(AgentSettings):
    """An agent's settings once checked (E1, D.13, G3, D.5, A.6, D.18): each model's harness
    resolved, the folder it works in known (an ad-hoc agent's scope, its project's folder; None:
    a folderless agent's sessions each get their own)."""

    models: list[RunsAs]
    scope: AbsolutePath | None

    def runs_as(self, given: ModelAccess | None = None) -> RunsAs:
        """The model a session runs with: `given` (its harness may be left out, an account's),
        else the first. ModelNotListedError when the agent does not list it."""
        if given is None:
            return self.models[0]
        for m in self.models:
            same = (given.account, given.provider, given.model) == (m.account, m.provider, m.model)
            if same and given.harness in (None, m.harness):
                return m
        raise ModelNotListedError(f"the agent has no model {describe(given)}")

    def resumes_as(
        self, harness: str, account: str | None, provider: str | None, model: str | None
    ) -> RunsAs:
        """The model a session started with that harness, account or provider and model resumes
        with: the agent's on the same harness and access (its model may have changed since), else
        the session's own: a session may run with a model the agent does not list (D.19)."""
        same = [m for m in self.models if m.same_access(harness, account, provider)]
        own = RunsAs(harness=harness, account=account, provider=provider, model=model)
        return next((m for m in same if m.model == model), same[0] if same else own)


def describe(m: ModelAccess) -> str:
    """`claude-code on account claude-pro (opus)`, for messages."""
    access = f"account {m.account}" if m.account else f"provider {m.provider}"
    harness = f"{m.harness} on " if m.harness else ""
    return f"{harness}{access}" + (f" ({m.model})" if m.model else "")


class AdHocOwn(NamedTuple):
    """What an ad-hoc agent has besides its settings (an agent of a project: through it)."""

    description: str | None = None
    instructions: str | None = None
    skills: list[str] = []
    origin: str | None = None  # the built-in agent it is (builtin_agents.py)


class AgentRecord(CheckedSettings):
    """A registered agent: its settings, who it is, and its live state (not persisted)."""

    model_config = ConfigDict(frozen=False)

    id: str = ""
    name: str | None = None  # its name (ad-hoc agents: optional)
    project_id: str | None = None  # the project it is an agent of (projects.py)
    description: str | None = None  # an agent's: what it is for
    instructions: str | None = None  # an agent's: sent before the request starting a session
    remote_start: bool = False  # an agent's: paired devices may start sessions with it
    caches: CacheSharing = "global"  # resolved: its project's choice (caches.py)
    context: str | None = None  # resolved: its project's context (contexts.py, D.19)
    skills: list[str] = []  # the skills it picked (D.17)
    origin: str | None = None  # the built-in agent it is, at most one each (D.18)
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

    def ad_hoc(self, scope: str | None, name: str | None) -> AgentRecord | None:
        """The ad-hoc agent working in `scope` under `name` (None: the unnamed one; names compared
        without case): an ad-hoc agent is its folder and its name (D.1)."""
        key = (name or "").strip().lower()
        for record in self.agents.values():
            same = (record.scope, (record.name or "").lower()) == (scope, key)
            if record.project_id is None and same:
                return record
        return None

    def create(
        self, settings: CheckedSettings, name: str | None = None, own: AdHocOwn | None = None
    ) -> AgentRecord:
        """A new ad-hoc agent; its settings already checked (scope, bindings, knowledge), its
        folder and name not taken (`ad_hoc`)."""
        name = (name or "").strip() or None
        return self.add(
            AgentRecord(**settings.model_dump(), name=name, **(own or AdHocOwn())._asdict())
        )

    def add(self, record: AgentRecord) -> AgentRecord:
        """Register it under a new id (not idempotent: agents of projects)."""
        aid = secrets.token_hex(6)
        while aid in self.agents:
            aid = secrets.token_hex(6)
        record.id = aid
        self.agents[aid] = record
        self.save()
        return record

    def update(
        self,
        record: AgentRecord,
        settings: CheckedSettings,
        name: str | None,
        own: AdHocOwn | None = None,
    ) -> None:
        """Replace its settings and name (an ad-hoc agent: and its own fields); live connections
        keep running (the caller applies what can change live)."""
        record.set_settings(settings)
        record.name = (name or "").strip() or None
        if own is not None:
            record.description, record.instructions, record.skills, record.origin = own
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


async def apply_network(record: AgentRecord, egress: Enforcement | None = None) -> list[str]:
    """On an agent's running filtered sandboxes: the allow-list as now set (the required
    hosts as they started, its own as now), and `egress` if given (A.4). Other changes (mode,
    bindings…) apply to new connections only. Returns failures."""
    failures = []
    for conn in list(record.connections.values()):
        if conn.egress_base is None:
            continue  # not a filtered sandbox
        allow = sorted(set(conn.egress_base) | set(record.allow))
        error = await sandbox_process.set_allow(conn.sandbox, allow)
        if error is None and egress:
            error = await sandbox_process.set_egress(conn.sandbox, egress)
        if error:
            failures.append(f"{conn.id}: {error}")
    return failures


async def switch_egress(record: AgentRecord, egress: Enforcement) -> list[str]:
    """The enforcement of every live connection of the agent switched (A.4); returns failures."""
    failures = []
    for conn in list(record.connections.values()):
        if error := await sandbox_process.set_egress(conn.sandbox, egress):
            failures.append(f"{conn.id}: {error}")
    return failures
