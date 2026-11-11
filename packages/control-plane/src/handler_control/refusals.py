"""Hosts the network filter refused (F.9) that nobody answered as they came: a run's (a plan's
step, an automation's), read from its session's cards, said in Handler's own words rather than
the agent's guess; a session's while nobody could answer, told to the inbox when its turn ends.
A host the agent's lists name (allowed, kept blocked) is decided: never listed.

    refused     a session's hosts refused, neither allowed nor kept blocked: how many times
    reason      a run that failed with hosts refused: "pypi.org:443 was blocked by the network filter"
    completed   one that completed: "Completed, with 2 hosts refused"
    notes_line  what a plan's next steps read of them: "Hosts refused: pypi.org:443 (3 times)"
    said_about  what the agent's last message says of them
    decided     the hosts with the agent's answer, as its lists say now
    decide      hosts allowed or kept blocked for the agent, applied to its running sandboxes
"""

import re
from typing import Any

from handler_contracts import HostDecision, RefusedHost

from .agents import AgentRecord, AgentRegistry, apply_network
from .sessions import EventLog, SessionRecord

MAX_SAID = 1000  # characters of the agent's words kept
FENCED = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)  # its result's block, code
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def refused(log: EventLog, agent: AgentRecord) -> list[RefusedHost]:
    """The hosts refused in the session (its `host blocked` cards, one per host per turn, F.9),
    each counted over its cards, in the order they came; not those the agent's lists name now."""
    counts: dict[str, dict[int, int]] = {}
    for e in log.replay():
        if e.get("event") == "host blocked":
            counts.setdefault(e["host"], {})[e["card"]] = e["count"]
    return [
        RefusedHost(host=host, count=sum(cards.values()))
        for host, cards in counts.items()
        if sum(cards.values()) > 0 and host not in agent.allow and host not in agent.blocked
    ]


def _names(hosts: list[RefusedHost]) -> str:
    names = [h.host for h in hosts]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def reason(hosts: list[RefusedHost]) -> str:
    verb = "was" if len(hosts) == 1 else "were"
    return f"{_names(hosts)} {verb} blocked by the network filter"


def completed(hosts: list[RefusedHost]) -> str:
    return f"Completed, with {len(hosts)} host{'' if len(hosts) == 1 else 's'} refused"


def counted(hosts: list[RefusedHost]) -> str:
    return ", ".join(f"{h.host} ({'once' if h.count == 1 else f'{h.count} times'})" for h in hosts)


def notes_line(hosts: list[RefusedHost]) -> str:
    return f"Hosts refused: {counted(hosts)}"


def said_about(hosts: list[RefusedHost], *texts: str | None) -> str | None:
    """The sentences of the agent's last message (and of its result's own words) that name one
    of the hosts, in order, once each (its starting instructions ask it to say what it did
    instead, rule launch.a-filtered-agent-is-told)."""
    names = {h.host.rsplit(":", 1)[0] for h in hosts}
    found: list[str] = []
    for text in texts:
        for part in SENTENCE.split(FENCED.sub("", text or "")):
            sentence = part.strip()
            if sentence and sentence not in found and any(n in sentence for n in names):
                found.append(sentence)
    said = " ".join(found)
    return (said[: MAX_SAID - 1] + "…" if len(said) > MAX_SAID else said) or None


def decided(hosts: list[RefusedHost], agent: AgentRecord | None) -> list[RefusedHost]:
    def decision(host: str) -> HostDecision | None:
        if agent is None:
            return None
        return (
            "allowed" if host in agent.allow else "kept blocked" if host in agent.blocked else None
        )

    return [h.model_copy(update={"decision": decision(h.host)}) for h in hosts]


async def decide(
    registry: AgentRegistry, agent: AgentRecord, hosts: list[str], decision: HostDecision
) -> list[str]:
    """Each host saved in that list of the agent, off the other (as a card's answer), then
    applied to its running sandboxes: the failures."""
    for host in hosts:
        registry.decide_host(agent, host, keep_blocked=decision == "kept blocked")
    return await apply_network(agent)


def session_message(
    rec: SessionRecord, agent: AgentRecord, hosts: list[RefusedHost]
) -> dict[str, Any]:
    """The inbox message of a session's turn that ended with hosts refused while nobody could
    answer (`inbox.add`'s fields)."""
    one = len(hosts) == 1
    return {
        "source": "session",
        "name": rec.title or agent.name or "a session",
        "agent": agent.name or agent.id,
        "agent_id": agent.id,
        "person": "owner",
        "title": f"{reason(hosts) if one else f'{len(hosts)} hosts were blocked'} "
        "while you were away",
        "status": "attention",
        "summary": "Allow them or keep them blocked: the agent is told your answer.",
        "session_id": rec.id,
        "refused": hosts,
    }
