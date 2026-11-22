"""Resolution (SMD spec 5.3, milestone M2): the schemas of one folder indexed by `$id`, `extends`
applied once, then a document's schema found by its `$id` alone."""

import json

import pytest

from handler_smd.models import Diagnostic, Document
from handler_smd.resolver import SchemaFile, SchemaIndex, index_schemas, resolve_schema
from handler_smd.schema import parse_typedef


def typedef_file(file: str, schema_id: str, item: dict[str, object], **top: object) -> SchemaFile:
    text = json.dumps({"$id": schema_id, "title": schema_id, "item": item, **top})
    typedef, diagnostics = parse_typedef(text, file)
    assert diagnostics == []
    assert typedef is not None
    return SchemaFile(file=file, typedef=typedef)


def string(**more: object) -> dict[str, object]:
    return {"type": "string", **more}


def codes(diagnostics: list[Diagnostic]) -> list[tuple[str, str, str]]:
    return [(d.file, d.path, d.code) for d in diagnostics]


def document(schema: object = None) -> Document:
    meta = {} if schema is None else {"schema": schema}
    return Document(meta=meta, title="T", preamble=None, items=[])


def indexed(*files: SchemaFile) -> SchemaIndex:
    index, diagnostics = index_schemas(list(files))
    assert diagnostics == []
    return index


A1 = typedef_file("a1.json", "a@1", {"fields": {"x": string()}})
A2 = typedef_file("a2.json", "a@2", {"fields": {"y": string()}})


@pytest.mark.rule("smd.resolved-by-id-alone")
def test_a_document_finds_its_schema_by_id() -> None:
    typedef, diagnostics = resolve_schema(document("a@2"), indexed(A1, A2), "doc.md")
    assert diagnostics == []
    assert typedef == A2.typedef


@pytest.mark.rule("smd.resolved-by-id-alone")
def test_an_unknown_schema_is_reported_and_nothing_resolved() -> None:
    typedef, diagnostics = resolve_schema(document("b@1"), indexed(A1), "doc.md")
    assert typedef is None
    assert codes(diagnostics) == [("doc.md", "meta.schema", "schema-not-found")]
    assert diagnostics[0].severity == "error"


@pytest.mark.rule("smd.resolved-by-id-alone")
def test_another_version_only_is_a_version_mismatch() -> None:
    _, diagnostics = resolve_schema(document("a@3"), indexed(A1, A2), "doc.md")
    assert codes(diagnostics) == [("doc.md", "meta.schema", "schema-version-mismatch")]
    assert "a@1, a@2" in diagnostics[0].message


@pytest.mark.rule("smd.resolved-by-id-alone")
def test_no_schema_resolves_nothing_silently() -> None:
    """The parser already said `missing-schema-field`."""
    assert resolve_schema(document(), indexed(A1), "doc.md") == (None, [])


@pytest.mark.rule("smd.resolved-by-id-alone")
def test_a_schema_that_is_not_an_id_is_invalid_frontmatter() -> None:
    for bad in ["a", "a@x", 3, ["a@1"]]:
        typedef, diagnostics = resolve_schema(document(bad), indexed(A1), "doc.md")
        assert typedef is None
        assert codes(diagnostics) == [("doc.md", "meta.schema", "invalid-frontmatter")]


@pytest.mark.rule("smd.resolved-by-id-alone")
def test_two_schemas_with_one_id_keep_the_first_and_report_the_second() -> None:
    other = typedef_file("z.json", "a@1", {"fields": {"z": string()}})
    index, diagnostics = index_schemas([A1, other])
    assert codes(diagnostics) == [("z.json", "$id", "duplicate-schema-id")]
    assert index.schemas["a@1"] == A1.typedef


