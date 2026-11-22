"""The validator (SMD spec 4, 5.1, 6; milestone M3): a parsed document checked against its
schema, its fields coerced to their types, its sections keyed by the schema."""

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from textwrap import dedent

import pytest

from handler_smd.models import Diagnostic, Document, Item
from handler_smd.parser import parse
from handler_smd.schema import TypeDefinition, parse_typedef
from handler_smd.validator import validate

FIXTURES = Path(__file__).parent / "fixtures"


def load(text: str) -> TypeDefinition:
    typedef, diagnostics = parse_typedef(text, "s.json")
    assert diagnostics == []
    assert typedef is not None
    return typedef


DECISIONS = load((FIXTURES / "decision-log.schema.json").read_text())


def schema(item: Mapping[str, object]) -> TypeDefinition:
    return load(json.dumps({"$id": "x@1", "title": "X", "item": item}))


def check(text: str, typedef: TypeDefinition) -> tuple[Document, list[Diagnostic]]:
    parsed = parse(dedent(text).lstrip("\n"), "doc.md")
    return validate(parsed.document, typedef, "doc.md")


def table(diagnostics: list[Diagnostic]) -> list[tuple[int, str, str, str]]:
    return [(d.line, d.path, d.severity, d.code) for d in diagnostics]


def one_item(fields: str, typedef: TypeDefinition) -> tuple[Item, list[Diagnostic]]:
    document, diagnostics = check(f"# T\n\n## A\n{fields}\n", typedef)
    return document.items[0], diagnostics


@pytest.mark.rule("smd.severity-as-the-schema-says")
def test_the_spec_invalid_example_yields_exactly_its_diagnostics() -> None:
    """Spec 9.2, the golden test of the validator: its four, and the `info` its schema asks for
    a missing `tags` (5.1), which its table left out (spec 12, decision 9)."""
    parsed = parse((FIXTURES / "decision-log-invalid.md").read_text(), "decisions/db.md")
    _, diagnostics = validate(parsed.document, DECISIONS, "decisions/db.md")
    assert table(diagnostics) == [
        (19, "items[1].fields.owner", "warning", "missing-required-field"),
        (19, "items[1].fields.tags", "info", "missing-required-field"),
        (19, "items[1].sections.decision", "error", "missing-required-section"),
        (20, "items[1].fields.status", "error", "invalid-enum"),
        (21, "items[1].fields.date", "error", "invalid-date"),
    ]
    assert diagnostics[3].message == (
        "status must be one of: proposed, accepted, rejected, superseded (got 'maybe')"
    )
    assert {d.file for d in diagnostics} == {"decisions/db.md"}


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_the_spec_valid_example_is_valid_and_typed() -> None:
    parsed = parse((FIXTURES / "decision-log.md").read_text(), "decision-log.md")
    document, diagnostics = validate(parsed.document, DECISIONS, "decision-log.md")
    assert diagnostics == []
    fields = document.items[0].fields
    assert fields == {
        "status": "accepted",
        "date": date(2026, 11, 10),
        "owner": "jane.doe",
        "tags": ["database", "backend"],
    }
    assert parsed.document.items[0].fields["date"] == "2026-11-10"  # the input is not changed


@pytest.mark.rule("smd.severity-as-the-schema-says")
def test_an_empty_value_is_missing() -> None:
    _, diagnostics = one_item("status: accepted\ndate:\nowner: me", DECISIONS)
    assert ("items[0].fields.date", "missing-required-field") in [
        (d.path, d.code) for d in diagnostics
    ]


@pytest.mark.rule("smd.severity-as-the-schema-says")
def test_missing_says_the_severity_and_none_says_nothing() -> None:
    typedef = schema(
        {
            "fields": {
                "e": {"type": "string", "missing": "error", "description": "the e"},
                "w": {"type": "string", "missing": "warning"},
                "i": {"type": "string", "missing": "info"},
                "n": {"type": "string", "missing": "none"},
            },
        }
    )
    _, diagnostics = one_item("other: x", typedef)
    missing = [(d.path, d.severity) for d in diagnostics if d.code == "missing-required-field"]
    assert missing == [
        ("items[0].fields.e", "error"),
        ("items[0].fields.i", "info"),
        ("items[0].fields.w", "warning"),
    ]
    assert "the e" in next(d.message for d in diagnostics if d.path.endswith(".e"))


