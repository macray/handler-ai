"""A host the network filter refuses, asked about in the session (contract F.9).

The fake agent's `blocked HOST N` writes N refusals of HOST on its stderr, as its sandbox's filter
reports them (A.3), `held HOST N` one held request first; the fake sandbox keeps the live verbs
it is given (set-allow, set-blocked, set-watched).
"""

import contextlib
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ..support.acp_client import AcpClient, AcpError
from ..support.daemon import Daemon
from .test_sessions import attach, create_session, get_session

_TAKEN: dict[AcpClient, int] = {}  # a client's lines already taken by `lines`


def lines(client: AcpClient, count: int, timeout: float = 30) -> list[dict[str, Any]]:
    """The next `count` lines of Handler's own (`_handler/line`), also those that came while
    waiting for an answer."""
    deadline = time.monotonic() + timeout
    taken = _TAKEN.get(client, 0)
    while (
        len(found := [m for m in client.updates if m["method"] == "_handler/line"]) < taken + count
    ):
        client.wait_notification("_handler/line", deadline - time.monotonic())
    _TAKEN[client] = taken + count
    return [m["params"] for m in found[taken : taken + count]]


def agent_of(daemon: Daemon, aid: str) -> dict[str, Any]:
    with daemon.http() as c:
        return c.get(f"/v1/agents/{aid}").json()


def live_verb(daemon: Daemon, aid: str, verb: str) -> list[str]:
    """What the agent's running sandbox was last given by `verb`."""
    sandbox = agent_of(daemon, aid)["connections"][0]["sandbox"]
    return json.loads((daemon.config_dir.parent / "fake-ran" / f"{sandbox}.{verb}").read_text())


@pytest.fixture
def started(daemon: Daemon) -> tuple[dict[str, Any], dict[str, Any], AcpClient, str]:
    """A filtered agent's session, attached: the agent, the session, the client, its ACP id."""
    agent = daemon.create_ad_hoc("fake", daemon.make_scope(), egress="enforce")
    assert agent["network"] == "filtered"
    session = create_session(daemon, agent)
    client, _ = attach(daemon, session)
    return agent, session, client, get_session(daemon, session["id"])["acpSessionId"]


@pytest.mark.rule("session.a-refused-host-is-asked-once-per-turn", "history.the-log-is-the-history")
def test_one_card_per_host_per_turn_with_its_count(daemon: Daemon, started: Any) -> None:
    _, session, client, acp_id = started
    try:
        client.prompt(acp_id, "blocked pypi.org:443 3")
        first = lines(client, 3)
        card = first[0]["card"]
        assert first[0]["seq"] == card  # its first line is the card
        assert [(x["event"], x["host"], x["count"], x["card"]) for x in first] == [
            ("host blocked", "pypi.org:443", n, card) for n in (1, 2, 3)
        ]
        client.prompt(acp_id, "blocked pypi.org:443 1")
        (again,) = lines(client, 1)
        assert again["count"] == 1 and again["card"] == again["seq"] > card  # a new turn
    finally:
        client.close()
    later, _ = attach(daemon, session)  # the history: the lines in their place
    try:
        replayed = [m for m in later.updates if m["method"] in ("_handler/line", "session/update")]
        shown = [m["params"] for m in replayed if m["method"] == "_handler/line"]
        assert [(x["host"], x["count"], x["card"]) for x in shown] == [
            *(("pypi.org:443", n, card) for n in (1, 2, 3)),
            ("pypi.org:443", 1, again["card"]),
        ]
        seqs = [m["params"].get("seq") or m["params"]["_meta"]["handler.dev/seq"] for m in replayed]
        assert seqs == sorted(seqs)
    finally:
        later.close()


@pytest.mark.rule(
    "session.a-card-s-answer-is-saved-and-applied", "session.a-refused-host-is-asked-once-per-turn"
)
def test_allow_and_keep_blocked_apply_at_once_and_are_saved(daemon: Daemon, started: Any) -> None:
    agent, _, client, acp_id = started
    try:
        client.prompt(acp_id, "blocked a.org:443 1")
        lines(client, 1)
        client.request("_handler/decide_host", {"host": "a.org:443", "decision": "allowed"})
        decided, _ = lines(client, 2)  # then told to the agent, which goes on
        client.wait_notification("_handler/turn_ended")
        assert decided | {"seq": 0} == {
            "seq": 0,
            "event": "host decided",
            "host": "a.org:443",
            "decision": "allowed",
        }
        assert "a.org:443" in live_verb(daemon, agent["id"], "set-allow")
        assert agent_of(daemon, agent["id"])["allow"] == ["a.org:443"]

        client.prompt(acp_id, "blocked b.org:443 1")
        lines(client, 1)
        client.request("_handler/decide_host", {"host": "b.org:443", "decision": "kept blocked"})
        lines(client, 2)
        client.wait_notification("_handler/turn_ended")
        assert live_verb(daemon, agent["id"], "set-blocked") == ["b.org:443"]
        saved = agent_of(daemon, agent["id"])
        assert (saved["allow"], saved["blocked"]) == (["a.org:443"], ["b.org:443"])

        # kept blocked (or allowed): no card ever again; the filter's events come in order
        client.prompt(acp_id, "blocked b.org:443 2")
        client.prompt(acp_id, "blocked a.org:443 1")
        client.prompt(acp_id, "blocked c.org:443 1")
        (only,) = lines(client, 1)
        assert only["host"] == "c.org:443"

        with pytest.raises(AcpError, match="-32013"):  # only a host blocked in this session
            client.request("_handler/decide_host", {"host": "d.org:443", "decision": "allowed"})
    finally:
        client.close()


