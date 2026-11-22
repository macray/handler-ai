"""The parser (SMD spec 3, milestone M1): markdown to the parsed model, with line numbers, and the
syntax diagnostics. No schema here."""

import json
from pathlib import Path
from textwrap import dedent

import pytest

from handler_smd.models import Diagnostic, Document, Item
from handler_smd.parser import parse, section_key, slug

FIXTURES = Path(__file__).parent / "fixtures"


def doc(text: str) -> tuple[Document, list[Diagnostic]]:
    result = parse(dedent(text).lstrip("\n"), "doc.md")
    return result.document, result.diagnostics


def codes(diagnostics: list[Diagnostic]) -> list[tuple[int, str]]:
    return [(d.line, d.code) for d in diagnostics]


def only_item(text: str) -> Item:
    document, _ = doc(text)
    assert len(document.items) == 1
    return document.items[0]


HEAD = """\
---
schema: x@1
---

# T

"""


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_the_spec_example_parses_to_the_spec_model() -> None:
    """Spec 9.1 gives the JSON of 3.2, line numbers included, and no diagnostic."""
    result = parse((FIXTURES / "decision-log.md").read_text(), "decision-log.md")
    expected = json.loads((FIXTURES / "decision-log.expected.json").read_text())
    assert result.document.model_dump(mode="json") == expected
    assert result.diagnostics == []


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_headings_inside_code_fences_are_content() -> None:
    item = only_item(
        HEAD
        + dedent("""\
        ## A

        ### Example
        ```markdown
        ## Not an item
        ### Not a section
        ```
        """)
    )
    assert list(item.sections) == ["example"]
    assert "## Not an item" in item.sections["example"].content


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_headings_inside_a_quote_or_a_list_are_content() -> None:
    item = only_item(HEAD + "## A\n\n> ## quoted\n\n- ### listed\n")
    assert item.sections == {}
    assert item.body == "> ## quoted\n\n- ### listed"


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_a_field_block_is_the_first_paragraph_when_every_line_is_a_field() -> None:
    item = only_item(HEAD + "## A\nstatus: open\nowner:\n\nSome prose.\n")
    assert item.fields == {"status": "open", "owner": None}
    assert item.field_lines == {"status": 8, "owner": 9}
    assert item.body == "Some prose."


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_prose_with_a_colon_is_not_a_field_block() -> None:
    item = only_item(HEAD + "## A\nNote: something\n")
    assert item.fields == {}
    assert item.body == "Note: something"


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_one_line_that_is_not_a_field_makes_the_paragraph_prose() -> None:
    item = only_item(HEAD + "## A\nstatus: open\nand then some words\n")
    assert item.fields == {}
    assert item.body == "status: open\nand then some words"


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_a_url_alone_is_not_a_field() -> None:
    item = only_item(HEAD + "## A\nhttps://example.com\n")
    assert item.fields == {}
    assert item.body == "https://example.com"


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_a_value_may_hold_colons() -> None:
    item = only_item(HEAD + "## A\nat: 2026-11-10T14:30:00+01:00\n")
    assert item.fields == {"at": "2026-11-10T14:30:00+01:00"}


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_the_field_block_is_only_the_first_block() -> None:
    item = only_item(HEAD + "## A\n\nIntro.\n\nstatus: open\n")
    assert item.fields == {}
    assert item.body == "Intro.\n\nstatus: open"


@pytest.mark.rule("smd.parse-render-drops-nothing")
def test_a_duplicate_field_keeps_the_last_and_says_so() -> None:
    document, diagnostics = doc(HEAD + "## A\nstatus: open\nstatus: done\n")
    assert document.items[0].fields == {"status": "done"}
    assert document.items[0].field_lines == {"status": 9}
    assert codes(diagnostics) == [(9, "duplicate-field")]
    assert diagnostics[0].path == "items[0].fields.status"


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_body_is_between_the_fields_and_the_first_section() -> None:
    item = only_item(HEAD + "## A\nstatus: open\n\nFirst.\n\n#### deep\n\n### S\ncontent\n")
    assert item.body == "First.\n\n#### deep"
    assert item.sections["s"].content == "content"


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_a_section_ends_at_the_next_section_or_item() -> None:
    document, _ = doc(HEAD + "## A\n### One\n1\n### Two\n2\n\n## B\n### One\nb1\n")
    a, b = document.items
    assert {k: s.content for k, s in a.sections.items()} == {"one": "1", "two": "2"}
    assert (a.sections["two"].line, b.line, b.sections["one"].line) == (10, 13, 14)


@pytest.mark.rule("smd.parse-render-drops-nothing")
def test_an_empty_section_is_kept() -> None:
    item = only_item(HEAD + "## A\n### Empty\n### Full\nx\n")
    assert item.sections["empty"].content == ""


@pytest.mark.rule("smd.parse-render-drops-nothing")
def test_two_sections_with_one_key_are_both_kept() -> None:
    document, diagnostics = doc(HEAD + "## A\n### Notes\n1\n### notes!\n2\n### Notes\n3\n")
    sections = document.items[0].sections
    assert {k: (s.heading, s.content) for k, s in sections.items()} == {
        "notes": ("Notes", "1"),
        "notes_2": ("notes!", "2"),
        "notes_3": ("Notes", "3"),
    }
    assert codes(diagnostics) == [(10, "duplicate-section"), (12, "duplicate-section")]
    assert {d.severity for d in diagnostics} == {"warning"}


