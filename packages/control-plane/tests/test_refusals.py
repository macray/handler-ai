"""Hosts refused, read from a session's cards and said in Handler's words (refusals.py)."""

from pathlib import Path

import pytest

from handler_contracts import RefusedHost
from handler_control import refusals
from handler_control.agents import AgentRecord, RunsAs
from handler_control.sessions import EventLog


@pytest.mark.rule("plan.a-refused-host-is-reported", "automation.a-refused-host-is-reported")
def test_a_host_is_counted_over_its_cards_unless_the_agent_decided_it(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.ndjson")
    for host, count, card in [
        ("a.org:443", 1, 1),
        ("a.org:443", 2, 1),  # its card's count raised
        ("b.org:443", 0, 3),  # only held: nothing refused
        ("a.org:443", 1, 4),  # another turn's card
        ("c.org:443", 1, 5),
    ]:
        log.append("lifecycle", event="host blocked", shown=True, host=host, count=count, card=card)
    agent = AgentRecord(model=RunsAs(harness="codex", account="fake"), scope="/code/x", id="a1")
    assert refusals.refused(log, agent) == [
        RefusedHost(host="a.org:443", count=3),
        RefusedHost(host="c.org:443", count=1),
    ]
    agent.blocked = ["c.org:443"]
    hosts = refusals.refused(log, agent)
    assert [h.host for h in hosts] == ["a.org:443"]
    assert refusals.reason(hosts) == "a.org:443 was blocked by the network filter"
    two = [*hosts, RefusedHost(host="c.org:443", count=1)]
    assert refusals.reason(two) == "a.org:443 and c.org:443 were blocked by the network filter"
    assert refusals.completed(two) == "Completed, with 2 hosts refused"
    assert refusals.notes_line(two) == "Hosts refused: a.org:443 (3 times), c.org:443 (once)"
    assert [h.decision for h in refusals.decided(two, agent)] == [None, "kept blocked"]


def test_the_agent_s_words_are_its_sentences_naming_a_host() -> None:
    hosts = [RefusedHost(host="pypi.org:443", count=2)]
    answer = (
        "I set it up.\n\npypi.org was refused, so I used the vendored wheel. The tests pass.\n\n"
        '```json handler-result\n{"summary": "pypi.org failed"}\n```'
    )
    said = refusals.said_about(hosts, answer, "Done without pypi.org.")
    assert said == "pypi.org was refused, so I used the vendored wheel. Done without pypi.org."
    assert refusals.said_about(hosts, "All done.") is None
