"""Handler's needs (handler_needs.py): the agent given for one, and which agents fit; who you talk
to in Chat (its agents, agents.py)."""

from pathlib import Path
from typing import Any

import pytest

from handler_contracts import AgentInterface, AgentOrigin
from handler_control import agents, handler_needs, interfaces
from handler_control.agents import AgentRecord, RunsAs

MODEL = RunsAs(harness="claude-code", account="perso")
RESULT: dict[str, Any] = {
    "type": "object",
    "required": ["status", "summary"],
    "properties": {
        "status": {"enum": ["ok", "attention", "failed"]},
        "summary": {"type": "string"},
    },
}
OPTIONAL = {"type": "object", "properties": {"request": {"type": "string"}}}


def test_who_you_talk_to_are_chats_agents_the_last_used_first() -> None:
    old = AgentRecord(id="a1", scope=None, model=MODEL, chat=True)
    new = AgentRecord(id="a2", scope=None, model=MODEL, chat=True)
    new.last_used_at = new.created_at.replace(year=new.created_at.year + 1)
    outside = AgentRecord(id="a3", scope=None, model=MODEL)
    assert [a.id for a in agents.chats([old, new, outside])] == ["a2", "a1"]


@pytest.mark.rule("agent.deleting-it-stops-what-runs-on-it", "helper.handler-uses-the-one-given")
def test_a_deleted_agent_is_given_for_no_need(tmp_path: Path) -> None:
    handler_needs.give(tmp_path, "skill-review", "a1")
    handler_needs.give(tmp_path, "ask-router", "a2")
    handler_needs.forget(tmp_path, "a1")
    assert handler_needs.given(tmp_path) == {"ask-router": "a2"}


@pytest.mark.rule("helper.handler-uses-the-one-given")
def test_a_chat_helper_fits_when_set_up_for_its_need() -> None:
    need = handler_needs.get("skill-creator")
    assert need is not None
    mine = AgentOrigin(kind="handler-need", name=need.name, version=need.version)
    other = AgentOrigin(kind="agents-file", name="my-team", version=1, agent="skill-creator")
    assert handler_needs.misfit(need, mine, None, None) is None
    assert handler_needs.misfit(need, other, None, None) is not None
    assert handler_needs.misfit(need, mine, None, "/home/me/code") is not None  # it has no folder


@pytest.mark.rule("helper.handler-uses-the-one-given")
def test_misfit_compares_properties_types_and_required() -> None:
    """A job's need fits an agent whose form takes each field Handler sends and whose result
    gives each field it reads: properties, types and `required` only."""
    wanted = AgentInterface.model_validate({"fields": OPTIONAL, "result": RESULT})

    def why(**interface: Any) -> str | None:
        return interfaces.misfit(wanted, AgentInterface.model_validate(interface))

    assert why(fields=OPTIONAL, result=RESULT) is None
    extra = {"type": "object", "properties": {**RESULT["properties"], "more": {"type": "string"}}}
    assert why(fields=OPTIONAL, result={**RESULT, **extra}) is None
    assert why(result=RESULT) == "its form has no field request"
    number = {"type": "object", "properties": {"request": {"type": "number"}}}
    assert why(fields=number, result=RESULT) == "its form's request is not a string"
    loose = {**RESULT, "required": ["status"]}
    assert why(fields=OPTIONAL, result=loose) == ("its result does not always give summary")
    assert interfaces.misfit(wanted, None) == "it is not a job"


@pytest.mark.rule("definition.only-the-origin-follows")
def test_a_need_s_origin_must_be_its_current_version() -> None:
    need = handler_needs.get("skill-review")
    assert need is not None
    mine = AgentOrigin(kind="handler-need", name=need.name, version=need.version)
    assert handler_needs.folder(mine) == handler_needs.ROOT / "skill-review"
    old = AgentOrigin(kind="handler-need", name="skill-review", version=need.version + 1)
    try:
        handler_needs.folder(old)
    except handler_needs.NeedError as e:
        assert (e.status, e.title) == (409, "handler need changed")
    else:
        raise AssertionError("another version was taken")
    assert handler_needs.get("nope") is None and handler_needs.get("../data") is None
