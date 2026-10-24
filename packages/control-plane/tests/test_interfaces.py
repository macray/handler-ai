"""Agent interfaces (D.18): schemas checked, inputs checked, the request, the result parsed."""

from pathlib import Path

import pytest

from handler_contracts import AgentInterface, SessionInput
from handler_control import interfaces, skills

RESULT = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
SKILL = {"type": "string", "title": "Skill to review", "x-handler": "skill"}
ON_SKILL = AgentInterface(
    result=RESULT,
    fields={"type": "object", "properties": {"focus": {"type": "string"}, "target": SKILL}},
)


def test_schemas_are_checked() -> None:
    interfaces.check(AgentInterface(result=RESULT, fields={"type": "object"}))
    with pytest.raises(interfaces.InterfaceError, match="fields"):
        interfaces.check(AgentInterface(result=RESULT, fields={"type": "string"}))
    with pytest.raises(interfaces.InterfaceError, match="result: not a JSON Schema"):
        interfaces.check(AgentInterface(result={"type": 3}))
    with pytest.raises(interfaces.InterfaceError, match="larger"):
        interfaces.check(AgentInterface(result={"description": "x" * 70_000}))
    two = {"type": "object", "properties": {"a": SKILL, "b": SKILL}}
    with pytest.raises(interfaces.InterfaceError, match=r"one skill field at most \(a, b\)"):
        interfaces.check(AgentInterface(result=RESULT, fields=two))
    numbered = {"type": "object", "properties": {"a": {"type": "number", "x-handler": "skill"}}}
    with pytest.raises(interfaces.InterfaceError, match="a skill field is a string"):
        interfaces.check(AgentInterface(result=RESULT, fields=numbered))


def test_the_last_result_block_counts() -> None:
    answer = (
        'First try:\n```json handler-result\n{"ok": false}\n```\nBetter:\n\n'
        '```json handler-result\n{"ok": true}\n```\n'
    )
    assert interfaces.parse(answer, RESULT).model_dump(exclude_none=True) == {
        "valid": True,
        "value": {"ok": True},
    }
    plain = interfaces.parse('```json\n{"ok": true}\n```', RESULT)
    assert not plain.valid and "no `handler-result` block" in (plain.error or "")
    broken = interfaces.parse("```json handler-result\n{ok}\n```", RESULT)
    assert not broken.valid and "not JSON" in (broken.error or "")
    wrong = interfaces.parse('```json handler-result\n{"ok": 1}\n```', RESULT)
    assert (
        not wrong.valid
        and wrong.value == {"ok": 1}
        and wrong.error == "ok: 1 is not of type 'boolean'"
    )


def test_inputs_are_checked(tmp_path: Path) -> None:
    form = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    interface = AgentInterface(result=RESULT, fields=form)
    assert interfaces.check_input(interface, SessionInput(fields={"n": 1}), tmp_path) is None
    with pytest.raises(interfaces.InterfaceError, match="'n' is a required property"):
        interfaces.check_input(interface, SessionInput(), tmp_path)
    with pytest.raises(interfaces.InterfaceError, match="takes no fields"):
        interfaces.check_input(
            AgentInterface(result=RESULT), SessionInput(fields={"n": 1}), tmp_path
        )
    assert interfaces.skill_field(ON_SKILL) == "target"
    assert interfaces.check_input(ON_SKILL, SessionInput(), tmp_path) is None  # not required
    with pytest.raises(interfaces.InterfaceError, match=r"target: skill 'nope'.*unknown skill"):
        interfaces.check_input(ON_SKILL, SessionInput(fields={"target": "nope"}), tmp_path)


def test_a_subject_is_mounted_read_only_with_its_digest(tmp_path: Path) -> None:
    folder = tmp_path / "tidy"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: tidy\ndescription: Tidies.\n---\nTidy.\n")
    given = SessionInput(fields={"target": "tidy"})
    subject = interfaces.check_input(ON_SKILL, given, tmp_path)
    assert subject is not None and subject.skill == "tidy"
    assert subject.digest == skills.digest(folder)
    mount = interfaces.subject_mount(tmp_path, subject)
    assert (mount.target, mount.read_only, mount.kind) == ("/subject/tidy", True, "subject")
    (folder / "run.sh").write_text("echo\n")
    assert skills.digest(folder) != subject.digest  # changed since
    text = interfaces.request("Review it.", ON_SKILL, given, subject)
    assert text.startswith("Review it.") and "`/subject/tidy` (read-only)" in text
    assert '"required": [\n    "ok"\n  ]' in text and "json handler-result" in text


def test_instructions_name_fields_of_the_form() -> None:
    """D.18: `{{key}}` in an agent's instructions names a field of its form, filled in with its
    value in the first request; the Input block still holds every value."""
    form = {
        "type": "object",
        "properties": {
            "audience": {"type": "string"},
            "tags": {"type": "array"},
            "words": {"type": "number"},
            "short": {"type": "boolean"},
            "note": {"type": "string"},
        },
    }
    brief = AgentInterface(fields=form)
    text = "For {{audience}} ({{ tags }}), {{words}} words, short: {{short}}.{{note}}"
    interfaces.check_instructions(text, brief)
    interfaces.check_instructions("No placeholder.", None)
    with pytest.raises(interfaces.InterfaceError, match=r"\{\{audiance\}\} is not a field"):
        interfaces.check_instructions("For {{audiance}}.", brief)
    with pytest.raises(interfaces.InterfaceError, match="not a field"):
        interfaces.check_instructions("For {{audience}}.", None)  # a chat has no form
    given = SessionInput(
        fields={"audience": "users", "tags": ["a", "b"], "words": 300, "short": True}
    )
    assert interfaces.fill(text, given.fields) == "For users (a, b), 300 words, short: yes."
    request = interfaces.request(text, brief, given)
    assert request.startswith("For users (a, b)") and '"audience": "users"' in request
    assert "## Result" not in request
