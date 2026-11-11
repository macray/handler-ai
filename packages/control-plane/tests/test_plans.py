"""Unit tests: plans (D.27), without sandboxes: a plan file read from an agent's folder and
parsed, approved by its digest, kept in handlerd's state, its steps run one after another (their
sessions recorded, not run)."""

import asyncio
import hashlib
import os
import shutil
import stat
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import (
    AddonUse,
    AgentInterface,
    PlanStep,
    PlanView,
    SessionOutput,
    SessionPlanDraft,
)
from handler_control import desktop, plan_drafts, plans, save_rules, skills
from handler_control.agents import AgentRecord, AgentRegistry, CheckedSettings, RunsAs
from handler_control.inbox import Inbox
from handler_control.plan_drafts import DraftError, PlanDrafts
from handler_control.plans import PlanError, PlanStore, parse
from handler_control.projects import ProjectRecord, ProjectRegistry
from handler_control.sessions import DraftWork, SessionRecord, SessionStore
from handler_control.settings import Settings
from handler_harness.render import FILTERED_NETWORK

PLAN = """# Plan: the map's rules on the sandbox tests
Agent: dev
Context: read docs/concepts.md;
commit after each step.

## 1. Mark the sandbox tests
Goal: every test of tests/sandbox proving a rule carries its marker.
Done when: `pytest tests/sandbox` passes;
no sandbox rule without a test.

## 2. The docs
Read the README first.
Goal: the docs say it.

```sh
## not a heading: in a code block
```
Done when: `./scripts/ci.sh` passes.
"""


class Fixture:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.settings = Settings(
            port=7430,
            config_dir=tmp_path / "config",
            state_dir=tmp_path / "state",
            bindings_dir=tmp_path / "bindings",
            allowed_origins=frozenset(),
            web_ui_dir=tmp_path / "ui",
            data_dir=tmp_path / "data",
            skills_dir=tmp_path / "skills",
        )
        self.folder = tmp_path / "code" / "x"
        (self.folder / "plans").mkdir(parents=True)
        self.registry = AgentRegistry(self.settings.state_dir)
        self.projects = ProjectRegistry(self.settings.state_dir, self.registry)
        self.sessions = SessionStore(self.settings, self.registry)
        self.inbox = Inbox(self.settings)
        self.store = PlanStore(
            self.settings, self.registry, self.projects, self.sessions, self.inbox
        )
        self.created: list[dict[str, Any]] = []
        self.stopped: list[str] = []
        self.loop = asyncio.new_event_loop()
        monkeypatch.setattr(save_rules, "session_model", lambda _s, agent, _g: agent.model)
        monkeypatch.setattr(self.sessions, "create", self.create)
        monkeypatch.setattr(self.sessions, "stop", self.stop)
        monkeypatch.setattr(plans, "WATCH_POLL", 0.01)
        monkeypatch.setattr(desktop, "notify", lambda *_: False)

    def create(self, agent: AgentRecord, runs: RunsAs, **kw: Any) -> SessionRecord:
        """What SessionStore.create would record, running, without starting it."""
        now = datetime.now(UTC)
        step = kw["step"]
        rec = SessionRecord(
            id=f"s_{len(self.created)}",
            agent_id=agent.id,
            harness=runs.harness,
            scope=agent.scope or "",
            created_at=now,
            last_activity_at=now,
            agents_model=True,
            state="running",
            origin=kw["origin"],
            title=step.title,
            plan=step.plan.model_dump(),
            interface=step.interface.model_dump(mode="json", by_alias=True),
        )
        self.sessions.records[rec.id] = rec
        self.created.append(kw)
        return rec

    async def stop(self, session_id: str, reason: str, how: str) -> None:
        self.stopped.append(session_id)
        self.end(session_id, None, stop="cancelled")

    def end(self, session_id: str, result: dict[str, Any] | None, stop: str = "end_turn") -> None:
        """The step's session ended: with `result` in its final message, or none."""
        rec = self.sessions.records[session_id]
        rec.state, rec.last_stop_reason = "stopped", stop
        if result is not None:
            rec.output = SessionOutput(valid=True, value=result).model_dump(mode="json")
        elif stop == "end_turn":
            output = SessionOutput(valid=False, error="no `handler-result` block")
            rec.output = output.model_dump(mode="json")

    def run(self, coro: Any) -> Any:
        return self.loop.run_until_complete(coro)

    def approve(
        self, reader: AgentRecord, path: str, digest: str, runner: str | None = None
    ) -> PlanView:
        async def go() -> PlanView:
            return self.store.approve(plans.file_of(reader, path), digest, runner)

        return self.run(go())

    def restart(self) -> None:
        """handlerd started again: a new store, watching the plans running."""
        self.store = PlanStore(
            self.settings, self.registry, self.projects, self.sessions, self.inbox
        )

        async def go() -> None:
            self.store.start_watching()

        self.run(go())

    def until(self, check: Callable[[], bool]) -> None:
        async def go() -> None:
            for _ in range(500):
                if check():
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("never came")

        self.run(go())

    def state(self, plan_id: str) -> tuple[str, list[str]]:
        view = self.store.view(plan_id)
        return view.state, [s.state for s in view.steps]

    def agent(self, name: str = "dev", scope: str | None = None, **fields: Any) -> AgentRecord:
        settings = CheckedSettings(
            scope=str(self.folder) if scope is None else scope,
            model=RunsAs(harness="claude-code", provider="api"),
            **fields,
        )
        return self.registry.add(AgentRecord(**settings.model_dump(), name=name))

    def write(self, text: str = PLAN, name: str = "plans/p.md") -> str:
        (self.folder / name).write_text(text)
        return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def f(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Fixture]:
    fixture = Fixture(tmp_path, monkeypatch)
    yield fixture
    fixture.run(fixture.store.close())
    fixture.loop.close()


