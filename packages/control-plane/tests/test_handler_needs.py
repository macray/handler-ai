"""Handler's needs (handler_needs.py): the agent given for one, and which agents fit; who you talk
to in Chat (its agents, agents.py)."""

from pathlib import Path

from handler_contracts import AgentOrigin
from handler_control import agents, handler_needs
from handler_control.agents import AgentRecord, RunsAs

MODEL = RunsAs(harness="claude-code", account="perso")


def test_who_you_talk_to_are_chats_agents_the_last_used_first() -> None:
    old = AgentRecord(id="a1", scope=None, model=MODEL, chat=True)
    new = AgentRecord(id="a2", scope=None, model=MODEL, chat=True)
    new.last_used_at = new.created_at.replace(year=new.created_at.year + 1)
    outside = AgentRecord(id="a3", scope=None, model=MODEL)
    part = AgentRecord(id="a4", scope=None, model=MODEL, app="planner")
    assert [a.id for a in agents.chats([old, new, outside, part])] == ["a2", "a1"]


def test_a_deleted_agent_is_given_for_no_need(tmp_path: Path) -> None:
    handler_needs.give(tmp_path, "skill-review", "a1")
    handler_needs.give(tmp_path, "ask-router", "a2")
    handler_needs.forget(tmp_path, "a1")
    assert handler_needs.given(tmp_path) == {"ask-router": "a2"}


def test_a_chat_helper_fits_when_set_up_for_its_need() -> None:
    need = handler_needs.get("skill-creator")
    assert need is not None
    mine = handler_needs.origin(need)
    other = AgentOrigin(kind="agents-file", name="my-team", version=1, agent="skill-creator")
    assert handler_needs.misfit(need, mine, None, None) is None
    assert handler_needs.misfit(need, other, None, None) is not None
    assert handler_needs.misfit(need, mine, None, "/home/me/code") is not None  # it has no folder


def test_a_need_s_origin_must_be_its_current_version() -> None:
    need = handler_needs.get("skill-review")
    assert need is not None
    assert handler_needs.folder(handler_needs.origin(need)) == handler_needs.ROOT / "skill-review"
    old = AgentOrigin(kind="handler-need", name="skill-review", version=need.version + 1)
    try:
        handler_needs.folder(old)
    except handler_needs.NeedError as e:
        assert (e.status, e.title) == (409, "handler need changed")
    else:
        raise AssertionError("another version was taken")
    assert handler_needs.get("nope") is None and handler_needs.get("../data") is None
