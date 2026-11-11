"""Unit tests: the automations' runner (I.2, I.3, I.6, I.7): which stop fires past a cursor, which
slot a schedule runs, what a run's output may append, what the inbox is told, what an automation
says it does."""

import asyncio
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import AgentInterface, Automation, AutomationRun
from handler_control import automation_config as config
from handler_control import automations, save_rules
from handler_control.agents import AgentRecord, AgentRegistry, CheckedSettings, RunsAs
from handler_control.app_runs import AppRuns
from handler_control.apps import AppStore
from handler_control.automations import (
    AutomationCappedError,
    AutomationConflictError,
    AutomationError,
    Automations,
    pending_stop,
)
from handler_control.inbox import Inbox
from handler_control.interfaces import result_problems
from handler_control.projects import ProjectRegistry
from handler_control.sessions import SessionStore
from handler_control.settings import Settings

T0, T1, T2 = "2026-10-06T10:00:00+00:00", "2026-10-06T11:00:00+00:00", "2026-10-06T12:00:00+00:00"


def turn(seq: int) -> dict[str, Any]:
    return {"seq": seq, "t": T0, "kind": "turn", "phase": "end", "stopReason": "end_turn"}


def stop(seq: int, how: str, t: str = T1) -> dict[str, Any]:
    return {"seq": seq, "t": t, "kind": "lifecycle", "event": "stopped", "how": how}


@pytest.mark.rule("stop.each-part-read-once")
def test_a_stop_after_a_turn_fires() -> None:
    events = [turn(1), stop(2, "explicit")]
    assert pending_stop(events, 0, None) == events[1]
    assert pending_stop(events, 2, None) is None  # read already
    assert pending_stop([stop(1, "idle")], 0, None) is None  # no turn: nothing to read


@pytest.mark.rule("stop.each-part-read-once")
@pytest.mark.parametrize("how", ["deleted", "daemon_restarted"])
def test_some_stops_never_fire(how: str) -> None:
    assert pending_stop([turn(1), stop(2, how)], 0, None) is None


@pytest.mark.rule("stop.each-part-read-once")
def test_the_part_before_a_restart_is_read_with_the_next_stop() -> None:
    """`_load` writes a `daemon_restarted` stop: it does not fire, the next stop reads both."""
    events = [turn(1), stop(2, "daemon_restarted"), turn(3), stop(4, "idle")]
    assert pending_stop(events[:2], 0, None) is None
    assert pending_stop(events, 0, None) == events[3]


@pytest.mark.rule("stop.each-part-read-once")
def test_stops_before_since_are_not_read() -> None:
    since = datetime.fromisoformat(T1)
    assert pending_stop([turn(1), stop(2, "explicit", T0)], 0, since) is None
    assert pending_stop([turn(1), stop(2, "explicit", T2)], 0, since) is not None


# ── appends (I.6) ───────────────────────────────────────────────────────

TOML = """
apiVersion = "handler.automation/v1"
when = "session.stopped"
run = "true"
[[append]]
from = "note.md"
to = "handler/a.md"
[[append]]
from = "other.md"
to = "handler/b.md"
"""


@pytest.fixture
def runner(tmp_path: Path) -> Automations:
    (tmp_path / "knowledge" / "handler").mkdir(parents=True)
    settings = Settings(
        port=0,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path,
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
        knowledge_dir=tmp_path / "knowledge",
        automations_dir=tmp_path / "automations",
    )
    registry = AgentRegistry(settings.state_dir)
    inbox = Inbox(settings)
    sessions, projects = SessionStore(settings, registry), ProjectRegistry(tmp_path, registry)
    return Automations(
        settings,
        sessions,
        registry,
        projects,
        apps=AppStore(settings, "t0ken", inbox, AppRuns(settings, sessions, projects, inbox)),
        inbox=inbox,
    )


def setup(runner: Automations, trial: bool = False) -> tuple[config.Loaded, AutomationRun, Path]:
    folder = runner.settings.automations_dir / "notes"
    folder.mkdir(parents=True)
    (folder / "automation.toml").write_text(TOML)
    record = AutomationRun(
        id="a_0123456789abcdef",
        automation="notes",
        trial=trial,
        session_id="s_1",
        seq_from=1,
        seq_to=9,
        state="running",
        created_at=datetime.now(UTC),
    )
    output = runner.settings.state_dir / "out"
    output.mkdir(parents=True)
    return config.load(folder), record, output


