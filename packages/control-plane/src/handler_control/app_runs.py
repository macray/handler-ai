"""Runs of agents started by apps (H.11): an app whose manifest needs a job
(`needs.agents.<name>`) starts runs of the agent the person gave it (H.2) on handler.sock, only
while it answers a request of the owner's (the request's START_HEADER: so the owner started the
run, as with the Run button). Which agent, and whether it still fits, is AppStore's.

    <state>/apps/<name>/runs.json   the app's last KEEP runs: which need and agent, its session,
                                    whether the inbox was told

A run is a session of the job (D.18, origin "app"): its state and result are its session's. When
it ends, the owner's inbox is told its result (or why it failed), opening the app.
"""

import asyncio
import contextlib
import json
import secrets
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from handler_contracts import (
    AppRun,
    AppRunState,
    SessionInput,
    SessionOutput,
)

from . import interfaces, save_rules
from .agents import AgentRecord
from .inbox import Inbox, told_result
from .projects import ProjectRegistry
from .sessions import SessionStore
from .settings import Settings

KEEP = 50
RUNS_PER_HOUR = 30
WATCH_POLL = 1.0


class AppRunError(Exception):
    """A request of an app's backend on handler.sock refused (a run that cannot be started or
    changed, a need its manifest lacks): its HTTP status, and why."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status


@dataclass
class RunRecord:
    id: str
    agent: str  # the need
    agent_id: str  # the agent given for it when the run started
    session_id: str
    at: str  # ISO 8601
    cancelled: bool = False
    told: bool = False  # the inbox was told how it ended


class AppRuns:
    def __init__(
        self, settings: Settings, sessions: SessionStore, projects: ProjectRegistry, inbox: Inbox
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.projects = projects
        self.inbox = inbox
        self.root = settings.state_dir / "apps"
        self.started: dict[str, list[float]] = {}  # app → recent start times (rate limit)
        self.watchers: set[asyncio.Task[None]] = set()

    def file(self, app: str) -> Path:
        return self.root / app / "runs.json"

    def load(self, app: str) -> list[RunRecord]:
        try:
            return [RunRecord(**r) for r in json.loads(self.file(app).read_text())]
        except FileNotFoundError:
            return []

    def save(self, app: str, runs: list[RunRecord]) -> None:
        path = self.file(app)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(r) for r in runs[-KEEP:]], indent=2))
        tmp.replace(path)

    def forget(self, app: str) -> None:
        """The app is removed: its runs' records go (their sessions stay with their agents)."""
        shutil.rmtree(self.root / app, ignore_errors=True)

    # ── handler.sock: /runs ─────────────────────────────────────────────

    def start(self, app: str, need: str, agent: AgentRecord, fields: dict[str, Any]) -> AppRun:
        """A run of the job given for `need`, the start token and the agent already checked
        (AppStore)."""
        assert agent.interface is not None
        given = SessionInput(fields=fields)
        try:
            subject = interfaces.check_input(agent.interface, given, self.settings.skills_dir)
        except interfaces.InterfaceError as e:
            raise AppRunError(400, f"input invalid: {e}") from None
        try:
            runs = save_rules.session_model(self.settings, agent, None)
        except save_rules.CheckError as e:
            raise AppRunError(409, f"agent {need}'s model: {e}") from None
        now = time.monotonic()
        recent = [t for t in self.started.get(app, []) if now - t < 3600]
        if len(recent) >= RUNS_PER_HOUR:
            raise AppRunError(429, f"at most {RUNS_PER_HOUR} runs an hour")
        self.started[app] = [*recent, now]
        session = self.sessions.create(
            agent, runs, origin="app", run=given, subject=subject, app=app
        )
        record = RunRecord(
            id="r_" + secrets.token_hex(8),
            agent=need,
            agent_id=agent.id,
            session_id=session.id,
            at=datetime.now(UTC).isoformat(),
        )
        self.save(app, [*self.load(app), record])
        self.watch(app, record.id)
        return self.view(record)

    def get(self, app: str, run_id: str) -> AppRun:
        return self.view(self.find(app, run_id))

    async def cancel(self, app: str, run_id: str) -> AppRun:
        record = self.find(app, run_id)
        if self.state(record)[0] not in ("waiting", "running"):
            raise AppRunError(409, f"run {run_id} has ended")
        self.update(app, run_id, cancelled=True)
        await self.sessions.stop(record.session_id, f"cancelled by the app {app}", "explicit")
        return self.get(app, run_id)

    def find(self, app: str, run_id: str) -> RunRecord:
        for record in self.load(app):
            if record.id == run_id:
                return record
        raise AppRunError(404, f"no run {run_id} of {app}")

    def update(self, app: str, run_id: str, **fields: Any) -> None:
        runs = self.load(app)
        self.save(app, [_replace(r, fields) if r.id == run_id else r for r in runs])

    # ── its state: its session's ────────────────────────────────────────

    def state(self, record: RunRecord) -> tuple[AppRunState, Any, str | None]:
        """(state, result, error), from its session."""
        rec = self.sessions.records.get(record.session_id)
        if rec is None:
            return "failed", None, "its session was deleted"
        sid = rec.id
        if sid in self.sessions.waits or rec.waiting_for is not None:
            return "waiting", None, None
        live = sid in self.sessions.live or sid in self.sessions.starting
        if live or rec.state in ("starting", "running"):
            return "running", None, None
        if record.cancelled:
            return "cancelled", None, None
        output = SessionOutput.model_validate(rec.output) if rec.output else None
        if output is not None and output.valid and isinstance(output.value, dict):
            return "succeeded", output.value, None
        why = (
            (output.error if output else None)
            or rec.error
            or f"its turn ended: {rec.last_stop_reason or 'no result'}"
        )
        return "failed", None, why

    def view(self, record: RunRecord) -> AppRun:
        state, result, error = self.state(record)
        return AppRun(
            id=record.id,
            agent=record.agent,
            session_id=record.session_id,
            state=state,
            at=datetime.fromisoformat(record.at),
            result=result,
            error=error,
        )

    # ── the inbox, when it ends ─────────────────────────────────────────

    def watch(self, app: str, run_id: str) -> None:
        task = asyncio.get_running_loop().create_task(self._watch(app, run_id))
        self.watchers.add(task)
        task.add_done_callback(self.watchers.discard)

    def start_watching(self, apps: list[str]) -> None:
        """At start: the runs whose end the inbox was not told (handlerd stopped meanwhile)."""
        for app in apps:
            for record in self.load(app):
                if not record.told:
                    self.watch(app, record.id)

    async def _watch(self, app: str, run_id: str) -> None:
        while True:
            try:
                record = self.find(app, run_id)
            except AppRunError:
                return  # the app was removed
            state, result, error = self.state(record)
            if state not in ("waiting", "running"):
                break
            await asyncio.sleep(WATCH_POLL)
        self.update(app, run_id, told=True)
        if state == "cancelled":
            return
        agent = self.projects.registry.get(record.agent_id)
        title = (agent.name if agent else None) or record.agent
        fields: dict[str, Any] = {
            "source": "app",
            "name": app,
            "agent": title,
            "person": "owner",
            "title": title,
            "session_id": record.session_id,
            "app": app,
        }
        if result is not None:
            self.inbox.add(**fields, **told_result(result))
        else:
            self.inbox.add(**fields, status="failed", summary=error)

    async def close(self) -> None:
        for task in list(self.watchers):
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*self.watchers, return_exceptions=True)


def _replace(record: RunRecord, fields: dict[str, Any]) -> RunRecord:
    return RunRecord(**asdict(record) | fields)
