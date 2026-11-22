"""Schemas (SMD spec 5.1, 5.2, milestone M2): a schema file's text to a TypeDefinition, or the
`invalid-schema` diagnostics saying why not."""

import json
from pathlib import Path

import pytest

from handler_smd.models import Diagnostic
from handler_smd.schema import TypeDefinition, parse_typedef

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = (FIXTURES / "decision-log.schema.json").read_text()


def schema(item: dict[str, object], **top: object) -> str:
    return json.dumps({"$id": "x@1", "title": "X", "item": item, **top})


def problems(text: str) -> list[tuple[int, str, str]]:
    typedef, diagnostics = parse_typedef(text, "x.schema.json")
    assert typedef is None
    assert {d.code for d in diagnostics} == {"invalid-schema"}
    assert {d.severity for d in diagnostics} == {"error"}
    return [(d.line, d.path, d.message) for d in diagnostics]


def loads(text: str) -> TypeDefinition:
    typedef, diagnostics = parse_typedef(text, "x.schema.json")
    assert diagnostics == []
    assert typedef is not None
    return typedef


@pytest.mark.rule("smd.schema-says-only-known-words")
def test_the_spec_example_loads() -> None:
    typedef = loads(EXAMPLE)
    assert (typedef.id, typedef.title, typedef.extends) == ("decision-log@1", "Decision log", None)
    item = typedef.item
    assert list(item.fields) == ["status", "date", "owner", "tags", "supersedes"]
    assert item.fields["status"].values == ["proposed", "accepted", "rejected", "superseded"]
    assert item.fields["tags"].of == "string"
    assert item.fields["owner"].missing == "warning"
    assert list(item.sections) == ["context", "decision", "consequences"]
    assert item.sections["context"].aliases == ["Background"]
    assert item.lenient_when is not None
    assert (item.lenient_when.field, item.lenient_when.values) == ("status", ["proposed"])
    assert (item.additional_fields, item.additional_sections) == ("allow", "allow")


@pytest.mark.rule("smd.schema-says-only-known-words")
def test_defaults() -> None:
    typedef = loads(
        schema({"fields": {"a": {"type": "string"}}, "sections": {"s": {"heading": "S"}}})
    )
    field, section = typedef.item.fields["a"], typedef.item.sections["s"]
    assert (field.missing, field.description) == ("none", "")
    assert (section.missing, section.aliases) == ("none", [])
    assert (typedef.item.lenient_when, typedef.item.additional_fields) == (None, "allow")


@pytest.mark.rule("smd.schema-says-only-known-words", "smd.every-problem-is-a-located-diagnostic")
def test_invalid_json_points_to_its_line() -> None:
    [(line, path, message)] = problems('{\n  "$id": "x@1",\n  "item": {,}\n}')
    assert (line, path) == (3, "")
    assert "JSON" in message


@pytest.mark.rule("smd.schema-says-only-known-words")
def test_a_misspelt_key_is_refused_not_ignored() -> None:
    [(_, path, _)] = problems(schema({"fields": {"a": {"type": "string", "mising": "error"}}}))
    assert path == "item.fields.a.mising"


@pytest.mark.rule("smd.schema-says-only-known-words")
def test_identifiers_are_name_at_version() -> None:
    for bad in ["decision-log", "Decision@1", "x@0", "x@v1", "x@1.2", "-x@1"]:
        assert problems(json.dumps({"$id": bad, "title": "X", "item": {}}))[0][1] == "$id"
    assert problems(schema({}, extends="nope"))[0][1] == "extends"


@pytest.mark.rule("smd.schema-says-only-known-words")
def test_an_enum_needs_values_and_only_an_enum_has_them() -> None:
    assert problems(schema({"fields": {"a": {"type": "enum"}}}))[0][1] == "item.fields.a"
    assert problems(schema({"fields": {"a": {"type": "enum", "values": []}}}))
    assert problems(schema({"fields": {"a": {"type": "string", "values": ["x"]}}}))


@pytest.mark.rule("smd.schema-says-only-known-words")
def test_a_list_says_what_of_and_only_a_list_does() -> None:
    assert problems(schema({"fields": {"a": {"type": "list"}}}))[0][1] == "item.fields.a"
    assert problems(schema({"fields": {"a": {"type": "string", "of": "string"}}}))
    assert problems(schema({"fields": {"a": {"type": "list", "of": "list"}}}))
    enums = {"type": "list", "of": "enum", "values": ["x", "y"]}
    assert loads(schema({"fields": {"a": enums}})).item.fields["a"].values == ["x", "y"]


@pytest.mark.rule("smd.schema-says-only-known-words")
def test_field_and_section_keys_are_snake_case() -> None:
    assert problems(schema({"fields": {"Status": {"type": "string"}}}))[0][1] == "item.fields"
    assert problems(schema({"fields": {"a-b": {"type": "string"}}}))
    assert problems(schema({"sections": {"Context": {"heading": "Context"}}}))[0][1] == (
        "item.sections"
    )


@pytest.mark.rule("smd.schema-says-only-known-words")
def test_unknown_words_are_refused() -> None:
    assert problems(schema({"fields": {"a": {"type": "number"}}}))
    assert problems(schema({"fields": {"a": {"type": "string", "missing": "fatal"}}}))
    assert problems(schema({"additional_fields": "ignore"}))


@pytest.mark.rule("smd.schema-says-only-known-words", "smd.every-problem-is-a-located-diagnostic")
def test_not_an_object_is_invalid() -> None:
    assert problems("[]")[0][1] == ""


@pytest.mark.rule("smd.schema-says-only-known-words", "smd.every-problem-is-a-located-diagnostic")
def test_diagnostics_name_the_schema_file() -> None:
    _, diagnostics = parse_typedef("{", "schemas/x.schema.json")
    assert [d.file for d in diagnostics] == ["schemas/x.schema.json"]
    assert all(isinstance(d, Diagnostic) for d in diagnostics)
