"""Unit tests: structured markdown for an app's code (H.9, D.29): `/smd/*` on its
`handler.sock`, confined to the folders given to it; its `schemas` shipped in `schemas/`, put in
the Library at deploy. The format itself is `packages/smd`'s tests."""

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from test_apps import app_folder, store

from handler_contracts import AppManifest
from handler_control import knowledge_schemas
from handler_control.app_api import Handler as AppApiHandler
from handler_control.app_smd import AppSmd, shipped_problem
from handler_control.apps import AppStore, DeployError, snapshot

FIXTURES = Path(__file__).resolve().parents[2] / "smd" / "tests" / "fixtures"
SCHEMA = (FIXTURES / "decision-log.schema.json").read_text()
HEAD = "---\nschema: decision-log@1\n---\n\n# Decisions\n"
GOOD = HEAD + "\n## A\nstatus: accepted\ndate: 2026-11-10\nowner: me\ntags: x\n\n"
GOOD += "### Context\n\nc\n\n### Decision\n\nd\n"


@pytest.fixture
def given(tmp_path: Path) -> dict[str, Path]:
    """A backend's world: its version's schemas, a folder given read-write, one read-only, and
    beside them what was never given."""
    schemas = tmp_path / "code" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "decision-log@1.schema.json").write_text(SCHEMA)
    for name in ("rw", "ro", "outside"):
        (tmp_path / name).mkdir()
    (tmp_path / "outside" / "secret.md").write_text(GOOD)
    return {name: tmp_path / name for name in ("rw", "ro", "outside")} | {"schemas": schemas}


def smd(given: dict[str, Path]) -> AppSmd:
    return AppSmd(
        given["schemas"], [("cv", str(given["rw"]), True), ("notes", str(given["ro"]), False)]
    )


def call(s: AppSmd, what: str, **body: Any) -> tuple[int, dict[str, Any]]:
    return asyncio.run(s.answer("POST", f"/smd/{what}", body))


@pytest.mark.rule("app-sock.answers-only-what-the-app-declares")
def test_parse_check_write_on_a_folder_given(given: dict[str, Path]) -> None:
    """The editing loop of an app's code: parse (the model with its lines), change it, write
    (the canonical form, then its diagnostics), check a folder.

    If this fails: an app's code cannot read or write its documents through Handler, and
    re-implements the format."""
    s = smd(given)
    cv = given["rw"] / "cv.md"
    cv.write_text(GOOD)
    status, parsed = call(s, "parse", path=str(cv))
    assert status == 200 and parsed["diagnostics"] == []
    document = parsed["document"]
    assert document["items"][0]["line"] == 7
    assert document["items"][0]["fields"]["status"] == "accepted"
    document["items"][0]["fields"]["status"] = "rejected"
    del document["items"][0]["fields"]["owner"]
    status, answer = call(s, "write", path=str(cv), document=document)
    assert status == 200
    assert [d["code"] for d in answer["diagnostics"]] == ["missing-required-field"]  # owner
    assert "status: rejected\n" in cv.read_text()
    assert cv.read_text().startswith("---\nschema: decision-log@1\n---\n")  # kept as written
    new = given["rw"] / "sub" / "new.md"
    new.parent.mkdir()
    assert call(s, "write", path=str(new), document=document)[0] == 200  # a new document
    status, answer = call(s, "check", path=str(given["rw"]))
    assert status == 200
    assert sorted({Path(d["file"]).name for d in answer["diagnostics"]}) == ["cv.md", "new.md"]
    assert call(s, "check", path=str(given["ro"]))[0] == 200


@pytest.mark.rule("app-sock.answers-only-what-the-app-declares")
def test_what_it_cannot_do_is_said(given: dict[str, Path]) -> None:
    s = smd(given)
    cv = given["rw"] / "cv.md"
    cv.write_text(GOOD)
    assert call(s, "parse", path="cv.md")[0] == 400  # not absolute
    assert call(s, "parse", path=str(given["rw"]))[0] == 400  # a folder
    assert call(s, "parse", path=str(given["rw"] / "none.md"))[0] == 404
    assert call(s, "write", path=str(given["rw"] / "no" / "x.md"), document={})[0] == 404
    assert call(s, "write", path=str(cv), document={"items": "x"})[0] == 400
    assert asyncio.run(s.answer("GET", "/smd/parse", {"path": str(cv)}))[0] == 404
    assert asyncio.run(s.answer("POST", "/smd/fmt", {"path": str(cv)}))[0] == 404
    # its fields changed, a frontmatter holding a comment would lose it: refused, untouched
    commented = "---\nschema: decision-log@1  # mine\n---\n\n# Decisions\n"
    cv.write_text(commented)
    document = call(s, "parse", path=str(cv))[1]["document"]
    document["meta"]["more"] = "x"
    assert call(s, "write", path=str(cv), document=document)[0] == 409
    assert cv.read_text() == commented


