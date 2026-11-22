"""The validator (SMD spec 4, 5.1, 6): a parsed document checked against its schema. Pure.

It returns the same document, typed: each declared field's value coerced (spec 4), each section
under the schema's key (its heading or an alias). A value that does not coerce stays the text it
was, so nothing is lost; the diagnostic says why.
"""

import re
from collections.abc import Callable
from datetime import date, datetime

from handler_smd.models import (
    Diagnostic,
    Document,
    Entry,
    FieldValue,
    Item,
    Section,
    Severity,
    field_text,
)
from handler_smd.parser import section_key, slug
from handler_smd.schema import EntriesDef, FieldDef, ItemDef, LeadDef, TypeDefinition

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# ISO 8601 with a timezone, `T` between the date and the time (spec 4)
DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")
TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")  # local, 24 h (spec 13.2)
DURATION = re.compile(r"^(?:(\d+)h(?:([0-5]?\d)m?)?|(\d+)m)$")  # 1h, 1h30, 1h30m, 45m
LEAD = re.compile(r"^(\S+)(?:\s+(.*))?$")
TAG = re.compile(r"(?:^|\s)#([A-Za-z0-9_:/-]+)\s*$")  # the last `#word` of a text (13.3)
# `#item-slug`, `other.md`, or `other.md#item-slug`; whether it exists is the scanner's
REF = re.compile(r"^(?=.)(?:[^\s#]+\.md)?(?:#[^\s#]+)?$")
# report(line, where in the item, severity, code, message)
_Report = Callable[[int, str, Severity, str, str], None]
NOTE = re.compile(r"^[-*+][ \t]+(.+)$")
REVIEW_NOTES = "review_notes"  # a section's key no schema needs to declare (spec 6, 7)
UNKNOWN: dict[str, Severity] = {
    "allow": Severity.INFO,
    "warn": Severity.WARNING,
    "forbid": Severity.ERROR,
}
MISSING: dict[str, Severity] = {
    "error": Severity.ERROR,
    "warning": Severity.WARNING,
    "info": Severity.INFO,
}


class _InvalidError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate(
    document: Document, typedef: TypeDefinition, file: str
) -> tuple[Document, list[Diagnostic]]:
    found: list[Diagnostic] = []
    items = [
        _item(item, f"items[{index}]", typedef.item, file, found)
        for index, item in enumerate(document.items)
    ]
    found.sort(key=lambda d: (d.file, d.line, d.path))
    return document.model_copy(update={"items": items}), found


def _item(item: Item, path: str, schema: ItemDef, file: str, found: list[Diagnostic]) -> Item:
    def report(line: int, where: str, severity: Severity, code: str, message: str) -> None:
        found.append(
            Diagnostic(
                file=file,
                line=line,
                path=f"{path}.{where}",
                severity=severity,
                code=code,
                message=message,
            )
        )

    lenient = schema.lenient_when is not None and (
        item.fields.get(schema.lenient_when.field) in schema.lenient_when.values
    )

    def missing(where: str, code: str, level: str, message: str) -> None:
        if (severity := MISSING.get(level)) is not None:
            if lenient and severity == Severity.ERROR:
                severity = Severity.WARNING
            report(item.line, where, severity, code, message)

    given = dict(item.fields)
    if schema.title_lead is not None:
        where = "fields"
        _read_lead(item.title, schema.title_lead, given, line=item.line, where=where, report=report)
    fields = _fields(
        given,
        field_lines=item.field_lines,
        line_of_owner=item.line,
        definitions=schema.all_fields(),
        schema=schema,
        report=report,
        missing=missing,
    )

    entries = item.entries
    if schema.entries is not None and item.body is not None:
        report(
            item.line,
            "body",
            Severity.WARNING,
            "not-entries",
            "its body is expected to be a list (one `- ` line each), and is not: kept as it is",
        )
    if entries is not None:
        entries = _entries(entries, schema, report)

    sections = _sections(item, schema, report)
    for key, definition in schema.sections.items():
        if key not in sections:
            message = _described(
                f"the section '{definition.heading}' is missing", definition.description
            )
            missing(f"sections.{key}", "missing-required-section", definition.missing, message)
    return item.model_copy(update={"fields": fields, "entries": entries, "sections": sections})


