"""An agent's checks (D.20): runs of a job kept with their right answer, run again when the person
asks (never on their own). Run again with its input, a check passes when every field it compares
comes back as in its answer; free text is never compared (a judge would, later).

    <state>/agent-checks/<agent id>.json   its checks, its last check runs (KEEP), and what the
                                           agent was when they last ran (to say what changed)

A check run runs its agent's checks one after another, each a run of the job (D.18) with origin
`check`: not the agent's history (clients leave them out), never told to the inbox, deleted with
the check run that made it. One check run at a time per agent.
"""

import asyncio
import contextlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from handler_contracts import (
    AgentChecks,
    AgentsFileCheck,
    Check,
    CheckResult,
    CheckRun,
    CheckState,
    CheckUpdateRequest,
    KeepCheckRequest,
    SessionInput,
    SessionOutput,
)

from . import interfaces, save_rules
from .agents import AgentRecord
from .sessions import SessionStore
from .settings import Settings

KEEP = 20  # check runs kept per agent
# what a check's answer depends on, and how a change of it is said ("since you changed …")
MATTERS = {
    "instructions": "its instructions",
    "interface": "its form or its result",
    "model": "its model",
    "model_alone": "who works",
    "knowledge": "its knowledge",
    "skills": "its skills",
    "addons": "its addons",
}


class CheckError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass
class Stored:
    checks: list[Check] = field(default_factory=list)
    runs: list[CheckRun] = field(default_factory=list)  # oldest first
    ran_with: dict[str, Any] | None = None  # the agent's MATTERS when its last check run started


def now() -> datetime:
    return datetime.now(UTC)


def matters(agent: AgentRecord) -> dict[str, Any]:
    return json.loads(agent.model_dump_json(include=set(MATTERS)))


def comparable(result: dict[str, Any] | None) -> list[str]:
    """The fields of a result schema that are not free text: a choice, yes/no, a number, a list
    of choices. Free text is never compared."""
    found = []
    for key, s in ((result or {}).get("properties") or {}).items():
        items = s.get("items") or {}
        free = s.get("type") == "string" and "enum" not in s
        free_list = s.get("type") == "array" and "enum" not in items
        if not free and not free_list and s.get("type") != "object":
            found.append(key)
    return found


def differences(check: Check, got: dict[str, Any]) -> list[str]:
    """Each compared field that did not come back the same: `verdict: send, not rewrite`."""
    said = lambda v: "nothing" if v is None else json.dumps(v)  # noqa: E731
    return [
        f"{k}: {said(got.get(k))}, not {said(check.answer.get(k))}"
        for k in check.compare
        if got.get(k) != check.answer.get(k)
    ]


