"""Agent support (SMD spec 8): a schema as an agent reads it. Pure.

`to_json_schema`: the JSON an agent writes for a document of that schema; `template`: a blank
document, the schema's descriptions as hints; `prompt`: the instructions an agent follows to
turn text into a document of that schema, or to edit one.
"""

import json
from typing import Any

from handler_smd.models import Document, Entry, Item, Section
from handler_smd.renderer import render
from handler_smd.schema import EntriesDef, FieldDef, SectionDef, TypeDefinition
from handler_smd.validator import REF, REVIEW_NOTES

NULL = {"type": "null"}
CLOCK = {  # as an agent may write them; the validator writes them back its way (spec 13.2)
    "time": r"^([01]?\d|2[0-3]):[0-5]\d$",
    "time-range": r"^([01]?\d|2[0-3]):[0-5]\d(-([01]?\d|2[0-3]):[0-5]\d)?$",
    "duration": r"^(\d+h([0-5]?\dm?)?|\d+m)$",
}
TEXT_OR_NULL = {"type": ["string", "null"]}


def to_json_schema(typedef: TypeDefinition) -> dict[str, Any]:
    """The document's JSON (the parsed model, spec 3.2) as JSON Schema 2020-12. Every field may
    be null (not known: never invented, spec 8); those whose absence is an error or a warning
    are required keys, so the agent writes null rather than leaving them out."""
    item = typedef.item
    fields = _fields(item.all_fields(), item.additional_fields)
    section_object = {
        "type": "object",
        "properties": {
            "heading": {"type": "string"},
            "line": {"type": "integer"},
            "content": {"type": "string"},
        },
        "required": ["heading", "content"],
        "additionalProperties": False,
    }
    sections = {
        "type": "object",
        "properties": {k: _section(s, section_object) for k, s in item.sections.items()},
        "additionalProperties": False if item.additional_sections == "forbid" else section_object,
    }
    if item.additional_sections == "forbid":
        sections["properties"][REVIEW_NOTES] = section_object
    item_schema = {
        "type": "object",
        "description": item.description,
        "properties": {
            "title": {"type": "string"},
            "slug": {"type": "string"},
            "line": {"type": "integer"},
            "fields": fields,
            "field_lines": {"type": "object", "additionalProperties": {"type": "integer"}},
            "body": TEXT_OR_NULL,
            "entries": _entries(item.entries, item.additional_fields),
            "sections": sections,
        },
        "required": ["title"],
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": typedef.title,
        "description": typedef.description,
        "type": "object",
        "properties": {
            "meta": {
                "type": "object",
                "properties": {"schema": {"const": typedef.id}},
                "required": ["schema"],
            },
            "title": {"type": "string"},
            "preamble": TEXT_OR_NULL,
            "items": {"type": "array", "items": item_schema},
        },
        "required": ["meta", "title", "items"],
        "additionalProperties": False,
    }


def _fields(definitions: dict[str, FieldDef], additional: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {k: _field(f) for k, f in definitions.items()},
        "required": [k for k, f in definitions.items() if f.missing in ("error", "warning")],
        "additionalProperties": False if additional == "forbid" else TEXT_OR_NULL,
    }


def _entries(definition: EntriesDef | None, additional: str) -> dict[str, Any]:
    """An item's bullets (spec 13): `title` and the fields; `text` is what the parser read, and
    the renderer builds the line from `title`, the lead and the tags."""
    checked: dict[str, Any] = {"type": ["boolean", "null"]}
    if definition is not None and definition.checkbox == "require":
        checked = {"type": "boolean"}
    elif definition is not None and definition.checkbox == "forbid":
        checked = NULL
    entry = {
        "type": "object",
        "description": definition.description if definition else "",
        "properties": {
            "title": {"type": "string"},
            "text": {"type": "string"},
            "slug": {"type": "string"},
            "line": {"type": "integer"},
            "checked": checked,
            "fields": _fields(
                definition.all_fields() if definition else {},
                definition.additional_fields if definition else additional,
            ),
            "field_lines": {"type": "object", "additionalProperties": {"type": "integer"}},
            "notes": TEXT_OR_NULL,
        },
        "required": ["title"],
        "additionalProperties": False,
    }
    return {"anyOf": [{"type": "array", "items": entry}, NULL]}


