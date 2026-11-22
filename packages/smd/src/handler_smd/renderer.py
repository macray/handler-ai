"""The renderer (SMD spec 7): a document to its one canonical markdown. Pure, deterministic:
diffs stay clean, and an agent writing JSON cannot reformat a file.

The frontmatter a file already has (`keep`) is written back as it is when the document's fields
are those it holds (spec 7.1): its comments, layout and order stay. Changed fields write it again,
refused when that would lose what it holds beyond them (`FrontmatterKeptError`). The whole
behaviour, its cases and where each part lives: rule `smd.frontmatter-kept-as-written` (the map's
knowledge page); change it there first.

Given the schema, fields and sections follow its order and a known section is written under the
schema's heading (the validator keys sections by the schema); unknown ones follow, as they were.
"""

from typing import Any

import yaml
from pydantic_core import to_jsonable_python

from handler_smd.models import Document, Entry, FieldValue, Item, Section, field_text
from handler_smd.parser import (
    CHECKBOX,
    FIELD,
    closed_fences,
    frontmatter_meta,
    section_key,
    unwritable,
)
from handler_smd.schema import EntriesDef, ItemDef, TypeDefinition
from handler_smd.validator import REVIEW_NOTES, lead_text  # review notes: the last section (7.7)


class FrontmatterKeptError(ValueError):
    """The fields changed, and the frontmatter as written holds more than they say."""


def render(
    document: Document, typedef: TypeDefinition | None = None, keep: str | None = None
) -> str:
    """`keep`: the frontmatter the file has now, as written (`parser.frontmatter_block`)."""
    schema = typedef.item if typedef is not None else None
    blocks: list[str] = []
    if keep is not None:
        blocks.append(_kept(keep, document.meta))
    elif document.meta:
        blocks.append(_frontmatter(document.meta))
    elif document.title is None and (document.preamble or "").split("\n")[0].rstrip() == "---":
        blocks.append("---\n---")  # an empty frontmatter: else that rule would open one
    if document.title is not None:
        blocks.append(f"# {_one_line(document.title, 'the title')}")
    if document.preamble:
        blocks.append(closed_fences(document.preamble))
    for item in document.items:
        blocks += _item(item, schema)
    lines = "\n\n".join(blocks).split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n") + "\n"


def _kept(block: str, meta: dict[str, Any]) -> str:
    """The frontmatter `block` as written when `meta` is what it holds (compared as JSON: an
    agent's JSON has a date as text); else written again from `meta`, a value it holds already
    kept as YAML typed it, unless the block holds more than its fields (rule
    `smd.frontmatter-kept-as-written`: keep, write again or refuse is decided here)."""
    old = frontmatter_meta(block)
    if to_jsonable_python(old) == to_jsonable_python(meta):
        return block
    problem = unwritable(block)
    if problem is not None:
        raise FrontmatterKeptError(
            f"{problem}: changing its fields would lose it; change them by hand in the file"
        )
    if not meta:
        return "---\n---"
    same = lambda k: k in old and to_jsonable_python(old[k]) == to_jsonable_python(meta[k])  # noqa: E731
    return _frontmatter({k: old[k] if same(k) else v for k, v in meta.items()})


def _frontmatter(meta: dict[str, object]) -> str:
    """`schema` first, then the other keys alphabetically (spec 7.1)."""
    keys = sorted(meta, key=lambda k: (k != "schema", k))
    yaml_text = "".join(
        yaml.safe_dump({k: meta[k]}, allow_unicode=True, sort_keys=False) for k in keys
    )
    return f"---\n{yaml_text}---"


def _item(item: Item, schema: ItemDef | None) -> list[str]:
    fields = dict(item.fields)
    lead = schema.title_lead if schema else None
    value = fields.get(lead.field) if lead is not None else None
    # the title says it already (spec 13.4.5)
    if (
        lead is not None
        and value is not None
        and lead_text(item.title, lead.type)[0] == field_text(value)
    ):
        del fields[lead.field]
    head = [f"## {_one_line(item.title, 'an item title')}"]
    head += _field_lines(fields, list(schema.fields) if schema else [])
    blocks = ["\n".join(head)]
    if item.body:
        blocks.append(closed_fences(item.body))
    if item.entries:
        entries = schema.entries if schema else None
        blocks.append("\n".join(_entry(entry, entries) for entry in item.entries))
    blocks += [_section(heading, section) for heading, section in _sections(item, schema)]
    return blocks


def _field_lines(fields: dict[str, FieldValue], declared: list[str]) -> list[str]:
    """`key: value` lines: the schema's order, then the others alphabetically (spec 7.5)."""
    order = [k for k in declared if k in fields] + sorted(set(fields) - set(declared))
    lines = []
    for key in order:
        value = fields[key]
        text = "" if value is None else _one_line(field_text(value), f"the field {key}")
        lines.append(f"{key}: {text}" if text else f"{key}:")
    return lines


def _entry(entry: Entry, schema: EntriesDef | None) -> str:
    """One bullet (spec 13.4): its checkbox, its line (built from its lead, title and tags once
    validated), its fields indented, then its notes, after a blank line when they could be read
    as fields."""
    fields = dict(entry.fields)
    if schema is not None and entry.title is not None:
        parts = []
        if schema.lead is not None and (value := fields.pop(schema.lead.field, None)) is not None:
            parts.append(field_text(value))
        parts.append(entry.title)
        if schema.tags is not None and (tags := fields.pop(schema.tags.field, None)):
            parts += [f"#{tag}" for tag in (tags if isinstance(tags, list) else [tags])]
        text = " ".join(part for part in parts if part)
    else:
        text = entry.text
    text = _one_line(text, "an entry's line")
    if entry.checked is None and CHECKBOX.match(text):
        raise ValueError(f"an entry with no checkbox cannot start with one: {text!r}")
    box = {None: "", False: "[ ] ", True: "[x] "}[entry.checked]
    lines = [f"- {box}{text}"]
    lines += [f"  {line}" for line in _field_lines(fields, list(schema.fields) if schema else [])]
    if entry.notes:
        notes = closed_fences(entry.notes).split("\n")
        first = []
        for line in notes:
            if not line.strip():
                break
            first.append(line)
        if fields or all(FIELD.match(line) for line in first):
            lines.append("")
        lines += [f"  {line}" for line in notes]
    return "\n".join(lines)


def _sections(item: Item, schema: ItemDef | None) -> list[tuple[str, Section]]:
    """Schema-declared ones in its order, under its heading; then the others as they came; the
    review notes last (spec 7.7)."""
    known = schema.sections if schema else {}
    ordered = [(known[k].heading, item.sections[k]) for k in known if k in item.sections]
    others = [(s.heading, s) for k, s in item.sections.items() if k not in known]
    notes = [o for o in others if section_key(o[0]) == REVIEW_NOTES]
    return ordered + [o for o in others if o not in notes] + notes


def _section(heading: str, section: Section) -> str:
    title = f"### {_one_line(heading, 'a section heading')}"
    return f"{title}\n\n{closed_fences(section.content)}" if section.content else title


def _one_line(text: str, what: str) -> str:
    if "\n" in text or "\r" in text:
        raise ValueError(f"{what} is one line: {text!r}")
    return text
