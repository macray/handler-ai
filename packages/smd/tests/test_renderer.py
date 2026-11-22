"""The renderer (SMD spec 7, milestone M4): a document to its one canonical markdown. Its laws,
on generated documents: the round trip, idempotence, nothing unknown lost."""

import re
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from handler_smd.models import Document, Entry, Item, Section
from handler_smd.parser import frontmatter_block, parse, section_key
from handler_smd.renderer import render
from handler_smd.schema import TypeDefinition, parse_typedef
from handler_smd.validator import validate

FIXTURES = Path(__file__).parent / "fixtures"


def decisions() -> TypeDefinition:
    typedef, _ = parse_typedef((FIXTURES / "decision-log.schema.json").read_text(), "s.json")
    assert typedef is not None
    return typedef


def without_lines(document: Document) -> Document:
    """The laws compare documents without line numbers: rendering moves lines (spec 7)."""
    items = [
        item.model_copy(
            update={
                "line": 0,
                "field_lines": {},
                "entries": None
                if item.entries is None
                else [e.model_copy(update={"line": 0, "field_lines": {}}) for e in item.entries],
                "sections": {k: s.model_copy(update={"line": 0}) for k, s in item.sections.items()},
            }
        )
        for item in document.items
    ]
    return document.model_copy(update={"items": items})


def reparsed(text: str) -> Document:
    return parse(text, "doc.md").document


@pytest.mark.rule("smd.one-canonical-form")
def test_without_its_schema_every_field_is_unknown_so_alphabetical() -> None:
    text = (FIXTURES / "decision-log.md").read_text()
    head = "## Use PostgreSQL\ndate: 2026-11-10\nowner: jane.doe\nstatus: accepted\ntags: database"
    assert head in render(reparsed(text))


@pytest.mark.rule("smd.one-canonical-form")
def test_the_canonical_layout() -> None:
    """Spec 7: frontmatter (schema first, then alphabetical), title, preamble, then each item:
    heading, fields right under it, body, sections; blank lines between blocks."""
    document = Document(
        meta={"zeta": 1, "schema": "x@1", "alpha": "a"},
        title="T",
        preamble="Intro.",
        items=[
            Item(
                title="A",
                slug="a",
                line=0,
                fields={"b": "2", "a": None},
                field_lines={},
                body="Body.",
                sections={"s": Section(heading="S", line=0, content="Text.")},
            )
        ],
    )
    assert render(document) == (
        "---\nschema: x@1\nalpha: a\nzeta: 1\n---\n\n# T\n\nIntro.\n\n"
        "## A\na:\nb: 2\n\nBody.\n\n### S\n\nText.\n"
    )


@pytest.mark.rule("smd.one-canonical-form")
def test_with_its_schema_fields_and_sections_follow_the_schema() -> None:
    text = (
        "---\nschema: decision-log@1\n---\n# T\n\n## A\nzz: unknown\nowner: me\naa: unknown\n"
        "date: 2026-11-10\nstatus: accepted\n\n### Notes\nn\n\n### Review notes\n- r\n\n"
        "### Background\nb\n\n### Decision\nd\n\n### Later\nl\n"
    )
    typedef = decisions()
    typed, _ = validate(reparsed(text), typedef, "doc.md")
    assert render(typed, typedef) == (
        "---\nschema: decision-log@1\n---\n\n# T\n\n## A\nstatus: accepted\ndate: 2026-11-10\n"
        "owner: me\naa: unknown\nzz: unknown\n\n### Context\n\nb\n\n### Decision\n\nd\n\n"
        "### Notes\n\nn\n\n### Later\n\nl\n\n### Review notes\n\n- r\n"
    )


@pytest.mark.rule("smd.one-canonical-form")
def test_typed_values_are_written_as_text() -> None:
    """The spec's 9.1, canonical: its order, and a blank line under each section heading (7.7),
    which 9.1 does not have."""
    typedef = decisions()
    text = (FIXTURES / "decision-log.md").read_text()
    typed, _ = validate(reparsed(text), typedef, "d.md")
    assert typed.items[0].fields["date"] == date(2026, 11, 10)
    canonical = text.replace("### Context\n", "### Context\n\n").replace(
        "### Decision\n", "### Decision\n\n"
    )
    assert render(typed, typedef) == canonical


