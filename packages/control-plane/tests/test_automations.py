"""Unit tests: the automations' runner (I.2, I.3, I.6, I.7): which stop fires past a cursor, which
slot a schedule runs, what a run's output may append, what the inbox is told, what an automation
says it does."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import AutomationRun
from handler_control import automation_config as config
from handler_control.agents import AgentRegistry
from handler_control.apps import AppStore
from handler_control.automations import AutomationError, Automations, pending_stop, result_problems
from handler_control.inbox import Inbox
from handler_control.projects import ProjectRegistry
from handler_control.sessions import SessionStore
from handler_control.settings import Settings

T0, T1, T2 = "2026-10-06T10:00:00+00:00", "2026-10-06T11:00:00+00:00", "2026-10-06T12:00:00+00:00"


def turn(seq: int) -> dict[str, Any]:
    return {"seq": seq, "t": T0, "kind": "turn", "phase": "end", "stopReason": "end_turn"}


def stop(seq: int, how: str, t: str = T1) -> dict[str, Any]:
    return {"seq": seq, "t": t, "kind": "lifecycle", "event": "stopped", "how": how}


def test_a_stop_after_a_turn_fires() -> None:
    events = [turn(1), stop(2, "explicit")]
    assert pending_stop(events, 0, None) == events[1]
    assert pending_stop(events, 2, None) is None  # read already
    assert pending_stop([stop(1, "idle")], 0, None) is None  # no turn: nothing to read


@pytest.mark.parametrize("how", ["deleted", "daemon_restarted"])
def test_some_stops_never_fire(how: str) -> None:
    assert pending_stop([turn(1), stop(2, how)], 0, None) is None


def test_the_part_before_a_restart_is_read_with_the_next_stop() -> None:
    """`_load` writes a `daemon_restarted` stop: it does not fire, the next stop reads both."""
    events = [turn(1), stop(2, "daemon_restarted"), turn(3), stop(4, "idle")]
    assert pending_stop(events[:2], 0, None) is None
    assert pending_stop(events, 0, None) == events[3]


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
    return Automations(
        settings,
        SessionStore(settings, registry),
        registry,
        ProjectRegistry(tmp_path, registry),
        apps=AppStore(settings, "t0ken", inbox),
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


def test_a_try_appends_nothing(runner: Automations) -> None:
    loaded, record, output = setup(runner, trial=True)
    (output / "note.md").write_text("x" * 5000)
    [would] = runner.append(loaded, record, output)
    assert would.bytes == 5000 and would.text == "x" * 4096
    assert not ((runner.settings.knowledge_dir or Path()) / "handler" / "a.md").exists()


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


def test_an_agent_run_s_result_makes_a_message() -> None:
    assert result_problems(RESULT) == []
    assert result_problems({"properties": {}}) == [
        "its result has no required 'status' enum (ok, attention, failed)",
        "its result has no required 'summary' string",
    ]
    bad = RESULT | {"properties": {"status": {"enum": ["good"]}, "summary": {"type": "string"}}}
    assert result_problems(bad) == ["its result's status has ['good']: only ok, attention, failed"]


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
        'apiVersion = "handler.automation/v1"\nwhen = { every = "1h" }\n'
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
