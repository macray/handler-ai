"""Automations (I): when a session stops or a schedule's slot comes, the enabled automations it
fires run, one at a time for the whole daemon. A run is the automation's script in a sandbox (on
the new part of the conversation, for a stop; once it succeeded, handlerd appends what it wrote to
the declared knowledge notes), a run of an agent with an interface (its result goes to the inbox),
or a call to a mini app's route.

    pending_stop         pure: the stop of a log that fires an automation past its cursor (I.2)
    result_problems      pure: why an interface's result cannot make an inbox message (I.3)
    Automations          the runner: stops and schedules checked, the queue, runs and their
                         records, on and off (I.7), tries (I.8), what the API shows (I.9)

No other log than the sessions' own: a stop is told by `SessionStore.stop_listeners` (only the
session's id: the check reads its log, off the event loop), and at start every session is checked
once (the catch-up scan: stops while handlerd was not running, runs cut by its stop). Schedules are
checked every SCHEDULE_TICK seconds. Nothing pending is stored: a cursor per (automation, session),
moved when a run ends, is what was read; a schedule's last slot, moved when its run starts.

Storage, per automation (automation_config.state_dir):
    state.json                   on or off, since, the cursors, the schedule's last slot
    runs/<runId>/                run.json, definition/, input/, output/, run.log, services.ndjson
"""

import asyncio
import contextlib
import json
import logging
import os
import secrets as pysecrets
import shutil
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from handler_contracts import (
    DEFAULT_TIMEOUT_SEC,
    MAX_APPEND,
    Automation,
    AutomationAgentRun,
    AutomationAppended,
    AutomationCheck,
    AutomationLlmUsage,
    AutomationRun,
    AutomationView,
    InboxStatus,
    SessionInput,
    SessionOutput,
)
from handler_harness import catalog, images

from . import automation_config as config
from . import (
    checks,
    compose,
    interfaces,
    knowledge,
    runtime,
    sandbox_process,
    schedules,
    secrets,
    service_router,
    transcript,
)
from .agents import AgentRecord, AgentRegistry
from .apps import AppError, AppStore
from .inbox import Inbox
from .projects import ProjectRegistry
from .sessions import SessionRecord, SessionStore
from .settings import Settings

log = logging.getLogger("handler.automations")

BIN = Path(__file__).resolve().parent / "data" / "automation" / "bin"  # handler-llm
DAILY_CAP = 100  # runs per automation per day (I.3)
KEEP_RUNS = 50
KEEP_DAYS = 30
MAX_LOG = 1024 * 1024  # run.log
PREVIEW = 4096  # of what a try would append
NOT_FIRING = ("deleted", "daemon_restarted")
LAST = 2**62  # a seq past any log's end
LINE_LIMIT = 1024 * 1024  # one line of a run's output
SCHEDULE_TICK = 20.0  # schedules are checked this often (seconds)
DELETE_WAIT = 30.0  # a deleted one's run in progress is given this long to stop (seconds)
SESSION_POLL = 1.0  # an agent run's session is looked at this often (seconds)
STATUSES = ("ok", "attention", "failed")


class AutomationError(ValueError):
    """What was asked cannot be done (the message says why)."""


class AutomationNotFoundError(AutomationError):
    pass


class AutomationConflictError(AutomationError):
    """The state does not allow it: problems, a run that ended."""


class AutomationCappedError(AutomationError):
    pass


def now() -> datetime:
    return datetime.now(UTC)


def pending_stop(
    events: Sequence[dict[str, Any]], cursor: int, since: datetime | None
) -> dict[str, Any] | None:
    """The last stop after `cursor` that fires (I.2): not `deleted` nor `daemon_restarted`, at or
    after `since`, in a log with a turn after `cursor`. None: nothing to read."""
    if not any(e.get("kind") == "turn" and e["seq"] > cursor for e in events):
        return None
    stops = [
        e
        for e in events
        if e.get("kind") == "lifecycle"
        and e.get("event") == "stopped"
        and e["seq"] > cursor
        and e.get("how") not in NOT_FIRING
        and (since is None or datetime.fromisoformat(e["t"]) >= since)
    ]
    return stops[-1] if stops else None


def result_problems(schema: dict[str, Any]) -> list[str]:
    """An agent run by an automation gives a result its inbox message is made of (I.3):
    required `status` (some of ok, attention, failed) and `summary` (a string)."""
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    found = []
    status = props.get("status") or {}
    if "status" not in required or not status.get("enum"):
        found.append("its result has no required 'status' enum (ok, attention, failed)")
    elif unknown := [v for v in status["enum"] if v not in STATUSES]:
        found.append(f"its result's status has {unknown}: only ok, attention, failed")
    if "summary" not in required or (props.get("summary") or {}).get("type") != "string":
        found.append("its result has no required 'summary' string")
    return found


@dataclass
class Item:
    """A run waiting: for (automation, session), or (automation, its schedule), at most one
    (coalescing); or a try."""

    automation: str
    session_id: str | None = None  # a stop's
    slot: datetime | None = None  # a schedule's
    missed: int = 0
    trial: AutomationRun | None = None  # a try's record, written when it was asked

    @property
    def key(self) -> tuple[str, str, str]:
        return self.automation, self.session_id or "", self.trial.id if self.trial else ""


