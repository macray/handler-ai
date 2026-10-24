"""Unit tests: what a check compares (D.20): never free text, and what differs, said."""

from datetime import UTC, datetime

from handler_contracts import Check
from handler_control.agent_checks import comparable, differences

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


def test_free_text_is_never_compared() -> None:
    assert comparable(RESULT) == ["status", "verdict", "score", "urgent", "tags"]
    assert comparable(None) == []


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
