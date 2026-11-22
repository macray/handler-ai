"""H.1: `handler app deploy` installing an app (handler_cli/app_commands.py) lists the automations
it suggests and turns on none by default: each asked on a terminal, else only those named with
`--automation`, made and turned on through the Control API. A daemon answering as it does."""

import argparse
from typing import Any

import pytest

from handler_cli import app_commands

APP: dict[str, Any] = {
    "name": "planner",
    "state": "stopped",
    "url": "http://planner.localhost:8800/",
    "current": None,
    "source": {"version": "1.0.0"},
    "suggests": [
        {"description": "What to do next", "when": {"every": "5h"}, "run": {"job": "plan"}},
        {
            "description": "Weekly review",
            "when": {"at": "09:00", "days": ["mon"]},
            "run": {"job": "review"},
            "optional": True,
        },
    ],
}


class Daemon:
    """Answers by method and path, keeping what was asked."""

    def __init__(self, app: dict[str, Any], refused: str = "") -> None:
        self.app = app
        self.refused = refused  # a description whose check answers a problem
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self) -> "Daemon":
        return self

    def call(self, method: str, path: str, body: Any = None, **_: Any) -> Any:
        self.calls.append((method, path, body))
        if path == "/v1/automations" and method == "GET":
            return []
        if path == "/v1/automations/check":
            refused = body["definition"]["description"] == self.refused
            return {"problems": ["job plan runs on account max: refused"] if refused else []}
        if path == "/v1/automations":
            return {"name": body["name"], "enabled": body["enable"]}
        return self.app

    def made(self) -> list[dict[str, Any]]:
        return [b for m, p, b in self.calls if (m, p) == ("POST", "/v1/automations")]


def deploy(monkeypatch: pytest.MonkeyPatch, daemon: Daemon, *named: str) -> int:
    monkeypatch.setattr(app_commands, "Daemon", daemon)
    args = argparse.Namespace(app_cmd="deploy", name="planner", yes=False, automation=list(named))
    return app_commands.dispatch(args)


@pytest.mark.rule("automation.off-until-you-turn-it-on", "app.its-automations-shown-before-install")
def test_installing_asks_for_each_suggested_automation_none_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    asked: list[str] = []
    answers = iter(["y", ""])
    monkeypatch.setattr(app_commands.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda q: asked.append(q) or next(answers))
    daemon = Daemon(APP)
    assert deploy(monkeypatch, daemon) == 0
    assert asked == [
        "Turn on planner-what-to-do-next: every 5h, runs its job plan? [y/N] ",
        "Turn on planner-weekly-review: at 09:00 on mon, runs its job review? [y/N] ",
    ]
    made = daemon.made()
    assert [b["name"] for b in made] == ["planner-what-to-do-next"]
    assert made[0]["enable"] is True and "agentId" not in made[0]
    assert made[0]["definition"] == {
        "apiVersion": "handler.automation/v1",
        "description": "What to do next",
        "when": {"every": "5h"},
        "run": {"app": "planner", "job": "plan", "input": {}},
    }
    deployed = [i for i, c in enumerate(daemon.calls) if c[1] == "/v1/apps/planner/deploy"]
    assert deployed and deployed[0] < daemon.calls.index(("POST", "/v1/automations", made[0]))
    out = capsys.readouterr().out
    assert "planner-weekly-review: Weekly review (at 09:00 on mon, runs its job review)" in out
    assert "not turned on: planner-weekly-review; make one later from planner's page" in out
    assert "planner-what-to-do-next: made, on" in out


@pytest.mark.rule("automation.off-until-you-turn-it-on", "app.its-automations-shown-before-install")
def test_without_a_terminal_only_those_named_are_turned_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(app_commands.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("asked without a terminal"))
    daemon = Daemon(APP)
    assert deploy(monkeypatch, daemon) == 0
    assert daemon.made() == []
    assert (
        "not turned on: planner-what-to-do-next, planner-weekly-review" in capsys.readouterr().out
    )
    daemon = Daemon(APP)
    assert deploy(monkeypatch, daemon, "planner-weekly-review") == 0
    assert [b["name"] for b in daemon.made()] == ["planner-weekly-review"]


def test_a_name_it_does_not_suggest_deploys_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = Daemon(APP)
    with pytest.raises(app_commands.ClientError, match="suggests no automation nightly"):
        deploy(monkeypatch, daemon, "nightly")
    assert not [c for c in daemon.calls if c[0] == "POST"]


