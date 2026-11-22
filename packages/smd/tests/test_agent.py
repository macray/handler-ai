"""Agent support (SMD spec 8, milestone M6): a schema exported as JSON Schema, as a blank
template, as instructions; and a document an agent wrote as JSON rendered into its file."""

import io
import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from handler_smd.agent import prompt, template, to_json_schema
from handler_smd.cli import main
from handler_smd.models import Document
from handler_smd.parser import parse
from handler_smd.renderer import render
from handler_smd.schema import TypeDefinition, parse_typedef
from handler_smd.validator import validate

FIXTURES = Path(__file__).parent / "fixtures"


def decisions() -> TypeDefinition:
    typedef, _ = parse_typedef((FIXTURES / "decision-log.schema.json").read_text(), "s.json")
    assert typedef is not None
    return typedef


def as_json(name: str) -> object:
    document = parse((FIXTURES / name).read_text(), name).document
    return json.loads(validate(document, decisions(), name)[0].model_dump_json())


@pytest.mark.rule("smd.agent-told-the-schema")
def test_the_json_schema_is_valid_and_matches_the_documents() -> None:
    exported = to_json_schema(decisions())
    Draft202012Validator.check_schema(exported)
    validator = Draft202012Validator(exported)
    assert list(validator.iter_errors(as_json("decision-log.md"))) == []
    errors = [e.message for e in validator.iter_errors(as_json("decision-log-invalid.md"))]
    assert any("'maybe'" in e for e in errors)


@pytest.mark.rule("smd.agent-told-the-schema")
def test_the_json_schema_says_what_an_agent_writes() -> None:
    exported = to_json_schema(decisions())
    item = exported["properties"]["items"]["items"]
    fields = item["properties"]["fields"]
    assert exported["properties"]["meta"]["properties"]["schema"] == {"const": "decision-log@1"}
    assert fields["required"] == ["status", "date", "owner"]  # missing: none or info may go
    assert fields["properties"]["status"]["description"] == "Where the decision stands."
    validator = Draft202012Validator(exported)
    minimal = {
        "meta": {"schema": "decision-log@1"},
        "title": "T",
        "items": [{"title": "A", "fields": {"status": None, "date": None, "owner": None}}],
    }
    assert list(validator.iter_errors(minimal)) == []  # null: not known, never invented
    wrong = {**minimal, "items": [{"title": "A", "fields": {"status": "maybe"}}]}
    assert list(validator.iter_errors(wrong))


@pytest.mark.rule("smd.agent-told-the-schema")
def test_a_forbidding_schema_exports_no_other_fields() -> None:
    typedef = decisions()
    item = typedef.item.model_copy(update={"additional_fields": "forbid"})
    exported = to_json_schema(typedef.model_copy(update={"item": item}))
    fields = exported["properties"]["items"]["items"]["properties"]["fields"]
    assert fields["additionalProperties"] is False


@pytest.mark.rule("smd.agent-told-the-schema")
def test_the_template_is_a_canonical_document_with_hints() -> None:
    text = template(decisions())
    assert render(parse(text, "t.md").document, decisions()) == text
    assert "status:\ndate:\nowner:\ntags:\nsupersedes:\n" in text
    assert "Where the decision stands." in text
    assert "proposed, accepted, rejected, superseded" in text
    assert "### Context" in text
    assert "Why a decision is needed." in text
    parsed = parse(text, "t.md")
    assert [d.code for d in parsed.diagnostics] == []
    _, diagnostics = validate(parsed.document, decisions(), "t.md")
    assert {d.code for d in diagnostics} == {"missing-required-field"}


@pytest.mark.rule("smd.agent-told-the-schema")
def test_the_prompt_tells_the_agent_the_rules_and_the_schema() -> None:
    text = prompt(decisions())
    for expected in [
        "decision-log@1",
        "status",
        "Where the decision stands.",
        "Background",
        "null",
        "Never invent",
        "### Review notes",
        "handler-smd write",
        "handler-smd check",
        '"const": "decision-log@1"',
    ]:
        assert expected in text, expected


@pytest.fixture
def schemas(tmp_path: Path) -> Path:
    folder = tmp_path / "schemas"
    folder.mkdir()
    shutil.copy(FIXTURES / "decision-log.schema.json", folder)
    return folder