@pytest.mark.rule("append.only-what-it-declares-once-it-succeeded")
def test_appends_in_order_with_their_provenance(runner: Automations) -> None:
    loaded, record, output = setup(runner)
    (output / "note.md").write_text("- a finding")
    appended = runner.append(loaded, record, output)  # other.md is missing: skipped
    note = (runner.settings.knowledge_dir or Path()) / "handler" / "a.md"
    text = note.read_text()
    assert text.startswith(
        "\n<!-- handler automation notes · run a_0123456789abcdef · session s_1 · "
    )
    assert text.endswith(" -->\n- a finding\n")
    assert [a.to for a in appended] == ["handler/a.md"] and appended[0].bytes == len(text.encode())
    runner.append(loaded, record, output)
    assert note.read_text().count("- a finding") == 2  # duplicates are kept


@pytest.mark.rule("append.only-what-it-declares-once-it-succeeded", "try.now-on-or-off")
def test_a_try_appends_nothing(runner: Automations) -> None:
    loaded, record, output = setup(runner, trial=True)
    (output / "note.md").write_text("x" * 5000)
    [would] = runner.append(loaded, record, output)
    assert would.bytes == 5000 and would.text == "x" * 4096
    assert not ((runner.settings.knowledge_dir or Path()) / "handler" / "a.md").exists()


@pytest.mark.rule("append.only-what-it-declares-once-it-succeeded")
def test_what_cannot_be_appended_fails_the_run(runner: Automations, tmp_path: Path) -> None:
    loaded, record, output = setup(runner)
    secret = tmp_path / "secret"
    secret.write_text("host file")
    os.symlink(secret, output / "note.md")  # a script reaching out of its output
    with pytest.raises(AutomationError, match="outside the run's output"):
        runner.append(loaded, record, output)
    (output / "note.md").unlink()
    (output / "note.md").write_text("x" * (256 * 1024 + 1))
    with pytest.raises(AutomationError, match="larger than 256 KiB"):
        runner.append(loaded, record, output)
    (output / "note.md").write_text("fine")
    (output / "other.md").write_text("too")
    (runner.settings.knowledge_dir or Path()).joinpath("handler").rename(tmp_path / "moved")
    with pytest.raises(AutomationError, match="folder does not exist"):
        runner.append(loaded, record, output)  # checked before anything is written


# ── an agent's result, the inbox (I.3) ──────────────────────────────────

RESULT = {
    "type": "object",
    "required": ["status", "summary"],
    "properties": {"status": {"enum": ["ok", "attention"]}, "summary": {"type": "string"}},
}


@pytest.mark.rule("automation.with-problems-never-runs")
def test_an_agent_run_s_result_makes_a_message() -> None:
    assert result_problems(RESULT) == []
    assert result_problems({"properties": {}}) == [
        "its result has no required 'status' enum (ok, attention, failed)",
        "its result has no required 'summary' string",
    ]
    bad = RESULT | {"properties": {"status": {"enum": ["good"]}, "summary": {"type": "string"}}}
    assert result_problems(bad) == ["its result's status has ['good']: only ok, attention, failed"]


@pytest.mark.rule("inbox.what-it-is-told")
def test_the_inbox_is_told_results_and_failures(runner: Automations) -> None:
    loaded, record, _ = setup(runner)

    async def ends() -> None:
        runner.end(record, "failed", error="the script exited with 1")
        runner.end(record.model_copy(update={"trial": True}), "failed", error="a try")
        runner.end(record, "succeeded")

    asyncio.run(ends())
    [failed] = runner.inbox.list()  # a script's try and success tell nothing
    assert (failed.source, failed.name, failed.status) == ("automation", "notes", "failed")
    assert failed.summary == "the script exited with 1" and failed.run_id == record.id
    review = runner.settings.automations_dir / "review"
    review.mkdir()
    (review / "automation.toml").write_text(
        'apiVersion = "handler.automation/v1"\nwhen = { every = "1h" }\napp = "planner"\n'
        'run = { agent = "reviewer" }\n'
    )
    result = {"status": "attention", "summary": "2 issues", "issues": ["a", "b"]}
    ran = record.model_copy(update={"automation": "review", "agent_session_id": "s_2"})

    async def told() -> None:
        runner.end(ran, "succeeded", result=result)

    asyncio.run(told())
    message = runner.inbox.list()[0]
    assert (message.name, message.agent, message.status) == ("review", "reviewer", "attention")
    assert message.summary == "2 issues" and message.data == result
    assert message.session_id == "s_2" and loaded.definition is not None
    assert message.app == "planner" and failed.app is None  # the app its automation names