@pytest.mark.rule("smd.resolved-by-id-alone")
def test_extends_starts_from_the_parent_and_the_child_wins_per_key() -> None:
    parent = typedef_file(
        "p.json",
        "p@1",
        {
            "fields": {"a": string(missing="error"), "b": string()},
            "sections": {"s": {"heading": "S"}},
            "lenient_when": {"field": "a", "in": ["draft"]},
            "additional_fields": "forbid",
        },
    )
    child = typedef_file(
        "c.json",
        "c@1",
        {"fields": {"b": string(missing="warning"), "c": string()}},
        extends="p@1",
    )
    index = indexed(parent, child)
    item = index.schemas["c@1"].item
    assert list(item.fields) == ["a", "b", "c"]
    assert (item.fields["a"].missing, item.fields["b"].missing) == ("error", "warning")
    assert list(item.sections) == ["s"]
    assert item.lenient_when is not None
    assert item.lenient_when.field == "a"
    assert item.additional_fields == "forbid"  # the child did not say
    assert index.schemas["c@1"].extends == "p@1"


@pytest.mark.rule("smd.resolved-by-id-alone")
def test_what_the_child_says_overrides_the_parents_settings() -> None:
    parent = typedef_file("p.json", "p@1", {"additional_fields": "forbid"})
    child = typedef_file("c.json", "c@1", {"additional_fields": "allow"}, extends="p@1")
    assert indexed(parent, child).schemas["c@1"].item.additional_fields == "allow"


@pytest.mark.rule("smd.resolved-by-id-alone")
def test_extends_an_unknown_schema_breaks_the_child() -> None:
    child = typedef_file("c.json", "c@1", {}, extends="p@1")
    index, diagnostics = index_schemas([child])
    assert codes(diagnostics) == [("c.json", "extends", "schema-not-found")]
    typedef, found = resolve_schema(document("c@1"), index, "doc.md")
    assert typedef is None
    assert codes(found) == [("doc.md", "meta.schema", "schema-not-found")]
    assert "c.json" in found[0].message


@pytest.mark.rule("smd.resolved-by-id-alone")
def test_extends_is_one_level_only() -> None:
    grand = typedef_file("g.json", "g@1", {})
    parent = typedef_file("p.json", "p@1", {}, extends="g@1")
    child = typedef_file("c.json", "c@1", {}, extends="p@1")
    index, diagnostics = index_schemas([grand, parent, child])
    assert codes(diagnostics) == [("c.json", "extends", "invalid-schema")]
    assert set(index.schemas) == {"g@1", "p@1"}


@pytest.mark.rule("smd.schema-says-only-known-words")
def test_two_sections_answering_one_heading_are_invalid() -> None:
    """Even when only the merge makes them meet."""
    parent = typedef_file("p.json", "p@1", {"sections": {"context": {"heading": "Context"}}})
    child = typedef_file(
        "c.json",
        "c@1",
        {"sections": {"why": {"heading": "Why", "aliases": ["context"]}}},
        extends="p@1",
    )
    index, diagnostics = index_schemas([parent, child])
    assert codes(diagnostics) == [("c.json", "item.sections", "invalid-schema")]
    assert set(index.schemas) == {"p@1"}
    sections = {"a": {"heading": "A"}, "b": {"heading": "B", "aliases": ["a"]}}
    alone = typedef_file("a.json", "a@1", {"sections": sections})
    assert codes(index_schemas([alone])[1]) == [("a.json", "item.sections", "invalid-schema")]
    redundant = {"s": {"heading": "S", "aliases": ["s"]}}  # its own heading again: harmless
    assert index_schemas([typedef_file("r.json", "r@1", {"sections": redundant})])[1] == []


@pytest.mark.rule("smd.schema-says-only-known-words")
def test_lenient_when_names_a_field_of_the_schema() -> None:
    bad = typedef_file("b.json", "b@1", {"lenient_when": {"field": "status", "in": ["draft"]}})
    _, diagnostics = index_schemas([bad])
    assert codes(diagnostics) == [("b.json", "item.lenient_when.field", "invalid-schema")]


@pytest.mark.rule("smd.every-problem-is-a-located-diagnostic")
def test_index_diagnostics_are_sorted() -> None:
    late = typedef_file("b.json", "x@1", {}, extends="nope@1")
    early = typedef_file("a.json", "y@1", {}, extends="nope@1")
    _, diagnostics = index_schemas([late, early])
    assert [d.file for d in diagnostics] == ["a.json", "b.json"]