@pytest.mark.rule("smd.severity-as-the-schema-says")
def test_a_draft_is_lenient_about_what_it_lacks_not_about_what_it_says() -> None:
    _, diagnostics = check(
        """
        # T

        ## Idea
        status: proposed
        date: soon
        """,
        DECISIONS,
    )
    assert table(diagnostics) == [
        (3, "items[0].fields.owner", "warning", "missing-required-field"),
        (3, "items[0].fields.tags", "info", "missing-required-field"),
        (3, "items[0].sections.context", "warning", "missing-required-section"),
        (3, "items[0].sections.decision", "warning", "missing-required-section"),
        (5, "items[0].fields.date", "error", "invalid-date"),
    ]


def coerced(kind: Mapping[str, object], value: str) -> tuple[object, list[str]]:
    item, diagnostics = one_item(f"v: {value}", schema({"fields": {"v": kind}}))
    return item.fields["v"], [d.code for d in diagnostics]


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_strings_and_enums() -> None:
    assert coerced({"type": "string"}, "any text: really") == ("any text: really", [])
    assert coerced({"type": "enum", "values": ["a", "b"]}, "b") == ("b", [])
    assert coerced({"type": "enum", "values": ["a", "b"]}, "B") == ("B", ["invalid-enum"])


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_dates() -> None:
    assert coerced({"type": "date"}, "2026-02-28") == (date(2026, 2, 28), [])
    for bad in ["2026-02-30", "20260228", "28/02/2026", "2026-2-28"]:
        assert coerced({"type": "date"}, bad) == (bad, ["invalid-date"])


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_datetimes_need_a_timezone() -> None:
    plus_one = timezone(timedelta(hours=1))
    assert coerced({"type": "datetime"}, "2026-11-10T14:30:00+01:00") == (
        datetime(2026, 11, 10, 14, 30, tzinfo=plus_one),
        [],
    )
    assert coerced({"type": "datetime"}, "2026-11-10T14:30Z") == (
        datetime(2026, 11, 10, 14, 30, tzinfo=UTC),
        [],
    )
    for bad in ["2026-11-10T14:30:00", "2026-11-10 14:30+01:00", "2026-11-10", "tomorrow"]:
        assert coerced({"type": "datetime"}, bad) == (bad, ["invalid-datetime"])


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_lists() -> None:
    strings = {"type": "list", "of": "string"}
    assert coerced(strings, "a,  b ,c") == (["a", "b", "c"], [])
    assert coerced(strings, "one") == (["one"], [])
    assert coerced(strings, "a,,b") == ("a,,b", ["invalid-type"])
    assert coerced(strings, "a,") == ("a,", ["invalid-type"])
    dates = {"type": "list", "of": "date"}
    assert coerced(dates, "2026-01-01, 2026-01-02") == ([date(2026, 1, 1), date(2026, 1, 2)], [])
    assert coerced(dates, "2026-01-01, soon") == ("2026-01-01, soon", ["invalid-date"])
    enums = {"type": "list", "of": "enum", "values": ["x", "y"]}
    assert coerced(enums, "x, z") == ("x, z", ["invalid-enum"])


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_refs_are_checked_for_their_form_only() -> None:
    for good in ["#use-postgresql", "other.md", "other.md#use-redis", "../db/other.md#a"]:
        assert coerced({"type": "ref"}, good) == (good, [])
    for bad in ["#", "other.txt", "other.md#", "two words.md", "#a#b", "use-postgresql"]:
        assert coerced({"type": "ref"}, bad) == (bad, ["invalid-ref"])


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_a_value_on_two_lines_is_invalid() -> None:
    """Never from a file; from an agent's JSON, before the renderer refuses it."""
    document = parse("# T\n\n## A\nv: x\nw: y\n", "doc.md").document
    lines = {"v": "a\nb", "w": "c\nd"}
    item = document.items[0].model_copy(update={"fields": lines})
    wrong = document.model_copy(update={"items": [item]})
    _, diagnostics = validate(wrong, schema({"fields": {"v": {"type": "string"}}}), "doc.md")
    assert table(diagnostics) == [
        (4, "items[0].fields.v", "error", "invalid-type"),
        (5, "items[0].fields.w", "error", "invalid-type"),
        (5, "items[0].fields.w", "info", "unknown-field"),
    ]


@pytest.mark.rule("smd.parse-render-drops-nothing", "smd.severity-as-the-schema-says")
def test_unknown_fields_follow_additional_fields() -> None:
    for setting, severity in [("allow", "info"), ("warn", "warning"), ("forbid", "error")]:
        item, diagnostics = one_item("extra: kept", schema({"additional_fields": setting}))
        assert table(diagnostics) == [(4, "items[0].fields.extra", severity, "unknown-field")]
        assert item.fields == {"extra": "kept"}


