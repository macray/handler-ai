"""Runs started by apps (H.11): of one of its jobs (H.1), run by the Who works the person chose
for it (H.2); started on handler.sock only while it answers a request of the owner's (the
request's START_HEADER: so the owner started the run, as with the Run button), by one of its
actions, or by an automation. Which job, and who runs it, is AppStore's.

    <state>/apps/<name>/runs.json   the app's last KEEP runs: which job, what started it (its
                                    code, one of its actions and how it was asked, an
                                    automation), the fields it was given, its session,
                                    whether the inbox was told

The app lists them (`GET /runs`, newest first), each with what it was asked, and keeps none of
its own.

A run is a session (D.18, origin "app" or "automation", with no agent: F): its state and result are its
session's. When it ends, its job's `then` route is called once (rule app-job.then-called-once),
then the owner's inbox is told its result (or why it failed), opening the app.
"""

import asyncio
import contextlib
import json
import secrets
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from handler_contracts import (
    AppRun,
    AppRunStartedBy,
    AppRunState,
    SessionInput,
    SessionOutput,
)

from . import agent_state, interfaces
from .agents import AgentRecord, RunsAs
from .inbox import Inbox, told_result
from .launcher import JobPlace
from .sessions import JobRun, SessionStore
from .settings import Settings

KEEP = 50
RUNS_PER_HOUR = 30
WATCH_POLL = 1.0
# kept while its `then` is called: what stays if handlerd stops before it answered
THEN_CUT = "handlerd stopped while calling it: not called again"

# calls a job's `then` route of an app (AppStore.call_then): None, or why it failed
ThenCall = Callable[[str, str, dict[str, Any]], Awaitable[str | None]]


