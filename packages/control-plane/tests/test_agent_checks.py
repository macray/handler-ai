"""Unit tests: what a check compares (D.20): never free text, and what differs, said."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from handler_contracts import Check, CheckResult, CheckRun, CheckState
from handler_control.agent_checks import CheckStore, Stored, comparable, differences
from handler_control.settings import Settings

RESULT = {
    "type": "object",
    "properties": {
        "status": {"enum": ["ok", "attention", "failed"]},
        "summary": {"type": "string"},
        "verdict": {"enum": ["send", "rewrite"]},
        "score": {"type": "number"},
        "urgent": {"type": "boolean"},
        "tags": {"type": "array", "items": {"enum": ["a", "b"]}},
        "notes": {"type": "array", "items": {"type": "string"}},
        "where": {"type": "object"},
    },
}


@pytest.mark.rule("check.free-text-is-never-compared")
def test_free_text_is_never_compared() -> None:
    assert comparable(RESULT) == ["status", "verdict", "score", "urgent", "tags"]
    assert comparable(None) == []


@pytest.mark.rule("check.passes-when-what-it-compares-comes-back")
def test_differences_say_what_came_back() -> None:
    check = Check(
        id="c_00000000",
        name="irony",
        answer={"verdict": "rewrite", "score": 2, "summary": "blame"},
        compare=["verdict", "score"],
        created_at=datetime.now(UTC),
    )
    assert differences(check, {"verdict": "rewrite", "score": 2, "summary": "other"}) == []
    assert differences(check, {"verdict": "send"}) == [
        'verdict: "send", not "rewrite"',
        "score: nothing, not 2",
    ]


class DeletedSessions:
    """The sessions' side of a check store: which sessions it deleted."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, session_id: str) -> None:
        self.deleted.append(session_id)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        port=0, config_dir=tmp_path, state_dir=tmp_path / "state", bindings_dir=tmp_path,
        allowed_origins=frozenset(), web_ui_dir=tmp_path,
    )  # fmt: skip


def _run(n: int, state: CheckState = "passed", ended: bool = True) -> CheckRun:
    started = datetime(2026, 10, 1, tzinfo=UTC) + timedelta(minutes=n)
    result = CheckResult(check_id="c1", name="one", state=state, session_id=f"s_{n}")
    return CheckRun(
        id=f"k_{n:08x}", started_at=started, ended_at=started if ended else None, results=[result]
    )


@pytest.mark.rule("check.keeps-its-last-20-runs")
def test_an_agent_keeps_its_last_20_check_runs_and_deletes_the_older_ones_sessions(
    tmp_path: Path,
) -> None:
    """The 21st check run ends: 20 are kept, the oldest gone with its sessions.

    If this fails: check runs' sessions pile up for ever, or a recent one is lost."""
    sessions = DeletedSessions()
    store = CheckStore(_settings(tmp_path), cast(Any, sessions))
    store.save("a1", Stored(runs=[_run(n) for n in range(20)] + [_run(20, ended=False)]))

    async def finish() -> None:
        store.running["a1"] = cast(Any, None)  # its run, under way until it finishes
        store.finish("a1", _run(20).id)
        store.running.pop("a1")
        await asyncio.sleep(0)  # the older sessions' deletion

    asyncio.run(finish())
    kept = store.load("a1").runs
    assert [r.id for r in kept] == [_run(n).id for n in range(1, 21)]
    assert sessions.deleted == ["s_0"]


@pytest.mark.rule("check.keeps-its-last-20-runs")
def test_a_check_run_handlerd_stopped_in_the_middle_of_ends_in_error(tmp_path: Path) -> None:
    """A check run left under way (handlerd stopped meanwhile): read again, what had ended stays
    as it was, the others are `error` "handlerd stopped meanwhile", and the run has ended.

    If this fails: a check run shows "running" for ever after a restart."""
    store = CheckStore(_settings(tmp_path), cast(Any, DeletedSessions()))
    left = _run(0, ended=False)
    left = left.model_copy(
        update={"results": [*left.results, CheckResult(check_id="c2", name="two", state="running")]}
    )
    store.save("a1", Stored(runs=[_run(1), left]))
    (_, last) = CheckStore(_settings(tmp_path), cast(Any, DeletedSessions())).load("a1").runs
    assert last.ended_at is not None
    assert [(r.state, r.why) for r in last.results] == [
        ("passed", None),
        ("error", "handlerd stopped meanwhile"),
    ]