@pytest.mark.rule("app-sock.smd-only-in-its-folders")
@pytest.mark.parametrize("call_", ["parse", "check", "write"])
def test_nothing_outside_the_folders_given(given: dict[str, Path], call_: str) -> None:
    """A path outside the folders given, or leaving one by `..`, is refused before anything is
    read or written.

    If this fails: an app's code reads or writes any file of yours through handlerd."""
    s = smd(given)
    secret = given["outside"] / "secret.md"
    document = {"title": "Mine now"}
    for path in (str(secret), f"{given['rw']}/../outside/secret.md", "/etc/passwd"):
        status, answer = call(s, call_, path=path, document=document)
        assert status == 403, answer
    assert secret.read_text() == GOOD


@pytest.mark.rule("app-sock.smd-only-in-its-folders")
@pytest.mark.parametrize("call_", ["parse", "check", "write"])
def test_never_through_a_link(given: dict[str, Path], call_: str) -> None:
    """A link the app made in a folder it may write, to a file or a folder outside, is never
    followed: the file itself, a folder on the way, or a folder checked whole.

    If this fails: an app reads your keys, or overwrites a file of yours, by linking to it."""
    s = smd(given)
    rw, secret = given["rw"], given["outside"] / "secret.md"
    (rw / "file.md").symlink_to(secret)
    (rw / "dir").symlink_to(given["outside"])
    for path in (rw / "file.md", rw / "dir" / "secret.md", rw / "dir"):
        status, answer = call(s, call_, path=str(path), document={"title": "Mine now"})
        assert status == 403, (path, answer)
    assert secret.read_text() == GOOD


@pytest.mark.rule("app-sock.smd-only-in-its-folders")
def test_a_folder_checked_whole_skips_links_and_follows_no_reference_out(
    given: dict[str, Path],
) -> None:
    """Checking a folder lists no link in it, and a reference leading out of the folder (or
    through a link in it) is said broken, never read.

    If this fails: an app learns what files of yours exist, and what they hold, by referencing
    them."""
    s = smd(given)
    rw = given["rw"]
    (rw / "linked.md").symlink_to(given["outside"] / "secret.md")
    (rw / "dir").symlink_to(given["outside"])
    out = GOOD.replace("tags: x\n", "tags: x\nsupersedes: ../outside/secret.md#a\n")
    (rw / "refs.md").write_text(out.replace("## A", "## B"))
    (rw / "via.md").write_text(out.replace("../outside/secret.md", "linked.md"))
    status, answer = call(s, "check", path=str(rw))
    assert status == 200
    found = sorted((Path(d["file"]).name, d["code"], d["message"]) for d in answer["diagnostics"])
    assert found == [
        ("refs.md", "broken-ref", "supersedes: ../outside/secret.md is outside the folder"),
        (
            "via.md",
            "broken-ref",
            "supersedes: linked.md is a link or not a file: never followed here",
        ),
    ]


@pytest.mark.rule("app-sock.smd-only-in-its-folders")
def test_a_folder_given_read_only_is_never_written(given: dict[str, Path]) -> None:
    """If this fails: an app changes your notes you gave it to read only."""
    s = smd(given)
    note = given["ro"] / "note.md"
    note.write_text(GOOD)
    assert call(s, "parse", path=str(note))[0] == 200
    status, answer = call(s, "write", path=str(note), document={"title": "Mine now"})
    assert status == 403 and "read-only" in answer["error"]
    assert note.read_text() == GOOD


@pytest.mark.rule("app-sock.smd-only-in-its-folders")
def test_a_pipe_is_not_read(given: dict[str, Path]) -> None:
    """If this fails: an app hangs handlerd's thread on a named pipe it made."""
    os.mkfifo(given["rw"] / "pipe.md")
    for what in ("parse", "write"):
        assert call(smd(given), what, path=str(given["rw"] / "pipe.md"), document={})[0] == 403


@pytest.mark.rule("app-sock.smd-only-in-its-folders", "app-need.a-file-given-is-that-file")
def test_a_file_given_is_written_in_place(tmp_path: Path, given: dict[str, Path]) -> None:
    """A files need given one file: that file read and written, in place (its inode kept: the
    sandbox mounts that very file); its folder's other files are not the app's.

    If this fails: an app's write through Handler is not seen by its own backend, or reaches
    the files beside the one you gave."""
    cv = tmp_path / "home" / "cv.md"
    cv.parent.mkdir()
    cv.write_text(GOOD)
    (cv.parent / "other.md").write_text(GOOD)
    s = AppSmd(given["schemas"], [("cv", str(cv), True)])
    inode = cv.stat().st_ino
    document = call(s, "parse", path=str(cv))[1]["document"]
    document["title"] = "Mine"
    assert call(s, "write", path=str(cv), document=document)[0] == 200
    assert cv.stat().st_ino == inode and "# Mine\n" in cv.read_text()
    assert call(s, "parse", path=str(cv.parent / "other.md"))[0] == 403