def test_a_plan_is_parsed_as_written() -> None:
    parsed = parse(PLAN)
    assert parsed.problems == []
    assert parsed.title == "the map's rules on the sandbox tests"
    assert parsed.agent == "dev"
    assert parsed.context == "read docs/concepts.md;\ncommit after each step."
    assert parsed.step_timeout_sec == plans.DEFAULT_STEP_TIMEOUT_SEC == 3 * 3600
    one, two = parsed.steps
    assert (one.n, one.title) == (1, "Mark the sandbox tests")
    assert one.done_when == "`pytest tests/sandbox` passes;\nno sandbox rule without a test."
    assert two.goal == (
        "Read the README first.\nthe docs say it.\n\n```sh\n## not a heading: in a code block\n```"
    )
    assert two.done_when == "`./scripts/ci.sh` passes."


def test_the_step_time_limit() -> None:
    assert (
        parse(PLAN.replace("Agent: dev", "Agent: dev\nStep time limit: 90m")).step_timeout_sec
        == 5400
    )
    assert (
        parse(PLAN.replace("Agent: dev", "Agent: dev\nStep time limit: 24h")).step_timeout_sec
        == 86400
    )
    for wrong in ("25h", "0m", "3 hours", ""):
        problems = parse(
            PLAN.replace("Agent: dev", f"Agent: dev\nStep time limit: {wrong}")
        ).problems
        assert len(problems) == 1 and "between 1m and 24h" in problems[0], wrong


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("", "no title"),
        ("Hello\n" + PLAN, "starts with `# Plan: <title>`"),
        (PLAN + "# Plan: another\n", "two `# Plan:` titles"),
        (PLAN.replace("# Plan: the map's rules on the sandbox tests", "# Plan:"), "title is empty"),
        (PLAN.replace("Agent: dev\n", "Agent: dev\nAgent: other\n"), "two `Agent:` lines"),
        (PLAN.replace("Agent: dev\n", "Agent: dev\nModel: opus\n"), "not a header line"),
        (PLAN.split("## 1.", maxsplit=1)[0], "no step"),
        (PLAN.replace("## 2. The docs", "## 3. The docs"), "step 2 is numbered 3"),
        (PLAN.replace("## 2. The docs", "## The docs"), "a step's heading is `## <n>. <title>`"),
        (PLAN.replace("Goal: every", "Aim: every"), "step 1 has no `Goal:`"),
        (PLAN.replace("Done when: `./", "Then: `./"), "step 2 has no `Done when:`"),
        (PLAN.replace("Goal: the docs", "Goal: x\nGoal: the docs"), "step 2: two `Goal:` lines"),
        (PLAN.replace("## 1. Mark the sandbox tests", "## 1."), "step 1 has no title"),
    ],
)
def test_each_problem_is_told(text: str, problem: str) -> None:
    problems = parse(text).problems
    assert any(problem in p for p in problems), problems


