"""Agent interfaces (D.18): what a run of an agent takes (a form, a handler object to work on) and
gives back (data of a known shape, in its final message). An agent with one runs unattended.

    check            an interface's schemas: JSON Schemas (draft 2020-12), the form an object
    check_input      a run's input against its agent's interface, the subject's digest set
    subject_mount    the subject, mounted read-only at /subject/<name>
    request          the run's one request: instructions, input, subject, the rule for the result
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


class InterfaceError(ValueError):
    """An interface, or a run's input, is not valid."""


def check(interface: AgentInterface) -> None:
    """Its `fields` and `result` are JSON Schemas (draft 2020-12), `fields` one of an object;
    each at most MAX_SCHEMA_BYTES as JSON."""
    for name, schema in (("fields", interface.fields), ("result", interface.result)):
        if schema is None:
            continue
        if len(json.dumps(schema)) > MAX_SCHEMA_BYTES:
            raise InterfaceError(f"{name}: larger than {MAX_SCHEMA_BYTES} bytes")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as e:
            raise InterfaceError(f"{name}: not a JSON Schema: {e.message}") from None
    if interface.fields is not None and interface.fields.get("type") != "object":
        raise InterfaceError('fields: the schema of a form, "type": "object"')


def errors(schema: dict[str, Any], value: Any) -> list[str]:
    """Why `value` does not match `schema` (the first few reasons), [] when it does."""
    found = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.path))
    return [
        f"{'/'.join(str(p) for p in e.path) or '(top)'}: {e.message}" for e in found[:MAX_ERRORS]
    ]


def check_input(interface: AgentInterface, given: SessionInput, skills_dir: Path) -> SessionInput:
    """A run's input, checked against the interface: its fields against `fields`, a subject
    when (and only when) the interface takes one, and that subject usable. Returned with the
    subject's digest: what the run sees."""
    if interface.fields is not None and (found := errors(interface.fields, given.fields)):
        raise InterfaceError("; ".join(found))
    if interface.fields is None and given.fields:
        raise InterfaceError("this agent takes no fields")
    if (interface.subject is None) != (given.subject is None):
        wanted = f"a {interface.subject}" if interface.subject else "none"
        raise InterfaceError(f"subject: this agent takes {wanted}")
    if given.subject is None:
        return given
    skill = skills.get(skills_dir, given.subject.skill)
    if skill.error:
        raise InterfaceError(f"skill '{skill.name}': {skill.error}")
    subject = SessionSubject(skill=skill.name, digest=skills.digest(skill.path))
    return given.model_copy(update={"subject": subject})


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
    subject_notes: str | None = None,
) -> str:
    """The one request a run starts with: what the agent is for, what it is given, and how to
    give its result back."""
    parts = [instructions.strip()] if instructions and instructions.strip() else []
    if given.fields:
        parts.append("## Input\n\n```json\n" + json.dumps(given.fields, indent=2) + "\n```")
    if given.subject is not None:
        where = subject_path(given.subject)
        text = (
            f"## Subject\n\nThe skill `{given.subject.skill}` is in `{where}` (read-only). "
            f"Paths in your result are relative to that folder."
        )
        parts.append(text + (f"\n\n{subject_notes}" if subject_notes else ""))
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
