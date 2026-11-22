"""A session's start refused before its sandbox (F.1): its agent deleted, or working elsewhere."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from handler_contracts import Build
from handler_control.agents import AgentRegistry
from handler_control.sessions import SessionError, SessionRecord, SessionStore
from handler_control.settings import Settings


def store(tmp_path: Path) -> SessionStore:
    settings = Settings(
        port=7430,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path / "bindings",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path / "ui",
        data_dir=tmp_path / "data",
    )
    return SessionStore(settings, AgentRegistry(settings.state_dir))


def record(state: str) -> SessionRecord:
    now = datetime.now(UTC)
    return SessionRecord(
        id="s_1", agent_id="gone", harness="fake", scope="/code", created_at=now,
        last_activity_at=now, agents_model=True, state=state,  # ty: ignore[invalid-argument-type]
    )  # fmt: skip


@pytest.mark.rule("session.a-start-that-fails-says-why")
def test_a_first_start_refused_before_its_sandbox_leaves_it_failed(tmp_path: Path) -> None:
    """Created by `POST /v1/sessions` and started without anyone attached: refused (its agent
    deleted meanwhile), it is failed with why, not "starting" forever."""
    sessions = store(tmp_path)
    rec = sessions.records["s_1"] = record("starting")
    with pytest.raises(SessionError, match="its agent was deleted"):
        asyncio.run(sessions.ensure_running("s_1"))
    assert (rec.state, rec.error) == ("failed", "its agent was deleted")


@pytest.mark.rule("session.a-start-that-fails-says-why")
def test_a_resume_refused_before_its_sandbox_stays_stopped(tmp_path: Path) -> None:
    """Resumed by someone attaching, who is told why: the session stays as it was."""
    sessions = store(tmp_path)
    rec = sessions.records["s_1"] = record("stopped")
    with pytest.raises(SessionError, match="its agent was deleted"):
        asyncio.run(sessions.ensure_running("s_1"))
    assert (rec.state, rec.error) == ("stopped", None)


def built(target: str, state: str = "succeeded", harnesses: tuple[str, ...] = ()) -> Build:
    now = datetime.now(UTC)
    return Build(
        id="b_1", target=target, state=state, harnesses=list(harnesses), started_at=now,  # ty: ignore[invalid-argument-type]
        ended_at=now,
    )  # fmt: skip


@pytest.mark.rule("session.a-first-request-waits-for-its-image")
def test_a_session_waiting_with_its_request_starts_once_its_image_is_built(
    tmp_path: Path,
) -> None:
    """Started by handlerd when the build ends, with no page open (F.1): the build of its
    image or the toolbox's that rebuilt it; not a failed one, another image's, or a resume."""
    sessions = store(tmp_path)
    started: list[str] = []

    async def ensure_running(session_id: str) -> None:
        started.append(session_id)

    sessions.ensure_running = ensure_running  # ty: ignore[invalid-assignment]
    for sid, request in (("s_wait", "fix the bug"), ("s_resume", None)):
        rec = sessions.records[sid] = record("stopped")
        rec.id, rec.request, rec.missing_image = sid, request, "codex"

    async def ends(build: Build) -> list[str]:
        started.clear()
        sessions.image_built(build)
        await asyncio.gather(*sessions.background)
        return started

    assert asyncio.run(ends(built("codex", state="failed"))) == []
    assert asyncio.run(ends(built("pi"))) == []
    assert asyncio.run(ends(built("toolbox", harnesses=("pi",)))) == []
    assert asyncio.run(ends(built("codex"))) == ["s_wait"]
    assert asyncio.run(ends(built("toolbox", harnesses=("codex",)))) == ["s_wait"]