class CheckStore:
    def __init__(self, settings: Settings, sessions: SessionStore) -> None:
        self.settings, self.sessions = settings, sessions
        self.root = settings.state_dir / "agent-checks"
        self.running: dict[str, asyncio.Task[None]] = {}  # agent id → its check run

    # ── storage ─────────────────────────────────────────────────────────

    def file(self, agent_id: str) -> Path:
        return self.root / f"{agent_id}.json"

    def load(self, agent_id: str) -> Stored:
        if not self.file(agent_id).exists():
            return Stored()
        raw = json.loads(self.file(agent_id).read_text())
        stored = Stored(
            checks=[Check.model_validate(c) for c in raw["checks"]],
            runs=[CheckRun.model_validate(r) for r in raw["runs"]],
            ran_with=raw.get("ranWith"),
        )
        if stored.runs and stored.runs[-1].ended_at is None and agent_id not in self.running:
            stored.runs[-1] = interrupted(stored.runs[-1])  # handlerd stopped meanwhile
        return stored

    def save(self, agent_id: str, stored: Stored) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        raw = {
            "checks": [c.model_dump(mode="json", by_alias=True) for c in stored.checks],
            "runs": [r.model_dump(mode="json", by_alias=True) for r in stored.runs],
            "ranWith": stored.ran_with,
        }
        tmp = self.file(agent_id).with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, indent=2))
        tmp.replace(self.file(agent_id))

    # ── what clients see ────────────────────────────────────────────────

    def view(self, agent: AgentRecord) -> AgentChecks:
        stored = self.load(agent.id)
        checks = [c.model_copy(update={"problem": self.problem(agent, c)}) for c in stored.checks]
        current = matters(agent)
        ran_with = stored.ran_with or current
        changed = [MATTERS[k] for k in MATTERS if ran_with.get(k) != current.get(k)]
        last = stored.runs[-1] if stored.runs else None
        can = comparable(agent.interface.result if agent.interface else None)
        return AgentChecks(
            checks=checks, comparable=can, last=last, changed=changed if last else []
        )

    def problem(self, agent: AgentRecord, check: Check) -> str | None:
        """Why the check cannot run now: its agent is no job any more, its form refuses its
        input, its result has no field it compares."""
        if agent.interface is None or agent.interface.result is None:
            return "its agent is not a job any more"
        try:
            interfaces.check_input(
                agent.interface, SessionInput(fields=check.input), self.settings.skills_dir
            )
        except interfaces.InterfaceError as e:
            return f"its form changed: {e}"
        gone = [k for k in check.compare if k not in comparable(agent.interface.result)]
        return f"its result no longer has {', '.join(gone)}" if gone else None

    # ── keeping, editing, forgetting ────────────────────────────────────

    def keep(self, agent: AgentRecord, body: KeepCheckRequest) -> Check:
        """A run of the agent kept as a check: its input, its valid result as the answer."""
        if agent.interface is None or agent.interface.result is None:
            raise CheckError(400, "only a job's runs can be kept as checks")
        rec = self.sessions.records.get(body.from_run)
        if rec is None or rec.agent_id != agent.id or not (rec.interface or {}).get("result"):
            raise CheckError(400, f"{body.from_run}: not a run of this agent")
        output = SessionOutput.model_validate(rec.output) if rec.output else None
        if output is None or not output.valid or not isinstance(output.value, dict):
            raise CheckError(400, "this run did not end with a valid result")
        can = comparable(agent.interface.result)
        compare = body.compare if body.compare is not None else can
        if not compare:
            raise CheckError(400, "nothing to compare: its result is free text only")
        if not set(compare) <= set(can):
            raise CheckError(400, f"not compared (free text, or not in its result): {compare}")
        check = Check(
            id="c_" + secrets.token_hex(4),
            name=body.name or rec.title or "a check",
            input=(rec.input or {}).get("fields") or {},
            answer=output.value,
            compare=compare,
            from_run=rec.id,
            created_at=now(),
        )
        stored = self.load(agent.id)
        stored.checks.append(check)
        self.save(agent.id, stored)
        return check

    def adopt(self, agent_id: str, checks: list[AgentsFileCheck]) -> None:
        """The checks of the agents file's agent a new agent is set up from (D.23)."""
        if not checks:
            return
        stored = self.load(agent_id)
        stored.checks += [
            Check(id="c_" + secrets.token_hex(4), **c.model_dump(), created_at=now())
            for c in checks
        ]
        self.save(agent_id, stored)

    def update(self, agent: AgentRecord, check_id: str, body: CheckUpdateRequest) -> Check:
        stored = self.load(agent.id)
        i = self.index(stored, check_id)
        assert agent.interface is not None and agent.interface.result is not None
        if not set(body.compare) <= set(comparable(agent.interface.result)):
            raise CheckError(400, f"not compared (free text, or not in its result): {body.compare}")
        stored.checks[i] = stored.checks[i].model_copy(
            update={"name": body.name, "compare": body.compare}
        )
        self.save(agent.id, stored)
        return stored.checks[i]

    def delete(self, agent_id: str, check_id: str) -> None:
        stored = self.load(agent_id)
        stored.checks.pop(self.index(stored, check_id))
        self.save(agent_id, stored)

    def index(self, stored: Stored, check_id: str) -> int:
        for i, c in enumerate(stored.checks):
            if c.id == check_id:
                return i
        raise CheckError(404, f"no check {check_id}")

    async def forget(self, agent_id: str) -> None:
        """The agent is deleted: its check run stopped, its checks and their runs gone."""
        if (task := self.running.pop(agent_id, None)) is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for run in self.load(agent_id).runs:
            await self.delete_sessions(run)
        self.file(agent_id).unlink(missing_ok=True)

    async def delete_sessions(self, run: CheckRun) -> None:
        for r in run.results:
            if r.session_id is not None:
                await self.sessions.delete(r.session_id)

    # ── a check run ─────────────────────────────────────────────────────

    def start(self, agent: AgentRecord) -> CheckRun:
        if agent.id in self.running:
            raise CheckError(409, "its checks are running")
        stored = self.load(agent.id)
        ready = [c for c in stored.checks if self.problem(agent, c) is None]
        if not ready:
            raise CheckError(400, "no check it can run")
        try:
            save_rules.session_model(self.settings, agent, None)
        except save_rules.CheckError as e:
            raise CheckError(409, f"its model: {e}") from None
        run = CheckRun(
            id="k_" + secrets.token_hex(4),
            started_at=now(),
            results=[CheckResult(check_id=c.id, name=c.name, state="waiting") for c in ready],
        )
        stored.runs.append(run)
        stored.ran_with = matters(agent)
        self.save(agent.id, stored)
        task = asyncio.get_running_loop().create_task(self.go(agent, run.id))
        self.running[agent.id] = task
        task.add_done_callback(lambda _: self.running.pop(agent.id, None))
        return run

    async def go(self, agent: AgentRecord, run_id: str) -> None:
        stored = self.load(agent.id)
        wanted = {r.check_id for r in self.find(stored, run_id).results}
        checks = [c for c in stored.checks if c.id in wanted]
        await self.check_all(agent, checks, None, lambda r: self.record(agent.id, run_id, r))
        self.finish(agent.id, run_id)

    async def check_all(
        self,
        agent: AgentRecord,
        checks: list[Check],
        instructions: str | None,
        update: Callable[[CheckResult], None],
    ) -> list[CheckResult]:
        """Run each check, one after another, on the agent as it is or with other `instructions`
        (an improvement's attempt, D.21); `update` is told each result as it changes."""
        done: list[CheckResult] = []
        for check in checks:
            result = CheckResult(check_id=check.id, name=check.name, state="running")
            try:
                runs = save_rules.session_model(self.settings, agent, None)
                rec = self.sessions.create(
                    agent,
                    runs,
                    origin="check",
                    run=SessionInput(fields=check.input),
                    instructions=instructions,
                )
            except (save_rules.CheckError, ValueError) as e:
                result = result.model_copy(update={"state": "error", "why": str(e)})
            else:
                result = result.model_copy(update={"session_id": rec.id})
                update(result)
                state, got, why = await self.outcome(rec.id, check)
                result = result.model_copy(update={"state": state, "got": got, "why": why})
            update(result)
            done.append(result)
        return done

    async def outcome(
        self, session_id: str, check: Check
    ) -> tuple[CheckState, dict[str, Any] | None, str | None]:
        """(state, what came back of the compared fields, why), once its run ended."""
        value, why = await self.sessions.result_of(session_id)
        if value is None:
            return "error", None, why
        got = {k: value.get(k) for k in check.compare}
        diff = differences(check, value)
        return ("failed", got, "; ".join(diff)) if diff else ("passed", got, None)

    def record(self, agent_id: str, run_id: str, result: CheckResult) -> None:
        """One check's result in a check run, as it is now."""

        def changed(run: CheckRun) -> CheckRun:
            results = [result if r.check_id == result.check_id else r for r in run.results]
            return run.model_copy(update={"results": results})

        self.replace(agent_id, run_id, changed)

    def finish(self, agent_id: str, run_id: str) -> None:
        self.replace(agent_id, run_id, lambda run: run.model_copy(update={"ended_at": now()}))
        stored = self.load(agent_id)
        old, stored.runs = stored.runs[:-KEEP], stored.runs[-KEEP:]
        self.save(agent_id, stored)
        for run in old:
            asyncio.get_running_loop().create_task(self.delete_sessions(run))

    def find(self, stored: Stored, run_id: str) -> CheckRun:
        return next(r for r in stored.runs if r.id == run_id)

    def replace(self, agent_id: str, run_id: str, change: Callable[[CheckRun], CheckRun]) -> None:
        stored = self.load(agent_id)
        stored.runs = [change(r) if r.id == run_id else r for r in stored.runs]
        self.save(agent_id, stored)

    async def close(self) -> None:
        for task in list(self.running.values()):
            task.cancel()


def interrupted(run: CheckRun) -> CheckRun:
    """A check run handlerd stopped in the middle of: what had not ended, an error."""
    results = [
        r
        if r.state in ("passed", "failed", "error")
        else r.model_copy(update={"state": "error", "why": "handlerd stopped meanwhile"})
        for r in run.results
    ]
    return run.model_copy(update={"results": results, "ended_at": run.started_at})