@pytest.mark.rule(
    "automation.off-until-you-turn-it-on",
    "automation.says-what-it-does",
    "schedule.the-latest-slot-once",
)
def test_a_schedule_queues_the_latest_slot_once(runner: Automations) -> None:
    folder = runner.settings.automations_dir / "hourly"
    folder.mkdir(parents=True)
    (folder / "automation.toml").write_text(
        'apiVersion = "handler.automation/v1"\nwhen = { every = "1h" }\nrun = "true"\n'
    )
    assert runner.due() == []  # off
    since = datetime.now(UTC) - timedelta(hours=4, minutes=10)
    config.write_state(runner.settings.state_dir, "hourly", config.State(enabled=True, since=since))
    [item] = runner.due()
    assert item.slot is not None and item.slot == since + timedelta(hours=4) and item.missed == 3
    record = runner.new_record(config.load(folder), item, [])
    assert record is not None and record.slot == item.slot and record.missed == 3
    assert config.read_state(runner.settings.state_dir, "hourly").last_slot == item.slot
    assert runner.due() == []  # its slot is taken
    view = runner.view("hourly")
    assert view.next_at == item.slot + timedelta(hours=1)
    assert view.permissions[0].startswith("Starts every 1h")
    assert "reading nothing but the time it runs" in view.permissions[1]


@pytest.mark.rule("automation.with-problems-never-runs", "automation.says-what-it-does")
def test_what_an_agent_run_says_it_does(runner: Automations) -> None:
    folder = runner.settings.automations_dir / "review"
    folder.mkdir(parents=True)
    (folder / "automation.toml").write_text(
        'apiVersion = "handler.automation/v1"\nwhen = { at = "08:30", days = ["mon"] }\n'
        'run = { agent = "reviewer", project = "handler" }\n'
    )
    view = runner.view("review")
    assert view.problems == ["run.project: no project named handler"]
    assert view.permissions == [
        "Starts at 08:30 (local time) on mon; after the computer was off, only the latest missed"
        " slot runs.",
        "Runs the agent reviewer of project handler unattended, without asking you.",
        "Sends its result to your inbox.",
    ]


@pytest.mark.rule("automation.with-problems-never-runs", "automation.says-what-it-does")
def test_an_agent_run_s_messages_may_open_an_app(runner: Automations) -> None:
    folder = runner.settings.automations_dir / "plan"
    folder.mkdir(parents=True)
    (folder / "automation.toml").write_text(
        'apiVersion = "handler.automation/v1"\nwhen = { every = "5h" }\napp = "planner"\n'
        'run = { agent = "Planner" }\n'
    )
    view = runner.view("plan")
    assert "app: no app named planner" in view.problems
    assert view.permissions[-1] == "Sends its result to your inbox, which opens the app planner."
    with pytest.raises(ValueError, match="'app' goes with an agent run"):
        Automation.model_validate(
            {"apiVersion": "handler.automation/v1", "when": {"every": "1h"}, "run": "true"}
            | {"app": "planner"}
        )


# ── what its names are bound to (I.1) ───────────────────────────────────

JOB = {
    "result": {
        "type": "object",
        "required": ["status", "summary"],
        "properties": {
            "status": {"enum": ["ok", "attention", "failed"]},
            "summary": {"type": "string"},
        },
    }
}


def job(runner: Automations, name: str, folder: str = "/code/x") -> Any:
    settings = CheckedSettings(
        scope=folder,
        model=RunsAs(harness="fake", account="fake"),
        interface=AgentInterface.model_validate(JOB),
    )
    return runner.registry.add(AgentRecord(**settings.model_dump(), name=name))


@pytest.fixture(autouse=True)
def any_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Its agents run on a provider (no account terms to read): their model is not the test's."""
    runs = RunsAs(harness="fake", provider="local")
    monkeypatch.setattr(save_rules, "session_model", lambda *_: runs)


def write(runner: Automations, name: str, text: str) -> None:
    folder = runner.settings.automations_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "automation.toml").write_text('apiVersion = "handler.automation/v1"\n' + text)


