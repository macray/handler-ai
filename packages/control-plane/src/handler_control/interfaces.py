"""Agent interfaces (D.18): what a session of an agent is started with (a form, one of its fields
maybe naming a skill to work on: the subject) and, for a job, what it gives back (data of a known
shape, in its final message). A job's runs are unattended; a brief's sessions are chats.

    check            an interface's schemas: JSON Schemas (draft 2020-12), the form an object
                     with one skill field at most
    skill_field      the key of the form's skill field
    check_instructions  the form's fields its instructions name, `{{key}}`, exist
    fill             instructions with the form's values in place of their placeholders
    check_input      a run's input against its agent's interface → its subject, digest set
    misfit           why an agent's interface does not fit the one an app needs (H.2)
    subject_mount    the subject, mounted read-only at /subject/<name>
    request          the first request: instructions, input, subject, a job's rule for the result
    parse            the result, from the final message
    repair           the turn sent once when the result is missing or invalid
"""

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from handler_contracts import (
    MAX_SCHEMA_BYTES,
    SKILL_FIELD,
    SUBJECT_ROOT,
    AgentInterface,
    Mount,
    SessionInput,
    SessionOutput,
    SessionSubject,
)

from . import skills

FENCE = "handler-result"  # the info string of the block holding the result
# a fenced block whose info string names it: ```json handler-result … ```
RESULT_BLOCK = re.compile(r"^```[^\n`]*\bhandler-result\b[^\n`]*\n(.*?)^```[ \t]*$", re.S | re.M)
MAX_ERRORS = 5  # validation errors told (to the agent, to the user)
# a field of the form named in an agent's instructions: {{key}}, filled in at the start
PLACEHOLDER = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")


RESULT_STATUSES = ("ok", "attention", "failed")  # a job's `status`, when it says how it went


class InterfaceError(ValueError):
    """An interface, or a run's input, is not valid."""


def check(interface: AgentInterface) -> None:
    """Its `fields` and `result` are JSON Schemas (draft 2020-12), `fields` one of an object
    with one skill field at most, a string; each at most MAX_SCHEMA_BYTES as JSON. A brief (no
    result) has its form."""
    for name, schema in (("fields", interface.fields), ("result", interface.result)):
        if schema is None:
            continue
        if len(json.dumps(schema)) > MAX_SCHEMA_BYTES:
            raise InterfaceError(f"{name}: larger than {MAX_SCHEMA_BYTES} bytes")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as e:
            raise InterfaceError(f"{name}: not a JSON Schema: {e.message}") from None
    if interface.fields is None and interface.result is None:
        raise InterfaceError("fields: a brief (no result) is its form")
    if interface.fields is not None and interface.fields.get("type") != "object":
        raise InterfaceError('fields: the schema of a form, "type": "object"')
    marked = [k for k, s in properties(interface.fields) if s.get("x-handler") == SKILL_FIELD]
    if len(marked) > 1:
        raise InterfaceError(f"fields: one skill field at most ({', '.join(marked)})")
    if marked and dict(properties(interface.fields))[marked[0]].get("type") != "string":
        raise InterfaceError(f'fields: {marked[0]}: a skill field is a string, "type": "string"')


def properties(schema: dict[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    """The properties of an object schema, those that are schemas."""
    props = (schema or {}).get("properties")
    if not isinstance(props, dict):
        return []
    return [(k, s) for k, s in props.items() if isinstance(s, dict)]


def skill_field(interface: AgentInterface) -> str | None:
    """The key of the form's skill field: its value names a skill of the library, the run's
    subject."""
    return next(
        (k for k, s in properties(interface.fields) if s.get("x-handler") == SKILL_FIELD), None
    )


def check_instructions(instructions: str | None, interface: AgentInterface | None) -> None:
    """Each `{{key}}` of the instructions names a field of the form (none without a form)."""
    keys = {k for k, _ in properties(interface.fields)} if interface is not None else set()
    for name in dict.fromkeys(PLACEHOLDER.findall(instructions or "")):
        if name not in keys:
            raise InterfaceError(f"instructions: {{{{{name}}}}} is not a field of its form")


def fill(instructions: str, fields: dict[str, Any]) -> str:
    """The instructions with each `{{key}}` replaced by that field's value: text as it is, a
    list joined by ", ", a number or yes/no as text, a field left empty: nothing."""

    def value(m: re.Match[str]) -> str:
        v = fields.get(m.group(1))
        if v is None:
            return ""
        if isinstance(v, bool):
            return "yes" if v else "no"
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return v if isinstance(v, str) else json.dumps(v)

    return PLACEHOLDER.sub(value, instructions)


def errors(schema: dict[str, Any], value: Any) -> list[str]:
    """Why `value` does not match `schema` (the first few reasons), [] when it does."""
    found = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.path))
    return [
        f"{'/'.join(str(p) for p in e.path) or '(top)'}: {e.message}" for e in found[:MAX_ERRORS]
    ]


def misfit(wanted: AgentInterface, interface: AgentInterface | None) -> str | None:
    """Why an agent with `interface` cannot be given for an app's need of a job with `wanted`
    (H.2), None when it fits: its form takes each field the app sends, of that type, and requires
    none the app may leave out; its result requires each field the app's requires, of that type.
    Properties, types and `required` only: not everything a JSON Schema can say."""
    if interface is None or interface.result is None:
        return "it is not a job"
    return _form_misfit(wanted.fields, interface.fields) or _result_misfit(
        wanted.result, interface.result
    )