@pytest.mark.rule("smd.one-canonical-form")
def test_an_empty_section_and_an_empty_document() -> None:
    document = reparsed("# T\n## A\n### Empty\n### Full\nx\n")
    assert render(document) == "# T\n\n## A\n\n### Empty\n\n### Full\n\nx\n"
    assert render(Document(meta={}, title=None, preamble=None, items=[])) == "\n"


@pytest.mark.rule("smd.parse-render-drops-nothing")
def test_a_rule_first_is_not_taken_for_a_frontmatter() -> None:
    document = Document(meta={}, title=None, preamble="---\ntext", items=[])
    assert render(document) == "---\n---\n\n---\ntext\n"
    assert reparsed(render(document)) == document


@pytest.mark.rule("smd.one-canonical-form")
def test_no_trailing_whitespace_and_one_final_newline() -> None:
    text = render(reparsed("# T  \n\n## A\nk: v   \n\ntext   \nmore\t\n\n\n\n"))
    assert text == "# T\n\n## A\nk: v\n\ntext\nmore\n"


@pytest.mark.rule("smd.write-refuses-or-writes-then-checks")
def test_a_field_value_on_two_lines_cannot_be_written() -> None:
    item = Item(
        title="A", slug="a", line=0, fields={"k": "a\nb"}, field_lines={}, body=None, sections={}
    )
    with pytest.raises(ValueError, match="one line"):
        render(Document(meta={}, title="T", preamble=None, items=[item]))


@pytest.mark.rule("smd.parse-render-drops-nothing")
def test_unknown_fields_and_sections_survive_a_round_trip_with_the_schema() -> None:
    typedef = decisions()
    text = "---\nschema: decision-log@1\n---\n# T\n## A\nmood: good\n### Aside\nkept\n"
    typed, _ = validate(reparsed(text), typedef, "d.md")
    again, _ = validate(reparsed(render(typed, typedef)), typedef, "d.md")
    assert again.items[0].fields == {"mood": "good"}
    assert again.items[0].sections["aside"].content == "kept"


# Generated documents. Words never hold a `:` nor a markdown mark, so a paragraph of them is
# prose, never a field block nor a heading; structure is in the tree, as parse makes it.
words = st.lists(
    st.text("abcdefghijXYZ0123456789", min_size=1, max_size=6), min_size=1, max_size=4
).map(" ".join)
paragraph = st.lists(words, min_size=1, max_size=3).map("\n".join)
fence = words.map(lambda w: f"```\n## {w}\n### {w}\n```")
content = st.lists(
    st.one_of(paragraph, fence, words.map("#### {}".format)), min_size=1, max_size=3
).map("\n\n".join)
key = st.from_regex(r"[a-z][a-z0-9_]{0,5}", fullmatch=True)
value = st.one_of(st.none(), words, st.lists(words, min_size=2, max_size=3).map(", ".join))


@st.composite
def sections(draw: st.DrawFn) -> dict[str, Section]:
    headings = draw(st.lists(words, max_size=3, unique_by=section_key))
    if draw(st.booleans()):
        headings.append("Review notes")
    return {
        section_key(h): Section(heading=h, line=0, content=draw(st.one_of(st.just(""), content)))
        for h in headings
    }


@st.composite
def entries(draw: st.DrawFn) -> list[Entry]:
    """A list's bullets (spec 13): a checkbox or none, a line, fields, notes (prose, a fence, a
    sub-list); slugs as the parser numbers them."""
    found: list[Entry] = []
    seen: dict[str, int] = {}
    for _ in range(draw(st.integers(1, 4))):
        text = draw(st.one_of(words, words.map("{} #tag".format), words.map("10:00 {}".format)))
        base = text.lower().replace(" ", "-").replace("#", "").replace(":", "-")
        seen[base] = seen.get(base, 0) + 1
        notes = st.one_of(content, words.map("- {}".format), st.just("k: v\nmore"))
        found.append(
            Entry(
                text=text,
                slug=base if seen[base] == 1 else f"{base}-{seen[base]}",
                checked=draw(st.sampled_from([None, False, True])),
                fields=draw(st.dictionaries(key, value, max_size=3)),
                notes=draw(st.one_of(st.none(), notes)),
            )
        )
    return found


@st.composite
def items(draw: st.DrawFn) -> Item:
    title = draw(words)
    listed = draw(st.booleans())
    return Item(
        title=title,
        slug=title.lower().replace(" ", "-"),
        line=0,
        fields=draw(st.dictionaries(key, value, max_size=4)),
        field_lines={},
        body=None if listed else draw(st.one_of(st.none(), content)),
        entries=draw(entries()) if listed else None,
        sections=draw(sections()),
    )