@pytest.mark.rule("plan.read-without-following-links")
def test_the_file_is_read_in_the_folder_without_following_links(f: Fixture, tmp_path: Path) -> None:
    reader = f.agent()
    secret = tmp_path / "id_ed25519"
    secret.write_text(PLAN)  # a plan's text, so only the link can refuse it
    (f.folder / "plans" / "link.md").symlink_to(secret)
    (f.folder / "out").symlink_to(tmp_path)
    for path, status in (
        ("plans/link.md", 400),
        ("out/id_ed25519", 400),
        ("../id_ed25519", 400),
        ("/etc/passwd", 400),
        ("plans/none.md", 404),
        ("plans", 400),
    ):
        with pytest.raises(PlanError) as e:
            f.store.read(plans.file_of(reader, path))
        assert e.value.status == status, path
    f.write()
    read = f.store.read(plans.file_of(reader, "plans/p.md"))
    assert read.problems == [] and read.agent_id == reader.id
    assert read.digest == hashlib.sha256(PLAN.encode()).hexdigest()
    assert read.text == PLAN


def test_its_agent_is_named_among_those_of_the_folder(f: Fixture) -> None:
    reader = f.agent("reader")
    f.write()
    assert (
        "no agent named dev works in"
        in f.store.read(plans.file_of(reader, "plans/p.md")).problems[0]
    )
    f.agent("dev", scope="/elsewhere")
    assert "no agent named dev" in f.store.read(plans.file_of(reader, "plans/p.md")).problems[0]
    dev = f.agent("Dev")  # names compared without case
    assert f.store.read(plans.file_of(reader, "plans/p.md")).agent_id == dev.id
    f.agent("dev")
    assert "2 agents named dev" in f.store.read(plans.file_of(reader, "plans/p.md")).problems[0]


@pytest.mark.rule("plan.its-agent-its-settings")
def test_a_runner_chosen_on_review_runs_it(f: Fixture) -> None:
    reader = f.agent("reader")
    f.agent("dev")
    other = f.agent("other")
    digest = f.write(PLAN.replace("Agent: dev\n", ""))
    read = f.store.read(plans.file_of(reader, "plans/p.md"))
    assert read.agent_id is None
    assert read.problems == ["no `Agent:` line: choose the agent that runs its steps"]
    chosen = f.store.read(plans.file_of(reader, "plans/p.md"), other.id)
    assert (chosen.problems, chosen.agent, chosen.agent_id) == ([], None, other.id)
    named = f.write()  # names dev: the runner chosen wins
    read = f.store.read(plans.file_of(reader, "plans/p.md"), other.id)
    assert (read.agent, read.agent_id, read.problems) == ("dev", other.id, [])
    elsewhere = f.agent("far", scope="/elsewhere")
    problems = f.store.read(plans.file_of(reader, "plans/p.md"), elsewhere.id).problems
    assert problems == [f"the agent chosen to run it does not work in {f.folder}"]
    with pytest.raises(PlanError) as e:
        f.approve(reader, "plans/p.md", named, elsewhere.id)
    assert e.value.title == "the plan has problems"
    assert digest != named
    plan = f.approve(reader, "plans/p.md", named, other.id)  # bound by id
    assert (plan.agent_id, plan.agent) == (other.id, "other")
    f.until(lambda: len(f.created) == 1)
    assert f.sessions.records["s_0"].agent_id == other.id
    other.name = "renamed"  # bound by id, not by name
    assert f.store.view(plan.id).agent == "renamed"


def test_the_runners_offered_are_the_folders_agents_that_may_run_steps(f: Fixture) -> None:
    project = f.projects.add(ProjectRecord(id="p1", name="x", folder=str(f.folder)))
    reader = f.agent("reader", permissions="ask")
    f.agent("Bee")
    f.agent("job", interface=AgentInterface(result={"type": "object"}))
    f.agent("far", scope="/elsewhere")
    f.agent("chat").chat = True  # Chat's: someone you talk to
    f.write()
    read = f.store.read(plans.file_of(reader, "plans/p.md"))
    assert [(r.name, r.bypass) for r in read.runners] == [("Bee", True), ("reader", False)]
    assert read.project_id == project.id
    f.projects.delete(project)
    assert f.store.read(plans.file_of(reader, "plans/p.md")).project_id is None