def _scalar(kind: str, values: list[str] | None) -> dict[str, Any]:
    match kind:
        case "enum":
            return {"enum": values}
        case "date":
            return {"type": "string", "format": "date"}
        case "datetime":
            return {"type": "string", "format": "date-time"}
        case "ref":
            return {"type": "string", "pattern": REF.pattern}
        case "time" | "time-range" | "duration":
            return {"type": "string", "pattern": CLOCK[kind]}
        case _:
            return {"type": "string"}


def _field(definition: FieldDef) -> dict[str, Any]:
    if definition.type == "list":
        assert definition.of is not None
        entries = _scalar(definition.of, definition.values)
        # an array, or the text a document holds (`a, b`), as `handler-smd parse` gives it
        kinds = [{"type": "array", "items": entries, "minItems": 1}, {"type": "string"}, NULL]
    else:
        kinds = [_scalar(definition.type, definition.values), NULL]
    return {"anyOf": kinds, "description": definition.description}


def _section(definition: SectionDef, section_object: dict[str, Any]) -> dict[str, Any]:
    return {**section_object, "description": definition.description}


def _kind(definition: FieldDef) -> str:
    if definition.type == "list":
        assert definition.of is not None
        of = (
            "text"
            if definition.of == "string"
            else _kind(FieldDef(type=definition.of, values=definition.values))
        )
        return f"a list written `a, b, c`, each {of}"
    if definition.type == "enum":
        return f"one of: {', '.join(definition.values or [])}"
    return KINDS.get(definition.type, "text, one line")


KINDS = {
    "date": "a date, YYYY-MM-DD",
    "datetime": "a date and time with its timezone, such as 2026-11-10T14:30:00+01:00",
    "ref": "a reference: #item-slug, other.md or other.md#item-slug",
    "time": "a time, HH:MM",
    "time-range": "a time or two, HH:MM or HH:MM-HH:MM",
    "duration": "a duration: 1h, 1h30 or 45m",
}


NEED = {"error": "required", "warning": "expected", "info": "optional", "none": "optional"}


def _field_hint(key: str, definition: FieldDef) -> str:
    about = f" {definition.description}" if definition.description else ""
    return f"{key}: {_kind(definition)}; {NEED[definition.missing]}.{about}"


def _section_hint(definition: SectionDef) -> str:
    also = f" Also read: {', '.join(definition.aliases)}." if definition.aliases else ""
    return f"{NEED[definition.missing].capitalize()}.{also} {definition.description}".strip()


def template(typedef: TypeDefinition) -> str:
    """A blank document of the schema, canonical: one item, its fields empty, the descriptions
    as HTML comments (an editor shows them; a field block cannot hold them)."""
    item = typedef.item
    hints = [item.description] if item.description else []
    hints += [_field_hint(k, f) for k, f in item.all_fields().items()]
    entries = None
    if item.entries is not None:
        # the item's body is its list: the hints go before the first item
        hints += [_entries_hint(item.entries)]
        hints += [f"Each line's {_field_hint(k, f)}" for k, f in item.entries.all_fields().items()]
        checkbox = None if item.entries.checkbox != "require" else False
        entries = [Entry(title="The first line", checked=checkbox)]
    blank = Item(
        title="The first item's title",
        fields=dict.fromkeys(item.fields),
        body=_comment(hints) if hints and entries is None else None,
        entries=entries,
        sections={
            k: Section(heading=s.heading, content=_comment([_section_hint(s)]))
            for k, s in item.sections.items()
        },
    )
    preamble = [typedef.description] if typedef.description else []
    if entries is not None:
        preamble += hints
    document = Document(
        meta={"schema": typedef.id},
        title=typedef.title,
        preamble=_comment(preamble) if preamble else None,
        items=[blank],
    )
    return render(document, typedef)


