"""The scanner and the CLI (SMD spec 5.3, 6, 7; milestone M5): files and folders read, every
document checked against the schemas folder, references followed, files formatted."""

import json
import shutil
from pathlib import Path

import pytest

from handler_smd.cli import main
from handler_smd.models import Document
from handler_smd.scanner import check, check_file, documents, fmt, load_schemas
from handler_smd.scanner import write as write_document

FIXTURES = Path(__file__).parent / "fixtures"
HEAD = "---\nschema: decision-log@1\n---\n\n# T\n\n"
GOOD = HEAD + "## A\nstatus: accepted\ndate: 2026-11-10\nowner: me\ntags: x\n\n"
GOOD += "### Context\n\nc\n\n### Decision\n\nd\n"


@pytest.fixture
def schemas(tmp_path: Path) -> Path:
    folder = tmp_path / "schemas"
    folder.mkdir()
    shutil.copy(FIXTURES / "decision-log.schema.json", folder / "decision-log.schema.json")
    return folder


@pytest.fixture
def notes(tmp_path: Path) -> Path:
    folder = tmp_path / "notes"
    folder.mkdir()
    return folder


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def found(diagnostics: list) -> list[tuple[str, int, str]]:
    return [(Path(d.file).name, d.line, d.code) for d in diagnostics]


@pytest.mark.rule("smd.check-covers-a-folder")
def test_a_folder_is_checked_against_the_schemas(notes: Path, schemas: Path) -> None:
    shutil.copy(FIXTURES / "decision-log-invalid.md", notes / "db.md")
    write(notes / "good.md", GOOD)
    diagnostics = check(notes, schemas)
    assert found(diagnostics) == [
        ("db.md", 19, "missing-required-field"),
        ("db.md", 19, "missing-required-field"),
        ("db.md", 19, "missing-required-section"),
        ("db.md", 20, "invalid-enum"),
        ("db.md", 21, "invalid-date"),
    ]
    assert diagnostics[0].file == str(notes / "db.md")


@pytest.mark.rule("smd.check-covers-a-folder")
def test_markdown_files_are_found_inside_folders_not_hidden_ones(
    notes: Path, schemas: Path
) -> None:
    write(notes / "a" / "b" / "deep.md", "# T\n\n## A\nbad\n")
    write(notes / ".git" / "hidden.md", "no title")
    write(notes / "readme.txt", "no title")
    assert {Path(d.file).name for d in check(notes, schemas)} == {"deep.md"}


@pytest.mark.rule("smd.check-covers-a-folder")
def test_one_file_can_be_checked(notes: Path, schemas: Path) -> None:
    write(notes / "x.md", GOOD)
    assert check(notes / "x.md", schemas) == []


@pytest.mark.rule("smd.check-covers-a-folder")
def test_without_schemas_a_document_naming_one_finds_none(notes: Path) -> None:
    write(notes / "x.md", GOOD)
    assert found(check(notes, None)) == [("x.md", 1, "schema-not-found")]


@pytest.mark.rule("smd.check-covers-a-folder", "smd.every-problem-is-a-located-diagnostic")
def test_schema_problems_are_reported_on_their_files(notes: Path, schemas: Path) -> None:
    write(schemas / "broken.schema.json", "{")
    write(schemas / "twice.schema.json", (FIXTURES / "decision-log.schema.json").read_text())
    write(schemas / "notes.md", "not a schema: ignored")
    write(notes / "x.md", GOOD)
    assert found(check(notes, schemas)) == [
        ("broken.schema.json", 1, "invalid-schema"),
        ("twice.schema.json", 1, "duplicate-schema-id"),
    ]


@pytest.mark.rule("smd.check-covers-a-folder")
def test_a_draft_schema_replaces_its_id_for_one_run(notes: Path, schemas: Path) -> None:
    draft = json.loads((FIXTURES / "decision-log.schema.json").read_text())
    draft["item"]["fields"]["reviewer"] = {"type": "string", "missing": "error"}
    draft_file = write(notes.parent / "draft.json", json.dumps(draft))
    write(notes / "x.md", GOOD)
    assert found(check(notes, schemas, draft_file)) == [("x.md", 7, "missing-required-field")]
    assert check(notes, schemas) == []


