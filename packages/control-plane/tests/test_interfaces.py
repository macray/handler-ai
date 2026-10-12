"""Agent interfaces (D.18): schemas checked, inputs checked, the request, the result parsed."""

from pathlib import Path

import pytest

from handler_contracts import AgentInterface, SessionInput, SessionSubject
from handler_control import interfaces, skills

RESULT = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_schemas_are_checked() -> None:
    interfaces.check(AgentInterface(result=RESULT, fields={"type": "object"}))
    with pytest.raises(interfaces.InterfaceError, match="fields"):
        interfaces.check(AgentInterface(result=RESULT, fields={"type": "string"}))
    with pytest.raises(interfaces.InterfaceError, match="result: not a JSON Schema"):
        interfaces.check(AgentInterface(result={"type": 3}))
    with pytest.raises(interfaces.InterfaceError, match="larger"):
        interfaces.check(AgentInterface(result={"description": "x" * 70_000}))


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
    assert interfaces.check_input(interface, SessionInput(fields={"n": 1}), tmp_path).fields == {
        "n": 1
    }
    with pytest.raises(interfaces.InterfaceError, match="'n' is a required property"):
        interfaces.check_input(interface, SessionInput(), tmp_path)
    with pytest.raises(interfaces.InterfaceError, match="takes no fields"):
        interfaces.check_input(
            AgentInterface(result=RESULT), SessionInput(fields={"n": 1}), tmp_path
        )
    on_skill = AgentInterface(result=RESULT, subject="skill")
    with pytest.raises(interfaces.InterfaceError, match="takes a skill"):
        interfaces.check_input(on_skill, SessionInput(), tmp_path)
    with pytest.raises(interfaces.InterfaceError, match="unknown skill"):
        interfaces.check_input(
            on_skill, SessionInput(subject=SessionSubject(skill="nope")), tmp_path
        )


def test_a_subject_is_mounted_read_only_with_its_digest(tmp_path: Path) -> None:
    folder = tmp_path / "tidy"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: tidy\ndescription: Tidies.\n---\nTidy.\n")
    interface = AgentInterface(result=RESULT, subject="skill")
    given = interfaces.check_input(
        interface, SessionInput(subject=SessionSubject(skill="tidy")), tmp_path
    )
    assert given.subject is not None and given.subject.digest == skills.digest(folder)
    mount = interfaces.subject_mount(tmp_path, given.subject)
    assert (mount.target, mount.read_only, mount.kind) == ("/subject/tidy", True, "subject")
    (folder / "run.sh").write_text("echo\n")
    assert skills.digest(folder) != given.subject.digest  # changed since
    text = interfaces.request("Review it.", interface, given)
    assert text.startswith("Review it.") and "`/subject/tidy` (read-only)" in text
    assert '"required": [\n    "ok"\n  ]' in text and "json handler-result" in text