def _fields(
    given: dict[str, FieldValue],
    *,
    field_lines: dict[str, int],
    line_of_owner: int,
    definitions: dict[str, FieldDef],
    schema: ItemDef | EntriesDef,
    report: _Report,
    missing: Callable[[str, str, str, str], None],
    prefix: str = "",
) -> dict[str, FieldValue]:
    """Fields typed as their definitions say; the unknown and the missing reported."""
    fields: dict[str, FieldValue] = {}
    for key, value in given.items():
        line = field_lines.get(key, line_of_owner)
        definition = definitions.get(key)
        if value is not None and "\n" in field_text(value):
            # never from a file; from an agent's JSON: a field is one line (spec 3.1)
            report(
                line,
                f"{prefix}fields.{key}",
                Severity.ERROR,
                "invalid-type",
                f"{key} is one line: longer text goes into a section",
            )
        if definition is None:
            report(
                line,
                f"{prefix}fields.{key}",
                UNKNOWN[schema.additional_fields],
                "unknown-field",
                f"{key} is not a field of this schema",
            )
            fields[key] = value
        elif value is None:
            fields[key] = None
        else:
            try:
                fields[key] = _coerce(key, field_text(value), definition)
            except _InvalidError as invalid:
                report(line, f"{prefix}fields.{key}", Severity.ERROR, invalid.code, str(invalid))
                fields[key] = field_text(value)
    for key, definition in definitions.items():
        if given.get(key) is None:
            message = _described(f"{key} is missing", definition.description)
            missing(f"{prefix}fields.{key}", "missing-required-field", definition.missing, message)
    return fields


def _entries(entries: list[Entry], schema: ItemDef, report: _Report) -> list[Entry]:
    """Each entry checked against the schema's `entries` (spec 13.3): its checkbox, its lead and
    tags taken out of its text (once parsed: an entry with a `title` already has them as
    fields), its fields typed. Without `entries` in the schema, its fields are unknown."""
    definition = schema.entries or EntriesDef(additional_fields=schema.additional_fields)
    definitions = definition.all_fields()
    typed: list[Entry] = []
    seen: dict[str, int] = {}
    for index, entry in enumerate(entries):
        prefix = f"entries[{index}]."

        def missing(
            where: str, code: str, level: str, message: str, line: int = entry.line
        ) -> None:
            if (severity := MISSING.get(level)) is not None:
                report(line, where, severity, code, message)

        if definition.checkbox == "require" and entry.checked is None:
            report(
                entry.line,
                f"{prefix}checked",
                Severity.ERROR,
                "invalid-checkbox",
                "each line of this list starts with a checkbox, `- [ ] ` (or `- [x] `)",
            )
        elif definition.checkbox == "forbid" and entry.checked is not None:
            report(
                entry.line,
                f"{prefix}checked",
                Severity.ERROR,
                "invalid-checkbox",
                "the lines of this list have no checkbox",
            )
        given = dict(entry.fields)
        title = entry.title
        if title is None and schema.entries is not None:
            title = entry.text
            where = f"{prefix}fields"
            if definition.lead is not None:
                title = _read_lead(
                    title, definition.lead, given, line=entry.line, where=where, report=report
                )
            if definition.tags is not None:
                title = _read_tags(
                    title, definition.tags.field, given, line=entry.line, where=where, report=report
                )
        fields = _fields(
            given,
            field_lines=entry.field_lines,
            line_of_owner=entry.line,
            definitions=definitions,
            schema=definition,
            report=report,
            missing=missing,
            prefix=prefix,
        )
        update: dict[str, object] = {"fields": fields}
        if title is not None:
            base = slug(title)
            seen[base] = seen.get(base, 0) + 1
            update |= {"title": title, "slug": base if seen[base] == 1 else f"{base}-{seen[base]}"}
        typed.append(entry.model_copy(update=update))
    return typed


def lead_text(text: str, kind: str) -> tuple[str | None, str]:
    """The value `text` starts with, as its type writes it, and the rest; (None, text) when it
    starts with none (spec 13.3: never an error)."""
    match = LEAD.match(text.strip())
    if match is None:
        return None, text
    try:
        value = _scalar("lead", match.group(1), kind, None)
    except _InvalidError:
        return None, text
    return field_text(value), (match.group(2) or "").strip()


def tags_text(text: str) -> tuple[list[str], str]:
    """The `#word`s at the end of `text`, in order, and the text before them."""
    tags: list[str] = []
    while match := TAG.search(text):
        tags.insert(0, match.group(1))
        text = text[: match.start()].rstrip()
    return tags, text


def _read_lead(
    text: str,
    lead: LeadDef,
    given: dict[str, FieldValue],
    *,
    line: int,
    where: str,
    report: _Report,
) -> str:
    value, rest = lead_text(text, lead.type)
    if value is not None:
        _give(lead.field, value, given, line=line, where=where, report=report)
        return rest
    return text


def _read_tags(
    text: str, field: str, given: dict[str, FieldValue], *, line: int, where: str, report: _Report
) -> str:
    tags, rest = tags_text(text)
    if tags:
        _give(field, ", ".join(tags), given, line=line, where=where, report=report)
    return rest


def _give(
    key: str, value: str, given: dict[str, FieldValue], *, line: int, where: str, report: _Report
) -> None:
    """A value read from a line, unless a field line gives another one: it wins (spec 13.3)."""
    written = given.get(key)
    if written is None:
        given[key] = value
    elif field_text(written) != value:
        report(
            line,
            f"{where}.{key}",
            Severity.WARNING,
            "duplicate-field",
            f"'{key}' is given in the line and as a field: the field is kept",
        )


