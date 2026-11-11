"""Improvements of a job's instructions (D.21): the prompt writer (the agent given for one of
Handler's needs, D.18) rewrites them, again and again, and the job's checks (D.20) judge each
attempt, until they all pass or the budget (attempts, minutes) is spent. Nothing changes in the
agent until an attempt is kept.

    <state>/improvements/<agent id>.json   its last KEEP improvements, newest last

Each attempt's checks are runs of the job with the attempt's instructions instead of its own
(sessions.create's `instructions`, origin `check`); the prompt writer's runs have origin `check`
too: neither is anyone's history. Attempt 0 is the instructions as they were: it is checked
first, and kept it puts them back.
"""

import asyncio
import contextlib
import json
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from handler_contracts import (
    AgentInterface,
    Attempt,
    CheckResult,
    Improvement,
    KeepAttemptRequest,
    SessionInput,
    StartImprovementRequest,
)

from . import handler_needs, save_rules
from .agent_checks import CheckError, CheckStore
from .agents import AgentRecord, AgentRegistry
from .settings import Settings

KEEP = 10
WRITER = "prompt-writer"  # the need whose agent writes the attempts


def now() -> datetime:
    return datetime.now(UTC)


def form_fields(interface: AgentInterface | None) -> str:
    """The form's fields the instructions may name, one per line: `{{key}}: its title`."""
    props = ((interface.fields if interface else None) or {}).get("properties") or {}
    return "\n".join(f"{{{{{k}}}}}: {s.get('title', k)}" for k, s in props.items()) or "(none)"


def failures(checks: dict[str, Any], results: list[CheckResult]) -> str:
    """What the prompt writer is told of the checks that did not pass: each one's input, the
    right answer of what it compares, and what came back (or why nothing did)."""
    told = []
    for r in results:
        if r.state == "passed" or (check := checks.get(r.check_id)) is None:
            continue
        right = {k: check.answer.get(k) for k in check.compare}
        came = r.got if r.got is not None else f"no result ({r.why})"
        told.append(
            f"- {check.name}\n  input: {json.dumps(check.input)}\n  right answer: "
            f"{json.dumps(right)}\n  came back: {json.dumps(came)}"
        )
    return "\n".join(told) or "(none: every check passes)"