@dataclass
class Running:
    record: AutomationRun
    proc: Any = None  # asyncio.subprocess.Process, once a script started
    cancelled: bool = False


class Automations:
    def __init__(
        self,
        settings: Settings,
        sessions: SessionStore,
        registry: AgentRegistry,
        projects: ProjectRegistry,
        *,
        apps: AppStore,
        inbox: Inbox,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.registry = registry
        self.projects = projects
        self.apps = apps
        self.inbox = inbox
        self.queue: dict[tuple[str, str, str], Item] = {}  # in the order queued
        self.stopped: set[str] = set()  # sessions whose stop is to be checked
        self.running: Running | None = None
        self.started_today: dict[tuple[str, str], int] = {}  # (automation, day) → runs
        self.wake = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.lock = threading.Lock()  # state.json: read, changed, written by one at a time
        self.schedule_tick = SCHEDULE_TICK
        self._load()
        sessions.stop_listeners.append(self.on_stop)

    # ── start, stop ─────────────────────────────────────────────────────

    def _load(self) -> None:
        """Runs the previous handlerd left queued or running are `interrupted` (a stop's part is
        read again: the cursor did not move); today's runs count in the cap."""
        today = now().date().isoformat()
        for loaded in config.load_all(self.settings.automations_dir):
            for record in self.runs(loaded.name):
                if record.state in ("queued", "running"):
                    ended = record.model_copy(update={"state": "interrupted", "ended_at": now()})
                    self.write_record(ended)
                if record.created_at.date().isoformat() == today:
                    key = (loaded.name, today)
                    self.started_today[key] = self.started_today.get(key, 0) + 1

    def start(self) -> None:
        self.stopped |= set(self.sessions.records)  # the catch-up scan (I.2)
        self.task = asyncio.create_task(self.work())

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    def on_stop(self, session_id: str) -> None:
        """A session's `lifecycle stopped` was written: checked later, off this path."""
        self.stopped.add(session_id)
        self.wake.set()

    # ── the queue ───────────────────────────────────────────────────────

    async def work(self) -> None:
        while True:
            if self.stopped:
                sessions, self.stopped = self.stopped, set()
                found = await asyncio.to_thread(self.check, sessions)
                for item in found:
                    self.queue.setdefault(item.key, item)
            for item in await asyncio.to_thread(self.due):
                self.queue[item.key] = item  # a pending one gets the latest slot
            item = self.next_item()
            if item is None:
                self.wake.clear()
                with contextlib.suppress(TimeoutError):  # a schedule, a capped one tomorrow
                    await asyncio.wait_for(self.wake.wait(), self.schedule_tick)
                continue
            try:
                await self.run(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("automation %s", item.automation)

    def next_item(self) -> Item | None:
        for key, item in self.queue.items():
            if not self.capped(item.automation):
                del self.queue[key]
                return item
        return None

    def capped(self, name: str) -> bool:
        return self.started_today.get((name, now().date().isoformat()), 0) >= DAILY_CAP

    def count_start(self, name: str) -> None:
        key = (name, now().date().isoformat())
        self.started_today[key] = self.started_today.get(key, 0) + 1

    def check(self, session_ids: set[str]) -> list[Item]:
        """The automations these sessions' stops fire (I.2)."""
        found = []
        logs: dict[str, list[dict[str, Any]]] = {}  # each read once
        for loaded in config.load_all(self.settings.automations_dir):
            state = config.read_state(self.settings.state_dir, loaded.name)
            definition = loaded.definition
            if not state.enabled or definition is None or definition.when != "session.stopped":
                continue
            for sid in sorted(session_ids):
                rec = self.sessions.records.get(sid)
                if rec is None or rec.interface is not None or not self.matches(loaded, rec):
                    continue
                path = self.log_path(sid)
                with contextlib.suppress(OSError):
                    if state.since and path.stat().st_mtime < state.since.timestamp():
                        continue  # written before it was turned on: nothing to read
                if sid not in logs:
                    logs[sid] = transcript.read(path, 0, LAST)
                if pending_stop(logs[sid], state.cursors.get(sid, 0), state.since):
                    found.append(Item(loaded.name, sid))
        return found

    def due(self) -> list[Item]:
        """The scheduled automations whose slot came (I.2): one run each, for the latest slot."""
        t, found = now(), []
        for loaded in config.load_all(self.settings.automations_dir):
            schedule = loaded.definition.schedule if loaded.definition else None
            if schedule is None:
                continue
            state = config.read_state(self.settings.state_dir, loaded.name)
            last = state.last_slot or state.since
            if not state.enabled or last is None:
                continue
            slot = schedules.latest_slot(schedule, last, t)
            if slot is None:
                continue
            found.append(
                Item(loaded.name, slot=slot, missed=schedules.missed(schedule, last, slot))
            )
        return found

    def matches(self, loaded: config.Loaded, rec: SessionRecord) -> bool:
        only = loaded.definition.only if loaded.definition else None
        if only is None:
            return True
        agent, project = self.names(rec)
        return (only.project is None or project in only.project) and (
            only.agent is None or agent in only.agent
        )

    def names(self, rec: SessionRecord) -> tuple[str | None, str | None]:
        """The session's agent's name and its project's, now."""
        agent = self.registry.get(rec.agent_id)
        if agent is None:
            return None, None
        project = self.projects.get(agent.project_id) if agent.project_id else None
        return agent.name, project.name if project else None

    def log_path(self, session_id: str) -> Path:
        return self.sessions.folder(session_id) / "events.ndjson"

    # ── state, problems, what it may touch (I.7) ────────────────────────

    def update_state(self, name: str, change: Callable[[config.State], None]) -> config.State:
        with self.lock:
            state = config.read_state(self.settings.state_dir, name)
            change(state)
            config.write_state(self.settings.state_dir, name, state)
            return state

    def find_agent(self, run: AutomationAgentRun) -> AgentRecord:
        """The agent an agent run names: by its name, in its project (none: of no project)."""
        project = None
        if run.project is not None:
            found = [p for p in self.projects.projects.values() if p.name == run.project]
            if not found:
                raise AutomationError(f"run.project: no project named {run.project}")
            project = found[0].id
        agents = [
            a
            for a in self.registry.agents.values()
            if a.name == run.agent and a.project_id == project
        ]
        where = f"in project {run.project}" if run.project else "of no project"
        if not agents:
            raise AutomationError(f"run.agent: no agent named {run.agent} {where}")
        if len(agents) > 1:
            raise AutomationError(f"run.agent: {len(agents)} agents named {run.agent} {where}")
        return agents[0]

    def agent_problems(self, run: AutomationAgentRun) -> tuple[list[str], list[str]]:
        """(problems, warnings) of an agent run: the agent, its interface and input, its model
        and the terms of its account's subscription (I.7)."""
        try:
            agent = self.find_agent(run)
        except AutomationError as e:
            return [str(e)], []
        if agent.interface is None:
            return [f"agent {run.agent} has no interface: only those run unattended (D.18)"], []
        found = result_problems(agent.interface.result)
        try:
            self.agent_input(agent, run)
        except AutomationError as e:
            found.append(str(e))
        warnings: list[str] = []
        try:
            runs = checks.session_model(self.settings, agent, None)
        except checks.CheckError as e:
            return [*found, f"agent {run.agent}'s model: {e}"], warnings
        if runs.account is not None:
            login = catalog.get(runs.harness).descriptor.login
            assert login is not None  # an account's harness has one
            read = f", read on {login.checked}" if login.checked else ", not read yet"
            terms = f"{login.subscription} terms ({login.terms}{read})"
            if login.unattended == "refused":
                found.append(
                    f"agent {run.agent} runs on account {runs.account}: unattended use of a "
                    f"{login.subscription} subscription is refused by handler until it is clearly "
                    f"allowed by the {terms}; give the agent a provider (an API key) first"
                )
            elif login.unattended == "check-terms":
                warnings.append(
                    f"Runs on your subscription (account {runs.account}). Check your "
                    f"{login.subscription} plan's terms: automated or unattended use may not be "
                    f"allowed ({login.terms}). An API key (a provider) is recommended."
                )
        return found, warnings

    def agent_input(self, agent: AgentRecord, run: AutomationAgentRun) -> SessionInput:
        assert agent.interface is not None
        given = SessionInput.model_validate(run.input.model_dump(by_alias=True))
        try:
            return interfaces.check_input(agent.interface, given, self.settings.skills_dir)
        except interfaces.InterfaceError as e:
            raise AutomationError(f"run.input: {e}") from None

    def checked(self, loaded: config.Loaded) -> tuple[list[str], list[str]]:
        """(problems, warnings): what keeps it from running (I.1), what to know first (I.7)."""
        root, _ = knowledge.root(self.settings)
        found = config.problems(
            loaded,
            providers_dir=self.settings.providers_dir,
            store=secrets.SecretStore(self.settings.data_dir),
            knowledge_root=root,
            projects={p.name for p in self.projects.projects.values()},
            agents={a.name for a in self.registry.agents.values() if a.name},
        )
        definition, warnings = loaded.definition, []
        if definition is not None and (run := definition.agent_run) is not None:
            more, warnings = self.agent_problems(run)
            found += more
        call = definition.app_call if definition is not None else None
        if call is not None and call.app not in self.apps.records:
            found.append(f"run.app: no app named {call.app}")
        return found, warnings

    def problems(self, loaded: config.Loaded) -> list[str]:
        return self.checked(loaded)[0]

    def permissions(self, definition: Automation) -> list[str]:
        """What it may touch and what starts it, in sentences (I.7)."""
        if (schedule := definition.schedule) is not None:
            days = f" on {', '.join(schedule.days)}" if schedule.days else ""
            when = (
                f"Starts every {schedule.every}"
                if schedule.every
                else f"Starts at {schedule.at} (local time){days}"
            )
            when += "; after the computer was off, only the latest missed slot runs."
        else:
            only = definition.only
            whose = [
                f"{kind} {', '.join(names)}"
                for kind, names in (
                    ("of project", only.project if only else None),
                    ("of agent", only.agent if only else None),
                )
                if names
            ]
            when = "Starts when a session " + (" ".join(whose) + " " if whose else "") + "stops."
        found = [when]
        if (script := definition.script) is not None:
            reads = (
                "the conversation of the session that stopped"
                if definition.schedule is None
                else "nothing but the time it runs"
            )
            found.append(f"Runs `{script}` in a sandbox without network, reading {reads}.")
            if definition.services and definition.services.llm:
                found.append(f"May call the models {', '.join(definition.services.llm)}.")
            if definition.append:
                notes = ", ".join(a.to for a in definition.append)
                found.append(f"Appends what it writes to the notes {notes}.")
            found.append("Tells your inbox when a run fails.")
        elif (run := definition.agent_run) is not None:
            where = f"of project {run.project}" if run.project else "of no project"
            found.append(f"Runs the agent {run.agent} {where} unattended, without asking you.")
            with contextlib.suppress(AutomationError):
                agent = self.find_agent(run)
                folder = agent.scope or "a folder of its own for each run"
                runs = agent.models[0] if agent.models else None
                model = (
                    " · ".join(
                        x for x in (runs.harness, runs.account or runs.provider, runs.model) if x
                    )
                    if runs
                    else "none"
                )
                found.append(
                    f"It works in {folder} (read-write), network {agent.network}, "
                    f"confinement {agent.confinement}, on {model}."
                )
            found.append("Sends its result to your inbox.")
        elif (call := definition.app_call) is not None:
            found.append(f"Calls {call.call} of the app {call.app}, as you.")
            found.append("Tells your inbox when a call fails.")
        return found

    def get(self, name: str) -> config.Loaded:
        loaded = config.get(self.settings.automations_dir, name)
        if loaded is None:
            raise AutomationNotFoundError(f"no automation named {name}")
        return loaded

    def view(self, name: str) -> AutomationView:
        loaded = self.get(name)
        state = config.read_state(self.settings.state_dir, name)
        definition = loaded.definition
        problems, warnings = self.checked(loaded)
        runs = self.runs(name)
        next_at = None
        if state.enabled and definition is not None and definition.schedule is not None:
            last = state.last_slot or state.since
            if last is not None:
                next_at = schedules.next_slot(definition.schedule, last, now())
        pending = sum(1 for i in self.queue.values() if i.automation == name and not i.trial)
        busy = self.running.record.automation if self.running else None
        return AutomationView(
            name=name,
            description=definition.description if definition else None,
            definition=definition,
            directory=str(loaded.path),
            files=config.files(loaded.path),
            problems=problems,
            enabled=state.enabled,
            permissions=self.permissions(definition) if definition else [],
            warnings=warnings,
            next_at=next_at,
            pending=pending,
            behind=busy if pending and busy != name else None,
            capped=self.capped(name),
            last_run=runs[0] if runs else None,
        )

    def views(self) -> list[AutomationView]:
        return [self.view(a.name) for a in config.load_all(self.settings.automations_dir)]

    def enable(self, name: str) -> AutomationView:
        """Turned on: the owner's only approval (I.7). Stops and slots before are not read."""
        loaded = self.get(name)
        if loaded.definition is None or (found := self.problems(loaded)):
            raise AutomationConflictError(f"{name} has problems: {'; '.join(found)}")

        def on(state: config.State) -> None:
            if not state.enabled:
                state.since, state.last_slot = now(), None
            state.enabled = True

        self.update_state(name, on)
        return self.view(name)

    def disable(self, name: str) -> AutomationView:
        self.get(name)

        def off(state: config.State) -> None:
            state.enabled = False

        self.update_state(name, off)
        for key in [k for k, i in self.queue.items() if i.automation == name and not i.trial]:
            del self.queue[key]
        return self.view(name)

    def create(
        self,
        name: str,
        *,
        example: str | None = None,
        definition: Automation | None = None,
        enable: bool = False,
    ) -> AutomationView:
        """A new one, off: an example copied, or `definition` written (I.1); `enable`: then
        turned on, when it has no problems (409 else, and it stays, off)."""
        directory = self.settings.automations_dir
        try:
            if definition is not None:
                config.write_new(directory, name, definition)
            else:
                assert example is not None
                config.copy_example(directory, name, example)
        except config.AutomationExistsError as e:
            raise AutomationConflictError(str(e)) from None
        except config.AutomationConfigError as e:
            raise AutomationNotFoundError(str(e)) from None
        return self.enable(name) if enable else self.view(name)

    def update(self, name: str, definition: Automation) -> AutomationView:
        """`definition` written over its automation.toml (the owner's edit, as in an editor: on,
        it stays on and the edit applies at its next run, I.7)."""
        config.write_definition(self.get(name).path, definition)
        return self.view(name)

    def preview(self, definition: Automation) -> AutomationCheck:
        """What `definition` would do, its problems and warnings, before it is saved."""
        problems, warnings = self.checked(config.Loaded("", Path(), definition))
        at, schedule = now(), definition.schedule
        return AutomationCheck(
            problems=problems,
            warnings=warnings,
            permissions=self.permissions(definition),
            next_at=schedules.next_slot(schedule, at, at) if schedule is not None else None,
        )

    async def delete(self, name: str) -> None:
        """Gone: its waiting runs dropped, the one in progress stopped (and waited for, so that
        nothing it writes brings its state back), its folder and its state (runs, logs) removed.
        What it told the inbox stays."""
        loaded = self.get(name)
        for key in [k for k, i in self.queue.items() if i.automation == name]:
            del self.queue[key]
        running = self.running
        if running is not None and running.record.automation == name:
            await self.cancel(name, running.record.id)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + DELETE_WAIT
            while self.running is running and loop.time() < deadline:
                await asyncio.sleep(0.1)
        await asyncio.to_thread(shutil.rmtree, loaded.path)
        state = config.state_dir(self.settings.state_dir, name)
        await asyncio.to_thread(shutil.rmtree, state, ignore_errors=True)

    # ── runs ────────────────────────────────────────────────────────────

    def runs_dir(self, name: str) -> Path:
        return config.state_dir(self.settings.state_dir, name) / "runs"

    def runs(self, name: str) -> list[AutomationRun]:
        """Most recent first."""
        found = []
        for path in self.runs_dir(name).glob("a_*/run.json"):
            with contextlib.suppress(OSError, ValueError):
                found.append(AutomationRun.model_validate_json(path.read_text()))
        return sorted(found, key=lambda r: r.created_at, reverse=True)

    def runs_of_session(self, session_id: str) -> list[AutomationRun]:
        found = [
            r
            for loaded in config.load_all(self.settings.automations_dir)
            for r in self.runs(loaded.name)
            if session_id in (r.session_id, r.agent_session_id)
        ]
        return sorted(found, key=lambda r: r.created_at, reverse=True)

    def get_run(self, name: str, run_id: str) -> AutomationRun:
        self.get(name)
        path = self.runs_dir(name) / run_id / "run.json"
        if "/" in run_id or not run_id.startswith("a_") or not path.is_file():
            raise AutomationNotFoundError(f"no run {run_id} of {name}")
        if self.running and self.running.record.id == run_id:
            return self.running.record
        return AutomationRun.model_validate_json(path.read_text())

    def run_log(self, name: str, run_id: str) -> str:
        self.get_run(name, run_id)
        path = self.runs_dir(name) / run_id / "run.log"
        return path.read_text(errors="replace") if path.is_file() else ""

    def write_record(self, record: AutomationRun) -> None:
        folder = self.runs_dir(record.automation) / record.id
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = folder / "run.json.tmp"
        tmp.write_text(record.model_dump_json(by_alias=True, exclude_none=True, indent=2))
        tmp.replace(folder / "run.json")

    def try_run(self, name: str, session_id: str | None) -> AutomationRun:
        """I.8: now, on or off; on a stop's whole log; appends nothing."""
        loaded = self.get(name)
        if loaded.definition is None or (found := self.problems(loaded)):
            raise AutomationConflictError(f"{name} has problems: {'; '.join(found)}")
        on_stop = loaded.definition.when == "session.stopped"
        if on_stop and session_id is None:
            raise AutomationConflictError(f"{name} runs on a session that stopped: give one")
        if not on_stop and session_id is not None:
            raise AutomationConflictError(f"{name} runs on a schedule: no session")
        if session_id is not None and session_id not in self.sessions.records:
            raise AutomationNotFoundError(f"no session {session_id}")
        if self.capped(name):
            raise AutomationCappedError(f"{name} ran {DAILY_CAP} times today")
        record = AutomationRun(
            id=new_run_id(), automation=name, trial=True, state="queued", created_at=now()
        )
        if session_id is not None:
            events = transcript.read(self.log_path(session_id), 0, LAST)
            seq_to = events[-1]["seq"] if events else 0
            record = record.model_copy(
                update={"session_id": session_id, "seq_from": 1, "seq_to": seq_to}
            )
        self.write_record(record)
        item = Item(name, session_id, trial=record)
        self.queue[item.key] = item
        self.wake.set()
        return record

    async def cancel(self, name: str, run_id: str) -> AutomationRun:
        record = self.get_run(name, run_id)
        if (key := (name, record.session_id or "", run_id)) in self.queue:
            del self.queue[key]
            record = record.model_copy(update={"state": "cancelled", "ended_at": now()})
            self.write_record(record)
            return record
        running = self.running
        if running is None or running.record.id != run_id:
            raise AutomationConflictError(f"run {run_id} has ended ({record.state})")
        running.cancelled = True
        if running.proc is not None:
            await sandbox_process.stop(running.proc)
        if (sid := running.record.agent_session_id) is not None:
            await self.sessions.stop(sid, "its automation run was cancelled", "explicit")
        return running.record

    async def run(self, item: Item) -> None:
        loaded = config.get(self.settings.automations_dir, item.automation)
        rec = self.sessions.records.get(item.session_id) if item.session_id else None
        if loaded is None or loaded.definition is None or (item.session_id and rec is None):
            if item.trial:
                self.end(item.trial, "failed", error="the automation or the session is gone")
            return
        events: list[dict[str, Any]] = []
        if item.session_id is not None:
            events = await asyncio.to_thread(
                transcript.read, self.log_path(item.session_id), 0, LAST
            )
        record = self.new_record(loaded, item, events)
        if record is None:
            return
        self.count_start(loaded.name)
        self.running = Running(record)
        self.write_record(record)
        try:
            await self.execute(loaded, rec, events, self.running)
        except asyncio.CancelledError:  # handlerd stops: a stop's part is read again at its start
            if self.running.proc is not None:
                await sandbox_process.stop(self.running.proc)
            self.end(self.running.record, "interrupted", move=False)
            raise
        except Exception as e:  # handlerd's side failed (a file, the sandbox's executable)
            log.exception("automation %s: run %s", loaded.name, record.id)
            self.end(self.running.record, "failed", error=f"handler could not run it: {e}")
        finally:
            self.running = None

    def new_record(
        self, loaded: config.Loaded, item: Item, events: list[dict[str, Any]]
    ) -> AutomationRun | None:
        """The record of the run starting now; None when it does not run after all: turned off or
        with problems meanwhile (read once it is on again without problems), nothing new read.
        A schedule's slot is taken now: a run cut by handlerd stopping is not run again."""
        if item.trial is not None:
            return item.trial.model_copy(update={"state": "running"})
        state = config.read_state(self.settings.state_dir, loaded.name)
        if not state.enabled or self.problems(loaded):
            return None
        record = AutomationRun(
            id=new_run_id(), automation=loaded.name, state="running", created_at=now()
        )
        if item.session_id is not None:
            cursor = state.cursors.get(item.session_id, 0)
            if not pending_stop(events, cursor, state.since):
                return None
            seqs = {"seq_from": cursor + 1, "seq_to": events[-1]["seq"]}
            return record.model_copy(update={"session_id": item.session_id} | seqs)
        slot = item.slot

        def ran(s: config.State) -> None:
            s.last_slot = slot

        self.update_state(loaded.name, ran)
        return record.model_copy(update={"slot": slot, "missed": item.missed})

    async def execute(
        self,
        loaded: config.Loaded,
        rec: SessionRecord | None,
        events: list[dict[str, Any]],
        running: Running,
    ) -> None:
        definition = loaded.definition
        assert definition is not None
        if (run := definition.agent_run) is not None:
            await self.execute_agent(loaded, run, running)
        elif (call := definition.app_call) is not None:
            loop = asyncio.get_running_loop()
            started = loop.time()
            try:
                status = await self.apps.call(call.app, call.call, loaded.name)
            except AppError as e:
                self.end(running.record, "failed", error=f"app {call.app}: {e}")
                return
            running.record = running.record.model_copy(
                update={"ms": int((loop.time() - started) * 1000)}
            )
            if status >= 400:
                self.end(running.record, "failed", error=f"{call.call}: HTTP {status}")
            else:
                self.end(running.record, "succeeded")
        else:
            await self.execute_script(loaded, rec, events, running)

    async def execute_agent(
        self, loaded: config.Loaded, run: AutomationAgentRun, running: Running
    ) -> None:
        """A run of the agent (D.18), watched until its session stops; its result → the inbox."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            agent = self.find_agent(run)
            given = self.agent_input(agent, run)
            runs = checks.session_model(self.settings, agent, None)
        except (AutomationError, checks.CheckError) as e:
            self.end(running.record, "failed", error=str(e))
            return
        if running.cancelled:  # before its session: nothing to stop, nothing to start
            self.end(running.record, "cancelled")
            return
        session = self.sessions.create(agent, runs, origin="automation", run=given)
        running.record = running.record.model_copy(update={"agent_session_id": session.id})
        self.write_record(running.record)
        while True:
            await asyncio.sleep(SESSION_POLL)
            rec = self.sessions.records.get(session.id)
            if rec is None:
                self.end(running.record, "failed", error="its session was deleted")
                return
            busy = session.id in self.sessions.live or session.id in self.sessions.starting
            if rec.state in ("stopped", "failed") and not busy:
                break
        running.record = running.record.model_copy(
            update={"ms": int((loop.time() - started) * 1000)}
        )
        output = SessionOutput.model_validate(rec.output) if rec.output else None
        if running.cancelled:
            self.end(running.record, "cancelled")
        elif output is not None and output.valid and isinstance(output.value, dict):
            value: dict[str, Any] = output.value
            self.end(running.record, "succeeded", result=value)
        else:
            why = (
                (output.error if output else None)
                or rec.error
                or f"its turn ended: {rec.last_stop_reason or 'no result'}"
            )
            self.end(running.record, "failed", error=f"no valid result: {why}")

    async def execute_script(
        self,
        loaded: config.Loaded,
        rec: SessionRecord | None,
        events: list[dict[str, Any]],
        running: Running,
    ) -> None:
        definition = loaded.definition
        assert definition is not None and definition.script is not None
        record = running.record
        folder = self.runs_dir(loaded.name) / record.id
        redact = secrets.redactor(secrets.SecretStore(self.settings.data_dir).values())
        if rec is not None and record.seq_from is not None and record.seq_to is not None:
            slice_ = [e for e in events if record.seq_from <= e["seq"] <= record.seq_to]
            await asyncio.to_thread(self.prepare, loaded, rec, slice_, record, redact)
        else:
            await asyncio.to_thread(self.prepare_scheduled, loaded, record)
        if running.cancelled:
            self.end(record, "cancelled")
            return
        toolbox = images.ref(images.TOOLBOX, images.LATEST)
        if not await asyncio.to_thread(runtime.exists, toolbox):
            self.end(record, "failed", error="toolbox not built: `handler image rebuild toolbox`")
            return
        code, timed_out = await self.sandboxed(definition, toolbox, folder, running, redact)
        record = running.record
        if running.cancelled:
            self.end(record, "cancelled")
        elif timed_out:
            timeout = definition.timeout_sec or DEFAULT_TIMEOUT_SEC
            self.end(record, "failed", error=f"timed out after {timeout} s")
        elif code != 0:
            self.end(record, "failed", error=f"the script exited with {code}")
        else:
            try:
                appended = await asyncio.to_thread(self.append, loaded, record, folder / "output")
            except AutomationError as e:
                self.end(record, "failed", error=str(e))
            else:
                self.end(record, "succeeded", appended=appended)

    async def sandboxed(
        self,
        definition: Automation,
        toolbox: str,
        folder: Path,
        running: Running,
        redact: Callable[[str], str],
    ) -> tuple[int | None, bool]:
        """The run's sandbox (I.3), with its services socket (I.5) when it calls models, until
        it ends or its timeout: (its exit code, timed out). Its record gets what it used."""
        assert definition.script is not None
        record = running.record
        grant, server, socket_dir = None, None, None
        if models := definition.services.llm if definition.services else []:
            socket_dir = self.settings.runtime_dir / "automations" / record.id
            socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            grant = service_router.Grant(llm=frozenset(models), log=folder / "services.ndjson")
            server = await service_router.serve(self.settings, socket_dir / "services.sock", grant)
        spec = compose.automation_run_spec(
            name=f"handler-run-{record.id.replace('_', '-')}",
            run_id=record.id,
            toolbox=toolbox,
            run=definition.script,
            definition=str(folder / "definition"),
            input_dir=str(folder / "input"),
            output=str(folder / "output"),
            bin_dir=str(BIN),
            services=str(socket_dir / "services.sock") if socket_dir else None,
            trial=record.trial,
        )
        loop = asyncio.get_running_loop()
        started, timed_out = loop.time(), False
        try:
            running.proc = proc = await sandbox_process.start_piped(spec, line_limit=LINE_LIMIT)
            copying = asyncio.create_task(copy_log(proc, folder / "run.log", redact))
            if running.cancelled:  # while it was being set up: there was nothing to stop yet
                await sandbox_process.stop(proc)
            try:
                await asyncio.wait_for(proc.wait(), definition.timeout_sec or DEFAULT_TIMEOUT_SEC)
            except TimeoutError:
                timed_out = True
                await sandbox_process.stop(proc)
            await copying
        finally:
            if server is not None:
                server.close()
            if socket_dir is not None:
                shutil.rmtree(socket_dir, ignore_errors=True)
        used: dict[str, Any] = {
            "exit_code": proc.returncode,
            "ms": int((loop.time() - started) * 1000),
        }
        if grant is not None:
            used["llm"] = AutomationLlmUsage(
                calls=grant.calls, in_tokens=grant.in_tokens, out_tokens=grant.out_tokens
            )
        running.record = record.model_copy(update=used)
        return proc.returncode, timed_out

    def copy_definition(self, loaded: config.Loaded, record: AutomationRun) -> Path:
        """The run's folder (I.3): a copy of the automation's, an empty input and output."""
        folder = self.runs_dir(loaded.name) / record.id
        shutil.copytree(
            loaded.path,
            folder / "definition",
            ignore=shutil.ignore_patterns(".*", "__pycache__"),
            dirs_exist_ok=True,
        )
        (folder / "output").mkdir(exist_ok=True)
        (folder / "input").mkdir(exist_ok=True)
        return folder

    def prepare_scheduled(self, loaded: config.Loaded, record: AutomationRun) -> None:
        """A scheduled script's input (I.4): its slot only."""
        folder = self.copy_definition(loaded, record)
        event = {
            "type": "schedule",
            "slot": record.slot.isoformat() if record.slot else None,
            "missed": record.missed,
            "t": now().isoformat(),
        }
        (folder / "input" / "event.json").write_text(json.dumps(event, indent=2) + "\n")

    def prepare(
        self,
        loaded: config.Loaded,
        rec: SessionRecord,
        events: list[dict[str, Any]],
        record: AutomationRun,
        redact: Callable[[str], str],
    ) -> None:
        """A stop's run folder (I.3, I.4): its input is the session's part read."""
        given = self.copy_definition(loaded, record) / "input"
        agent = self.registry.get(rec.agent_id)
        agent_name, project_name = self.names(rec)
        stops = [e for e in events if e.get("kind") == "lifecycle" and e.get("event") == "stopped"]
        event = {
            "type": "session.stopped",
            "sessionId": rec.id,
            "agentId": rec.agent_id,
            "agent": agent_name,
            "projectId": agent.project_id if agent else None,
            "project": project_name,
            "how": stops[-1].get("how") if stops else None,
            "seqFrom": record.seq_from,
            "seqTo": record.seq_to,
            "t": stops[-1]["t"] if stops else now().isoformat(),
        }
        session = self.sessions.to_contract(rec).model_dump(mode="json", by_alias=True)
        settings: dict[str, Any] = {"name": agent_name}
        if agent is not None:
            settings |= agent.settings.model_dump(
                mode="json",
                by_alias=True,
                include={"network", "allow", "confinement", "permissions", "bindings", "knowledge"},
            )
        session["agent"] = settings
        model = " · ".join(x for x in (rec.harness, rec.account or rec.provider, rec.model) if x)
        header = [
            ("Agent", agent_name or rec.harness),
            ("Project", project_name or "none (an ad-hoc agent)"),
            ("Model", model),
            ("Folder", rec.scope),
            ("Network", f"{settings.get('network')} {' '.join(settings.get('allow') or [])}"),
            ("Confinement", str(settings.get("confinement"))),
            ("Permissions", str(settings.get("permissions"))),
            ("Addons", ", ".join(settings.get("bindings") or []) or "none"),
            ("Knowledge", ", ".join(settings.get("knowledge") or []) or "none"),
            ("Events", f"{record.seq_from} to {record.seq_to}"),
        ]
        files = {
            "event.json": json.dumps(event, indent=2) + "\n",
            "session.json": json.dumps(session, indent=2) + "\n",
            "events.ndjson": "".join(json.dumps(e) + "\n" for e in events),
            "transcript.md": transcript.render(events, header),
        }
        for file, text in files.items():
            (given / file).write_text(redact(text))

    def append(
        self, loaded: config.Loaded, record: AutomationRun, output: Path
    ) -> list[AutomationAppended]:
        """I.6: each `from` file the run wrote to its note, in order, once every one was
        checked (a try: what would be appended, nothing written)."""
        assert loaded.definition is not None
        root, _ = knowledge.root(self.settings)
        base = os.path.realpath(output)
        blocks = []
        for append in loaded.definition.append:
            path = os.path.realpath(os.path.join(base, append.from_))
            if not path.startswith(base + "/"):
                raise AutomationError(f"{append.from_}: outside the run's output folder")
            if not os.path.lexists(path):
                continue  # nothing to add
            if not os.path.isfile(path):
                raise AutomationError(f"{append.from_}: not a file")
            if os.path.getsize(path) > MAX_APPEND:
                raise AutomationError(f"{append.from_}: larger than {MAX_APPEND // 1024} KiB")
            try:
                knowledge.check_note(root, append.to)
            except knowledge.KnowledgeError as e:
                raise AutomationError(str(e)) from None
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            blocks.append((append.to, text))
        appended = []
        for to, text in blocks:
            if record.trial:
                size = len(text.encode())
                appended.append(AutomationAppended(to=to, bytes=size, text=text[:PREVIEW]))
                continue
            where = f"run {record.id}" + (
                f" · session {record.session_id}" if record.session_id else ""
            )
            t = now().isoformat(timespec="seconds")
            head = f"<!-- handler automation {loaded.name} · {where} · {t} -->"
            block = f"\n{head}\n{text}" + ("" if text.endswith("\n") else "\n")
            knowledge.append_note(root, to, block)
            appended.append(AutomationAppended(to=to, bytes=len(block.encode())))
        return appended

    def end(
        self,
        record: AutomationRun,
        state: str,
        *,
        error: str | None = None,
        appended: list[AutomationAppended] | None = None,
        result: dict[str, Any] | None = None,
        move: bool = True,
    ) -> None:
        """Its record, then (a run of a stop) its cursor: the part it read is read (I.2); then
        what the inbox is told (I.3): an agent run's result, a failure."""
        update: dict[str, Any] = {"state": state, "ended_at": now(), "error": error}
        if appended is not None:
            update["appended"] = appended
        record = record.model_copy(update=update)
        self.write_record(record)
        if move and not record.trial and record.session_id is not None:
            session_id, seq_to = record.session_id, record.seq_to or 0

            def moved(s: config.State) -> None:
                s.cursors[session_id] = max(s.cursors.get(session_id, 0), seq_to)

            self.update_state(record.automation, moved)
        self.tell(record, result)
        self.prune(record.automation)

    def tell(self, record: AutomationRun, result: dict[str, Any] | None) -> None:
        """The inbox message of a run that ended (I.3): an agent run's result (a try's too), a
        failure (not a try's: its page shows it), nothing else."""
        loaded = config.get(self.settings.automations_dir, record.automation)
        run = loaded.definition.agent_run if loaded and loaded.definition else None
        title = record.automation + (" (try)" if record.trial else "")
        fields: dict[str, Any] = {
            "source": "automation",
            "name": record.automation,
            "agent": run.agent if run else None,
            "person": "owner",
            "title": title,
            "run_id": record.id,
            "session_id": record.agent_session_id,
        }
        if result is not None:
            status: InboxStatus = result["status"] if result.get("status") in STATUSES else "ok"
            summary = result.get("summary")
            summary = summary if isinstance(summary, str) else None
            self.inbox.add(**fields, status=status, summary=summary, data=result)
        elif record.state == "failed" and (run is not None or not record.trial):
            self.inbox.add(**fields, status="failed", summary=record.error)

    def prune(self, name: str) -> None:
        """The last KEEP_RUNS runs, none older than KEEP_DAYS days."""
        oldest = now() - timedelta(days=KEEP_DAYS)
        busy = self.running.record.id if self.running else None
        for i, record in enumerate(self.runs(name)):
            if (
                record.id != busy
                and record.state != "queued"
                and (i >= KEEP_RUNS or record.created_at < oldest)
            ):
                shutil.rmtree(self.runs_dir(name) / record.id, ignore_errors=True)


def new_run_id() -> str:
    return "a_" + pysecrets.token_hex(8)


async def copy_log(proc: Any, path: Path, redact: Callable[[str], str]) -> None:
    """The run's output into run.log, redacted, at most MAX_LOG bytes (the rest is read, not
    kept)."""
    written = 0
    with path.open("w") as f:
        while True:
            try:
                raw = await proc.stdout.readline()
            except (ValueError, asyncio.LimitOverrunError):
                raw = b"(a line longer than 1 MiB, left out)\n"
            if not raw:
                break
            line = redact(raw.decode(errors="replace"))
            if written < MAX_LOG:
                kept = line[: MAX_LOG - written]
                f.write(kept)
                written += len(kept)
                if written >= MAX_LOG:
                    f.write("\n… the log is cut at 1 MiB\n")
            f.flush()
