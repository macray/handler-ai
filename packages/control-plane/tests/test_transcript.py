"""Unit tests: a session's log slice as a transcript (I.4), from a hand-written log."""

import json
from pathlib import Path
from typing import Any

import pytest

from handler_control import transcript
from handler_control.secrets import redactor


def update(seq: int, **u: Any) -> dict[str, Any]:
    return {"seq": seq, "t": "2026-10-06T10:00:00+00:00", "kind": "update", "update": u}


def text(kind: str, value: str) -> dict[str, Any]:
    return {"sessionUpdate": kind, "content": {"type": "text", "text": value}}


LOG = [
    {"seq": 1, "t": "…", "kind": "lifecycle", "event": "started"},
    {"seq": 2, "t": "…", "kind": "turn", "phase": "start"},
    update(3, **text("user_message_chunk", "Install the deps")),
    update(4, **text("agent_thought_chunk", "I need npm.")),
    update(5, **text("agent_message_chunk", "Let me ")),
    update(6, **text("agent_message_chunk", "try.")),
    update(
        7,
        sessionUpdate="tool_call",
        toolCallId="t1",
        title="npm install",
        kind="execute",
        status="pending",
        rawInput={"command": "npm install"},
    ),
    {"seq": 8, "t": "…", "kind": "lifecycle", "event": "permission answered", "detail": "x: ok"},
    update(9, sessionUpdate="tool_call_update", toolCallId="t1", status="failed",
           content=[{"type": "content", "content": {"type": "text", "text": "npm: not found"}}]),
    update(10, **text("agent_message_chunk", "npm is missing.")),
    {"seq": 11, "t": "…", "kind": "turn", "phase": "end", "stopReason": "end_turn"},
    {"seq": 12, "t": "…", "kind": "lifecycle", "event": "stopped", "detail": "x", "how": "idle"},
]  # fmt: skip


def write(tmp_path: Path, events: list[dict[str, Any]]) -> Path:
    log = tmp_path / "events.ndjson"
    log.write_text("".join(json.dumps(e) + "\n" for e in events) + "not json\n")
    return log


@pytest.mark.rule("script.reads-its-part-redacted")
def test_read_keeps_the_slice(tmp_path: Path) -> None:
    log = write(tmp_path, LOG)
    assert [e["seq"] for e in transcript.read(log, 3, 6)] == [3, 4, 5, 6]
    assert transcript.read(log, 13, 20) == []
    assert transcript.read(tmp_path / "missing", 1, 2) == []


@pytest.mark.rule("script.reads-its-part-redacted")
def test_render_joins_chunks_and_merges_tool_calls() -> None:
    out = transcript.render(LOG, [("Agent", "dev"), ("Events", "1 to 12")])
    assert out.startswith("# Session transcript\n\n- Agent: dev\n- Events: 1 to 12\n")
    assert "## [3] Person\n\nInstall the deps" in out
    assert "## [4] Agent's thought\n\nI need npm." in out
    assert "## [5] Agent\n\nLet me try." in out  # two chunks, one message
    assert "### [7] Tool call: npm install (execute, failed)" in out  # as it ended
    assert '"command": "npm install"' in out and "npm: not found" in out
    assert out.count("Tool call:") == 1
    assert "[8] Permission answered: x: ok" in out
    assert "## [10] Agent\n\nnpm is missing." in out
    assert "[11] Turn ended (end_turn)" in out and "[12] Session stopped (idle): x" in out
    assert out.index("[7] Tool call") < out.index("[8] Permission") < out.index("[10] Agent")


@pytest.mark.rule("script.reads-its-part-redacted")
def test_tool_io_is_cut_and_fenced() -> None:
    long = "a" * 2500 + "`````" + "b" * 2000
    call = update(1, sessionUpdate="tool_call", toolCallId="t", title="cat", rawOutput=long)
    out = transcript.render([call], [])
    assert "characters left out" in out and "b" * 1000 in out and "b" * 1001 not in out
    assert "a" * 2000 in out and "a" * 2001 not in out
    assert transcript.fenced("x ````` y").startswith("``````\n")


@pytest.mark.rule("script.reads-its-part-redacted")
def test_an_update_of_a_call_started_before_the_slice_is_shown() -> None:
    late = update(5, sessionUpdate="tool_call_update", toolCallId="old", status="completed")
    assert "### [5] Tool call: old (completed)" in transcript.render([late], [])


@pytest.mark.rule("script.reads-its-part-redacted")
def test_redacted_with_raw_and_json_escaped_values() -> None:
    secret = 'sk-"quoted"-value'
    out = transcript.render([update(1, **text("agent_message_chunk", f"key {secret}"))], [])
    escaped = json.dumps(secret)[1:-1]
    redact = redactor([secret])
    assert secret not in redact(out)
    assert escaped not in redact(f"raw {escaped}")


@pytest.mark.rule("session.an-unreachable-model-is-said")
def test_handler_s_line_on_a_model_that_does_not_answer_is_in_the_transcript() -> None:
    said = {"seq": 4, "t": "…", "kind": "lifecycle", "event": "model unreached", "shown": True}
    local = said | {"host": "host.containers.internal:3000", "error": "connection refused"}
    out = transcript.render([local | {"local": True}], [])
    assert (
        "[4] Handler: The model at host.containers.internal:3000 does not answer (connection "
        "refused). Is the server listening on 0.0.0.0?"
    ) in out
    remote = said | {"host": "api.example.com:443", "error": "host not found", "local": False}
    assert "does not answer (host not found).\n" in transcript.render([remote], []) + "\n"