def test_an_update_asks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    installed = APP | {"current": {"version": "0.9.0"}}
    monkeypatch.setattr(app_commands.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("asked on an update"))
    daemon = Daemon(installed)
    assert deploy(monkeypatch, daemon) == 0
    assert daemon.made() == []


@pytest.mark.rule("automation.off-until-you-turn-it-on", "app.its-automations-shown-before-install")
def test_one_it_cannot_turn_on_is_not_offered_but_said_why(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Its account's terms refuse runs nobody follows (I.7): never asked, its problem said;
    named, an error before anything is deployed."""
    asked: list[str] = []
    monkeypatch.setattr(app_commands.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda q: asked.append(q) or "y")
    daemon = Daemon(APP, refused="What to do next")
    assert deploy(monkeypatch, daemon) == 0
    assert asked == ["Turn on planner-weekly-review: at 09:00 on mon, runs its job review? [y/N] "]
    assert [b["name"] for b in daemon.made()] == ["planner-weekly-review"]
    out = capsys.readouterr().out
    assert "cannot be turned on: job plan runs on account max: refused" in out
    assert "not turned on: planner-what-to-do-next;" in out
    daemon = Daemon(APP, refused="What to do next")
    with pytest.raises(app_commands.ClientError, match="cannot turn on planner-what-to-do-next"):
        deploy(monkeypatch, daemon, "planner-what-to-do-next")
    assert not [c for c in daemon.calls if c[1] == "/v1/apps/planner/deploy"]


@pytest.mark.rule("deploy.an-update-takes-then-deploys", "deploy.what-it-adds-is-said-first")
def test_update_says_what_it_changes_and_asks_for_what_it_adds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`handler app update`: what the version its source offers changes, what it adds (asked
    first: no, nothing done), then POST …/update; none offered, an error."""
    offered = {"source": "official", "version": "1.1.0", "changes": "Pages by month"}
    app = APP | {"current": {"version": "1.0.0"}, "offered": offered | {"addedNeeds": ["notify"]}}
    monkeypatch.setattr("builtins.input", lambda _: "n")
    daemon = Daemon(app)
    monkeypatch.setattr(app_commands, "Daemon", daemon)
    args = argparse.Namespace(app_cmd="update", name="planner", yes=False)
    assert app_commands.dispatch(args) == 1
    out = capsys.readouterr().out
    assert "planner 1.1.0: Pages by month" in out and "  + notify" in out
    assert ("POST", "/v1/apps/planner/update", None) not in daemon.calls
    args.yes = True
    assert app_commands.dispatch(args) == 0
    assert ("POST", "/v1/apps/planner/update", None) in daemon.calls
    monkeypatch.setattr(app_commands, "Daemon", Daemon(APP))
    with pytest.raises(app_commands.ClientError, match="its source offers no other version"):
        app_commands.dispatch(args)


@pytest.mark.rule("app.its-automations-shown-before-install")
def test_a_suggested_call_to_its_route_is_made_as_a_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`run = { call }` (I.1, I.3): the automation calls the app's route; its code, no model,
    so no API key advice."""
    nightly = {
        "description": "Archive",
        "when": {"at": "03:00"},
        "run": {"call": "POST /api/archive"},
    }
    monkeypatch.setattr(app_commands.sys.stdin, "isatty", lambda: False)
    daemon = Daemon({**APP, "suggests": [nightly]})
    assert deploy(monkeypatch, daemon, "planner-archive") == 0
    assert daemon.made()[0]["definition"]["run"] == {"app": "planner", "call": "POST /api/archive"}
    out = capsys.readouterr().out
    assert "planner-archive: Archive (at 03:00, calls POST /api/archive)" in out
    assert "API key" not in out


def test_list_says_where_each_app_comes_from(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An app added from a file or a draft is yours: no source offers it a new version."""
    current = {"version": "1.0.0"}
    apps = [
        APP | {"name": "planner", "current": current, "fromSource": None},
        APP | {"name": "cv", "current": current, "fromSource": "private"},
    ]

    class Apps(Daemon):
        def call(self, method: str, path: str, body: Any = None, **_: Any) -> Any:
            assert (method, path) == ("GET", "/v1/apps")
            return apps

    monkeypatch.setattr(app_commands, "Daemon", Apps(APP))
    assert app_commands.dispatch(argparse.Namespace(app_cmd="list")) == 0
    rows = {line.split()[0]: line.split() for line in capsys.readouterr().out.splitlines()}
    assert rows["NAME"][4] == "FROM"
    assert rows["planner"][4] == "yours"
    assert rows["cv"][4] == "private"
