"""Unit tests: the Library's schemas (D.29): one per `$id`, a different one asks, an agent gets
its schemas and those they extend."""

import json
from pathlib import Path

import pytest

from handler_contracts import AgentDefinition, KnowledgeUse
from handler_control import definitions, knowledge_schemas
from handler_control.knowledge_schemas import SchemaClashError, SchemaError


def schema(schema_id: str, *, extends: str | None = None, title: str = "Contacts") -> str:
    item = {"fields": {"email": {"type": "string", "missing": "warning"}}}
    found = {"$id": schema_id, "title": title, "item": item}
    return json.dumps(found | ({"extends": extends} if extends else {}), indent=2) + "\n"


@pytest.mark.rule("knowledge.one-schema-per-id")
def test_one_schema_per_id_a_different_one_asks(tmp_path: Path) -> None:
    folder = tmp_path / "schemas"
    assert knowledge_schemas.add(folder, schema("contacts@1")) == ("contacts@1", True)
    assert (folder / "contacts@1.schema.json").read_text() == schema("contacts@1")
    assert knowledge_schemas.add(folder, schema("contacts@1")) == ("contacts@1", False)
    other = schema("contacts@1", title="People")
    with pytest.raises(SchemaClashError, match="contacts@1 is already in the Library"):
        knowledge_schemas.add(folder, other)
    assert knowledge_schemas.add(folder, other, replace=True) == ("contacts@1", True)
    assert knowledge_schemas.add(folder, schema("contacts@2")) == ("contacts@2", True)  # beside
    assert [s.id for s in knowledge_schemas.load_all(folder)] == ["contacts@1", "contacts@2"]
    with pytest.raises(SchemaError, match="not valid JSON"):
        knowledge_schemas.add(folder, "{")
    with pytest.raises(SchemaError, match="name>@<version"):
        knowledge_schemas.add(folder, schema("Contacts"))


@pytest.mark.rule("knowledge.one-schema-per-id")
def test_what_no_agent_can_use_says_why(tmp_path: Path) -> None:
    folder = tmp_path / "schemas"
    folder.mkdir()
    (folder / "broken@1.schema.json").write_text("{")
    (folder / "named@1.schema.json").write_text(schema("other@1"))
    (folder / "orphan@1.schema.json").write_text(schema("orphan@1", extends="gone@1"))
    (folder / "notes.md").write_text("not a schema")
    errors = {s.id: s.error for s in knowledge_schemas.load_all(folder)}
    assert set(errors) == {"broken@1", "named@1", "orphan@1"}
    assert "not valid JSON" in (errors["broken@1"] or "")
    assert "its `$id` is other@1" in (errors["named@1"] or "")
    assert "gone@1" in (errors["orphan@1"] or "")


@pytest.mark.rule("knowledge.schemas-read-only")
def test_an_agent_gets_its_schemas_and_those_they_extend(tmp_path: Path) -> None:
    folder = tmp_path / "schemas"
    knowledge_schemas.add(folder, schema("people@1"))
    knowledge_schemas.add(folder, schema("contacts@1", extends="people@1"))
    knowledge_schemas.add(folder, schema("books@1"))
    assert knowledge_schemas.files(folder, ["contacts@1"]) == {
        "contacts@1.schema.json": schema("contacts@1", extends="people@1"),
        "people@1.schema.json": schema("people@1"),
    }
    with pytest.raises(SchemaError, match="no schema gone@1"):
        knowledge_schemas.files(folder, ["gone@1"])
    knowledge_schemas.remove(folder, "people@1")
    with pytest.raises(SchemaError, match="contacts@1 cannot be used"):
        knowledge_schemas.files(folder, ["contacts@1"])


@pytest.mark.rule("knowledge.one-schema-per-id")
def test_an_agent_brings_its_schemas_and_takes_them_along(tmp_path: Path) -> None:
    """A definition's `schemas/` join the Library when it is set up (a different one with an
    `$id` there refuses it, adding none); an export carries the schemas the agent uses."""
    library = tmp_path / "schemas"
    shipped = tmp_path / "agent" / "schemas"
    shipped.mkdir(parents=True)
    (shipped / "contacts@1.schema.json").write_text(schema("contacts@1"))
    (shipped / "people@1.schema.json").write_text(schema("people@1"))
    knowledge_schemas.add(library, schema("people@1", title="Mine"))
    with pytest.raises(SchemaClashError, match="people@1 in your Library differs"):
        definitions.install_schemas(tmp_path / "agent", library, "it brings")
    assert [s.id for s in knowledge_schemas.load_all(library)] == ["people@1"]  # none added
    knowledge_schemas.add(library, schema("people@1"), replace=True)
    assert definitions.install_schemas(tmp_path / "agent", library, "it brings") == [
        "contacts@1",
        "people@1",
    ]

    definition = AgentDefinition(
        agent_name="keeper", schemas=[KnowledgeUse(schema_id="contacts@1", access="write")]
    )
    out = tmp_path / "out"
    definitions.write(out, definition, tmp_path / "skills", library)
    assert sorted(p.name for p in (out / "schemas").iterdir()) == ["contacts@1.schema.json"]
    assert definitions.read(out).schemas == definition.schemas