def test_a_kept_blocked_host_is_saved_in_the_agents_file(daemon: Daemon, started: Any) -> None:
    """The answer outlives handlerd: it is in agents.json."""
    agent, _, client, acp_id = started
    try:
        client.prompt(acp_id, "blocked e.org:443 1")
        lines(client, 1)
        client.request("_handler/decide_host", {"host": "e.org:443", "decision": "kept blocked"})
    finally:
        client.close()
    state = Path(daemon.config_dir.parent / "state" / "agents.json")
    (saved,) = [a for a in json.loads(state.read_text()) if a["id"] == agent["id"]]
    assert saved["blocked"] == ["e.org:443"]


def report_of(client: AcpClient, acp_id: str) -> dict[str, Any]:
    """The fake agent's report (what it received)."""
    before = len(client.updates)
    client.prompt(acp_id, "report")
    chunks = [
        u["params"]["update"]["content"]["text"]
        for u in client.updates[before:]
        if u["method"] == "session/update"
        and u["params"]["update"].get("sessionUpdate") == "agent_message_chunk"
    ]
    return json.loads("".join(chunks))


def watched(daemon: Daemon, aid: str, then: Any, timeout: float = 10) -> list[str]:
    """What the agent's sandbox's filter was last told of who watches (`set-watched`), once
    `then(it)` holds."""
    deadline = time.monotonic() + timeout
    while True:
        with contextlib.suppress(FileNotFoundError):
            if then(told := live_verb(daemon, aid, "set-watched")) or time.monotonic() > deadline:
                return told
        time.sleep(0.05)


@pytest.mark.rule("network.a-watched-request-waits-for-the-answer")
def test_the_filter_is_told_whether_someone_watches_and_in_which_turn(
    daemon: Daemon, started: Any
) -> None:
    agent, _, client, acp_id = started
    try:
        (turn,) = watched(daemon, agent["id"], bool)  # attached: watched
        client.prompt(acp_id, "hello")
        (later,) = watched(daemon, agent["id"], lambda t: t != [turn])
        assert int(later) > int(turn)  # a new turn: held once more per host
    finally:
        client.close()
    assert watched(daemon, agent["id"], lambda t: t == []) == []  # nobody watches


@pytest.mark.rule("session.a-held-request-is-counted-down")
def test_a_held_request_is_counted_down_on_its_card(daemon: Daemon, started: Any) -> None:
    """A held request's card says until when the agent waits; its refusal ends that, the same
    card counting it. Answered while it was only held, the agent is told nothing: its request
    went through."""
    _, _, client, acp_id = started
    try:
        client.prompt(acp_id, "held pypi.org:443 1")
        held, refused = lines(client, 2)
        assert (held["count"], refused["count"], refused["card"]) == (0, 1, held["card"])
        left = datetime.fromisoformat(held["until"]) - datetime.now(UTC)
        assert timedelta(seconds=5) < left <= timedelta(seconds=8)
        assert "until" not in refused

        client.prompt(acp_id, "held a.org:443 0")
        (only_held,) = lines(client, 1)
        assert only_held["count"] == 0
        client.request("_handler/decide_host", {"host": "a.org:443", "decision": "allowed"})
        (decided,) = lines(client, 1)
        assert decided["event"] == "host decided" and "queued" not in decided
        report = report_of(client, acp_id)
        assert not [p for p in report["prompts"] if "Handler:" in p[-1]]
    finally:
        client.close()


@pytest.mark.rule("session.a-later-answer-is-told-to-the-agent", "history.the-log-is-the-history")
def test_an_answer_after_the_turn_is_told_to_the_agent_at_once(
    daemon: Daemon, started: Any
) -> None:
    _, session, client, acp_id = started
    told = "Handler: a.org:443 is now allowed. Go on."
    try:
        client.prompt(acp_id, "blocked a.org:443 1")
        lines(client, 1)
        client.request("_handler/decide_host", {"host": "a.org:443", "decision": "allowed"})
        decided, line = lines(client, 2)
        assert "queued" not in decided
        assert (line["event"], line["text"]) == ("told agent", told)
        client.wait_notification("_handler/turn_ended")  # the agent went on by itself
        report = report_of(client, acp_id)
        assert report["prompts"][-2] == [told]
    finally:
        client.close()
    later, _ = attach(daemon, session)  # Handler's line, never the person's message
    try:
        texts = [json.dumps(m["params"]) for m in later.updates if "user_message" in str(m)]
        assert not [t for t in texts if "Handler:" in t]
        shown = [m["params"] for m in later.updates if m["method"] == "_handler/line"]
        assert [x["text"] for x in shown if x["event"] == "told agent"] == [told]
    finally:
        later.close()