documents = st.builds(
    Document,
    meta=st.one_of(
        st.just({}), st.dictionaries(key, words, max_size=3).map(lambda m: {"schema": "x@1", **m})
    ),
    title=st.one_of(st.none(), words),
    preamble=st.one_of(st.none(), content),
    items=st.lists(items(), max_size=4),
)


@pytest.mark.rule("smd.parse-render-drops-nothing")
@given(documents)
def test_round_trip(document: Document) -> None:
    """parse(render(tree)) == tree, without line numbers."""
    again = reparsed(render(document))
    assert without_lines(again) == without_lines(document)
    for before, after in zip(document.items, again.items, strict=True):
        notes = [k for k in before.sections if k == "review_notes"]
        assert list(after.sections) == [k for k in before.sections if k != "review_notes"] + notes


@pytest.mark.rule("smd.one-canonical-form")
@given(documents)
def test_idempotence(document: Document) -> None:
    once = render(document)
    assert render(reparsed(once)) == once


FRONTMATTER_LINES = [
    "schema: a@1",
    "# a comment",
    "tags: [a, b]  # inline",
    "k: 1",
    "k: 2",
    "url: http://x#y",
    "bad: [unclosed",
    "- a list",
    "created: 2026-11-12",
]
LINES = [
    "# T",
    "## A",
    "### S",
    "#### d",
    "key: v",
    "other: w",
    "Note: x",
    "https://x.y",
    "```",
    "- item",
    "> quote",
    "",
    "",
    "---",
    "words here",
    "    indented",
    "Title",
    "=====",
    "### Review notes",
    "<!-- c -->",
    "| a | b |",
    "- [ ] 10:00 a task #work",
    "- [x] done",
    "* star",
    "  until: 2026-11-23",
    "  a note",
    "  - sub",
    "-",
]


# a fence never closed, last in the text, written before the review notes (spec 7.7)
UNCLOSED_FENCE = "## A\n### Review notes\n```\n## A\n```\n### S\n```"


@pytest.mark.rule("smd.one-canonical-form")
@given(st.lists(st.sampled_from(LINES), max_size=25).map("\n".join))
@example(UNCLOSED_FENCE)
def test_formatting_any_text_is_stable(text: str) -> None:
    """Whatever a person wrote: formatting it once is formatting it for good."""
    once = render(reparsed(text))
    assert render(reparsed(once)) == once


@pytest.mark.rule("smd.one-canonical-form")
@given(st.lists(st.sampled_from(LINES), max_size=25).map("\n".join))
@example(UNCLOSED_FENCE)
def test_formatting_with_the_schema_is_stable(text: str) -> None:
    typedef = decisions()
    once = render(
        validate(reparsed("---\nschema: decision-log@1\n---\n" + text), typedef, "d.md")[0], typedef
    )
    assert render(validate(reparsed(once), typedef, "d.md")[0], typedef) == once


@pytest.mark.rule("smd.parse-render-drops-nothing", "smd.frontmatter-kept-as-written")
@given(st.lists(st.sampled_from(LINES), max_size=25).map("\n".join))
def test_formatting_any_text_keeps_every_word(text: str) -> None:
    """Formatting moves and marks text, never drops it, the frontmatter included (kept as
    written, spec 7.1); a field written twice in an item keeps its last value (spec 3.1.5)."""
    result = parse(text, "x.md")
    assume(
        all(d.code != "duplicate-field" or d.path.startswith("meta") for d in result.diagnostics)
    )
    words = re.compile(r"[A-Za-z0-9]+")
    formatted = render(result.document, keep=frontmatter_block(text))
    assert Counter(words.findall(formatted)) == Counter(words.findall(text))


@pytest.mark.rule("smd.frontmatter-kept-as-written")
@given(st.lists(st.sampled_from(FRONTMATTER_LINES), max_size=6).map("\n".join))
def test_a_kept_frontmatter_is_written_as_it_is(lines: str) -> None:
    """Whatever the frontmatter holds (comments, a key twice, not YAML): with its fields
    unchanged, it is written back as it is; formatting then stays stable."""
    text = f"---\n{lines}\n---\n# T\n" if lines else "---\n---\n# T\n"
    block = frontmatter_block(text)
    once = render(parse(text, "x.md").document, keep=block)
    assert once.startswith("\n".join(line.rstrip() for line in (block or "").split("\n")))
    assert render(parse(once, "x.md").document, keep=frontmatter_block(once)) == once