@pytest.mark.rule("smd.check-covers-a-folder")
def test_references_are_followed(notes: Path, schemas: Path) -> None:
    write(notes / "other.md", "# O\n\n## Use Redis\n")
    refs = [
        "#a",
        "other.md",
        "other.md#use-redis",
        "#nope",
        "missing.md",
        "other.md#nope",
        "sub/../other.md#use-redis",
    ]
    text = HEAD + "".join(
        f"## {name}\nstatus: proposed\ndate: 2026-11-10\nsupersedes: {ref}\n\n"
        for name, ref in zip("ABCDEFG", refs, strict=True)
    )
    write(notes / "x.md", text)
    broken = [(d.line, d.message) for d in check(notes, schemas) if d.code == "broken-ref"]
    assert [line for line, _ in broken] == [25, 30, 35]
    assert "nope" in broken[0][1]


@pytest.mark.rule("smd.every-problem-is-a-located-diagnostic")
def test_a_file_that_is_not_utf8_is_reported(notes: Path, schemas: Path) -> None:
    (notes / "bad.md").write_bytes(b"# T\n\n\xff\xfe")
    assert found(check(notes, schemas)) == [("bad.md", 1, "invalid-encoding")]


@pytest.mark.rule("smd.one-canonical-form")
def test_fmt_rewrites_only_what_changes(notes: Path, schemas: Path) -> None:
    canonical = write(notes / "canonical.md", GOOD)
    messy = write(notes / "messy.md", HEAD + "## A\ntags: x\nstatus: accepted\n### Background\nb\n")
    before = canonical.stat().st_mtime_ns
    assert fmt(notes, schemas) == [messy]
    assert messy.read_text() == HEAD + "## A\nstatus: accepted\ntags: x\n\n### Context\n\nb\n"
    assert canonical.stat().st_mtime_ns == before
    assert fmt(notes, schemas) == []


@pytest.mark.rule("smd.one-canonical-form")
def test_fmt_without_a_schema_still_formats(notes: Path) -> None:
    messy = write(notes / "m.md", "# T\n## A\nb: 1\na: 2\n")
    assert fmt(notes, None) == [messy]
    assert messy.read_text() == "# T\n\n## A\na: 2\nb: 1\n"