class AppRunError(Exception):
    """A request of an app's backend on handler.sock refused (a run that cannot be started or
    changed, a need its manifest lacks): its HTTP status, and why."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status


@dataclass
class RunRecord:
    id: str
    job: str  # the job it runs (H.1)
    started_by: dict[str, Any]  # AppRunStartedBy: its code, one of its actions, an automation
    session_id: str
    at: str  # ISO 8601
    fields: dict[str, Any]  # the fields its run was given (H.11)
    cancelled: bool = False
    told: bool = False  # the inbox was told how it ended
    then: str | None = None  # its job's `then` route when it started (H.1)
    then_called: bool = False  # it was called (or is being called): never again
    then_error: str | None = None  # why it failed (THEN_CUT while it is called)


class AppRuns:
    def __init__(self, settings: Settings, sessions: SessionStore, inbox: Inbox) -> None:
        self.settings = settings
        self.sessions = sessions
        self.inbox = inbox
        self.root = settings.state_dir / "apps"
        self.started: dict[str, list[float]] = {}  # app → recent start times (rate limit)
        self.watchers: set[asyncio.Task[None]] = set()
        self.call_then: ThenCall | None = None  # set by the AppStore
        self.calling: set[str] = set()  # runs whose `then` is being called

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

    async def forget(self, app: str) -> None:
        """The app is removed: its runs' records go, its jobs' runs (their sessions) and its
        harness state with them (rule app.uninstalled-leaves-nothing-of-it)."""
        shutil.rmtree(self.root / app, ignore_errors=True)
        for rec in self.sessions.list():
            if rec.app == app and rec.job is not None:
                await self.sessions.delete(rec.id)
        shutil.rmtree(agent_state.app_folder(self.settings.data_dir, app), ignore_errors=True)

    # ── handler.sock: /runs ─────────────────────────────────────────────

    def start_job(
        self,
        app: str,
        job: str,
        *,
        stand_in: AgentRecord,
        runs: RunsAs,
        place: tuple[JobPlace, str],
        fields: dict[str, Any],
        started_by: AppRunStartedBy,
        then: str | None = None,
    ) -> AppRun:
        """A run of one of the app's jobs (H.1), with no agent: `stand_in` launches it on the
        Who works' model `runs`, in `place` (and its request's section naming its folders), all
        checked (AppStore, app_jobs); `started_by`: its code, one of its actions, or an
        automation; `then`: its job's route, called once when it ends."""
        assert stand_in.interface is not None
        given = SessionInput(fields=fields)
        try:
            subject = interfaces.check_input(stand_in.interface, given, self.settings.skills_dir)
        except interfaces.InterfaceError as e:
            raise AppRunError(400, f"input invalid: {e}") from None
        self.count_start(app)
        work = JobRun(app=app, name=job, agent=stand_in, place=place[0], folders=place[1])
        origin = "automation" if started_by.by == "automation" else "app"
        session = self.sessions.create(
            stand_in, runs, origin=origin, run=given, subject=subject, app=app, job=work
        )
        record = RunRecord(
            id="r_" + secrets.token_hex(8),
            job=job,
            then=then,
            started_by=started_by.model_dump(mode="json"),
            fields=fields,
            session_id=session.id,
            at=datetime.now(UTC).isoformat(),
        )
        return self.started_run(app, record)

    def count_start(self, app: str) -> None:
        """At most RUNS_PER_HOUR runs of its jobs an hour."""
        now = time.monotonic()
        recent = [t for t in self.started.get(app, []) if now - t < 3600]
        if len(recent) >= RUNS_PER_HOUR:
            raise AppRunError(429, f"at most {RUNS_PER_HOUR} runs an hour")
        self.started[app] = [*recent, now]

    def started_run(self, app: str, record: RunRecord) -> AppRun:
        self.save(app, [*self.load(app), record])
        self.watch(app, record.id)
        return self.view(record)

    def get(self, app: str, run_id: str) -> AppRun:
        return self.view(self.find(app, run_id))

    def recent(self, app: str) -> list[AppRun]:
        """The app's runs handlerd keeps (the last KEEP), newest first."""
        return [self.view(r) for r in reversed(self.load(app))]

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
        self.save(app, [replace(r, **fields) if r.id == run_id else r for r in runs])

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
        rec = self.sessions.records.get(record.session_id)
        ended = rec is not None and state not in ("waiting", "running")
        return AppRun(
            id=record.id,
            job=record.job,
            started_by=record.started_by,
            fields=record.fields,
            session_id=record.session_id,
            state=state,
            at=datetime.fromisoformat(record.at),
            ended_at=rec.last_activity_at if ended and rec is not None else None,
            result=result,
            error=error,
            # while it is called, nothing to say yet
            then_error=None if record.id in self.calling else record.then_error,
        )

    # ── the inbox, when it ends ─────────────────────────────────────────

    def watch(self, app: str, run_id: str) -> None:
        task = asyncio.get_running_loop().create_task(self._watch(app, run_id))
        self.watchers.add(task)
        task.add_done_callback(self.watchers.discard)

    def start_watching(self, apps: list[str]) -> None:
        """At start: the runs whose end the inbox was not told (handlerd stopped meanwhile): a
        job's run that ended meanwhile (its session ended by the restart) gets its `then` called
        now, once; one whose `then` was being called keeps THEN_CUT, not called again."""
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
        if record.then is not None and state != "cancelled" and not record.then_called:
            called = await self.then(app, record, state, result)
            if called is None:
                return  # the app was removed meanwhile
            record = called
        self.update(app, run_id, told=True)
        if state == "cancelled" or record.started_by.get("by") == "automation":
            return  # an automation's run: the automation tells it (I.3)
        failed = f"{record.then} failed: {record.then_error}" if record.then_error else None
        fields: dict[str, Any] = {
            "source": "app",
            "name": app,
            "person": "owner",
            "title": record.job,
            "session_id": record.session_id,
            "app": app,
        }
        told = told_result(result) if result is not None else {"status": "failed", "summary": error}
        if failed:  # its `then` failed: said with its result, which stays in the run
            told["summary"] = "\n\n".join(s for s in (told["summary"], failed) if s)
        self.inbox.add(**fields, **told)

    async def then(
        self, app: str, record: RunRecord, state: AppRunState, result: Any
    ) -> RunRecord | None:
        """Its job's `then` route called once, its end recorded (rule app-job.then-called-once):
        with `{runId, job, state, fields, result}`, as the owner, with no start token (it cannot
        start a run); marked called before, THEN_CUT kept until it answers, so it is never called
        twice, even when handlerd stops meanwhile; its failure kept, never retried. The record
        after it, None when the app was removed meanwhile."""
        assert record.then is not None and self.call_then is not None
        self.update(app, record.id, then_called=True, then_error=THEN_CUT)
        session = self.sessions.records.get(record.session_id)
        given = SessionInput.model_validate(session.input) if session and session.input else None
        payload = {
            "runId": record.id,
            "job": record.job,
            "state": state,
            "fields": given.fields if given else {},
            "result": result,
        }
        self.calling.add(record.id)
        try:
            error = await self.call_then(app, record.then, payload)
        finally:
            self.calling.discard(record.id)
        try:
            self.find(app, record.id)
        except AppRunError:
            return None
        self.update(app, record.id, then_error=error)
        return self.find(app, record.id)

    async def close(self) -> None:
        for task in list(self.watchers):
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*self.watchers, return_exceptions=True)