@pytest.mark.rule("automation.names-bound-by-id")
def test_its_agent_is_kept_by_id_when_renamed(runner: Automations) -> None:
    planner = job(runner, "Planner")
    write(runner, "plan", 'when = { every = "5h" }\nrun = { agent = "Planner" }\n')
    assert runner.view("plan").agent_id == planner.id  # bound when first read
    planner.name = "Daily planner"
    view = runner.view("plan")
    assert view.agent_id == planner.id and not any("run." in p for p in view.problems)
    assert "Runs the agent Daily planner of no project" in view.permissions[1]
    runner.registry.delete(planner.id)
    assert "run.agent: the agent it ran (Planner) was deleted: choose another" in (
        runner.view("plan").problems
    )


@pytest.mark.rule("automation.names-bound-by-id")
def test_a_file_edited_by_hand_is_read_again(runner: Automations) -> None:
    job(runner, "Planner")
    other = job(runner, "Other", "/code/y")
    write(runner, "plan", 'when = { every = "5h" }\nrun = { agent = "Planner" }\n')
    runner.view("plan")
    write(runner, "plan", 'when = { every = "5h" }\nrun = { agent = "Other" }\n')
    assert runner.view("plan").agent_id == other.id


@pytest.mark.rule("automation.names-bound-by-id")
def test_the_form_s_agent_is_written_and_bound(runner: Automations) -> None:
    twin_a = job(runner, "Twin", "/code/a")
    job(runner, "Twin", "/code/b")  # two agents of no project named so: by name, ambiguous
    definition = Automation.model_validate(
        {"apiVersion": "handler.automation/v1", "when": {"every": "1h"}, "run": {"agent": "x"}}
    )
    check = runner.preview(definition)
    assert any("2 agents named x" in p or "no agent named x" in p for p in check.problems)
    view = runner.create("twin", definition=definition, agent_id=twin_a.id)
    assert view.agent_id == twin_a.id
    assert view.definition is not None and view.definition.agent_run is not None
    assert view.definition.agent_run.agent == "Twin"  # its name written in the file
    with pytest.raises(AutomationError, match="no such agent"):
        runner.update("twin", definition, "nope")


@pytest.mark.rule("automation.names-bound-by-id")
def test_only_is_bound_by_id(runner: Automations) -> None:
    dev = job(runner, "dev")
    write(runner, "watch", 'when = "session.stopped"\nonly = { agent = ["dev"] }\nrun = "true"\n')
    view = runner.view("watch")
    assert (view.only_agents, view.problems) == ([dev.id], [])
    dev.name = "developer"
    assert runner.view("watch").only_agents == [dev.id]
    runner.registry.delete(dev.id)
    assert runner.view("watch").problems == ["only.agent: the agent dev was deleted"]
    write(
        runner, "watch", 'when = "session.stopped"\nonly = { agent = ["nobody"] }\nrun = "true"\n'
    )
    assert runner.view("watch").problems == ["only.agent: no agent named nobody"]


HOURLY = 'when = { every = "1h" }\nrun = "true"\n'


def hourly_and_on(runner: Automations, *names: str) -> None:
    """Each an automation every hour, on since 70 minutes: its slot has come."""
    since = datetime.now(UTC) - timedelta(minutes=70)
    for name in names:
        write(runner, name, HOURLY)
        config.write_state(runner.settings.state_dir, name, config.State(enabled=True, since=since))


