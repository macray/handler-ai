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
    return ask_commands.dispatch(argparse.Namespace(words=list(words)))


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