@pytest.mark.rule("smd.sections-keyed-by-the-schema")
def test_an_alias_is_read_as_its_section() -> None:
    document, diagnostics = check(
        """
        # T

        ## A
        status: accepted
        date: 2026-11-10
        owner: me
        tags: x

        ### Background
        Why.

        ### Decision
        What.
        """,
        DECISIONS,
    )
    assert diagnostics == []
    sections = document.items[0].sections
    assert list(sections) == ["context", "decision"]
    assert (sections["context"].heading, sections["context"].content) == ("Background", "Why.")


@pytest.mark.rule("smd.parse-render-drops-nothing", "smd.sections-keyed-by-the-schema")
def test_a_heading_and_its_alias_together_keep_both_and_say_so() -> None:
    document, diagnostics = check(
        "# T\n\n## A\n### Context\none\n### Background\ntwo\n", schema_with_context()
    )
    assert {k: s.content for k, s in document.items[0].sections.items()} == {
        "context": "one",
        "context_2": "two",
    }
    third, _ = check(
        "# T\n\n## A\n### Context\n1\n### Background\n2\n### Background\n3\n",
        schema_with_context(),
    )
    assert list(third.items[0].sections) == ["context", "context_2", "context_3"]
    assert table(diagnostics) == [
        (6, "items[0].sections.context_2", "warning", "duplicate-section")
    ]


@pytest.mark.rule("smd.sections-keyed-by-the-schema")
def test_a_heading_twice_is_said_once_by_the_parser_not_again() -> None:
    parsed = parse("# T\n\n## A\n### Context\none\n### Context\ntwo\n", "doc.md")
    document, diagnostics = validate(parsed.document, schema_with_context(), "doc.md")
    assert [d.code for d in parsed.diagnostics] == ["missing-schema-field", "duplicate-section"]
    assert diagnostics == []
    assert list(document.items[0].sections) == ["context", "context_2"]


def schema_with_context() -> TypeDefinition:
    context = {"heading": "Context", "aliases": ["Background"], "missing": "error"}
    return schema({"sections": {"context": context}, "additional_sections": "forbid"})


@pytest.mark.rule("smd.parse-render-drops-nothing", "smd.severity-as-the-schema-says")
def test_unknown_sections_follow_additional_sections() -> None:
    for setting, severity in [("allow", "info"), ("warn", "warning"), ("forbid", "error")]:
        document, diagnostics = check(
            "# T\n\n## A\n### Notes\nx\n", schema({"additional_sections": setting})
        )
        assert table(diagnostics) == [(4, "items[0].sections.notes", severity, "unknown-section")]
        assert document.items[0].sections["notes"].content == "x"


@pytest.mark.rule("smd.sections-keyed-by-the-schema")
def test_an_unknown_section_never_takes_a_schema_sections_key() -> None:
    """`### Why` is not the schema's `why` (written `Rationale`): that one is still missing."""
    why = {"heading": "Rationale", "missing": "error"}
    document, diagnostics = check("# T\n\n## A\n### Why\nx\n", schema({"sections": {"why": why}}))
    assert list(document.items[0].sections) == ["why_2"]
    assert [d.code for d in diagnostics] == ["missing-required-section", "unknown-section"]


@pytest.mark.rule("smd.severity-as-the-schema-says")
def test_review_notes_are_surfaced_one_per_list_item() -> None:
    _, diagnostics = check(
        """
        # T

        ## A
        ### Review notes
        - the date was inferred from "last Tuesday"
        * owner unsure
        not a note
        """,
        schema({"additional_sections": "forbid"}),
    )
    assert [(d.line, d.code, d.severity, d.message) for d in diagnostics] == [
        (4, "review-note", "info", 'the date was inferred from "last Tuesday"'),
        (4, "review-note", "info", "owner unsure"),
    ]


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_items_are_checked_each_with_their_index() -> None:
    _, diagnostics = check(
        "# T\n\n## A\nv: x\n\n## B\nv: y\n",
        schema({"fields": {"v": {"type": "enum", "values": ["x"]}}}),
    )
    assert table(diagnostics) == [(7, "items[1].fields.v", "error", "invalid-enum")]


@pytest.mark.rule("smd.values-typed-or-kept-as-text")
def test_typed_values_are_checked_as_they_would_be_written() -> None:
    """An agent's JSON, or a document validated before, holds values typed: checked the same."""
    parsed = parse((FIXTURES / "decision-log.md").read_text(), "decision-log.md")
    typed, _ = validate(parsed.document, DECISIONS, "decision-log.md")
    assert validate(typed, DECISIONS, "decision-log.md") == (typed, [])
    item = typed.items[0].model_copy(update={"fields": {**typed.items[0].fields, "status": ["a"]}})
    wrong = typed.model_copy(update={"items": [item]})
    _, diagnostics = validate(wrong, DECISIONS, "decision-log.md")
    assert [d.code for d in diagnostics] == ["invalid-enum"]
