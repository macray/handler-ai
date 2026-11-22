"""List entries (SMD spec 13): an item whose body is a bullet list holds typed entries, so a
to-do list stays `- [ ] 10:00 Call the bank #work` and is still parsed and validated."""

import copy
import json
from datetime import date
from typing import Any

import pytest

from handler_smd.agent import prompt, template, to_json_schema
from handler_smd.models import Document, Entry, Item
from handler_smd.parser import parse
from handler_smd.renderer import render
from handler_smd.schema import TypeDefinition, parse_typedef
from handler_smd.validator import validate

CALENDAR = """---
schema: calendar@1
---

# Calendar

## To do

- [ ] Buy milk
- [ ] Renew passport #perso

## 2026-11-19 · Thursday

- 14:00-15:00 Sprint review #work
- [ ] 10:00 Call the bank
  ask about the loan
- [x] Send the report #work #urgent

## 2026-11-21 · Saturday

- Weekend in Lyon #perso
  until: 2026-11-23

  some notes
  - a sub-list is notes
"""

SCHEMA: dict[str, Any] = {
    "$id": "calendar@1",
    "title": "Calendar",
    "item": {
        "title_lead": {"field": "day", "type": "date", "description": "The day."},
        "entries": {
            "description": "An event, or a task.",
            "lead": {"field": "time", "type": "time-range"},
            "tags": {"field": "area"},
            "fields": {"until": {"type": "date", "description": "Its last day."}},
        },
    },
}


def calendar(**entries: object) -> TypeDefinition:
    schema = copy.deepcopy(SCHEMA)
    schema["item"]["entries"].update(entries)
    return TypeDefinition.model_validate(schema)


def typed(text: str, typedef: TypeDefinition | None = None) -> tuple[Document, list[str]]:
    result = parse(text, "c.md")
    document, found = validate(result.document, typedef or calendar(), "c.md")
    said = [d for d in result.diagnostics + found if d.code != "missing-schema-field"]
    return document, [f"{d.code} {d.path}" for d in said]


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_a_body_that_is_only_a_list_is_its_entries() -> None:
    document = parse(CALENDAR, "c.md").document
    todo, thursday, saturday = document.items
    assert todo.body is None
    assert [(e.checked, e.text) for e in todo.entries or []] == [
        (False, "Buy milk"),
        (False, "Renew passport #perso"),
    ]
    call = (thursday.entries or [])[1]
    assert (call.line, call.checked, call.text, call.notes) == (
        15,
        False,
        "10:00 Call the bank",
        "ask about the loan",
    )
    assert (thursday.entries or [])[2].checked is True
    lyon = (saturday.entries or [])[0]
    assert lyon.fields == {"until": "2026-11-23"}
    assert lyon.field_lines == {"until": 22}
    assert lyon.notes == "some notes\n- a sub-list is notes"


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_prose_or_two_lists_stay_a_body() -> None:
    for body in ["Some prose.\n\n- a\n- b", "- a\n\nprose", "- a\n* b", "1. a\n2. b"]:
        item = parse(f"# T\n## A\n{body}\n", "c.md").document.items[0]
        assert (item.entries, item.body) == (None, body)


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_lines_under_a_bullet_are_fields_only_when_every_one_is() -> None:
    text = "# T\n## A\n- a\n  k: v\n  more text\n- b\n  k: v\n  j:\n"
    a, b = parse(text, "c.md").document.items[0].entries or []
    assert (a.fields, a.notes) == ({}, "k: v\nmore text")
    assert (b.fields, b.notes) == ({"k": "v", "j": None}, None)


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_the_lead_and_the_tags_are_fields_the_rest_is_the_title() -> None:
    document, found = typed(CALENDAR)
    todo, thursday, saturday = document.items
    assert found == []
    assert thursday.fields == {"day": date(2026, 11, 19)}
    review, call, report = thursday.entries or []
    assert (review.title, review.fields) == (
        "Sprint review",
        {"time": "14:00-15:00", "area": ["work"]},
    )
    assert (call.title, call.slug, call.fields) == (
        "Call the bank",
        "call-the-bank",
        {"time": "10:00"},
    )
    assert report.fields == {"area": ["work", "urgent"]}
    assert (todo.entries or [])[1].fields == {"area": ["perso"]}
    lyon = (saturday.entries or [])[0]
    assert lyon.fields["until"] == date(2026, 11, 23)


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_a_start_that_is_not_its_type_stays_in_the_title() -> None:
    document, found = typed("# T\n## A\n- 25:00 late\n- 9:05-9:30 early\n- 1984 a year\n")
    late, early, year = document.items[0].entries or []
    assert (late.title, late.fields) == ("25:00 late", {})
    assert (early.title, early.fields) == ("early", {"time": "09:05-09:30"})
    assert year.title == "1984 a year"
    assert found == []


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_times_and_durations() -> None:
    typedef = TypeDefinition.model_validate(
        {
            "$id": "log@1",
            "title": "Log",
            "item": {
                "entries": {
                    "lead": {"field": "took", "type": "duration"},
                    "fields": {"at": {"type": "time"}},
                }
            },
        }
    )
    text = "# T\n## A\n- 1h30m fixed\n  at: 9:05\n- 45m call\n- 2h0 x\n- 9h05 y\n- z\n  at: 10:00-11:00\n"
    document, found = typed(text, typedef)
    took = [(e.title, e.fields) for e in document.items[0].entries or []]
    assert took == [
        ("fixed", {"took": "1h30", "at": "09:05"}),
        ("call", {"took": "45m"}),
        ("x", {"took": "2h"}),
        ("y", {"took": "9h05"}),
        ("z", {"at": "10:00-11:00"}),
    ]
    assert found == ["invalid-time items[0].entries[4].fields.at"]


