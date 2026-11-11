"""Plans (D.27): a list of steps written in a plan draft (plan_drafts.py) or in an agent's folder,
approved by you, run by handlerd one after another, each a fresh session of an agent working in
that folder, stopped at the first step not done.

    parse          a plan file's text → its title, agent, context, step time limit, steps and
                   problems (approval is refused while there is one)
    agent_problems why an agent cannot run a plan's steps (no folder, not in bypass mode…)
    Source         where a plan's text is read from: a file of an agent's folder, or a draft
    PlanStore      reading it (no link followed), its runner (named in it, or chosen on review),
                   approving it (the digest read), the copies approved and their state

The approved copy is handlerd's, never in the folder nor in any sandbox:

    <state>/plans/<id>/plan.md      the text approved, as read
                       plan.json    what runs: its agent (by id), its steps
                       state.json   how it goes: the plan's state, each step's
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import secrets
import shutil
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from handler_contracts import (
    AgentInterface,
    PlanRead,
    PlanRunner,
    PlanState,
    PlanStep,
    PlanStepResult,
    PlanStepState,
    PlanStepView,
    PlanView,
    RefusedHost,
    SessionOutput,
    SessionPlan,
)
from handler_harness import catalog

from . import definitions, interfaces, refusals, save_rules, session_files
from .agents import AgentRecord, AgentRegistry, RunsAs
from .files import write_private
from .inbox import Inbox
from .projects import ProjectRegistry
from .sessions import PlanTurn, SessionRecord, SessionStore
from .settings import Settings

log = logging.getLogger(__name__)

# skills/handler-plan, how to write a plan: shipped with the plan builder's definition (D.18)
SHIPPED = Path(__file__).parent / "data" / "handler-needs" / "plan-builder"

MAX_BYTES = 256 * 1024  # a plan file
DEFAULT_STEP_TIMEOUT_SEC = 3 * 3600  # a step's turn, when its plan says none
MAX_STEP_TIMEOUT_SEC = 24 * 3600  # as a job's (D.18)
MIN_STEP_TIMEOUT_SEC = 60
MAX_NOTES = 16 * 1024  # the notes of the steps before a step, in its first turn
WATCH_POLL = 1.0
# what a step's session ends with (PlanStepResult)
STEP_RESULT: dict[str, Any] = {
    "type": "object",
    "required": ["status", "summary"],
    "additionalProperties": False,
    "properties": {
        "status": {"enum": ["done", "failed"]},
        "summary": {"type": "string"},
        "notes": {"type": "string"},
    },
}

TITLE = re.compile(r"^#\s+Plan:\s*(.*?)\s*$", re.I)
STEP = re.compile(r"^##\s+(\d+)\.\s*(.*?)\s*$")
HEADING = re.compile(r"^##(?!#)")  # a step's level: any other is text
HEADER = re.compile(r"^(Agent|Context|Step time limit):\s*(.*?)\s*$", re.I)
FIELD = re.compile(r"^(Goal|Done when):\s*(.*?)\s*$", re.I)
LIMIT = re.compile(r"^(\d+)\s*(h|m)$", re.I)
FENCE = re.compile(r"^\s*(```|~~~)")


class PlanError(Exception):
    """A plan request refused: its HTTP status, and why."""

    def __init__(self, status: int, title: str, detail: str | None = None) -> None:
        super().__init__(detail or title)
        self.status = status
        self.title = title
        self.detail = detail


# ── the file ────────────────────────────────────────────────────────────


@dataclass
class Parsed:
    title: str | None = None
    agent: str | None = None
    context: str | None = None
    step_timeout_sec: int = DEFAULT_STEP_TIMEOUT_SEC
    steps: list[PlanStep] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass
class _Step:
    n: int
    title: str
    before: list[str] = field(default_factory=list)  # text before its Goal: part of its goal
    goal: list[str] | None = None
    done_when: list[str] | None = None


def parse(text: str) -> Parsed:
    """`# Plan: <title>`; then `Agent:`, `Context:` (until the first step, on several lines),
    `Step time limit:` (`<n>h` or `<n>m`); then the steps, `## <n>. <title>`, each with `Goal:`
    and `Done when:` (each on several lines; any other text of the step is part of its goal).
    Lines in a fenced code block are text."""
    parser = _Parser()
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            parser.text(line)
        elif fenced:
            parser.text(line)
        else:
            parser.line(line)
    return parser.end()


class _Parser:
    def __init__(self) -> None:
        self.out = Parsed()
        self.seen: set[str] = set()  # header lines, and text before the title
        self.steps: list[_Step] = []
        self.context: list[str] | None = None
        self.current: list[str] | None = None  # where the next lines go, under a heading

    def problem(self, text: str) -> None:
        self.out.problems.append(text)

    def line(self, line: str) -> None:
        if m := TITLE.match(line):
            if self.out.title is not None:
                self.problem("two `# Plan:` titles: a file holds one plan")
            self.out.title = m.group(1)
        elif self.out.title is not None and HEADING.match(line):
            self.heading(line)
        elif self.out.title is not None and self.current is None and (m := HEADER.match(line)):
            self.header(m.group(1), m.group(2))
        elif self.steps and self.current is not None and (m := FIELD.match(line)):
            self.field(self.steps[-1], m.group(1), m.group(2))
        else:
            self.text(line)

    def text(self, line: str) -> None:
        """A line of the current field (the context, a step's), else a problem when not blank."""
        if self.out.title is None:
            if line.strip() and "start" not in self.seen:
                self.problem("the file starts with `# Plan: <title>`")
                self.seen.add("start")
        elif self.current is not None:
            self.current.append(line)
        elif self.context is not None:
            self.context.append(line)
        elif line.strip():
            self.problem(
                f"`{line.strip()[:80]}`: not a header line (Agent:, Context:, Step time limit:)"
            )

    def heading(self, line: str) -> None:
        if m := STEP.match(line):
            self.steps.append(_Step(int(m.group(1)), m.group(2)))
            self.current = self.steps[-1].before
        else:
            self.problem(f"`{line.strip()}`: a step's heading is `## <n>. <title>`")
            self.current = []  # its text goes nowhere

    def header(self, name: str, value: str) -> None:
        key = name.lower()
        if key in self.seen:
            self.problem(f"two `{name}:` lines")
        self.seen.add(key)
        if key == "agent":
            self.out.agent = value or None
        elif key == "context":
            self.context = [value]
        elif (limit := _limit(value)) is not None:
            self.out.step_timeout_sec = limit
        else:
            self.problem(
                f"`Step time limit: {value}`: between 1m and 24h, written `<n>h` or `<n>m`"
            )

    def field(self, step: _Step, name: str, value: str) -> None:
        goal = name.lower() == "goal"
        if (step.goal if goal else step.done_when) is not None:
            self.problem(f"step {step.n}: two `{name}:` lines")
        self.current = [value]
        if goal:
            step.goal = self.current
        else:
            step.done_when = self.current

    def end(self) -> Parsed:
        out = self.out
        if out.title is None and "start" not in self.seen:
            self.problem("no title: the file starts with `# Plan: <title>`")
        elif not out.title:
            self.problem("the title is empty")
        out.context = _text(self.context)
        if not self.steps:
            self.problem("no step: each is `## <n>. <title>`, with `Goal:` and `Done when:`")
        for i, step in enumerate(self.steps, 1):
            if step.n != i:
                self.problem(f"steps are numbered 1, 2, … in order: step {i} is numbered {step.n}")
            goal = _text([*step.before, *(step.goal or [])])
            done_when = _text(step.done_when)
            if step.goal is None or goal is None:
                self.problem(f"step {step.n} has no `Goal:`")
            if done_when is None:
                self.problem(f"step {step.n} has no `Done when:`")
            if not step.title:
                self.problem(f"step {step.n} has no title")
            out.steps.append(
                PlanStep(n=step.n, title=step.title, goal=goal or "", done_when=done_when or "")
            )
        return out


def _limit(text: str) -> int | None:
    if not (m := LIMIT.match(text.strip())):
        return None
    seconds = int(m.group(1)) * (3600 if m.group(2).lower() == "h" else 60)
    return seconds if MIN_STEP_TIMEOUT_SEC <= seconds <= MAX_STEP_TIMEOUT_SEC else None


def _text(lines: list[str] | None) -> str | None:
    """The lines as one text, without the blank lines around it; None when there is none."""
    joined = "\n".join(lines or []).strip("\n")
    return joined.rstrip() or None


# ── its agent ───────────────────────────────────────────────────────────


def agent_problems(settings: Settings, agent: AgentRecord, mode: bool = True) -> list[str]:
    """Why `agent` cannot run a plan's steps: each one a fresh session nobody answers, working in
    its folder (`plan.its-agent-its-settings`); without its mode, when `mode` is False (one you
    may switch on review)."""
    name = agent.name or agent.id
    if agent.app is not None:
        return [f"{name} is one of the app {agent.app}'s parts: started by its app only"]
    if agent.scope is None or agent.model_alone:
        return [f"{name} has no folder of its own: a plan's steps work in one"]
    found = []
    if agent.interface is not None:
        found.append(f"{name} takes a form (a brief or a job): a plan's agent is one you chat with")
    if mode and agent.permissions != "bypass":
        found.append(f"its agent runs steps nobody answers: set {name}'s mode to bypass")
    try:
        save_rules.session_model(settings, agent, None)
    except save_rules.CheckError as e:
        found.append(f"{name}'s model: {e}")
    return found


def recommendation(runs: RunsAs) -> str | None:
    """On a subscription: what an unattended run on it is told (the vendors' terms, E), a
    recommendation, never a refusal: you approved the plan, so you started each step."""
    if runs.account is None or runs.harness is None:
        return None
    login = catalog.get(runs.harness).descriptor.login
    if login is None:
        return None
    return (
        f"Runs on your subscription (account {runs.account}): its steps run one after another, "
        f"nobody following them. Check the terms of your {login.subscription} subscription "
        f"({login.terms}); an API key (a provider) is recommended."
    )


def install_skill(settings: Settings) -> None:
    """The skill `handler-plan` (how an agent writes a plan) into the library, once (D.17): you
    give it to the agents you choose; deleted, it stays deleted."""
    marker = settings.state_dir / "plans" / "skill-installed"
    if marker.exists():
        return
    definitions.install_skills(SHIPPED, settings.skills_dir)
    marker.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker.touch()


# ── where its text is ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Source:
    """Where a plan's text is read from: `path` in the folder `where`, read without following a
    link; `folder`, where its steps work and its runners are; `draft_id`, a draft's (its text in
    its own folder, its steps in its project's), else a file of that folder."""

    where: Path
    path: str
    folder: str
    draft_id: str | None = None


def file_of(agent: AgentRecord, path: str) -> Source:
    """A file at `path` in an agent's folder."""
    if agent.scope is None:
        raise PlanError(409, "no folder", f"{agent.name or agent.id} has no folder of its own")
    return Source(Path(agent.scope), path, agent.scope)


# ── the copies approved ─────────────────────────────────────────────────


@dataclass
class StepProgress:
    n: int
    state: PlanStepState = "waiting"
    session_id: str | None = None
    result: dict[str, Any] | None = None  # PlanStepResult, as its session gave it
    error: str | None = None
    started_at: str | None = None  # ISO 8601
    ended_at: str | None = None
    refused: list[dict[str, Any]] = field(default_factory=list)  # RefusedHost, as JSON
    said: str | None = None  # what its agent's last message says of them


@dataclass
class Progress:
    state: PlanState
    steps: list[StepProgress]
    stopped_because: str | None = None

    @classmethod
    def of(cls, data: dict[str, Any]) -> "Progress":
        steps = [StepProgress(**s) for s in data.pop("steps")]
        return cls(**data, steps=steps)


@dataclass
class Approved:
    """plan.json: what runs, never changed after its approval."""

    id: str
    title: str
    source: str | None  # the file, relative to its folder; or…
    folder: str
    digest: str
    agent_id: str
    context: str | None
    step_timeout_sec: int
    approved_at: str  # ISO 8601
    steps: list[dict[str, Any]]  # PlanStep, as JSON
    draft_id: str | None = None  # …the draft it was approved from

    def step(self, n: int) -> PlanStep:
        return PlanStep.model_validate(self.steps[n - 1])


class PlanStore:
    def __init__(
        self,
        settings: Settings,
        registry: AgentRegistry,
        projects: ProjectRegistry,
        sessions: SessionStore,
        inbox: Inbox,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.projects = projects
        self.sessions = sessions
        self.inbox = inbox
        self.root = settings.state_dir / "plans"
        self.runners: dict[str, asyncio.Task[None]] = {}  # a running plan's id → its runner

    # ── reading a file ──────────────────────────────────────────────────

    def read(self, source: Source, runner: str | None = None) -> PlanRead:
        """The plan's text, read without following a link (`plan.read-without-following-links`),
        parsed; its agent the `runner` chosen among the agents working in its folder, else the one
        its `Agent:` line names among them."""
        path = source.path
        try:
            data, size = session_files.read_bytes(source.where, path)
        except session_files.PathError as e:
            raise PlanError(404 if e.missing else 400, "cannot read the plan", str(e)) from None
        except OSError as e:
            raise PlanError(400, "cannot read the plan", f"{path}: {e.strerror}") from None
        digest = hashlib.sha256(data).hexdigest()
        if size > MAX_BYTES:
            return PlanRead(
                path=path,
                digest=digest,
                step_timeout_sec=DEFAULT_STEP_TIMEOUT_SEC,
                problems=[f"larger than {MAX_BYTES // 1024} KiB"],
                text="",
            )
        try:
            text = data.decode()
        except UnicodeDecodeError:
            return PlanRead(
                path=path,
                digest=digest,
                step_timeout_sec=DEFAULT_STEP_TIMEOUT_SEC,
                problems=["not UTF-8 text"],
                text="",
            )
        parsed = parse(text)
        agent, problems = self.runner(source.folder, parsed.agent, runner)
        problems = parsed.problems + problems
        advice = None
        if agent is not None:
            problems += agent_problems(self.settings, agent)
            advice = recommendation(agent.model)
        project = self.projects.by_folder(source.folder)
        return PlanRead(
            path="/".join(p for p in path.split("/") if p),
            digest=digest,
            title=parsed.title,
            agent=parsed.agent,
            agent_id=agent.id if agent else None,
            runners=self.runners_in(source.folder),
            project_id=project.id if project else None,
            context=parsed.context,
            step_timeout_sec=parsed.step_timeout_sec,
            steps=parsed.steps,
            problems=problems,
            recommendation=advice,
            text=text,
        )

    def runner(
        self, folder: str, name: str | None, chosen: str | None
    ) -> tuple[AgentRecord | None, list[str]]:
        """The agent that runs a plan of `folder`, or why there is none: the one `chosen` on
        review, else the one its `Agent:` line names, among the agents working there."""
        if chosen is not None:
            agent = next((a for a in self.working_in(folder) if a.id == chosen), None)
            if agent is None:
                return None, [f"the agent chosen to run it does not work in {folder}"]
            return agent, []
        if name is None:
            return None, ["no `Agent:` line: choose the agent that runs its steps"]
        named = self.named(folder, name)
        if not named:
            return None, [f"no agent named {name} works in {folder}"]
        if len(named) > 1:
            return None, [f"{len(named)} agents named {name} work in this folder"]
        return named[0], []

    def working_in(self, folder: str) -> list[AgentRecord]:
        """The agents working in `folder`: its project's, and those of no project there."""
        return [a for a in self.registry.agents.values() if a.scope == folder and not a.chat]

    def named(self, folder: str, name: str) -> list[AgentRecord]:
        """The agents of that name (without case) working in `folder`."""
        key = name.strip().lower()
        return [a for a in self.working_in(folder) if (a.name or "").strip().lower() == key]

    def runners_in(self, folder: str) -> list[PlanRunner]:
        """The agents working in `folder` that may run a plan's steps, by name: those with no
        problem but their mode, which you may switch on review."""
        found = [
            PlanRunner(id=a.id, name=a.name or a.id, bypass=a.permissions == "bypass")
            for a in self.working_in(folder)
            if not agent_problems(self.settings, a, mode=False)
        ]
        return sorted(found, key=lambda r: r.name.lower())

    # ── approving ───────────────────────────────────────────────────────

    def approve(self, source: Source, digest: str, runner: str | None = None) -> PlanView:
        """Its text read again: the same digest as the one you read, no problem
        (`plan.what-runs-is-what-you-approved`); its copy kept in handlerd's state, a new plan
        each time, never changed by its draft afterwards (`plan.a-draft-is-not-a-plan`); its
        runner bound by id (`plan.its-agent-its-settings`), run from its first step."""
        read = self.read(source, runner)
        if read.digest != digest:
            raise PlanError(
                409, "the plan changed since you read it", "read it again, then approve it"
            )
        if read.problems:
            raise PlanError(409, "the plan has problems", "; ".join(read.problems))
        assert read.agent_id is not None and read.title is not None  # else a problem
        if self.running_of(read.agent_id) is not None:
            raise PlanError(409, "its agent already runs a plan", "cancel it, or wait for its end")
        plan = Approved(
            id="p_" + secrets.token_hex(8),
            title=read.title,
            source=None if source.draft_id else read.path,
            draft_id=source.draft_id,
            folder=source.folder,
            digest=read.digest,
            agent_id=read.agent_id,
            context=read.context,
            step_timeout_sec=read.step_timeout_sec,
            approved_at=datetime.now(UTC).isoformat(),
            steps=[s.model_dump(mode="json", by_alias=True) for s in read.steps],
        )
        folder = self.root / plan.id
        folder.mkdir(mode=0o700, parents=True)
        self.root.chmod(0o700)
        write_private(folder / "plan.md", read.text)
        write_private(folder / "plan.json", json.dumps(asdict(plan), indent=2))
        steps = [StepProgress(n=s.n) for s in read.steps]
        self.save_progress(plan.id, Progress(state="running", steps=steps))
        self.watch(plan.id)
        return self.view(plan.id)

    # ── stored ──────────────────────────────────────────────────────────

    def ids(self) -> list[str]:
        return [p.parent.name for p in self.root.glob("*/plan.json")]

    def plan(self, plan_id: str) -> Approved:
        try:
            return Approved(**json.loads((self.root / plan_id / "plan.json").read_text()))
        except (FileNotFoundError, NotADirectoryError):
            raise PlanError(404, "no such plan", plan_id) from None

    def text(self, plan_id: str) -> str:
        """The text approved, as read: Edit as a new draft copies it."""
        self.plan(plan_id)
        return (self.root / plan_id / "plan.md").read_text()

    def progress(self, plan_id: str) -> Progress:
        return Progress.of(json.loads((self.root / plan_id / "state.json").read_text()))

    def save_progress(self, plan_id: str, progress: Progress) -> None:
        write_private(self.root / plan_id / "state.json", json.dumps(asdict(progress), indent=2))

    def running_of(self, agent_id: str) -> str | None:
        """The plan of that agent running, if any (one at a time per agent)."""
        for plan_id in self.ids():
            if (
                self.plan(plan_id).agent_id == agent_id
                and self.progress(plan_id).state == "running"
            ):
                return plan_id
        return None

    def view(self, plan_id: str) -> PlanView:
        plan, progress = self.plan(plan_id), self.progress(plan_id)
        agent = self.registry.get(plan.agent_id)
        steps = []
        for p in progress.steps:
            result = p.result or {}
            steps.append(
                PlanStepView(
                    **plan.step(p.n).model_dump(),
                    state=p.state,
                    session_id=p.session_id,
                    summary=result.get("summary"),
                    notes=result.get("notes"),
                    error=p.error,
                    started_at=_time(p.started_at),
                    ended_at=_time(p.ended_at),
                    refused=refusals.decided(_hosts(p), agent),
                    said=p.said,
                )
            )
        return PlanView(
            id=plan.id,
            title=plan.title,
            source=plan.source,
            draft_id=plan.draft_id,
            folder=plan.folder,
            digest=plan.digest,
            agent_id=plan.agent_id,
            agent=(agent.name or agent.id) if agent else None,
            context=plan.context,
            step_timeout_sec=plan.step_timeout_sec,
            approved_at=datetime.fromisoformat(plan.approved_at),
            state=progress.state,
            stopped_because=progress.stopped_because,
            steps=steps,
        )

    def list(self, agent_id: str | None = None, folder: str | None = None) -> list[PlanView]:
        """Most recent first; those of that agent, those working in that folder (a project's)."""
        views = [self.view(i) for i in self.ids()]
        views = [v for v in views if agent_id is None or v.agent_id == agent_id]
        views = [v for v in views if folder is None or v.folder == folder]
        return sorted(views, key=lambda v: v.approved_at, reverse=True)

    def delete(self, plan_id: str) -> None:
        """Its copy and state (its steps' sessions stay with its agent); not while it runs."""
        self.plan(plan_id)
        if self.progress(plan_id).state == "running":
            raise PlanError(409, "the plan is running", "cancel it first")
        shutil.rmtree(self.root / plan_id)

    # ── running it ──────────────────────────────────────────────────────

    def run(self, plan_id: str, start: int) -> PlanView:
        """Run it again from step `start` (`plan.started-by-you-only`): stopped or done, `start` at
        most its first step not done; the steps from there start again, each a new session."""
        plan, progress = self.plan(plan_id), self.progress(plan_id)
        if progress.state == "running":
            raise PlanError(409, "the plan is running", "cancel it first")
        first = next((s.n for s in progress.steps if s.state != "done"), len(progress.steps))
        if start > first:
            raise PlanError(
                409, f"step {first} is not done", f"run it again from step {first} or before"
            )
        agent = self.registry.get(plan.agent_id)
        if agent is None:
            raise PlanError(409, "its agent was deleted", "approve the plan again for another")
        if found := agent_problems(self.settings, agent):
            raise PlanError(409, "its agent cannot run it", "; ".join(found))
        if self.running_of(plan.agent_id) is not None:
            raise PlanError(409, "its agent already runs a plan", "cancel it, or wait for its end")
        steps = [s if s.n < start else StepProgress(n=s.n) for s in progress.steps]
        self.save_progress(plan_id, Progress(state="running", steps=steps))
        self.watch(plan_id)
        return self.view(plan_id)

    async def allow(self, plan_id: str, n: int, hosts: Sequence[str]) -> None:
        """*Allow and run again*: hosts refused to step `n` allowed for the plan's agent, and
        applied to its running sandboxes, before `run` (rule plan.a-refused-host-is-reported)."""
        plan, progress = self.plan(plan_id), self.progress(plan_id)
        if not 1 <= n <= len(progress.steps):
            raise PlanError(404, "no such step", str(n))
        refused = {h.host for h in _hosts(progress.steps[n - 1])}
        if others := [h for h in hosts if h not in refused]:
            raise PlanError(409, f"not refused to step {n}", ", ".join(others))
        agent = self.registry.get(plan.agent_id)
        if agent is None:
            raise PlanError(409, "its agent was deleted", "approve the plan again for another")
        if failures := await refusals.decide(self.registry, agent, [*hosts], "allowed"):
            log.warning("plan %s: allowed, not applied: %s", plan_id, "; ".join(failures))

    async def cancel(self, plan_id: str) -> PlanView:
        """Its running step's session stopped; the plan stopped (`plan.stops-at-the-first-failure`)."""
        self.plan(plan_id)
        progress = self.progress(plan_id)
        if progress.state != "running":
            raise PlanError(409, "the plan is not running")
        if (runner := self.runners.pop(plan_id, None)) is not None:
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner
        progress = self.progress(plan_id)
        running = next((s for s in progress.steps if s.state == "running"), None)
        if running is not None:
            running.state, running.ended_at = "cancelled", _now()
        progress.state, progress.stopped_because = "stopped", "cancelled by you"
        self.save_progress(plan_id, progress)
        if running is not None and running.session_id is not None:
            await self.sessions.stop(running.session_id, "plan cancelled", "explicit")
        return self.view(plan_id)

    def watch(self, plan_id: str, resumed: bool = False) -> None:
        task = asyncio.get_running_loop().create_task(self._run(plan_id, resumed))
        self.runners[plan_id] = task
        task.add_done_callback(lambda t: self._forget(plan_id, t))

    def _forget(self, plan_id: str, task: asyncio.Task[None]) -> None:
        if self.runners.get(plan_id) is task:
            del self.runners[plan_id]
        if not task.cancelled() and (e := task.exception()) is not None:
            log.error("plan %s: its runner failed", plan_id, exc_info=e)

    def start_watching(self) -> None:
        """At start: the plans running when handlerd stopped go on; a step whose session handlerd
        stopped failed (its sessions were stopped with it)."""
        for plan_id in self.ids():
            if self.progress(plan_id).state == "running":
                self.watch(plan_id, resumed=True)

    async def _run(self, plan_id: str, resumed: bool) -> None:
        """One step after another (`plan.one-step-after-another`), stopped at the first not done
        (`plan.stops-at-the-first-failure`)."""
        while True:
            plan, progress = self.plan(plan_id), self.progress(plan_id)
            step = next((s for s in progress.steps if s.state in ("waiting", "running")), None)
            if step is None:
                progress.state = "done"
                self.save_progress(plan_id, progress)
                return
            if step.state == "waiting":
                try:
                    step.session_id = self.start_step(plan, progress, step.n)
                except PlanError as e:
                    step.error = e.detail or e.title
                    self.stop(plan_id, progress, step)
                    return
                step.state, step.started_at = "running", _now()
                self.save_progress(plan_id, progress)
            assert step.session_id is not None
            outcome = self.outcome(plan.agent_id, step.session_id, resumed)
            while outcome is None:
                await asyncio.sleep(WATCH_POLL)
                outcome = self.outcome(plan.agent_id, step.session_id, resumed)
            resumed = False
            progress = self.progress(plan_id)  # as it is now
            step = progress.steps[step.n - 1]
            step.result, step.error = outcome
            step.ended_at = _now()
            self.read_refused(plan, step)
            if step.result is None or step.result["status"] != "done":
                self.stop(plan_id, progress, step)
                return
            step.state = "done"
            self.save_progress(plan_id, progress)
            if step.refused:
                self.tell(plan, step)

    def stop(self, plan_id: str, progress: Progress, step: StepProgress) -> None:
        step.state, step.ended_at = "failed", step.ended_at or _now()
        why = step.error or (step.result or {}).get("summary") or "failed"
        progress.state, progress.stopped_because = "stopped", f"step {step.n} failed: {why}"
        self.save_progress(plan_id, progress)
        self.tell(self.plan(plan_id), step)

    def read_refused(self, plan: Approved, step: StepProgress) -> None:
        """The hosts the network filter refused to the step's session, neither allowed nor kept
        blocked: a step that failed with them failed because of them, in Handler's words, not
        its agent's guess; one done gets them in its notes, so the next steps know (rule
        plan.a-refused-host-is-reported)."""
        agent = self.registry.get(plan.agent_id)
        rec = self.sessions.records.get(step.session_id or "")
        if agent is None or rec is None:
            return
        hosts = refusals.refused(self.sessions.event_log(rec.id), agent)
        if not hosts:
            return
        result = step.result or {}
        step.refused = [h.model_dump(mode="json", exclude_none=True) for h in hosts]
        step.said = refusals.said_about(hosts, rec.answer, result.get("summary"))
        if result.get("status") == "done":
            notes, line = result.get("notes"), refusals.notes_line(hosts)
            step.result = result | {"notes": f"{notes}\n\n{line}" if notes else line}
        else:
            step.error = refusals.reason(hosts)

    def tell(self, plan: Approved, step: StepProgress) -> None:
        """The inbox told: the plan stopped at a step, and why; or a step that completed with
        hosts refused. One message per step's run."""
        agent = self.registry.get(plan.agent_id)
        hosts = _hosts(step)
        title = plan.step(step.n).title
        summary = (step.result or {}).get("summary")
        if step.state == "failed":
            what, why = f"Stopped at step {step.n}: {title}", step.error or summary or "failed"
        else:
            what, why = f"Step {step.n} completed: {title}", summary or refusals.completed(hosts)
        self.inbox.add(
            source="plan",
            name=plan.title,
            agent=(agent.name or agent.id) if agent else None,
            agent_id=plan.agent_id,
            person="owner",
            title=what,
            status="failed" if step.state == "failed" else "attention",
            summary=why,
            plan_id=plan.id,
            step=step.n,
            session_id=step.session_id,
            refused=hosts,
            said=step.said,
        )

    def start_step(self, plan: Approved, progress: Progress, n: int) -> str:
        """Step `n`'s session: a fresh one of the plan's agent, with its settings as they are now
        (`plan.its-agent-its-settings`), unattended, its first turn composed from the approved copy
        (`plan.a-step-knows-only-its-notes`)."""
        agent = self.registry.get(plan.agent_id)
        if agent is None:
            raise PlanError(409, "its agent was deleted")
        if found := agent_problems(self.settings, agent):
            raise PlanError(409, "its agent cannot run it", "; ".join(found))
        if agent.scope != plan.folder:
            raise PlanError(409, "its agent works elsewhere", f"{agent.scope}, not {plan.folder}")
        runs = save_rules.session_model(self.settings, agent, None)  # checked: agent_problems
        earlier = [
            (plan.step(s.n), (s.result or {}).get("notes")) for s in progress.steps if s.n < n
        ]
        step = plan.step(n)
        interface = AgentInterface(result=STEP_RESULT, timeout_sec=plan.step_timeout_sec)
        session = self.sessions.create(
            agent,
            runs,
            prompt=first_turn(plan, step, earlier),
            origin="plan",
            step=PlanTurn(
                plan=SessionPlan(id=plan.id, step=n),
                title=f"{plan.title} · step {n}: {step.title}",
                interface=interface,
            ),
        )
        return session.id

    def outcome(
        self, agent_id: str, session_id: str, resumed: bool
    ) -> tuple[dict[str, Any] | None, str | None] | None:
        """(its result, why it has none) once the step's session ended; None until then."""
        rec = self.sessions.records.get(session_id)
        if rec is None:
            return None, "its session was deleted"
        if self.registry.get(agent_id) is None:
            return None, "its agent was deleted"
        sessions = self.sessions
        live = session_id in sessions.live or session_id in sessions.starting
        waiting = session_id in sessions.waits or rec.waiting_for is not None
        if live or waiting or rec.state in ("starting", "running"):
            return None
        output = SessionOutput.model_validate(rec.output) if rec.output else None
        if output is not None and output.valid and isinstance(output.value, dict):
            return PlanStepResult.model_validate(output.value).model_dump(exclude_none=True), None
        return None, _why(rec, output, resumed)

    async def close(self) -> None:
        runners = list(self.runners.values())
        for task in runners:
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*runners, return_exceptions=True)


def first_turn(plan: Approved, step: PlanStep, earlier: list[tuple[PlanStep, str | None]]) -> str:
    """A step's first turn, after its agent's instructions: the plan, its step, the notes of the
    steps before it (at most MAX_NOTES bytes, the oldest left out first), what `done` means,
    and how to give the result back."""
    total = len(plan.steps)
    parts = [f"# Plan: {plan.title}"]
    if plan.context:
        parts.append(plan.context)
    parts.append(
        f"## You are doing step {step.n} of {total}: {step.title}\n\n"
        "This session is new: of the steps before it, you know only their notes below. "
        "Do this step only; the steps after it are done in sessions of their own.\n\n"
        f"### Goal\n\n{step.goal}\n\n### Done when\n\n{step.done_when}"
    )
    if earlier:
        parts.append(notes_part(earlier))
    parts.append(
        "## Before you answer\n\n"
        'Check the "Done when" yourself: run what it names, and read what it gives. Answer '
        "`done` only when it is met; answer `failed`, with why in the summary, when it is not "
        "or when you could not do the step: the plan then stops, and no later step runs. Put in "
        "`notes` what the steps after it need to know (what you did, where, what is left): "
        "they read your notes, never this session."
    )
    parts.append(interfaces.result_rule(STEP_RESULT))
    return "\n\n".join(parts)


def notes_part(earlier: list[tuple[PlanStep, str | None]]) -> str:
    """The steps before it, their title and notes, at most MAX_NOTES bytes: the oldest left out
    first, saying so."""
    blocks = [f"### Step {s.n}: {s.title}\n\n{notes or '(no notes)'}" for s, notes in earlier]
    dropped = 0
    while blocks and len("\n\n".join(blocks).encode()) > MAX_NOTES:
        blocks.pop(0)
        dropped += 1
    head = "## The steps before it"
    if dropped:
        head += f"\n\nThe notes of steps 1 to {dropped} are left out: more than 16 KiB in all."
    if not blocks:  # a single step's notes over the limit: its end
        last, notes = earlier[-1]
        text = (notes or "")[-(MAX_NOTES // 2) :]
        blocks = [f"### Step {last.n}: {last.title}\n\n… {text}"]
    return "\n\n".join([head, *blocks])


def _hosts(step: StepProgress) -> list[RefusedHost]:
    return [RefusedHost.model_validate(h) for h in step.refused]


def _why(rec: SessionRecord, output: SessionOutput | None, resumed: bool) -> str:
    """Why a step's session ended with no result."""
    if resumed:  # handlerd stopped its sessions as it stopped
        return "handlerd restarted during the step"
    if rec.last_stop_reason == "timed_out":
        limit = AgentInterface.model_validate(rec.interface).timeout_sec
        assert limit is not None  # a step's interface: the plan's step time limit (start_step)
        return f"timed out after {_duration(limit)}"
    return (
        (output.error if output else None)
        or rec.error
        or f"its turn ended: {rec.last_stop_reason or 'no result'}"
    )


def _duration(seconds: int) -> str:
    return f"{seconds // 3600} h" if seconds % 3600 == 0 else f"{seconds // 60} min"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _time(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso) if iso else None