@pytest.mark.rule("session.a-later-answer-is-told-to-the-agent")
def test_an_answer_during_a_turn_is_told_when_it_ends(daemon: Daemon, started: Any) -> None:
    _, _, client, acp_id = started
    told = "Handler: the user keeps b.org:443 blocked. Go on without it."
    try:
        client.prompt(acp_id, "blocked b.org:443 1")
        lines(client, 1)
        prompt = {"sessionId": acp_id, "prompt": [{"type": "text", "text": "sleep"}]}
        client.send({"id": 999, "method": "session/prompt", "params": prompt})  # a turn going on
        while not client.wait_notification("_handler/session_state")["busy"]:
            pass
        client.request("_handler/decide_host", {"host": "b.org:443", "decision": "kept blocked"})
        (decided,) = lines(client, 1)
        assert decided["queued"] is True
        client.send({"method": "session/cancel", "params": {"sessionId": acp_id}})
        (line,) = lines(client, 1)
        assert (line["event"], line["text"]) == ("told agent", told)
        client.wait_notification("_handler/turn_ended")
        report = report_of(client, acp_id)
        assert report["prompts"][-2] == [told]
    finally:
        client.close()


def inbox_of(daemon: Daemon, sid: str, count: int = 1, timeout: float = 30) -> list[dict[str, Any]]:
    """The inbox messages about the session, once there are `count`."""
    deadline = time.monotonic() + timeout
    while True:
        with daemon.http() as c:
            found = [m for m in c.get("/v1/inbox").json() if m.get("sessionId") == sid]
        if len(found) >= count or time.monotonic() > deadline:
            return found
        time.sleep(0.1)


def events_of(daemon: Daemon, sid: str) -> list[dict[str, Any]]:
    log = daemon.config_dir.parent / "state" / "sessions" / sid / "events.ndjson"
    return [json.loads(line) for line in log.read_text().splitlines()]


@pytest.mark.rule(
    "session.hosts-refused-while-away-go-to-the-inbox",
    "inbox.a-refused-host-is-answered-from-it",
    "session.a-later-answer-is-told-to-the-agent",
)
def test_hosts_refused_while_nobody_watched_go_to_the_inbox_once(daemon: Daemon) -> None:
    agent = daemon.create_ad_hoc("fake", daemon.make_scope(), egress="enforce")
    session = create_session(daemon, agent, prompt="blocked pypi.org:443 2")  # nobody attached
    (message,) = inbox_of(daemon, session["id"])
    assert (message["source"], message["status"], message["agentId"]) == (
        "session",
        "attention",
        agent["id"],
    )
    assert message["title"] == (
        "pypi.org:443 was blocked by the network filter while you were away"
    )
    assert message["refused"] == [{"host": "pypi.org:443", "count": 2}]  # one, never one a block

    with daemon.http() as c:  # its answer: saved, applied, and told to the agent
        answer = {"decision": "kept blocked", "hosts": ["pypi.org:443"]}
        r = c.post(f"/v1/inbox/{message['id']}/answer", json=answer)
        assert r.status_code == 200, r.text
        assert r.json()["refused"] == [
            {"host": "pypi.org:443", "count": 2, "decision": "kept blocked"}
        ]
        assert c.get(f"/v1/agents/{agent['id']}").json()["blocked"] == ["pypi.org:443"]
    told = "Handler: the user keeps pypi.org:443 blocked. Go on without it."
    deadline = time.monotonic() + 30
    while told not in [e.get("text") for e in events_of(daemon, session["id"])]:
        assert time.monotonic() < deadline
        time.sleep(0.1)
    assert len(inbox_of(daemon, session["id"])) == 1


@pytest.mark.rule("session.hosts-refused-while-away-go-to-the-inbox")
def test_no_inbox_message_while_someone_watches_nor_for_a_kept_blocked_host(
    daemon: Daemon, started: Any
) -> None:
    """Refused while a client is attached (its card asks there), or kept blocked: never told to
    the inbox."""
    _, session, client, acp_id = started
    try:
        client.prompt(acp_id, "blocked b.org:443 1")
        lines(client, 1)
    finally:
        client.close()
    agent = daemon.create_ad_hoc(
        "fake", daemon.make_scope(), egress="enforce", blocked=["a.org:443"]
    )
    unwatched = create_session(daemon, agent, prompt="blocked a.org:443 2")
    with daemon.http() as c:
        deadline = time.monotonic() + 30
        while c.get(f"/v1/sessions/{unwatched['id']}").json().get("lastStopReason") is None:
            assert time.monotonic() < deadline
            time.sleep(0.1)
    time.sleep(1.5)  # past the time its filter's last decisions take
    assert inbox_of(daemon, session["id"], timeout=0) == []
    assert inbox_of(daemon, unwatched["id"], timeout=0) == []