@pytest.mark.rule("plan.its-agent-its-settings")
def test_its_agent_runs_steps_nobody_answers(f: Fixture) -> None:
    reader = f.agent("reader")
    f.write()
    asks = f.agent(permissions="ask")
    problems = f.store.read(plans.file_of(reader, "plans/p.md")).problems
    assert problems == ["its agent runs steps nobody answers: set dev's mode to bypass"]
    f.registry.delete(asks.id)
    job = f.agent(interface=AgentInterface(result={"type": "object"}))
    assert "takes a form" in f.store.read(plans.file_of(reader, "plans/p.md")).problems[0]
    f.registry.delete(job.id)
    part = f.agent()
    part.app = "planner"
    assert (
        "one of the app planner's parts"
        in f.store.read(plans.file_of(reader, "plans/p.md")).problems[0]
    )


def test_large_or_binary_files_are_problems(f: Fixture) -> None:
    reader = f.agent()
    f.write(PLAN + "x" * plans.MAX_BYTES)
    assert f.store.read(plans.file_of(reader, "plans/p.md")).problems == ["larger than 256 KiB"]
    (f.folder / "plans" / "p.md").write_bytes(b"# Plan: \xff\n")
    assert f.store.read(plans.file_of(reader, "plans/p.md")).problems == ["not UTF-8 text"]


def test_on_a_subscription_an_api_key_is_recommended(f: Fixture) -> None:
    reader = f.agent()
    f.write()
    assert f.store.read(plans.file_of(reader, "plans/p.md")).recommendation is None  # a provider
    reader.model = RunsAs(harness="claude-code", account="claude-pro")
    read = f.store.read(plans.file_of(reader, "plans/p.md"))
    assert read.problems == []  # recommended, not refused
    assert read.recommendation is not None and "account claude-pro" in read.recommendation
    assert "Claude Pro or Max subscription" in read.recommendation


@pytest.mark.rule("plan.what-runs-is-what-you-approved")
def test_a_file_changed_since_it_was_read_is_refused(f: Fixture) -> None:
    reader = f.agent()
    digest = f.write()
    f.write(PLAN.replace("ci.sh", "ci.sh; curl evil"))
    with pytest.raises(PlanError) as e:
        f.approve(reader, "plans/p.md", digest)
    assert (e.value.status, e.value.title) == (409, "the plan changed since you read it")
    assert f.store.ids() == []
    changed = f.write(PLAN.replace("Agent: dev\n", ""))
    with pytest.raises(PlanError) as e:
        f.approve(reader, "plans/p.md", changed)
    assert e.value.title == "the plan has problems"


@pytest.mark.rule("plan.out-of-every-sandbox", "plan.what-runs-is-what-you-approved")
def test_the_approved_copy_is_handlerds(f: Fixture) -> None:
    reader = f.agent()
    digest = f.write()
    plan = f.approve(reader, "plans/p.md", digest)
    kept = f.settings.state_dir / "plans" / plan.id
    assert (kept / "plan.md").read_text() == PLAN
    for name in ("plan.md", "plan.json", "state.json"):
        assert stat.S_IMODE(os.stat(kept / name).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(kept).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(kept.parent).st_mode) == 0o700
    f.write("# Plan: changed\n")  # the folder's file changes: the copy does not
    view = f.store.view(plan.id)
    assert (view.title, view.digest, view.agent) == (plan.title, digest, "dev")
    assert [s.title for s in view.steps] == ["Mark the sandbox tests", "The docs"]
    assert view.state == "running" and view.source == "plans/p.md"
    assert view.folder == str(f.folder)
    assert sorted(p.name for p in (f.folder / "plans").iterdir()) == [
        "p.md"
    ]  # nothing written there
    with pytest.raises(PlanError) as e:
        f.store.delete(plan.id)
    assert e.value.status == 409


def test_one_plan_running_per_agent(f: Fixture) -> None:
    reader = f.agent()
    digest = f.write()
    f.approve(reader, "plans/p.md", digest)
    with pytest.raises(PlanError) as e:
        f.approve(reader, "plans/p.md", digest)
    assert e.value.title == "its agent already runs a plan"