def _entries_hint(definition: EntriesDef) -> str:
    box = {
        "allow": "`- [ ] ` (a checkbox) or `- `",
        "require": "a checkbox, `- [ ] ` (`- [x] ` once done)",
        "forbid": "`- `, no checkbox",
    }[definition.checkbox]
    parts = [f"The item's body is a list: one line each, starting with {box}."]
    if definition.lead is not None:
        parts.append(
            f"A line may start with its {definition.lead.field} ({_kind(definition.lead.as_field())})."
        )
    if definition.tags is not None:
        parts.append(f"It may end with #words: its {definition.tags.field}.")
    parts.append("Its other fields: `key: value` lines indented under it; then its notes.")
    if definition.description:
        parts.append(definition.description)
    return " ".join(parts)


def _comment(lines: list[str]) -> str:
    return "<!--\n" + "\n".join(line.replace("--", "—") for line in lines) + "\n-->"


def prompt(typedef: TypeDefinition) -> str:
    """The instructions for an agent writing or editing documents of this schema (spec 8)."""
    item = typedef.item
    sections = (
        "\n".join(
            f"- `{k}`: `### {s.heading}`. {_section_hint(s)}" for k, s in item.sections.items()
        )
        or "- none"
    )
    fields = "\n".join(f"- {_field_hint(k, f)}" for k, f in item.all_fields().items()) or "- none"
    if item.title_lead is not None:
        fields += (
            f"\n\nAn item's title may start with its {item.title_lead.field} "
            f"(`## 2026-11-19 · Thursday`): give it as that field, and write the title with it."
        )
    if item.entries is not None:
        entry_fields = "\n".join(
            f"- {_field_hint(k, f)}" for k, f in item.entries.all_fields().items()
        )
        fields += (
            f"\n\nIts `entries` (its body, a list): {_entries_hint(item.entries)} In JSON, an "
            "entry is its `checked` (true, false, or null for no checkbox), its `title` without "
            "the start value and the #words (they are its fields), its `fields`, its `notes`. "
            f"Fields:\n{entry_fields or '- none'}"
        )
    lenient = ""
    if item.lenient_when is not None:
        lenient = (
            f"\nAn item whose `{item.lenient_when.field}` is "
            f"{' or '.join(item.lenient_when.values)} is a draft: what it lacks is a warning, "
            "not an error.\n"
        )
    other_fields = {"allow": "allowed", "warn": "allowed, with a warning", "forbid": "refused"}
    schema_text = json.dumps(to_json_schema(typedef), indent=2)
    return f"""# Writing `{typedef.id}` documents: {typedef.title}

{typedef.description}

A document of this kind is a markdown file. Do not write the markdown yourself: write the
document as JSON, and `handler-smd write <file>` turns it into the file's canonical markdown,
then checks it and prints what is wrong.

## Rules

1. Write JSON that matches the JSON Schema below: `meta.schema` is `{typedef.id}`, then the
   document's `title`, an optional `preamble`, and its `items`. An item has a `title`, its
   `fields` (each value one line), an optional `body` (markdown), and its `sections` (each a
   `heading` and its markdown `content`), keyed as below.
2. Never invent a value. A value your source does not give is `null`: the check then reports
   it, and the document stays to be completed.
3. Discard nothing. What fits no field goes into a field of your own (one line), the item's
   `body`, or a section of your own. Here, fields of your own are
   {other_fields[item.additional_fields]}; sections of your own are
   {other_fields[item.additional_sections]}.
4. When you inferred something (a date from "last Tuesday", an owner from a signature), say
   so in the item's section `review_notes`, heading `Review notes` (`### Review notes`), one
   markdown list item per guess: the check shows each to the person.
5. Long text goes into a section, never into a field.

## An item of this kind

{item.description}

Fields:
{fields}

Sections:
{sections}
{lenient}
## Commands

- `handler-smd write <file>`, the JSON on its standard input: writes the file, prints its
  problems (exit 1 when one is an error; the file is written all the same).
- `handler-smd parse <file>`: a document as JSON. To edit one: parse it, change the JSON, write
  it back; everything you did not change stays as it was.
- `handler-smd check <file or folder>`: every problem, in every document.
- `handler-smd schema template {typedef.id}`: a blank document, for a person.

## The JSON Schema

```json
{schema_text}
```
"""