def _kinds(schema: dict[str, Any] | None) -> tuple[dict[str, Any], set[str]]:
    """An object schema's properties with their `type`, and its required ones."""
    required = (schema or {}).get("required")
    types = {k: s.get("type") for k, s in properties(schema)}
    return types, set(required) if isinstance(required, list) else set()


def _form_misfit(sent: dict[str, Any] | None, takes: dict[str, Any] | None) -> str | None:
    sent_types, sent_required = _kinds(sent)
    takes_types, takes_required = _kinds(takes)
    for key, kind in sent_types.items():
        if key not in takes_types:
            return f"its form has no field {key}"
        if kind is not None and takes_types[key] != kind:
            return f"its form's {key} is not a {kind}"
    if extra := sorted(takes_required - sent_required):
        return f"its form requires {', '.join(extra)}, which the app may leave out"
    return None


def _result_misfit(read: dict[str, Any] | None, gives: dict[str, Any] | None) -> str | None:
    read_types, read_required = _kinds(read)
    gives_types, gives_required = _kinds(gives)
    for key in sorted(read_required):
        if key not in gives_required:
            return f"its result does not always give {key}"
        if read_types.get(key) is not None and gives_types.get(key) != read_types[key]:
            return f"its result's {key} is not a {read_types[key]}"
    return None


def check_input(
    interface: AgentInterface, given: SessionInput, skills_dir: Path
) -> SessionSubject | None:
    """A run's input, checked against the interface: its fields against `fields`, the skill its
    skill field names (when given) usable. Returns that skill with its digest: what the run
    works on, and sees."""
    if interface.fields is not None and (found := errors(interface.fields, given.fields)):
        raise InterfaceError("; ".join(found))
    if interface.fields is None and given.fields:
        raise InterfaceError("this agent takes no fields")
    key = skill_field(interface)
    name = given.fields.get(key) if key else None
    if not name:
        return None
    skill = skills.get(skills_dir, name)
    if skill.error:
        raise InterfaceError(f"{key}: skill '{skill.name}': {skill.error}")
    return SessionSubject(skill=skill.name, digest=skills.digest(skill.path))


def subject_path(subject: SessionSubject) -> str:
    """Where the run sees its subject."""
    return f"{SUBJECT_ROOT}/{subject.skill}"


def subject_mount(skills_dir: Path, subject: SessionSubject) -> Mount:
    """The subject, read-only: the run reads it, never changes it. SkillError when it is gone."""
    skill = skills.get(skills_dir, subject.skill)
    if skill.error:
        raise skills.SkillError(f"skill '{subject.skill}': {skill.error}")
    return Mount(
        source=str(skill.path.resolve()),
        target=subject_path(subject),
        read_only=True,
        kind="subject",
    )


def request(
    instructions: str | None,
    interface: AgentInterface,
    given: SessionInput,
    subject: SessionSubject | None = None,
    subject_notes: str | None = None,
) -> str:
    """The request a session started from the form begins with: what the agent is for (its
    instructions, the form's values in them), what it is given (every value, as JSON), and for a
    job's run, how to give its result back."""
    text = fill(instructions, given.fields).strip() if instructions else ""
    parts = [text] if text else []
    if given.fields:
        parts.append("## Input\n\n```json\n" + json.dumps(given.fields, indent=2) + "\n```")
    if subject is not None:
        where = subject_path(subject)
        text = (
            f"## Subject\n\nThe skill `{subject.skill}` is in `{where}` (read-only). "
            f"Paths in your result are relative to that folder."
        )
        parts.append(text + (f"\n\n{subject_notes}" if subject_notes else ""))
    if interface.result is None:  # a brief: a chat goes on from there
        return "\n\n".join(parts)
    parts.append(
        "## Result\n\nWhen you are done, end your final message with one fenced code block whose "
        f"info string is `json {FENCE}`, holding one JSON value valid against this JSON Schema, "
        "and nothing after it:\n\n```json\n" + json.dumps(interface.result, indent=2) + "\n```"
    )
    return "\n\n".join(parts)


def parse(answer: str | None, schema: dict[str, Any]) -> SessionOutput:
    """The result in the final message: its last `handler-result` block, checked against
    `schema`."""
    blocks = RESULT_BLOCK.findall(answer or "")
    if not blocks:
        return SessionOutput(valid=False, error=f"no `{FENCE}` block in the final message")
    try:
        value = json.loads(blocks[-1])
    except ValueError as e:
        return SessionOutput(valid=False, error=f"the `{FENCE}` block is not JSON: {e}")
    if found := errors(schema, value):
        return SessionOutput(valid=False, value=value, error="; ".join(found))
    return SessionOutput(valid=True, value=value)


def repair(output: SessionOutput) -> str:
    """The turn sent once when the result is missing or invalid."""
    return (
        f"Your result could not be used: {output.error}. Give it again: end your message with one "
        f"fenced code block whose info string is `json {FENCE}`, valid against the schema given "
        "at the start."
    )


def result_problems(schema: dict[str, Any]) -> list[str]:
    """A job run by an automation (I.3) or for an app's ask (H.12) gives a result its inbox message
    and its answer are made of: required `status` (some of ok, attention, failed) and `summary`
    (a string)."""
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    found = []
    status = props.get("status") or {}
    if "status" not in required or not status.get("enum"):
        found.append("its result has no required 'status' enum (ok, attention, failed)")
    elif unknown := [v for v in status["enum"] if v not in RESULT_STATUSES]:
        found.append(f"its result's status has {unknown}: only ok, attention, failed")
    if "summary" not in required or (props.get("summary") or {}).get("type") != "string":
        found.append("its result has no required 'summary' string")
    return found