def _sections(item: Item, schema: ItemDef, report: _Report) -> dict[str, Section]:
    """The item's sections under the schema's keys; the others under the parser's, never one of
    the schema's."""
    by_heading = {
        section_key(heading): key
        for key, definition in schema.sections.items()
        for heading in [definition.heading, *definition.aliases]
    }
    sections: dict[str, Section] = {}
    read_as: dict[str, str] = {}  # a key given → the heading key that took it
    for parsed_key, section in item.sections.items():
        heading_key = section_key(section.heading)
        known = by_heading.get(heading_key)
        if known is None:
            key = _free(parsed_key, sections, schema)
            if heading_key == REVIEW_NOTES:
                for note in _notes(section.content):
                    report(section.line, f"sections.{key}", Severity.INFO, "review-note", note)
            else:
                report(
                    section.line,
                    f"sections.{key}",
                    UNKNOWN[schema.additional_sections],
                    "unknown-section",
                    f"'{section.heading}' is not a section of this schema",
                )
        elif known not in sections:
            key = known
        elif read_as[known] == heading_key:
            key = _free(parsed_key, sections, schema)  # the same heading again: the parser said so
        else:
            key = _free(known, sections, schema)
            report(
                section.line,
                f"sections.{key}",
                Severity.WARNING,
                "duplicate-section",
                f"'{section.heading}' is also the section {known}: kept as '{key}'",
            )
        read_as[key] = heading_key
        sections[key] = section
    return sections


def _free(key: str, taken: dict[str, Section], schema: ItemDef) -> str:
    """`key`, or `key_2`, `key_3`… : the first that is neither taken nor one of the schema's."""
    base, n = key, 1
    while key in taken or key in schema.sections:
        n += 1
        key = f"{base}_{n}"
    return key


def _notes(content: str) -> list[str]:
    return [m.group(1).strip() for line in content.splitlines() if (m := NOTE.match(line))]


def _described(message: str, description: str) -> str:
    return f"{message} ({description})" if description else message


def _coerce(key: str, value: str, definition: FieldDef) -> FieldValue:
    if definition.type != "list":
        return _scalar(key, value, definition.type, definition.values)
    entries = [entry.strip() for entry in value.split(",")]
    if not all(entries):
        raise _InvalidError("invalid-type", f"{key} is a list, `a, b, c`, with no empty entry")
    assert definition.of is not None  # the schema says what a list is of
    return [_scalar(key, entry, definition.of, definition.values) for entry in entries]


def _scalar(key: str, value: str, kind: str, values: list[str] | None) -> str | date | datetime:
    match kind:
        case "enum":
            assert values is not None  # the schema gives an enum its values
            if value not in values:
                raise _InvalidError(
                    "invalid-enum", f"{key} must be one of: {', '.join(values)} (got '{value}')"
                )
            return value
        case "date":
            try:
                if DATE.match(value):
                    return date.fromisoformat(value)
            except ValueError:
                pass
            raise _InvalidError("invalid-date", f"{key} is a date, YYYY-MM-DD (got '{value}')")
        case "datetime":
            try:
                if DATETIME.match(value):
                    return datetime.fromisoformat(value)
            except ValueError:
                pass
            raise _InvalidError(
                "invalid-datetime",
                f"{key} is a date and time with its timezone, "
                f"such as 2026-11-10T14:30:00+01:00 (got '{value}')",
            )
        case "time" | "time-range" | "duration":
            return _clock(key, value, kind)
        case "ref":
            if not REF.match(value):
                raise _InvalidError(
                    "invalid-ref",
                    f"{key} is `#item-slug`, `other.md` or `other.md#item-slug` (got '{value}')",
                )
            return value
        case _:
            return value


def _clock(key: str, value: str, kind: str) -> str:
    """A time, a time range or a duration, as the renderer writes it (spec 13.2)."""
    if kind == "duration":
        if not (m := DURATION.match(value)):
            raise _InvalidError(
                "invalid-duration", f"{key} is a duration: 1h, 1h30 or 45m (got '{value}')"
            )
        if m.group(3) is not None:
            return f"{int(m.group(3))}m"
        minutes = int(m.group(2) or 0)
        return f"{int(m.group(1))}h{minutes:02d}" if minutes else f"{int(m.group(1))}h"
    start, dash, end = value.partition("-")
    first, last = TIME.match(start.strip()), TIME.match(end.strip())
    if first is None or (dash and (kind == "time" or last is None)):
        expected = "a time, HH:MM" if kind == "time" else "a time or two, HH:MM or HH:MM-HH:MM"
        raise _InvalidError("invalid-time", f"{key} is {expected} (got '{value}')")
    text = f"{int(first.group(1)):02d}:{first.group(2)}"
    return f"{text}-{int(last.group(1)):02d}:{last.group(2)}" if last else text