def run(args: list[str], stdin: str, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return main(args)


AGENT_JSON = {
    "meta": {"schema": "decision-log@1"},
    "title": "Backend decisions",
    "items": [
        {
            "title": "Use PostgreSQL",
            "fields": {"date": "2026-11-10", "status": "accepted", "owner": None},
            "sections": {"context": {"heading": "Context", "content": "Integrity."}},
        }
    ],
}


@pytest.mark.rule("smd.write-refuses-or-writes-then-checks")
def test_write_renders_what_an_agent_wrote_and_checks_it(
    tmp_path: Path,
    schemas: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "db.md"
    code = run(
        ["write", str(target), "--schemas", str(schemas)], json.dumps(AGENT_JSON), monkeypatch
    )
    assert code == 1  # written, and its errors said: it stays reviewable (spec 8)
    assert target.read_text() == (
        "---\nschema: decision-log@1\n---\n\n# Backend decisions\n\n## Use PostgreSQL\n"
        "status: accepted\ndate: 2026-11-10\nowner:\n\n### Context\n\nIntegrity.\n"
    )
    out = capsys.readouterr().out
    assert "  7  warning  items[0].fields.owner  missing-required-field" in out
    assert "missing-required-section" in out


@pytest.mark.rule("smd.write-refuses-or-writes-then-checks")
def test_write_refuses_what_is_not_a_document(
    tmp_path: Path,
    schemas: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "db.md"
    target.write_text("kept\n")
    for wrong in ["{not json", json.dumps({"title": "T", "items": [{"fields": {}}]})]:
        assert run(["write", str(target), "--schemas", str(schemas)], wrong, monkeypatch) == 1
        assert target.read_text() == "kept\n"
    assert "items.0.title" in capsys.readouterr().err
    two_lines = {"title": "T", "items": [{"title": "A", "fields": {"k": "a\nb"}}]}
    assert run(["write", str(target)], json.dumps(two_lines), monkeypatch) == 1
    assert target.read_text() == "kept\n"


@pytest.mark.rule("smd.parse-render-drops-nothing")
def test_parse_then_write_is_the_editing_loop(
    tmp_path: Path,
    schemas: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An agent reads a document as JSON, changes it, writes it back: nothing else moves."""
    source = tmp_path / "db.md"
    canonical = render(Document.model_validate(as_json("decision-log.md")), decisions())
    source.write_text(canonical)
    assert main(["parse", str(source), "--schemas", str(schemas)]) == 0
    document = json.loads(capsys.readouterr().out)
    document["items"][0]["fields"]["status"] = "superseded"
    assert (
        run(["write", str(source), "--schemas", str(schemas)], json.dumps(document), monkeypatch)
        == 0
    )
    assert source.read_text() == canonical.replace("status: accepted", "status: superseded")


@pytest.mark.rule("smd.agent-told-the-schema")
def test_schema_commands_by_id(schemas: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema", "export", "decision-log@1", "--schemas", str(schemas)]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "Decision log"
    assert main(["schema", "template", "decision-log@1", "--schemas", str(schemas)]) == 0
    assert capsys.readouterr().out.startswith("---\nschema: decision-log@1\n---\n")
    assert main(["schema", "prompt", "decision-log@1", "--schemas", str(schemas)]) == 0
    assert "Never invent" in capsys.readouterr().out
    assert main(["schema", "export", "nope@1", "--schemas", str(schemas)]) == 1
    assert "nope@1" in capsys.readouterr().err


VAULT = (
    "---\n# my sync id, do not change\nschema: decision-log@1\ntags: [db, infra]  # Obsidian\n"
    "created: 2026-11-12\n---\n\n# Backend decisions\n\n## Use PostgreSQL\nstatus: accepted\n"
    "date: 2026-11-10\nowner: jane\n\n### Context\n\nIntegrity.\n"
)


@pytest.mark.rule("smd.frontmatter-kept-as-written")
def test_an_agent_s_edit_keeps_the_frontmatter_as_written(
    tmp_path: Path,
    schemas: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec 7.1: an item changed through parse then write, the frontmatter's fields the same:
    its comments, layout and order stay, a date as YAML typed it.

    If this fails: an agent adding one entry to your note strips the comments and the layout of
    its frontmatter, unseen."""
    source = tmp_path / "db.md"
    source.write_text(VAULT)
    assert main(["parse", str(source), "--schemas", str(schemas)]) == 0
    document = json.loads(capsys.readouterr().out)
    document["items"][0]["fields"]["status"] = "superseded"
    write = ["write", str(source), "--schemas", str(schemas)]
    run(write, json.dumps(document), monkeypatch)  # 1: written, its missing section said
    assert source.read_text() == VAULT.replace("status: accepted", "status: superseded")


@pytest.mark.rule("smd.frontmatter-kept-as-written")
def test_changing_a_frontmatter_that_holds_more_than_its_fields_is_refused(
    tmp_path: Path,
    schemas: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A changed field writes the frontmatter again: refused, the file untouched, when that
    would drop a comment, a key written twice or a frontmatter that is not YAML; written, its
    unchanged values as they were typed, when it holds nothing more.

    If this fails: changing a document's fields deletes your frontmatter's comments, or a
    broken frontmatter whole."""
    source = tmp_path / "db.md"
    for written in (
        VAULT,
        VAULT.replace("tags: [db, infra]  # Obsidian\n", "owner: a\nowner: b\n"),
        "---\nschema: [unclosed\n---\n\n# T\n",
    ):
        source.write_text(written)
        assert main(["parse", str(source), "--schemas", str(schemas)]) in (0, 1)
        document = json.loads(capsys.readouterr().out)
        document["meta"]["reviewed"] = True
        assert run(["write", str(source), "--schemas", str(schemas)], json.dumps(document), monkeypatch) == 1  # fmt: skip
        assert source.read_text() == written
        assert "change them by hand" in capsys.readouterr().err

    plain = "---\nschema: decision-log@1\ntags: [db, infra]\ncreated: 2026-11-12\n---\n\n# T\n"
    source.write_text(plain)
    assert main(["parse", str(source), "--schemas", str(schemas)]) == 0
    document = json.loads(capsys.readouterr().out)
    document["meta"]["reviewed"] = True
    run(["write", str(source), "--schemas", str(schemas)], json.dumps(document), monkeypatch)
    assert source.read_text().startswith(
        "---\nschema: decision-log@1\ncreated: 2026-11-12\nreviewed: true\ntags:\n- db\n- infra\n---\n"
    )