@pytest.mark.rule("smd.check-covers-a-folder")
def test_cli_check_exits_1_on_an_error_and_groups_by_file(
    notes: Path, schemas: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copy(FIXTURES / "decision-log-invalid.md", notes / "db.md")
    assert main(["check", str(notes), "--schemas", str(schemas)]) == 1
    out = capsys.readouterr().out
    assert out.splitlines()[0] == str(notes / "db.md")
    assert "  20  error    items[1].fields.status  invalid-enum  status must be one of" in out
    assert out.splitlines()[-1] == "3 errors, 1 warning, 1 info in 1 file"


@pytest.mark.rule("smd.check-covers-a-folder")
def test_cli_check_exits_0_without_errors(
    notes: Path, schemas: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(notes / "x.md", GOOD.replace("tags: x\n", ""))
    assert main(["check", str(notes), "--schemas", str(schemas)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "0 errors, 0 warnings, 1 info in 1 file"


@pytest.mark.rule("smd.check-covers-a-folder")
def test_cli_check_json_is_the_flat_list(
    notes: Path, schemas: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copy(FIXTURES / "decision-log-invalid.md", notes / "db.md")
    assert main(["check", str(notes), "--schemas", str(schemas), "--json"]) == 1
    listed = json.loads(capsys.readouterr().out)
    assert [d["code"] for d in listed][-1] == "invalid-date"
    assert set(listed[0]) == {"file", "line", "path", "severity", "code", "message"}


@pytest.mark.rule("smd.check-covers-a-folder")
def test_cli_reads_the_schemas_folder_from_the_environment(
    notes: Path, schemas: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SMD_SCHEMAS", raising=False)
    write(notes / "x.md", GOOD)
    assert main(["check", str(notes)]) == 1
    monkeypatch.setenv("SMD_SCHEMAS", str(schemas))
    assert main(["check", str(notes)]) == 0


@pytest.mark.rule("smd.one-canonical-form")
def test_cli_fmt_says_what_it_rewrote(
    notes: Path, schemas: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    messy = write(notes / "m.md", HEAD + "## A\n### Background\nb\n")
    assert main(["fmt", str(notes), "--schemas", str(schemas)]) == 0
    assert capsys.readouterr().out == f"{messy}\n"


@pytest.mark.rule("smd.sections-keyed-by-the-schema")
def test_cli_parse_prints_the_document_as_json(
    notes: Path, schemas: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(notes / "x.md", HEAD + "## A\ndate: 2026-11-10\n### Background\nb\n")
    assert main(["parse", str(notes / "x.md"), "--schemas", str(schemas)]) == 0
    document = json.loads(capsys.readouterr().out)
    item = document["items"][0]
    assert item["fields"] == {"date": "2026-11-10"}
    assert list(item["sections"]) == ["context"]  # keyed by the schema


@pytest.mark.rule("smd.check-covers-a-folder")
def test_cli_a_path_that_does_not_exist(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "/nowhere/at/all"]) == 2
    assert "/nowhere/at/all" in capsys.readouterr().err


@pytest.mark.rule("smd.frontmatter-kept-as-written")
def test_fmt_leaves_a_frontmatter_as_written(notes: Path) -> None:
    """Spec 7.1: `fmt` formats below the frontmatter only: a broken one, its comments, its
    layout and a key written twice stay, and a broken one is still reported.

    If this fails: formatting a folder deletes a frontmatter that YAML cannot read."""
    broken = write(notes / "broken.md", "---\nschema: [unclosed\n---\n# T\n## A\nk: v\n")
    kept = "---\n# a comment\ntags: [a, b]\nk: 1\nk: 2\n---\n"
    commented = write(notes / "commented.md", kept + "# T\n")
    fmt(notes, None)
    assert broken.read_text() == "---\nschema: [unclosed\n---\n\n# T\n\n## A\nk: v\n"
    assert commented.read_text() == kept + "\n# T\n"
    codes = {(Path(d.file).name, d.code) for d in check(notes, None)}
    assert ("broken.md", "invalid-frontmatter") in codes
    assert ("commented.md", "duplicate-field") in codes


@pytest.mark.rule("app-sock.smd-only-in-its-folders")
def test_confined_nothing_is_read_or_written_through_a_link(tmp_path: Path, schemas: Path) -> None:
    """Confined `within` a folder, each part of a path is opened without following a link:
    even a path whose link appeared after it was checked reads and writes nothing outside.

    If this fails: an app swaps a file of its folder for a link between handlerd's check and
    its read, and reads (or overwrites) any file of yours."""
    folder, outside = tmp_path / "given", tmp_path / "outside"
    folder.mkdir()
    outside.mkdir()
    write(outside / "secret.md", GOOD)
    (folder / "file.md").symlink_to(outside / "secret.md")
    (folder / "dir").symlink_to(outside)
    index, _ = load_schemas(schemas)
    for path in (folder / "file.md", folder / "dir" / "secret.md"):
        with pytest.raises(OSError):
            check_file(path, index, within=folder)
        with pytest.raises(OSError):
            write_document(path, Document(title="Mine now"), schemas, within=folder)
    with pytest.raises(OSError):
        check_file(outside / "secret.md", index, within=folder)
    assert (outside / "secret.md").read_text() == GOOD
    assert documents(folder, within=folder) == []  # neither link listed


@pytest.mark.rule("smd.write-refuses-or-writes-then-checks")
def test_confined_write_writes_in_place_then_checks(tmp_path: Path, schemas: Path) -> None:
    folder = tmp_path / "given"
    target = write(folder / "d.md", GOOD)
    inode = target.stat().st_ino
    document = Document(meta={"schema": "decision-log@1"}, title="T")
    diagnostics = write_document(target, document, schemas, within=folder)
    assert target.read_text() == HEAD.removesuffix("\n") and target.stat().st_ino == inode
    assert diagnostics == []