@pytest.mark.rule("runner.one-at-a-time")
def test_runs_go_one_at_a_time_a_waiting_one_saying_what_it_is_behind(
    runner: Automations, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two automations due at once: the first runs (held here until let go); the second waits,
    its view saying it is behind the first, and runs only once the first has ended.

    If this fails: runs pile up on the computer at once, or a waiting one says nothing of why."""
    hourly_and_on(runner, "first", "second")
    started: list[str] = []
    let_go = {name: asyncio.Event() for name in ("first", "second")}

    async def execute(loaded: config.Loaded, *args: Any) -> None:  # the run itself, held
        started.append(loaded.name)
        await let_go[loaded.name].wait()

    monkeypatch.setattr(runner, "execute", execute)

    async def scenario() -> None:
        work = asyncio.create_task(runner.work())
        try:
            await until(lambda: started == ["first"])
            for _ in range(20):
                await asyncio.sleep(0)
            assert started == ["first"]
            view = runner.view("second")
            assert (view.pending, view.behind) == (1, "first")
            let_go["first"].set()
            await until(lambda: started == ["first", "second"])
            assert runner.view("second").behind is None
            let_go["second"].set()
        finally:
            work.cancel()

    asyncio.run(scenario())


async def until(condition: Any, timeout: float = 5) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.01)


@pytest.mark.rule("runner.one-at-a-time")
def test_past_100_runs_a_day_its_runs_wait_for_the_next_day_and_a_try_is_refused(
    runner: Automations, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If this fails: a runaway automation runs all day, or a capped one never runs again."""
    hourly_and_on(runner, "busy", "other")
    today = datetime.now(UTC)
    runner.started_today[("busy", today.date().isoformat())] = 100
    runner.queue = {i.key: i for i in runner.due()}  # both due
    assert runner.view("busy").capped and not runner.view("other").capped
    with pytest.raises(AutomationCappedError, match="ran 100 times today"):
        runner.try_run("busy", None)
    first = runner.next_item()
    assert first is not None and first.automation == "other"  # busy's waits
    assert runner.next_item() is None
    monkeypatch.setattr(automations, "now", lambda: today + timedelta(days=1))
    second = runner.next_item()
    assert second is not None and second.automation == "busy"


@pytest.mark.rule("automation.with-problems-never-runs")
def test_a_file_that_does_not_parse_is_neither_turned_on_nor_tried(runner: Automations) -> None:
    """Its error said, as a problem, when it is turned on or tried (a conflict, not a crash).

    If this fails: turning on or trying an automation edited by hand answers an internal
    error, saying nothing of what is wrong in its file."""
    write(runner, "broken", 'when = { every = "1h" }\nrun = \n')
    for act in (lambda: runner.enable("broken"), lambda: runner.try_run("broken", None)):
        with pytest.raises(AutomationConflictError, match="broken has problems: "):
            act()
    assert not config.read_state(runner.settings.state_dir, "broken").enabled


@pytest.mark.rule("automation.off-until-you-turn-it-on")
def test_turning_it_off_drops_its_waiting_runs_but_a_try(runner: Automations) -> None:
    """Its slot's run waits when it is turned off: that run is dropped, a try asked of it stays,
    another automation's waiting run stays.

    If this fails: an automation you turned off still runs once more, unattended."""
    hourly_and_on(runner, "stopped", "other")
    runner.queue = {i.key: i for i in runner.due()}
    tried = runner.try_run("stopped", None)
    runner.disable("stopped")
    left = [(i.automation, i.trial is not None) for i in runner.queue.values()]
    assert sorted(left) == [("other", False), ("stopped", True)]
    assert tried.trial


def a_record(n: int, days_ago: float = 0) -> AutomationRun:
    at = datetime.now(UTC) - timedelta(days=days_ago, seconds=1000 - n)
    return AutomationRun(
        id=f"a_{n:016x}", automation="kept", state="succeeded", created_at=at, ended_at=at
    )


@pytest.mark.rule("runner.keeps-its-runs")
def test_the_last_50_runs_are_kept_none_older_than_30_days(runner: Automations) -> None:
    """A run ending with 50 before it: the oldest goes. A run older than 30 days goes at the
    next end, however few there are.

    If this fails: runs fill the disk, or one you are reading disappears early."""
    write(runner, "kept", HOURLY)
    for n in range(50):
        runner.write_record(a_record(n))
    runner.end(a_record(50).model_copy(update={"state": "running"}), "succeeded")
    assert [r.id for r in runner.runs("kept")] == [a_record(n).id for n in range(50, 0, -1)]
    for record in runner.runs("kept")[2:]:
        shutil.rmtree(runner.runs_dir("kept") / record.id)
    runner.write_record(a_record(0, days_ago=31))
    runner.end(a_record(51).model_copy(update={"state": "running"}), "succeeded")
    assert [r.id for r in runner.runs("kept")] == [a_record(n).id for n in (51, 50, 49)]


@pytest.mark.rule("inbox.keeps-the-last-200")
def test_the_inbox_keeps_its_last_200_and_shows_the_last_50(runner: Automations) -> None:
    """If this fails: the inbox file grows for ever, or the newest message is not shown first."""
    inbox = runner.inbox
    for n in range(201):
        inbox.add(source="automation", name="kept", person="alice", title=f"m{n}")
    kept = Inbox(runner.settings).messages  # as read back
    assert len(kept) == 200 and kept[0].title == "m1" and kept[-1].title == "m200"
    shown = inbox.list()
    assert len(shown) == 50 and shown[0].title == "m200" and shown[-1].title == "m151"
