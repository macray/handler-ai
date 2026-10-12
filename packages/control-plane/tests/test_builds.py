"""Image rebuilds (D.4): what the check reports, the build log, restart recovery. No podman here;
the real build → check → switch flow is in tests/harness/test_rebuild.py."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from handler_contracts import Build, BuildState, HarnessDescriptor
from handler_control.builds import BuildStore, _Job
from handler_control.image_check import (
    DUMMY_SECRET,
    MCP_PROBE_ENV,
    check_agent,
    mcp_probe,
    mcp_problems,
    mismatches,
)
from handler_control.settings import Settings
from handler_harness import catalog

DESCRIPTOR = HarnessDescriptor.model_validate(
    {
        "apiVersion": "handler.harness/v1",
        "name": "agent",
        "product": "Agent",
        "image": "localhost/handler-ai-agent",
        "acpCommand": ["agent-acp"],
        "home": "/home/agent",
        "modelOption": "model",
        "permissions": {
            "ask": {"sessionMode": "default"},
            "accept-edits": {"sessionMode": "acceptEdits"},
            "bypass": {"sessionMode": "bypassPermissions"},
        },
    }
)


def session(modes: list[str], options: list[str]) -> dict[str, Any]:
    return {
        "modes": {"availableModes": [{"id": m} for m in modes]},
        "configOptions": [{"id": o} for o in options],
    }


def test_check_accepts_a_matching_session() -> None:
    modes = ["default", "acceptEdits", "bypassPermissions", "plan"]
    assert mismatches(DESCRIPTOR, session(modes, ["model"])) == []


def test_check_reports_a_renamed_mode_and_a_missing_model_option() -> None:
    problems = mismatches(DESCRIPTOR, session(["default", "acceptEdits", "yolo"], []))
    assert len(problems) == 2
    assert "'bypass'" in problems[0] and "'bypassPermissions'" in problems[0]
    assert "yolo" in problems[0]  # what the agent offers instead, to fix the descriptor
    assert "'model'" in problems[1]


def settings(tmp_path: Path) -> Settings:
    return Settings(
        port=0,
        config_dir=tmp_path,
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path,
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
    )


def build(state: BuildState = "running", build_id: str = "b1") -> Build:
    return Build(
        id=build_id,
        target="vibe",
        state=state,
        started_at=datetime.now(UTC),
    )


def test_the_mcp_probe_must_start_with_the_sandbox_env_and_no_secret() -> None:
    """B6 in the rebuild's check: the stdio server a session gets, as an addon's would."""
    probe = mcp_probe("/scope/.handler-mcp-probe")
    assert (probe.command, probe.args[-1]) == ("sh", "env > /scope/.handler-mcp-probe; exec cat")
    good = f"PATH=/usr/bin\n{MCP_PROBE_ENV}=m4rk\n"
    assert mcp_problems(good, "m4rk", "s3cr3t") == []
    assert "did not start" in mcp_problems(None, "m4rk", "s3cr3t")[0]
    [reduced] = mcp_problems("PATH=/usr/bin\n", "m4rk", "s3cr3t")  # vibe's own env, unwrapped
    assert "sandbox's environment" in reduced
    [leak] = mcp_problems(good + "TOKEN=s3cr3t\n", "m4rk", "s3cr3t")
    assert "secret" in leak


def test_the_check_gives_each_harness_a_credential_it_accepts() -> None:
    """A token login: a dummy token on an account; else a provider with a dummy key (codex-acp
    refuses session/new with neither), as the conformance suite does. No model is called."""
    claude, token, key = check_agent(catalog.get("claude-code").descriptor)
    assert (claude.account, token, key) == ("image-check", DUMMY_SECRET, None)
    codex, token, key = check_agent(catalog.get("codex").descriptor)
    assert codex.account is None and codex.provider_spec is not None
    assert (token, key) == (None, DUMMY_SECRET)
    assert set(codex.provider_spec.endpoints) == {"responses"}


def test_daemon_restart_fails_running_builds(tmp_path: Path) -> None:
    store = BuildStore(settings(tmp_path))
    store._save(build("running"))
    restarted = BuildStore(settings(tmp_path))
    found = restarted.get("b1")
    assert found is not None and found.state == "failed" and found.error == "daemon restarted"


def test_log_is_read_in_whole_lines_from_an_offset(tmp_path: Path) -> None:
    store = BuildStore(settings(tmp_path))
    (store.dir / "b1.log").write_text("STEP 1/2: FROM x\nSTEP 2/2: RUN é")
    first = store.read_log(build("running"), 0)
    assert first.text == "STEP 1/2: FROM x\n" and not first.complete  # the last line is unfinished
    rest = store.read_log(build("succeeded"), first.next_offset)
    assert rest.text == "STEP 2/2: RUN é" and rest.complete
    assert store.read_log(build("succeeded"), rest.next_offset).text == ""


def test_log_lines_lose_terminal_escapes(tmp_path: Path) -> None:
    store = BuildStore(settings(tmp_path))
    job = _Job(store, build())
    with (store.dir / "b1.log").open("a") as out:
        job.out = out
        job.line("\x1b[1;32mSTEP 1/3:\x1b[0m FROM toolbox\r\n")
    assert (store.dir / "b1.log").read_text() == "STEP 1/3: FROM toolbox\n"
