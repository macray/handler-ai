"""Unit tests: the agent registry."""

import contextlib
from pathlib import Path
from typing import Any

from handler_control.agents import AgentRegistry, CheckedSettings, ModelNotListedError, RunsAs


def claude(**fields: Any) -> CheckedSettings:
    """Settings of an agent of harness "claude" in /code/x, with these changed."""
    fields.setdefault("models", [RunsAs(harness="claude", account="a")])
    return CheckedSettings(scope="/code/x", **fields)


def test_an_ad_hoc_agent_is_its_folder_and_its_name(tmp_path: Path) -> None:
    """Whatever its settings (D.1); names without case, no name being one too."""
    registry = AgentRegistry(tmp_path)
    plain = registry.create(claude())
    named = registry.create(claude(network="open"), name=" Review ")
    assert named.name == "Review"
    assert registry.ad_hoc("/code/x", None) is plain
    assert registry.ad_hoc("/code/x", "review ") is named
    assert registry.ad_hoc("/code/y", None) is None
    assert AgentRegistry(tmp_path).get(plain.id) is not None  # persisted


def test_lists_are_normalized(tmp_path: Path) -> None:
    registry = AgentRegistry(tmp_path)
    shop = registry.create(claude(bindings=["shop", "logs", "b", "b"], knowledge=["me"]))
    assert shop.bindings == ["b", "logs", "shop"]
    loaded = AgentRegistry(tmp_path).agents
    assert (loaded[shop.id].bindings, loaded[shop.id].knowledge) == (["b", "logs", "shop"], ["me"])


def test_update_keeps_the_id(tmp_path: Path) -> None:
    registry = AgentRegistry(tmp_path)
    w = registry.create(claude())
    settings = CheckedSettings(
        models=[RunsAs(harness="vibe", account="a")],
        scope="/code/x",
        network="filtered",
        allow=["b.example:443", "a.example:443"],
        confinement="nested",
        permissions="ask",
    )
    registry.update(w, settings, "  ")
    again = AgentRegistry(tmp_path).get(w.id)
    assert again is not None and again.settings == settings and again.name is None
    assert again.allow == ["a.example:443", "b.example:443"]


def test_touch_records_last_use(tmp_path: Path) -> None:
    registry = AgentRegistry(tmp_path)
    w = registry.create(claude())
    assert w.last_used_at is None
    registry.touch(w)
    assert AgentRegistry(tmp_path).agents[w.id].last_used_at == w.last_used_at


def test_a_session_runs_with_one_of_its_models() -> None:
    pro = RunsAs(harness="claude", account="pro", model="opus")
    local = RunsAs(harness="codex", provider="llamacpp", model="qwen")
    agent = claude(models=[pro, local])
    assert agent.runs_as() == pro  # the first by default
    assert agent.runs_as(RunsAs(harness="codex", provider="llamacpp", model="qwen")) == local
    with contextlib.suppress(ModelNotListedError):
        agent.runs_as(RunsAs(harness="codex", provider="llamacpp"))  # another model
        raise AssertionError("a model it does not list")


def test_a_session_resumes_with_its_model_or_one_on_the_same_access() -> None:
    sonnet = RunsAs(harness="claude", account="pro", model="sonnet")
    opus = RunsAs(harness="claude", account="pro", model="opus")
    agent = claude(models=[sonnet, opus])
    assert agent.resumes_as("claude", "pro", None, "opus") == opus
    assert agent.resumes_as("claude", "pro", None, "haiku") == sonnet  # its model changed
    # a model the agent does not list (D.19): the session's own, its history kept
    own = RunsAs(harness="codex", provider="llamacpp", model="qwen")
    assert agent.resumes_as("codex", None, "llamacpp", "qwen") == own
