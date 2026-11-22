"""D.24: the Ask router's result is checked before anything runs (assistant.py): only an action
of an app offered to Ask, its fields fitting the action's form, is run; anything else becomes a
question or none. A pick that cannot run, and a router run with no valid result, are said."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from handler_contracts import ActionOption, ActionRun, AppAction, AskTurn
from handler_control import assistant as assistant_module
from handler_control import handler_needs
from handler_control.apps import AppError
from handler_control.ask_history import AskHistoryStore
from handler_control.assistant import ROUTER, Assistant, AssistantError

FORM = {"type": "object", "required": ["what", "day"], "properties": {
    "what": {"type": "string"}, "day": {"type": "string"}}}  # fmt: skip
OFFERED: list[tuple[str, str, dict[str, Any]]] = [
    ("planner", "add", {"description": "Add to my calendar", "fields": FORM, "app": "Planner"}),
    ("planner", "planned", {"description": "Say what is planned", "app": "Planner"}),
]
LISTED = [ActionOption(app=a, action=k, description=v["description"]) for a, k, v in OFFERED]


class Apps:
    """An app store that only records what it is asked to run."""

    def __init__(self) -> None:
        self.ran: list[tuple[str, str, dict[str, Any]]] = []
        self.told: list[dict[str, Any]] = []
        self.inbox = SimpleNamespace(add=lambda **m: self.told.append(m))

    async def act(
        self, name: str, action: str, fields: dict[str, Any], *, asked: bool
    ) -> ActionRun:
        assert asked  # an Ask pick: its run says it was started via Ask
        self.ran.append((name, action, fields))
        return ActionRun(app=name, action=action, state="succeeded")


def routed(value: dict[str, Any]) -> tuple[Any, Apps]:
    apps = Apps()
    assistant = Assistant(cast(Any, None), cast(Any, apps), cast(Any, None), cast(Any, None))
    return asyncio.run(assistant.act(value, OFFERED, LISTED, "s-router")), apps


@pytest.mark.rule("ask.the-router-is-never-trusted", "ask.none-leads-to-chat")
@pytest.mark.parametrize(
    "value",
    [
        {"kind": "pick", "app": "bank", "action": "pay", "fields": {}},  # no such app
        {"kind": "pick", "app": "planner", "action": "delete", "fields": {}},  # not offered
        {"kind": "needs", "app": "bank", "action": "pay", "question": "Which account?"},
        {"kind": "maybe", "app": "planner", "action": "planned"},  # no such kind
    ],
)
def test_what_was_not_offered_is_never_run(value: dict[str, Any]) -> None:
    answer, apps = routed(value | {"summary": "x"})
    assert answer.kind == "none" and apps.ran == []
    assert {(o.app, o.action) for o in answer.actions} == {
        ("planner", "add"),
        ("planner", "planned"),
    }


@pytest.mark.rule("ask.the-router-is-never-trusted")
def test_fields_the_form_refuses_become_a_question() -> None:
    pick = {"kind": "pick", "app": "planner", "action": "add", "fields": {"what": "Dentist"}}
    answer, apps = routed(pick)
    assert (answer.kind, answer.app, answer.action) == ("needs", "planner", "add")
    assert "day" in (answer.question or "") and apps.ran == []


@pytest.mark.rule("ask.the-router-is-never-trusted")
def test_a_pick_that_fits_runs_with_its_fields() -> None:
    fields = {"what": "Dentist", "day": "2026-10-21"}
    pick = {"kind": "pick", "app": "planner", "action": "add", "fields": fields, "why": "a day"}
    answer, apps = routed(pick)
    assert (answer.kind, answer.why, answer.router_run) == ("pick", "a day", "s-router")
    assert apps.ran == [("planner", "add", fields)]


class FailingApps(Apps):
    async def act(
        self, name: str, action: str, fields: dict[str, Any], *, asked: bool
    ) -> ActionRun:
        raise AppError("its backend did not start")


@pytest.mark.rule("ask.a-pick-runs-at-once-as-the-owner")
def test_a_pick_that_cannot_run_is_said() -> None:
    assistant = Assistant(
        cast(Any, None), cast(Any, FailingApps()), cast(Any, None), cast(Any, None)
    )
    pick = {"kind": "pick", "app": "planner", "action": "planned", "fields": {}}
    with pytest.raises(AssistantError) as failed:
        asyncio.run(assistant.act(pick, OFFERED, LISTED, "s-router"))
    assert failed.value.status == 409
    assert str(failed.value) == "planner · planned: its backend did not start"


class Sessions:
    """A session store whose router run ends with no valid result."""

    def __init__(self) -> None:
        self.registry = SimpleNamespace(get=lambda agent_id: SimpleNamespace(id=agent_id))
        self.created: list[dict[str, Any]] = []

    def create(self, agent: Any, runs: Any, **started: Any) -> Any:
        self.created.append(started)
        return SimpleNamespace(id="s-router")

    async def result_of(self, session_id: str) -> tuple[None, str]:
        return None, "the result does not match its schema"


@pytest.mark.rule("ask.each-ask-is-one-router-run", "ask.each-ask-is-kept", "ask.a-failure-is-told")
def test_a_router_with_no_valid_result_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handler_needs.give(tmp_path, ROUTER, "a-router")
    monkeypatch.setattr(assistant_module.save_rules, "session_model", lambda *_: "runs")
    sessions, apps = Sessions(), Apps()
    settings = SimpleNamespace(state_dir=tmp_path)
    history = AskHistoryStore(cast(Any, settings))
    assistant = Assistant(cast(Any, settings), cast(Any, apps), cast(Any, sessions), history)
    monkeypatch.setattr(assistant, "options", lambda: OFFERED)
    turns = [AskTurn(who="you", text="Tomorrow I call the bank")]
    with pytest.raises(AssistantError) as failed:
        asyncio.run(assistant.answer(turns, "Europe/Paris", "key", True))
    assert failed.value.status == 502 and "does not match its schema" in str(failed.value)
    (run,) = sessions.created
    assert run["origin"] == "ask" and set(run["run"].fields) == {"said", "now", "actions"}
    assert apps.ran == []
    (kept,) = history.view().asks  # a failure is kept, and told
    assert (kept.via, kept.outcome, kept.turns) == ("key", "failed", turns)
    (told,) = apps.told
    assert told["source"] == "ask" and told["title"] == "Ask could not answer"
    assert told["summary"].startswith("“Tomorrow I call the bank”: the Ask router gave no answer")


@pytest.mark.rule("ask.only-the-actions-offered")
def test_an_action_taken_out_of_ask_is_not_offered() -> None:
    """If this fails: an action you took out of Ask is run from it, or one you kept is not."""

    def action(name: str, in_ask: bool) -> AppAction:
        return AppAction(name=name, description=name, by="code", in_ask=in_ask)

    app = SimpleNamespace(
        name="cv", current=object(), description="CV", actions=[action("add", True)]
    )
    app.actions.append(action("import", False))
    draft = SimpleNamespace(name="draft", current=None, description="", actions=[action("x", True)])
    apps = SimpleNamespace(views=lambda: [app, draft])
    options = Assistant(
        cast(Any, None), cast(Any, apps), cast(Any, None), cast(Any, None)
    ).options()
    assert [(a, k) for a, k, _ in options] == [("cv", "add")]
    assert "inAsk" not in options[0][2]  # the router reads the action, not your setting
