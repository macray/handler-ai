"""The state handler keeps for an agent (agent_state.py)."""

import json
from pathlib import Path

from handler_control import agent_state
from handler_control.agents import AgentRecord, RunsAs
from handler_harness import catalog


def test_an_agent_keeps_the_slots_that_are_not_a_login_nor_the_daemons() -> None:
    claude = catalog.get("claude-code").descriptor
    assert agent_state.owned_slots(claude) == ["config_dir", "config_json"]
    codex = catalog.get("codex").descriptor
    assert agent_state.owned_slots(codex) == []  # a login, and the sessions
    vibe = catalog.get("vibe").descriptor
    assert agent_state.owned_slots(vibe) == []  # a login, and the sessions


def test_ensure_creates_folders_and_json_files_once(tmp_path: Path) -> None:
    claude = catalog.get("claude-code").descriptor
    on_claude = RunsAs(harness="claude-code", account="perso")
    on_codex = RunsAs(harness="codex", provider="llamacpp")
    agent = AgentRecord(models=[on_claude, on_codex], scope="/code/x", id="a1")
    folder = agent_state.root(tmp_path, agent, on_claude)
    # its own, one per model it runs with
    assert folder == tmp_path / "agent-state" / "a1" / "claude-code@perso"
    assert agent_state.root(tmp_path, agent, on_codex).name == "codex@llamacpp"
    agent_state.ensure(claude, folder)
    assert (folder / "config_dir").is_dir()
    # the slot's initial content: onboarded, so Claude Code's terminal does not ask to log in
    assert json.loads((folder / "config_json").read_text()) == {"hasCompletedOnboarding": True}
    (folder / "config_json").write_text('{"kept": true}')
    agent_state.ensure(claude, folder)
    assert (folder / "config_json").read_text() == '{"kept": true}'  # never overwritten
    assert (folder / "config_json").stat().st_mode & 0o777 == 0o600


def test_a_json_file_without_initial_content_starts_empty(tmp_path: Path) -> None:
    claude = catalog.get("claude-code").descriptor
    slot = claude.state_slots["config_json"].model_copy(update={"initial": None})
    plain = claude.model_copy(update={"state_slots": claude.state_slots | {"config_json": slot}})
    agent_state.ensure(plain, tmp_path)
    assert (tmp_path / "config_json").read_text() == "{}\n"  # a JSON file the harness can read
