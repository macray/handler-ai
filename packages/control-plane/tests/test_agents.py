"""Unit tests: the agent registry."""

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from handler_control import agents
from handler_control.agents import (
    AgentRecord,
    AgentRegistry,
    CheckedSettings,
    LiveConnection,
    NotAgentsModelError,
    RunsAs,
)


def claude(**fields: Any) -> CheckedSettings:
    """Settings of an agent of harness "claude" in /code/x, with these changed."""
    fields.setdefault("model", RunsAs(harness="claude", account="a"))
    return CheckedSettings(scope="/code/x", **fields)


def add(registry: AgentRegistry, settings: CheckedSettings, **fields: Any) -> AgentRecord:
    return registry.add(AgentRecord(**settings.model_dump(), **fields))


def test_an_agent_outside_projects_is_its_folder_and_its_name(tmp_path: Path) -> None:
    """Whatever its settings (D.1); names without case, no name being one too; an app's agent
    is no agent outside projects."""
    registry = AgentRegistry(tmp_path)
    plain = add(registry, claude())
    named = add(registry, claude(network="open"), name="Review")
    add(registry, claude(), name="Planner", app="planner")
    assert registry.outside("/code/x", None) is plain
    assert registry.outside("/code/x", "review ") is named
    assert registry.outside("/code/x", "planner") is None
    assert registry.outside("/code/y", None) is None
    assert AgentRegistry(tmp_path).get(plain.id) is not None  # persisted


def test_lists_are_normalized(tmp_path: Path) -> None:
    registry = AgentRegistry(tmp_path)
    shop = add(registry, claude(bindings=["shop", "logs", "b", "b"], knowledge=["me"]))
    assert shop.bindings == ["b", "logs", "shop"]
    loaded = AgentRegistry(tmp_path).agents
    assert (loaded[shop.id].bindings, loaded[shop.id].knowledge) == (["b", "logs", "shop"], ["me"])


def test_update_keeps_the_id(tmp_path: Path) -> None:
    registry = AgentRegistry(tmp_path)
    w = add(registry, claude())
    settings = CheckedSettings(
        model=RunsAs(harness="vibe", account="a"),
        scope="/code/x",
        network="filtered",
        allow=["b.example:443", "a.example:443"],
        confinement="nested",
        permissions="ask",
    )
    w.set_settings(settings)
    registry.save()
    again = AgentRegistry(tmp_path).get(w.id)
    assert again is not None and again.settings == settings and again.name is None
    assert again.allow == ["a.example:443", "b.example:443"]


def test_touch_records_last_use(tmp_path: Path) -> None:
    registry = AgentRegistry(tmp_path)
    w = add(registry, claude())
    assert w.last_used_at is None
    registry.touch(w)
    assert AgentRegistry(tmp_path).agents[w.id].last_used_at == w.last_used_at


def test_a_session_runs_with_its_model_unless_given_another() -> None:
    pro = RunsAs(harness="claude", account="pro", model="opus")
    agent = claude(model=pro)
    assert agent.runs_as() == pro
    assert agent.runs_as(RunsAs(harness=None, account="pro", model="opus")) == pro  # its harness
    with contextlib.suppress(NotAgentsModelError):
        agent.runs_as(RunsAs(harness="claude", account="pro"))  # another model
        raise AssertionError("not the agent's model")


def test_a_session_resumes_with_its_model_or_one_on_the_same_access() -> None:
    sonnet = RunsAs(harness="claude", account="pro", model="sonnet")
    agent = claude(model=sonnet)
    assert agent.resumes_as("claude", "pro", None, "sonnet", agents_model=True) == sonnet
    # started with the agent's model, changed since: the agent's new one on that access
    assert agent.resumes_as("claude", "pro", None, "opus", agents_model=True) == sonnet
    # picked for the session alone (D.19), on the agent's access or not: the session's own
    haiku = RunsAs(harness="claude", account="pro", model="haiku")
    assert agent.resumes_as("claude", "pro", None, "haiku", agents_model=False) == haiku
    own = RunsAs(harness="codex", provider="llamacpp", model="qwen")
    assert agent.resumes_as("codex", None, "llamacpp", "qwen", agents_model=False) == own
    assert agent.resumes_as("codex", None, "llamacpp", "qwen", agents_model=True) == own


class Launcher:
    returncode: int | None = None  # running, as an asyncio process


def test_a_live_change_waits_for_a_launcher_still_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A.4: in the moments after its launcher started, before it made its instance, set-allow
    is tried again; on an older connection, or once its launcher ended, it fails at once."""
    registry = AgentRegistry(tmp_path)
    record = add(registry, claude(network="filtered", allow=["example.org:443"]))
    calls: list[str] = []

    async def set_allow(sandbox: str, _allow: list[str]) -> str | None:
        calls.append(sandbox)
        return "fresh is not a running filtered sandbox" if len(calls) < 3 else None

    monkeypatch.setattr(agents.sandbox_process, "set_allow", set_allow)
    now = datetime.now(UTC)
    fresh = LiveConnection("c1", "fresh", now, Launcher(), egress_base=[])
    record.connections = {"c1": fresh}
    assert asyncio.run(agents.apply_network(record)) == []
    assert calls == ["fresh"] * 3

    calls.clear()
    old = now - timedelta(seconds=agents.LAUNCHER_START_SECONDS + 1)
    record.connections = {"c2": LiveConnection("c2", "old", old, Launcher(), egress_base=[])}
    assert asyncio.run(agents.apply_network(record)) == [
        "c2: fresh is not a running filtered sandbox"
    ]
    assert calls == ["old"]

    calls.clear()
    ended = Launcher()
    ended.returncode = 1
    record.connections = {"c3": LiveConnection("c3", "ended", now, ended, egress_base=[])}
    assert len(asyncio.run(agents.apply_network(record))) == 1
    assert calls == ["ended"]