def test_a_folderless_agent_has_no_plan_file(f: Fixture) -> None:
    folderless = f.agent()
    folderless.scope = None
    with pytest.raises(PlanError) as e:
        f.store.read(plans.file_of(folderless, "plans/p.md"))
    assert e.value.status == 409


def done(summary: str = "did it", notes: str | None = None) -> dict[str, Any]:
    return {"status": "done", "summary": summary} | ({"notes": notes} if notes else {})


@pytest.mark.rule(
    "plan.one-step-after-another", "plan.its-agent-its-settings", "plan.a-step-knows-only-its-notes"
)
def test_steps_run_one_after_another_each_a_fresh_session(f: Fixture) -> None:
    dev = f.agent()
    plan = f.approve(dev, "plans/p.md", f.write())
    f.until(lambda: len(f.created) == 1)
    assert f.state(plan.id) == ("running", ["running", "waiting"])
    first = f.created[0]
    assert first["origin"] == "plan" and first["step"].plan.model_dump() == {
        "id": plan.id,
        "step": 1,
    }
    assert (
        first["step"].title
        == "the map's rules on the sandbox tests · step 1: Mark the sandbox tests"
    )
    assert first["step"].interface.result == plans.STEP_RESULT
    assert first["step"].interface.timeout_sec == 3 * 3600
    assert "step 1 of 2: Mark the sandbox tests" in first["prompt"]
    assert "the docs say it" not in first["prompt"]  # the next step is not its own
    assert "commit after each step." in first["prompt"]  # the plan's context
    f.end("s_0", done(notes="the markers are in tests/sandbox/conftest.py"))
    f.until(lambda: len(f.created) == 2)
    second = f.created[1]["prompt"]
    assert "step 2 of 2: The docs" in second
    assert (
        "### Step 1: Mark the sandbox tests\n\nthe markers are in tests/sandbox/conftest.py"
        in second
    )
    assert f.state(plan.id) == ("running", ["done", "running"])
    f.end("s_1", done("the docs say it"))
    f.until(lambda: f.state(plan.id)[0] == "done")
    view = f.store.view(plan.id)
    assert [s.summary for s in view.steps] == ["did it", "the docs say it"]
    assert [s.session_id for s in view.steps] == ["s_0", "s_1"]
    assert view.steps[0].notes == "the markers are in tests/sandbox/conftest.py"


@pytest.mark.rule("plan.stops-at-the-first-failure")
@pytest.mark.parametrize(
    ("result", "stop", "why"),
    [
        ({"status": "failed", "summary": "the tests fail"}, "end_turn", "the tests fail"),
        (None, "end_turn", "no `handler-result` block"),
        (None, "timed_out", "timed out after 3 h"),
    ],
)
def test_a_step_not_done_stops_the_plan(
    f: Fixture, result: dict[str, Any] | None, stop: str, why: str
) -> None:
    plan = f.approve(f.agent(), "plans/p.md", f.write())
    f.until(lambda: len(f.created) == 1)
    f.end("s_0", result, stop)
    f.until(lambda: f.state(plan.id)[0] == "stopped")
    assert f.state(plan.id) == ("stopped", ["failed", "waiting"])
    assert f.store.view(plan.id).stopped_because == f"step 1 failed: {why}"
    f.run(asyncio.sleep(0.05))
    assert len(f.created) == 1  # no later step started


@pytest.mark.rule("plan.stops-at-the-first-failure", "plan.started-by-you-only")
def test_cancel_stops_its_step_and_run_again_from_a_step(f: Fixture) -> None:
    dev = f.agent()
    plan = f.approve(dev, "plans/p.md", f.write())
    f.until(lambda: len(f.created) == 1)
    f.end("s_0", done())
    f.until(lambda: len(f.created) == 2)
    view = f.run(f.store.cancel(plan.id))
    assert (view.state, view.stopped_because) == ("stopped", "cancelled by you")
    assert [s.state for s in view.steps] == ["done", "cancelled"]
    assert f.stopped == ["s_1"]
    with pytest.raises(PlanError) as e:
        f.run(f.store.cancel(plan.id))
    assert e.value.status == 409
    with pytest.raises(PlanError) as e:
        f.store.run(plan.id, 3)  # past its first step not done
    assert e.value.title == "step 2 is not done"

    async def again(start: int) -> PlanView:
        return f.store.run(plan.id, start)

    view = f.run(again(2))
    assert [s.state for s in view.steps] == ["done", "waiting"]
    with pytest.raises(PlanError) as e:
        f.run(again(1))
    assert e.value.title == "the plan is running"
    f.until(lambda: len(f.created) == 3)
    assert f.created[2]["step"].plan.step == 2
    f.end("s_2", done())
    f.until(lambda: f.state(plan.id) == ("done", ["done", "done"]))
    view = f.run(again(1))  # a plan done runs again from any step
    f.until(lambda: len(f.created) == 4)
    assert f.created[3]["step"].plan.step == 1
    assert f.state(plan.id) == ("running", ["running", "waiting"])