@pytest.mark.rule("smd.severity-as-the-schema-says")
def test_a_field_line_wins_over_the_lead_and_says_so() -> None:
    document, found = typed(
        "# T\n## 2026-11-19\nday: 2026-11-20\n- 10:00 a\n  time: 11:00\n- 10:00 b\n  time: 10:00\n"
    )
    item = document.items[0]
    assert str(item.fields["day"]) == "2026-11-20"
    a, b = item.entries or []
    assert (a.fields, b.fields) == ({"time": "11:00"}, {"time": "10:00"})
    assert found == [
        "duplicate-field items[0].fields.day",
        "duplicate-field items[0].entries[0].fields.time",
    ]


@pytest.mark.rule("smd.severity-as-the-schema-says")
def test_the_checkbox_as_the_schema_says() -> None:
    text = "# T\n## A\n- [ ] a\n- b\n"
    assert typed(text, calendar(checkbox="require"))[1] == [
        "invalid-checkbox items[0].entries[1].checked"
    ]
    assert typed(text, calendar(checkbox="forbid"))[1] == [
        "invalid-checkbox items[0].entries[0].checked"
    ]
    assert typed(text)[1] == []


@pytest.mark.rule("smd.severity-as-the-schema-says")
def test_prose_where_a_list_is_expected_is_kept_and_said() -> None:
    document, found = typed("# T\n## A\nSome prose.\n")
    assert document.items[0].body == "Some prose."
    assert found == ["not-entries items[0].body"]