class ImprovementStore:
    def __init__(self, settings: Settings, registry: AgentRegistry, checks: CheckStore) -> None:
        self.settings, self.registry, self.checks = settings, registry, checks
        self.root = settings.state_dir / "improvements"
        self.running: dict[str, asyncio.Task[None]] = {}  # agent id → its improvement
        self.stopping: set[str] = set()  # improvement ids asked to stop

    # ── storage ─────────────────────────────────────────────────────────

    def file(self, agent_id: str) -> Path:
        return self.root / f"{agent_id}.json"

    def load(self, agent_id: str) -> list[Improvement]:
        if not self.file(agent_id).exists():
            return []
        found = [Improvement.model_validate(i) for i in json.loads(self.file(agent_id).read_text())]
        if found and found[-1].state == "running" and agent_id not in self.running:
            found[-1] = found[-1].model_copy(  # handlerd stopped meanwhile
                update={"state": "failed", "why": "handlerd stopped meanwhile", "ended_at": now()}
            )
        return found

    def save(self, agent_id: str, improvements: list[Improvement]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        raw = [i.model_dump(mode="json", by_alias=True) for i in improvements[-KEEP:]]
        tmp = self.file(agent_id).with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, indent=2))
        tmp.replace(self.file(agent_id))

    def get(self, agent_id: str, improvement_id: str) -> Improvement:
        for i in self.load(agent_id):
            if i.id == improvement_id:
                return i
        raise CheckError(404, f"no improvement {improvement_id}")

    def put(self, improvement: Improvement) -> None:
        """It, as it is now, in its agent's list."""
        found = self.load(improvement.agent_id)
        found = [improvement if i.id == improvement.id else i for i in found]
        self.save(improvement.agent_id, found)

    async def forget(self, agent_id: str) -> None:
        """The agent is deleted: its improvement stopped, its improvements gone."""
        if (task := self.running.pop(agent_id, None)) is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.file(agent_id).unlink(missing_ok=True)

    # ── starting, stopping, keeping ─────────────────────────────────────

    def writer(self) -> AgentRecord:
        """The prompt writer given (D.18); CheckError 409 when none is."""
        agent_id = handler_needs.given(self.settings.state_dir).get(WRITER)
        writer = self.registry.get(agent_id) if agent_id else None
        if writer is None:
            raise CheckError(409, "no prompt writer: set one up first")
        return writer

    def start(self, agent: AgentRecord, body: StartImprovementRequest) -> Improvement:
        if agent.id in self.running or agent.id in self.checks.running:
            raise CheckError(409, "it is being improved, or its checks are running")
        if agent.interface is None or agent.interface.result is None:
            raise CheckError(400, "only a job can be improved: its checks judge it")
        stored = self.checks.load(agent.id)
        if not [c for c in stored.checks if self.checks.problem(agent, c) is None]:
            raise CheckError(400, "no check it can run: keep a run whose answer is right first")
        self.writer()
        improvement = Improvement(
            id="i_" + secrets.token_hex(4),
            agent_id=agent.id,
            goal=body.goal,
            max_attempts=body.max_attempts,
            max_minutes=body.max_minutes,
            state="running",
            attempts=[Attempt(n=0, instructions=agent.instructions or "", state="checking")],
            started_at=now(),
        )
        self.save(agent.id, [*self.load(agent.id), improvement])
        task = asyncio.get_running_loop().create_task(self.go(agent, improvement.id))
        self.running[agent.id] = task
        task.add_done_callback(lambda _: self.running.pop(agent.id, None))
        return improvement

    def stop(self, agent_id: str, improvement_id: str) -> Improvement:
        improvement = self.get(agent_id, improvement_id)
        if improvement.state == "running":
            self.stopping.add(improvement_id)
        return improvement

    def keep(
        self, agent: AgentRecord, improvement_id: str, body: KeepAttemptRequest
    ) -> Improvement:
        """That attempt's instructions saved in the agent; 409 when they changed since the
        improvement started (someone else's change would be lost)."""
        improvement = self.get(agent.id, improvement_id)
        if improvement.state == "running":
            raise CheckError(409, "stop it first, or wait for its end")
        if body.attempt >= len(improvement.attempts):
            raise CheckError(404, f"no attempt {body.attempt}")
        attempt = improvement.attempts[body.attempt]
        # its instructions are still those it started from, or the attempt kept since
        ours = improvement.attempts[improvement.kept or 0].instructions
        if (agent.instructions or "") != ours:
            raise CheckError(409, "its instructions changed since: improve them again")
        try:
            save_rules.check_instructions(attempt.instructions, agent.interface)
        except save_rules.CheckError as e:
            raise CheckError(400, str(e)) from None
        self.registry.set_instructions(agent, attempt.instructions or None)
        kept = improvement.model_copy(update={"kept": attempt.n})
        self.put(kept)
        return kept

    # ── the loop ────────────────────────────────────────────────────────

    async def go(self, agent: AgentRecord, improvement_id: str) -> None:
        improvement = self.get(agent.id, improvement_id)
        deadline = time.monotonic() + improvement.max_minutes * 60
        improvement = await self.check(agent, improvement, 0)
        total = len(improvement.attempts[0].results)
        while True:
            best = improvement.attempts[improvement.best]
            why = (
                "every check passes"
                if best.passed == total
                else f"{improvement.max_attempts} attempts made"
                if len(improvement.attempts) > improvement.max_attempts
                else f"{improvement.max_minutes} min passed"
                if time.monotonic() > deadline
                else "stopped"
                if improvement_id in self.stopping
                else None
            )
            if why is not None:
                break
            improvement = await self.attempt(agent, improvement)
        self.stopping.discard(improvement_id)
        state = "stopped" if why == "stopped" else "done"
        self.put(improvement.model_copy(update={"state": state, "why": why, "ended_at": now()}))

    async def attempt(self, agent: AgentRecord, improvement: Improvement) -> Improvement:
        """One more: the prompt writer's new instructions from the best so far, then its checks."""
        n = len(improvement.attempts)
        best = improvement.attempts[improvement.best]
        writing = Attempt(n=n, instructions="", state="writing")
        improvement = self.with_attempt(improvement, writing)
        stored = {c.id: c for c in self.checks.load(agent.id).checks}
        fields = {
            "instructions": best.instructions,
            "goal": improvement.goal,
            "fields": form_fields(agent.interface),
            "failures": failures(stored, best.results),
        }
        try:
            writer = self.writer()
            runs = save_rules.session_model(self.settings, writer, None)
            rec = self.checks.sessions.create(
                writer, runs, origin="check", run=SessionInput(fields=fields)
            )
        except (CheckError, save_rules.CheckError, ValueError) as e:
            return self.with_attempt(
                improvement, writing.model_copy(update={"state": "error", "why": str(e)})
            )
        writing = writing.model_copy(update={"writer_run": rec.id})
        improvement = self.with_attempt(improvement, writing)
        value, why = await self.checks.sessions.result_of(rec.id)
        text = value.get("instructions") if value else None
        if value is None or not isinstance(text, str) or not text.strip():
            failed = writing.model_copy(update={"state": "error", "why": why or "no instructions"})
            return self.with_attempt(improvement, failed)
        try:
            save_rules.check_instructions(text, agent.interface)
        except save_rules.CheckError as e:
            failed = writing.model_copy(
                update={"state": "error", "why": str(e), "instructions": text}
            )
            return self.with_attempt(improvement, failed)
        change = str(value.get("change") or "") or None
        checking = writing.model_copy(
            update={"instructions": text, "change": change, "state": "checking"}
        )
        improvement = self.with_attempt(improvement, checking)
        return await self.check(agent, improvement, n)

    async def check(self, agent: AgentRecord, improvement: Improvement, n: int) -> Improvement:
        """Attempt n's checks, its results told as they come; then the best attempt so far."""
        stored = self.checks.load(agent.id)
        checks = [c for c in stored.checks if self.checks.problem(agent, c) is None]
        attempt = improvement.attempts[n]
        results: dict[str, CheckResult] = {}

        def told(result: CheckResult) -> None:
            nonlocal improvement
            results[result.check_id] = result
            improvement = self.with_attempt(
                improvement, attempt.model_copy(update={"results": list(results.values())})
            )

        done = await self.checks.check_all(agent, checks, attempt.instructions, told)
        passed = sum(r.state == "passed" for r in done)
        finished = attempt.model_copy(update={"results": done, "passed": passed, "state": "done"})
        improvement = self.with_attempt(improvement, finished)
        if passed > improvement.attempts[improvement.best].passed:
            improvement = improvement.model_copy(update={"best": n})
            self.put(improvement)
        return improvement

    def with_attempt(self, improvement: Improvement, attempt: Attempt) -> Improvement:
        """It with that attempt (new, or as it is now), saved."""
        attempts = [*improvement.attempts]
        if attempt.n < len(attempts):
            attempts[attempt.n] = attempt
        else:
            attempts.append(attempt)
        changed = improvement.model_copy(update={"attempts": attempts})
        self.put(changed)
        return changed

    async def close(self) -> None:
        for task in list(self.running.values()):
            task.cancel()