def test_handlerd_restarting_during_a_step_stops_the_plan(f: Fixture) -> None:
    plan = f.approve(f.agent(), "plans/p.md", f.write())
    f.until(lambda: len(f.created) == 1)
    f.run(f.store.close())  # handlerd stops, its sessions with it
    f.sessions.records["s_0"].state = "stopped"
    f.restart()
    f.until(lambda: f.state(plan.id)[0] == "stopped")
    assert (
        f.store.view(plan.id).stopped_because == "step 1 failed: handlerd restarted during the step"
    )


def test_a_step_that_ended_while_handlerd_was_down_is_read(f: Fixture) -> None:
    plan = f.approve(f.agent(), "plans/p.md", f.write())
    f.until(lambda: len(f.created) == 1)
    f.run(f.store.close())  # handlerd stops
    f.end("s_0", done())  # its step had ended, the plan not told
    f.restart()
    f.until(lambda: len(f.created) == 2)
    assert f.state(plan.id) == ("running", ["done", "running"])


@pytest.mark.rule("plan.its-agent-its-settings")
def test_a_step_runs_with_its_agents_settings_as_they_are(f: Fixture) -> None:
    dev = f.agent()
    plan = f.approve(dev, "plans/p.md", f.write())
    f.until(lambda: len(f.created) == 1)
    dev.permissions = "ask"
    f.end("s_0", done())
    f.until(lambda: f.state(plan.id)[0] == "stopped")
    assert "set dev's mode to bypass" in (f.store.view(plan.id).stopped_because or "")
    assert len(f.created) == 1
    f.registry.delete(dev.id)
    with pytest.raises(PlanError) as e:
        f.store.run(plan.id, 2)
    assert e.value.title == "its agent was deleted"
    assert f.store.view(plan.id).agent is None  # kept for reading


@pytest.mark.rule("plan.a-step-knows-only-its-notes")
def test_the_notes_before_a_step_are_trimmed_oldest_first() -> None:
    steps = [PlanStep(n=n, title=f"step {n}", goal="g", done_when="d") for n in range(1, 5)]
    big = "x" * 7000
    text = plans.notes_part([(s, f"{s.n}: {big}") for s in steps[:3]])
    assert "### Step 1:" not in text and "### Step 2:" in text and "### Step 3:" in text
    assert "The notes of steps 1 to 1 are left out" in text
    assert len(text.encode()) <= plans.MAX_NOTES + 200
    huge = plans.notes_part([(steps[0], "y" * 40_000 + "the end")])
    assert huge.endswith("the end") and len(huge.encode()) < plans.MAX_NOTES
    assert "(no notes)" in plans.notes_part([(steps[0], None)])


