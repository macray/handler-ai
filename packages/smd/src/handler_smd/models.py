"""The parsed document and the diagnostics (SMD spec 3.2, 6): plain data, no behaviour."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Diagnostic(Model):
    """One problem found in a document: never stored in it, computed on every scan (spec 6)."""

    file: str
    line: int  # 1-based, in the file as written
    path: str  # where in the model: "title", "meta", "items[1].fields.status"
    severity: Severity
    code: str  # stable, kebab-case
    message: str


# a field's value: the text as written (always, once parsed), or its type's once validated
FieldValue = str | date | datetime | list[str | date | datetime] | None


def field_text(value: str | date | datetime | list[str | date | datetime]) -> str:
    """A value as a document writes it (spec 7.5): what the validator checks, whatever came in
    (text parsed, or values typed by an agent's JSON or a validation before), and what the
    renderer writes."""
    if isinstance(value, list):
        return ", ".join(field_text(entry) for entry in value)
    return value if isinstance(value, str) else value.isoformat()


class Section(Model):
    """An H3 of an item: its heading as written, its content as raw markdown, trimmed."""

    heading: str
    line: int = 0  # 0: not from a file (an agent's JSON)
    content: str


class Entry(Model):
    """A bullet of an item's list (spec 13): its checkbox, its line's text, its fields (the
    indented `key: value` lines under it), its notes. `title` is None once parsed; the validator
    gives it, the text without the lead and the tags its schema reads (13.3)."""

    text: str = ""  # its line as written, after the bullet and the checkbox
    title: str | None = None
    slug: str = ""
    line: int = 0
    checked: bool | None = None  # `[ ]` False, `[x]` True, no checkbox None
    fields: dict[str, FieldValue] = {}
    field_lines: dict[str, int] = {}
    notes: str | None = None


class Item(Model):
    """An H2: the repeatable unit. Field values are the text as written (or None) once parsed,
    coerced to their types once validated (spec 4)."""

    title: str
    # the defaults: what an agent writing JSON leaves out; the parser always gives them
    slug: str = ""
    line: int = 0
    fields: dict[str, FieldValue] = {}
    field_lines: dict[str, int] = {}
    body: str | None = None
    entries: list[Entry] | None = None  # its body when it is only a bullet list (spec 13.1)
    sections: dict[str, Section] = {}


class Document(Model):
    meta: dict[str, Any] = {}  # the frontmatter, as YAML read it
    title: str | None = None
    preamble: str | None = None
    items: list[Item] = []


class ParseResult(Model):
    document: Document
    diagnostics: list[Diagnostic]