# ── the app's handler.sock: only with `schemas` ─────────────────────────


@pytest.mark.rule("app-sock.answers-only-what-the-app-declares")
def test_smd_only_for_an_app_declaring_schemas(given: dict[str, Path]) -> None:
    """A trial's or a draft's backend gets its `/smd/*` too, on the folders it was given (their
    copies); a version declaring no `schemas` gets 403, and the rest goes where it went.

    If this fails: an app reads your folders through Handler without saying so in its manifest,
    or a draft cannot be tried with its documents."""
    seen: list[str] = []

    async def rest(_n: str, _m: str, path: str, _b: dict[str, Any] | None) -> tuple[int, dict]:
        seen.append(path)
        return 200, {}

    note = given["rw"] / "note.md"
    note.write_text(GOOD)
    declared = AppStore.with_smd(smd(given), rest)
    none = AppStore.with_smd(None, rest)
    body = {"path": str(note)}

    def sock(handle: AppApiHandler, path: str, payload: dict[str, Any]) -> int:
        async def ask() -> tuple[int, dict[str, Any]]:
            return await handle("notes", "POST", path, payload)

        return asyncio.run(ask())[0]

    assert sock(declared, "/smd/parse", body) == 200
    assert sock(none, "/smd/parse", body) == 403
    assert sock(none, "/notify", {}) == 200
    assert seen == ["/notify"]


def test_an_app_declaring_schemas_reaches_handler_s_socket() -> None:
    m = AppManifest.model_validate(
        {"apiVersion": "handler.app/v1", "name": "cv", "version": "1.0.0", "schemas": ["cv@1"]}
    )
    assert m.handler_api


# ── its schemas: shipped, installed, into the Library ───────────────────


def with_schemas(tmp_path: Path, ids: list[str], files: dict[str, str]) -> Path:
    src = app_folder(tmp_path)
    toml = (src / "app.toml").read_text() + f"schemas = {json.dumps(ids)}\n"
    (src / "app.toml").write_text(toml)
    (src / "schemas").mkdir()
    for name, content in files.items():
        (src / "schemas" / name).write_text(content)
    return src


@pytest.mark.rule("deploy.a-failure-changes-nothing")
def test_its_schemas_are_installed_with_it(tmp_path: Path) -> None:
    src = with_schemas(tmp_path, ["decision-log@1"], {"decision-log@1.schema.json": SCHEMA})
    snapshot(src, tmp_path / "v1", AppManifest.from_toml((src / "app.toml").read_text()))
    assert (tmp_path / "v1" / "schemas" / "decision-log@1.schema.json").read_text() == SCHEMA


@pytest.mark.parametrize(
    ("ids", "files", "said"),
    [
        (["decision-log@1"], {}, "schemas/decision-log@1.schema.json does not exist"),
        ([], {"decision-log@1.schema.json": SCHEMA}, "is not declared in schemas"),
        (["other@1"], {"other@1.schema.json": SCHEMA}, "its `$id` is not other@1"),
        (["decision-log@1"], {"decision-log@1.schema.json": "{"}, "decision-log@1.schema.json"),
    ],
)
def test_its_schemas_are_those_it_declares(
    tmp_path: Path, ids: list[str], files: dict[str, str], said: str
) -> None:
    """If this fails: an app installs with formats it does not declare, or with none of those
    its code reads."""
    src = with_schemas(tmp_path, ids, files)
    problem = shipped_problem(src, ids)
    assert problem is not None and said in problem
    with pytest.raises(DeployError, match="schemas"):
        snapshot(src, tmp_path / "v1", AppManifest.from_toml((src / "app.toml").read_text()))


@pytest.mark.rule("knowledge.one-schema-per-id")
def test_its_schemas_join_the_library_a_different_one_refuses_it(tmp_path: Path) -> None:
    """At deploy, the app's schemas join the Library, as an agent definition's; one of an `$id`
    there that differs refuses the deploy, said, adding none.

    If this fails: two formats of one `$id` exist, and your documents are read with the wrong
    one."""
    s = store(tmp_path)
    library = s.settings.schemas_dir
    src = with_schemas(tmp_path, ["decision-log@1"], {"decision-log@1.schema.json": SCHEMA})
    knowledge_schemas.add(library, SCHEMA.replace("Decision log", "Mine"))
    with pytest.raises(DeployError, match=r"decision-log@1 in your Library differs .* notes"):
        s.library_schemas("notes", src)
    shutil.rmtree(library)
    s.library_schemas("notes", src)
    assert [x.id for x in knowledge_schemas.load_all(library)] == ["decision-log@1"]