def test_a_steps_session_is_unattended_with_its_own_interface(
    f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SessionStore.create for a step: its interface and first turn, the agent's instructions
    first; the agent unchanged."""
    monkeypatch.undo()  # the real create
    started: list[tuple[str, list[Any], float | None]] = []

    async def start(session_id: str, blocks: Sequence[Any], timeout: float | None = None) -> None:
        started.append((session_id, list(blocks), timeout))

    sessions = SessionStore(f.settings, f.registry)
    monkeypatch.setattr(sessions, "_start_quietly", start)
    dev = f.agent()
    dev.instructions = "You work on Handler."
    interface = AgentInterface(result=plans.STEP_RESULT, timeout_sec=600)
    turn = plans.PlanTurn(
        plan=plans.SessionPlan(id="p_1", step=2), title="P · step 2: x", interface=interface
    )

    async def go() -> SessionRecord:
        rec = sessions.create(dev, dev.model, prompt="the step", origin="plan", step=turn)
        await asyncio.sleep(0)
        return rec

    rec = f.run(go())
    view = sessions.to_contract(rec)
    assert view.origin == "plan" and view.plan is not None and view.plan.step == 2
    assert view.unattended and view.title == "P · step 2: x"
    assert rec.instructions is None  # sent with the first turn
    assert started == [
        (
            rec.id,
            [{"type": "text", "text": f"You work on Handler.\n\n{FILTERED_NETWORK}\n\nthe step"}],
            600,
        )
    ]
    assert dev.interface is None


def test_the_skill_is_installed_once_and_its_format_is_the_parsers(f: Fixture) -> None:
    plans.install_skill(f.settings)
    skill = skills.get(f.settings.skills_dir, "handler-plan")
    assert skill.error is None and skill.description
    text = (skill.path / "SKILL.md").read_text()
    example = text.split("```markdown\n", 1)[1].split("```\n", 1)[0]
    assert parse(example).problems == []  # what it tells the agent to write is a valid plan
    shutil.rmtree(skill.path)  # deleted by you: it stays deleted
    plans.install_skill(f.settings)
    assert not skill.path.exists()


# ── drafts and the plan builder ─────────────────────────────────────────


def drafts_of(f: Fixture) -> tuple[PlanDrafts, ProjectRecord]:
    project = f.projects.add(ProjectRecord(id="p1", name="x", folder=str(f.folder)))
    return PlanDrafts(f.settings, f.projects), project


def test_a_draft_is_kept_by_handler_for_a_project(f: Fixture) -> None:
    drafts, project = drafts_of(f)
    draft = drafts.create(project.id)
    root = f.settings.state_dir / "plan-drafts" / draft.id
    assert (draft.project_id, draft.folder, draft.title) == (project.id, str(f.folder), None)
    assert draft.digest == hashlib.sha256(b"").hexdigest() and draft.session_id is None
    assert drafts.folder(draft.id) == root / "draft"
    assert (root / "draft" / "plan.md").read_text() == ""
    assert sorted(p.name for p in root.iterdir()) == ["draft", "draft.json"]  # its meta apart
    for kept in (root.parent, root, root / "draft"):
        assert stat.S_IMODE(os.stat(kept).st_mode) == 0o700
    (root / "draft" / "plan.md").write_text(PLAN)  # its builder writes
    f.agent()  # dev, of the project's folder, runs it
    assert drafts.get(draft.id).title == "the map's rules on the sandbox tests"
    read = f.store.read(drafts.source(draft.id))
    assert read.problems == [] and read.path == "plan.md" and read.project_id == project.id
    assert [d.id for d in drafts.list(project.id)] == [draft.id] and drafts.list("other") == []
    with pytest.raises(DraftError) as e:
        drafts.create("nope")
    assert e.value.status == 404
    drafts.delete(draft.id)
    assert not root.exists() and drafts.list() == []


@pytest.mark.rule("plan.a-draft-is-not-a-plan")
def test_a_draft_changed_never_changes_its_plan(f: Fixture) -> None:
    drafts, project = drafts_of(f)
    f.agent()
    draft = drafts.create(project.id, PLAN)
    with pytest.raises(DraftError) as e:  # its builder wrote since you read it
        drafts.save(draft.id, "# Plan: mine\n", hashlib.sha256(b"older").hexdigest())
    assert (e.value.status, e.value.title) == (409, "the draft changed since you read it")
    plan = f.run(_approve_draft(f, drafts, draft.id, draft.digest))
    assert (plan.draft_id, plan.source, plan.folder) == (draft.id, None, str(f.folder))
    edited = drafts.save(draft.id, PLAN.replace("The docs", "The guide"), draft.digest)
    assert edited.digest != draft.digest
    assert [s.title for s in f.store.view(plan.id).steps] == ["Mark the sandbox tests", "The docs"]
    f.run(f.store.cancel(plan.id))
    again = f.run(_approve_draft(f, drafts, draft.id, edited.digest))
    assert again.id != plan.id and again.steps[1].title == "The guide"  # a new plan
    copy = drafts.create(project.id, f.store.text(plan.id), from_plan=plan.id)  # Edit as a new…
    assert copy.from_plan == plan.id and copy.digest == draft.digest


async def _approve_draft(f: Fixture, drafts: PlanDrafts, draft_id: str, digest: str) -> PlanView:
    return f.store.approve(drafts.source(draft_id), digest)


@pytest.mark.rule("plan.builder-reads-the-project-only", "plan.read-without-following-links")
def test_a_draft_is_saved_and_read_through_no_link_its_builder_left(
    f: Fixture, tmp_path: Path
) -> None:
    drafts, project = drafts_of(f)
    draft = drafts.create(project.id)
    yours = tmp_path / "authorized_keys"
    yours.write_text("yours\n")
    text = drafts.folder(draft.id) / "plan.md"
    text.unlink()
    text.symlink_to(yours)  # left by its builder
    (drafts.folder(draft.id) / "plan.md.tmp").symlink_to(yours)  # a name a writer might use
    with pytest.raises(plans.PlanError) as e:
        f.store.read(drafts.source(draft.id))
    assert e.value.status == 400
    empty = hashlib.sha256(b"").hexdigest()
    assert drafts.get(draft.id).digest == empty  # unreadable: as empty
    drafts.save(draft.id, PLAN, empty)
    assert yours.read_text() == "yours\n"  # never written through the link
    assert not text.is_symlink() and text.read_text() == PLAN


@pytest.mark.rule("plan.builder-has-no-secret")
def test_a_plan_builder_has_no_more_rights_than_writing_its_draft(f: Fixture) -> None:
    builder = f.agent("Plan builder")
    builder.scope = None  # folderless: each session works on a draft
    assert plan_drafts.builder_problems(builder) == []
    builder.addons = [AddonUse(addon="shopify", binding="shop")]
    assert "has tools" in plan_drafts.builder_problems(builder)[0]
    builder.addons = []
    for network, egress, allow in (("open", "enforce", []), ("filtered", "log-only", []),
                                   ("filtered", "enforce", ["evil.example:443"])):  # fmt: skip
        builder.network, builder.egress, builder.allow = network, egress, allow
        assert "reaches more than its model's sites" in plan_drafts.builder_problems(builder)[0], (
            network
        )
    builder.network, builder.egress, builder.allow = "none", "enforce", []
    assert plan_drafts.builder_problems(builder) == []
    builder.scope = str(f.folder)
    assert "has a folder" in plan_drafts.builder_problems(builder)[0]


@pytest.mark.rule("plan.builder-reads-the-project-only")
def test_a_builders_session_works_in_its_draft_told_its_brief(
    f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.undo()  # the real create
    started: list[list[Any]] = []

    async def start(session_id: str, blocks: Sequence[Any], timeout: float | None = None) -> None:
        started.append(list(blocks))

    sessions = SessionStore(f.settings, f.registry)
    monkeypatch.setattr(sessions, "_start_quietly", start)
    drafts, project = drafts_of(f)
    draft = drafts.create(project.id)
    builder = f.agent("Plan builder")
    builder.scope, builder.instructions = None, "You write plans."
    folder = drafts.folder(draft.id)
    told = plan_drafts.brief(project.folder, folder, ["dev"])
    assert f"The project is {f.folder}: you see it read-only" in told
    assert f"write the plan in {folder / 'plan.md'}" in told and "may run its steps: dev" in told
    assert "leave `Agent:` out" in plan_drafts.brief(project.folder, folder, [])
    work = DraftWork(SessionPlanDraft(id=draft.id, project_id=project.id, folder=str(f.folder)),
                     folder, told)  # fmt: skip

    async def go() -> SessionRecord:
        rec = sessions.create(builder, builder.model, prompt="a plan", plan_draft=work)
        await asyncio.sleep(0)
        return rec

    rec = f.run(go())
    assert rec.scope == str(folder)  # its draft, not a folder of its own
    assert not sessions.work_folder(rec.id).exists()
    view = sessions.to_contract(rec)
    assert view.plan_draft is not None and view.plan_draft.folder == str(f.folder)
    told = f"You write plans.\n\n{told}\n\n{FILTERED_NETWORK}"  # its network is filtered
    # the request kept with them, both sent once it runs (F.1)
    assert started == [[]] and (rec.instructions, rec.request) == (told, "a plan")
