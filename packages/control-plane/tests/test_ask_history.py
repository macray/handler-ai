"""D.24: Ask's history (ask_history.py, assistant.py): each ask kept as it ended, from anywhere;
a job's action read again until it ends; a failure, or no app for it, also told to the inbox;
turned off, nothing kept and what was is emptied; the last 200, 30 days at most."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from handler_contracts import ActionResult, ActionRun, AskTurn, AssistantAnswer
from handler_control import ask_history
from handler_control.ask_history import AskHistoryStore
from handler_control.assistant import Assistant

SAID = [AskTurn(who="you", text="add call the bank tomorrow")]


def store(tmp_path: Path) -> AskHistoryStore:
    return AskHistoryStore(cast(Any, SimpleNamespace(state_dir=tmp_path)))


def pick(run: ActionRun) -> AssistantAnswer:
    return AssistantAnswer(kind="pick", summary="s", app="planner", action="add", run=run)


DONE = ActionRun(
    app="planner",
    action="add",
    state="succeeded",
    result=ActionResult(status="ok", summary="Added Call the bank, Friday 21 November."),
)


class Apps:
    """What the assistant reads of the app store: a job's run, and the inbox."""

    def __init__(self) -> None:
        self.told: list[dict[str, Any]] = []
        self.inbox = SimpleNamespace(add=lambda **m: self.told.append(m))
        self.run = ActionRun(app="planner", action="plan", state="running", run_id="r1")

    def action_run(self, name: str, action: str, run_id: str) -> ActionRun:
        return self.run


def asking(tmp_path: Path, answer: AssistantAnswer) -> tuple[Assistant, Apps]:
    apps = Apps()
    assistant = Assistant(cast(Any, None), cast(Any, apps), cast(Any, None), store(tmp_path))

    async def routed(*_: Any) -> AssistantAnswer:
        return answer

    assistant.routed = routed  # ty: ignore[invalid-assignment]
    return assistant, apps


@pytest.mark.rule("ask.each-ask-is-kept")
def test_each_ask_is_kept_with_where_it_went_and_how_it_ended(tmp_path: Path) -> None:
    """What was said, from where, the app and action, its answer: kept, newest first, read
    again after handlerd restarts.

    If this fails: you cannot tell what Handler received from your key, nor what came of it."""
    assistant, apps = asking(tmp_path, pick(DONE))
    asyncio.run(assistant.answer(SAID, None, "key", True))
    (kept,) = store(tmp_path).view().asks  # as handlerd reads it at its next start
    assert (kept.via, kept.spoken, kept.turns, kept.outcome) == ("key", True, SAID, "done")
    assert kept.summary == "Added Call the bank, Friday 21 November."
    assert kept.answer is not None and (kept.answer.app, kept.answer.action) == ("planner", "add")
    assert apps.told == []  # done: nothing to the inbox
    assert (tmp_path / "asks.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.rule("ask.each-ask-is-kept")
def test_a_job_still_running_is_read_again_until_it_ends(tmp_path: Path) -> None:
    running = ActionRun(app="planner", action="plan", state="running", run_id="r1")
    assistant, apps = asking(tmp_path, pick(running).model_copy(update={"action": "plan"}))
    asyncio.run(assistant.answer(SAID, None, "web", False))
    assert assistant.history_view().asks[0].outcome == "running"
    apps.run = DONE.model_copy(update={"action": "plan", "run_id": "r1"})
    (kept,) = assistant.history_view().asks
    assert kept.outcome == "done" and kept.summary.startswith("Added Call the bank")


@pytest.mark.rule("ask.a-failure-is-told")
@pytest.mark.parametrize(
    "answer, title, summary",
    [
        (
            AssistantAnswer(kind="none", summary="None of your apps books tables."),
            "No app does that",
            "“add call the bank tomorrow”: None of your apps books tables.",
        ),
        (
            pick(ActionRun(app="planner", action="add", state="failed", error="no such day")),
            "planner · add failed",
            "“add call the bank tomorrow”: no such day",
        ),
    ],
)
def test_a_failure_or_no_app_for_it_is_told_to_the_inbox(
    tmp_path: Path, answer: AssistantAnswer, title: str, summary: str
) -> None:
    """If this fails: an ask that did nothing is seen only if you go and look for it."""
    assistant, apps = asking(tmp_path, answer)
    asyncio.run(assistant.answer(SAID, None, "key", True))
    (told,) = apps.told
    assert (told["source"], told["title"], told["summary"]) == ("ask", title, summary)
    assert told["person"] == "owner" and told["status"] == "failed"


@pytest.mark.rule("ask.a-failure-is-told", "ask.each-ask-is-kept")
def test_what_could_not_be_written_down_is_kept_and_told(tmp_path: Path) -> None:
    assistant, apps = asking(tmp_path, pick(DONE))
    assistant.unheard("key", "the provider failed")
    (kept,) = assistant.history.view().asks
    assert (kept.turns, kept.outcome) == ([], "failed")
    assert kept.summary == "Nothing was written down: the provider failed"
    assert apps.told[0]["summary"] == "Nothing was written down: the provider failed"


@pytest.mark.rule("ask.history-yours-to-turn-off")
def test_turned_off_nothing_is_kept_and_what_was_is_emptied(tmp_path: Path) -> None:
    """Off, what you say is not kept; each ask can also be deleted, or all at once.

    If this fails: what you said stays on disk after you asked Handler not to keep it."""
    history = store(tmp_path)
    first = history.add("web", False, SAID, pick(DONE))
    history.add("web", False, SAID, pick(DONE))
    assert history.delete(first.id) and not history.delete(first.id)
    assert len(history.view().asks) == 1
    assert history.set_keep(False).asks == []
    history.add("web", False, SAID, pick(DONE))
    again = store(tmp_path).view()
    assert (again.keep, again.asks) == (False, [])
    assert "bank" not in (tmp_path / "asks.json").read_text()
    history.set_keep(True)
    history.add("web", False, SAID, pick(DONE))
    history.clear()
    assert store(tmp_path).view().asks == []


def test_the_last_ones_are_kept_none_older_than_30_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ask_history, "KEEP", 3)
    history = store(tmp_path)
    for _ in range(5):
        history.add("web", False, SAID, pick(DONE))
    assert len(history.view().asks) == 3
    old = history.asks[0].model_copy(update={"at": datetime.now(UTC) - timedelta(days=31)})
    history.asks[0] = old
    assert len(history.view().asks) == 2