@pytest.mark.rule("smd.every-problem-is-a-located-diagnostic")
def test_a_duplicate_item_title_is_reported() -> None:
    document, diagnostics = doc(HEAD + "## Same\n\n## same!\n")
    assert [i.slug for i in document.items] == ["same", "same"]
    assert codes(diagnostics) == [(9, "duplicate-item-title")]
    assert diagnostics[0].path == "items[1]"


@pytest.mark.rule("smd.parse-render-drops-nothing")
def test_text_before_and_after_the_title_is_the_preamble() -> None:
    document, diagnostics = doc("---\nschema: x@1\n---\nBefore.\n\n# T\n\nAfter.\n\n## A\n")
    assert document.title == "T"
    assert document.preamble == "Before.\n\nAfter."
    assert diagnostics == []


@pytest.mark.rule("smd.parse-render-drops-nothing", "smd.structure-only-from-top-level-blocks")
def test_a_section_heading_before_any_item_is_preamble() -> None:
    document, _ = doc(HEAD + "### Loose\ntext\n\n## A\n")
    assert document.preamble == "### Loose\ntext"


@pytest.mark.rule("smd.parse-render-drops-nothing")
def test_a_second_title_before_the_items_is_reported_and_kept() -> None:
    document, diagnostics = doc(HEAD + "# Again\n\n## A\n")
    assert document.title == "T"
    assert document.preamble == "# Again"
    assert codes(diagnostics) == [(7, "multiple-titles")]


@pytest.mark.rule("smd.parse-render-drops-nothing")
def test_a_title_after_the_first_item_stays_in_that_item() -> None:
    document, diagnostics = doc("---\nschema: x@1\n---\n\n## A\n\n# Late\n")
    assert document.title is None
    assert document.items[0].body == "# Late"
    assert codes(diagnostics) == [(1, "missing-title"), (7, "misplaced-title")]


@pytest.mark.rule("smd.every-problem-is-a-located-diagnostic")
def test_no_title_is_reported() -> None:
    document, diagnostics = doc("---\nschema: x@1\n---\n\nJust text.\n")
    assert document.title is None
    assert document.preamble == "Just text."
    assert codes(diagnostics) == [(1, "missing-title")]


@pytest.mark.rule("smd.every-problem-is-a-located-diagnostic")
def test_no_frontmatter_is_parsed_and_said_at_info() -> None:
    document, diagnostics = doc("# T\n\n## A\n")
    assert document.meta == {}
    assert [(d.code, d.severity, d.path) for d in diagnostics] == [
        ("missing-schema-field", "info", "meta.schema")
    ]


@pytest.mark.rule("smd.every-problem-is-a-located-diagnostic")
def test_frontmatter_without_schema_is_said_at_info() -> None:
    document, diagnostics = doc("---\nowner: me\n---\n# T\n")
    assert document.meta == {"owner": "me"}
    assert codes(diagnostics) == [(1, "missing-schema-field")]


@pytest.mark.rule("smd.every-problem-is-a-located-diagnostic")
def test_invalid_yaml_is_a_diagnostic_not_a_crash() -> None:
    document, diagnostics = doc("---\nschema: [unclosed\n---\n# T\n")
    assert document.meta == {}
    assert document.title == "T"
    assert codes(diagnostics) == [(1, "invalid-frontmatter")]


@pytest.mark.rule("smd.every-problem-is-a-located-diagnostic")
def test_frontmatter_that_is_not_a_mapping_is_invalid() -> None:
    _, diagnostics = doc("---\n- a\n- b\n---\n# T\n")
    assert codes(diagnostics) == [(1, "invalid-frontmatter")]


@pytest.mark.rule("smd.parse-render-drops-nothing")
def test_unclosed_frontmatter_is_reported_and_its_text_kept() -> None:
    document, diagnostics = doc("---\nschema: x@1\n# T\n")
    assert document.title == "T"
    assert document.preamble is not None
    assert "schema: x@1" in document.preamble
    assert (1, "invalid-frontmatter") in codes(diagnostics)


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_line_numbers_count_the_frontmatter() -> None:
    document, _ = doc(HEAD + "## A\nk: v\n### S\nx\n")
    item = document.items[0]
    assert (item.line, item.field_lines["k"], item.sections["s"].line) == (7, 8, 9)


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_windows_line_endings_parse_the_same() -> None:
    text = (FIXTURES / "decision-log.md").read_text()
    crlf = parse(text.replace("\n", "\r\n"), "decision-log.md")
    assert crlf == parse(text, "decision-log.md")


@pytest.mark.rule("smd.every-problem-is-a-located-diagnostic")
def test_diagnostics_are_sorted_by_line_then_path() -> None:
    _, diagnostics = doc(HEAD + "## A\nk: 1\nk: 2\n### S\n### S\n## A\n")
    assert [d.line for d in diagnostics] == sorted(d.line for d in diagnostics)


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_a_heading_over_two_lines_is_one_line() -> None:
    """An underlined (setext) heading may span lines; a title is one line."""
    document, _ = doc("# T\n\nkey: v\nkey: w\n---\n")
    assert [i.title for i in document.items] == ["key: v key: w"]


@pytest.mark.rule("smd.structure-only-from-top-level-blocks")
def test_slugs_and_section_keys() -> None:
    assert slug("Use PostgreSQL 17!") == "use-postgresql-17"
    assert slug("  --Décision prise--  ") == "décision-prise"
    assert slug("a_b") == "a-b"
    assert section_key("Review notes") == "review_notes"
