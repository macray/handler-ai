"""D.24: `handler ask` reads Ask's answer (handler_cli/ask_commands.py): a pick and its action's
run read again until it ends, a question answered in the terminal, none listing what can be
asked. A daemon answering as the Control API does."""

import argparse
from typing import Any

import pytest

from handler_cli import ask_commands


class Answers:
    """A daemon giving each call's answer in turn, keeping what was asked."""

    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self) -> "Answers":
        return self

    def call(self, method: str, path: str, body: Any = None, **_: Any) -> dict[str, Any]:
        self.calls.append((method, path, body))
        return self.answers.pop(0)


def ask(monkeypatch: pytest.MonkeyPatch, daemon: Answers, *words: str) -> int:
    monkeypatch.setattr(ask_commands, "Daemon", daemon)
    monkeypatch.setattr(ask_commands.time, "sleep", lambda _: None)
    args = argparse.Namespace(
        words=list(words), listen=False, toggle=False, check=False, history=False
    )
    return ask_commands.dispatch(args)


@pytest.mark.rule("ask.a-pick-runs-at-once-as-the-owner")
def test_a_pick_is_said_then_its_run_read_until_it_ends(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pick: dict[str, Any] = {
        "kind": "pick",
        "summary": "Planner plans",
        "app": "planner",
        "action": "plan",
    }
    pick |= {"why": "a day to plan", "run": {"runId": "r1", "state": "running"}}
    done: dict[str, Any] = {"runId": "r1", "state": "succeeded"}
    done |= {"result": {"status": "ok", "summary": "The bank first."}}
    daemon = Answers(pick, done)
    assert ask(monkeypatch, daemon, "plan", "my", "day") == 0
    assert daemon.calls[0][:2] == ("POST", "/v1/ask")
    assert daemon.calls[0][2]["turns"] == [{"who": "you", "text": "plan my day"}]
    assert daemon.calls[1][:2] == ("GET", "/v1/apps/planner/actions/plan/runs/r1")
    out = capsys.readouterr().out
    assert "→ planner · plan  (a day to plan)" in out and "The bank first." in out


@pytest.mark.rule("ask.none-leads-to-chat")
def test_none_lists_what_can_be_asked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    none: dict[str, Any] = {"kind": "none", "summary": "None of your apps books tables."}
    none |= {"actions": [{"app": "planner", "action": "add", "description": "Add to my calendar"}]}
    assert ask(monkeypatch, Answers(none), "book", "a", "table") == 1
    out = capsys.readouterr().out
    assert "None of your apps books tables." in out and "planner · Add to my calendar" in out


def test_a_question_without_a_terminal_stops(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    needs = {"kind": "needs", "summary": "Which day?", "question": "Which day?"}
    monkeypatch.setattr(ask_commands.sys.stdin, "isatty", lambda: False)
    assert ask(monkeypatch, Answers(needs), "call", "the", "bank") == 1
    assert "Which day?" in capsys.readouterr().out


@pytest.mark.rule("ask.each-ask-is-kept")
def test_history_says_what_was_heard_where_it_went_and_how_it_ended(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`handler ask --history`: each ask, from anywhere, newest first: when, from where, what
    was said, the app and action, how it ended.

    If this fails: from a terminal you cannot tell what Handler got from your key."""
    answer = {"kind": "pick", "summary": "s", "app": "planner", "action": "add"}
    kept = {
        "keep": True,
        "asks": [
            {
                "id": "a1",
                "at": "2026-11-20T09:12:00Z",
                "via": "key",
                "turns": [{"who": "you", "text": "add call the bank tomorrow"}],
                "outcome": "done",
                "summary": "Added Call the bank, Friday 21 November.",
                "answer": answer,
            },
            {
                "id": "a2",
                "at": "2026-11-20T09:10:00Z",
                "via": "key",
                "turns": [],
                "outcome": "failed",
                "summary": "Nothing was written down: the provider failed",
            },
        ],
    }
    monkeypatch.setattr(ask_commands, "Daemon", Answers(kept))
    args = argparse.Namespace(words=[], listen=False, toggle=False, check=False, history=True)
    assert ask_commands.dispatch(args) == 0
    out = capsys.readouterr().out.splitlines()
    assert "key       “add call the bank tomorrow”" in out[0]
    assert out[1].strip() == "→ planner · add  ✓ Added Call the bank, Friday 21 November."
    assert "(nothing heard)" in out[2]
    assert out[3].strip() == "✕ Nothing was written down: the provider failed"