@pytest.mark.rule("smd.severity-as-the-schema-says")
def test_entry_fields_unknown_and_missing() -> None:
    typedef = calendar(
        fields={"until": {"type": "date", "missing": "warning"}}, additional_fields="warn"
    )
    _, found = typed("# T\n## A\n- a\n  mood: ok\n  until: 2026-11-23\n- b\n", typedef)
    assert found == [
        "unknown-field items[0].entries[0].fields.mood",
        "missing-required-field items[0].entries[1].fields.until",
    ]
    # a schema without entries: the fields of an item's list are unknown
    plain = TypeDefinition.model_validate({"$id": "p@1", "title": "P", "item": {}})
    assert typed("# T\n## A\n- a\n  k: v\n", plain)[1] == [
        "unknown-field items[0].entries[0].fields.k"
    ]


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_entries_alike_are_numbered_in_their_item() -> None:
    document, _ = typed("# T\n## A\n- [ ] Call #a\n- [x] Call #b\n## B\n- Call\n")
    a, b = document.items
    assert [e.slug for e in a.entries or []] == ["call", "call-2"]
    assert [e.slug for e in b.entries or []] == ["call"]


@pytest.mark.rule("smd.one-canonical-form")
def test_the_canonical_entries() -> None:
    typedef = calendar()
    document, _ = typed(CALENDAR.replace("[x]", "[X]"), typedef)
    keep = "---\nschema: calendar@1\n---"
    assert render(document, typedef, keep=keep) == CALENDAR
    # without the schema, the line as it was read
    assert render(parse(CALENDAR, "c.md").document, keep=keep) == CALENDAR


@pytest.mark.rule("smd.one-canonical-form")
def test_an_agent_gives_the_title_and_the_fields() -> None:
    """Section 12.12 for entries: the renderer builds the line; notes that would read as fields
    come after a blank line."""
    typedef = calendar()
    item = Item(
        title="2026-11-19 · Thursday",
        fields={"day": "2026-11-19"},
        entries=[
            Entry(title="Dentist", checked=None, fields={"time": "9:30", "area": ["perso"]}),
            Entry(title="Pay", checked=False, notes="until: tomorrow"),
        ],
    )
    text = render(Document(meta={"schema": "calendar@1"}, title="C", items=[item]), typedef)
    assert text.endswith(
        "## 2026-11-19 · Thursday\n\n- 9:30 Dentist #perso\n- [ ] Pay\n\n  until: tomorrow\n"
    )
    again, found = typed(text, typedef)
    dentist, pay = again.items[0].entries or []
    assert dentist.fields == {"time": "09:30", "area": ["perso"]}
    assert (pay.fields, pay.notes) == ({}, "until: tomorrow")
    assert found == []


@pytest.mark.rule("smd.write-refuses-or-writes-then-checks")
def test_an_entry_with_no_checkbox_cannot_start_with_one() -> None:
    item = Item(title="A", entries=[Entry(text="[x] looks done", checked=None)])
    with pytest.raises(ValueError, match="checkbox"):
        render(Document(title="T", items=[item]))


@pytest.mark.rule("smd.schema-says-only-known-words")
def test_the_lead_and_the_tags_have_their_own_fields() -> None:
    bad = {**SCHEMA, "item": {**SCHEMA["item"], "fields": {"day": {"type": "date"}}}}
    typedef, found = parse_typedef(json.dumps(bad), "s.json")
    assert typedef is None
    assert [d.code for d in found] == ["invalid-schema"]
    worse = {
        "$id": "x@1",
        "title": "X",
        "item": {"entries": {"lead": {"field": "a", "type": "string"}}},
    }
    assert parse_typedef(json.dumps(worse), "s.json")[0] is None


@pytest.mark.rule("smd.agent-told-the-schema")
def test_an_agent_is_told_the_entries() -> None:
    typedef = calendar(checkbox="require")
    schema = to_json_schema(typedef)
    entry = schema["properties"]["items"]["items"]["properties"]["entries"]["anyOf"][0]["items"]
    assert entry["properties"]["checked"] == {"type": "boolean"}
    assert set(entry["properties"]["fields"]["properties"]) == {"time", "area", "until"}
    told = prompt(typedef)
    assert "starting with a checkbox" in told
    assert "its time" in told
    blank = template(typedef)
    assert "- [ ] The first line" in blank
    _, found = typed(blank, typedef)
    assert [f for f in found if not f.startswith("missing-required")] == []
