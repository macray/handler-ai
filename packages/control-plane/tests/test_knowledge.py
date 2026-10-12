"""Unit tests: knowledge folders (D.5) checked, turned into mounts, listed; part of an agent."""

from pathlib import Path

import pytest

from handler_contracts import Mount
from handler_control import knowledge
from handler_control.knowledge import KnowledgeConflictError, KnowledgeError
from handler_control.settings import Settings


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "knowledge"
    for folder in ("me", "projects/shop", "projects/blog", "other/shop", ".obsidian", "_drafts"):
        (base / folder).mkdir(parents=True)
    (base / "note.md").write_text("not a folder")
    return base


def test_check_normalizes_and_sorts(root: Path) -> None:
    folders = ["projects/shop", "me", str(root / "me"), "./projects/blog/"]
    assert knowledge.check(root, folders) == ["me", "projects/blog", "projects/shop"]
    assert knowledge.check(root, []) == []


@pytest.mark.parametrize(
    ("folders", "error"),
    [
        (["../outside"], "outside the knowledge root"),
        (["/etc"], "outside the knowledge root"),
        (["nope"], "not a folder"),
        (["note.md"], "not a folder"),
        ([".obsidian"], "hidden"),
        (["projects", "projects/shop"], "inside projects"),
        ([".", "me"], "inside ."),
        (["projects/shop", "other/shop"], "both be /knowledge/shop"),
    ],
)
def test_check_refuses(root: Path, folders: list[str], error: str) -> None:
    with pytest.raises(KnowledgeError, match=error):
        knowledge.check(root, folders)


def test_check_refuses_a_symlink_out_of_the_root(root: Path, tmp_path: Path) -> None:
    (tmp_path / "secret").mkdir()
    (root / "link").symlink_to(tmp_path / "secret")
    with pytest.raises(KnowledgeError, match="outside the knowledge root"):
        knowledge.check(root, ["link"])


def test_mounts_are_read_only_at_knowledge_name(root: Path) -> None:
    assert knowledge.mounts(root, ["me", "projects/shop"]) == [
        Mount(source=str(root / "me"), target="/knowledge/me", read_only=True, kind="knowledge"),
        Mount(
            source=str(root / "projects" / "shop"),
            target="/knowledge/shop",
            read_only=True,
            kind="knowledge",
        ),
    ]
    assert knowledge.mounts(root, ["."])[0].target == "/knowledge/knowledge"


def test_listing(root: Path, tmp_path: Path) -> None:
    listing = knowledge.listing(root, "config")
    assert listing.source == "config"
    assert listing.exists
    assert listing.folders == [
        "me",
        "other",
        "other/shop",
        "projects",
        "projects/blog",
        "projects/shop",
    ]
    missing = knowledge.listing(tmp_path / "missing", "default")
    assert (missing.exists, missing.folders) == (False, [])


def settings(tmp_path: Path, forced: Path | None = None) -> Settings:
    return Settings(
        port=0,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path / "bindings",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
        knowledge_dir=forced,
    )


def test_root_default_config_and_env(root: Path, tmp_path: Path) -> None:
    s = settings(tmp_path)
    assert knowledge.root(s) == (Path.home() / "knowledge", "default")
    knowledge.set_root(s, str(root))
    assert knowledge.root(s) == (root.resolve(), "config")
    with pytest.raises(KnowledgeError, match="not a folder"):
        knowledge.set_root(s, str(tmp_path / "new"))
    knowledge.set_root(s, str(tmp_path / "new" / "vault"), create=True)
    assert knowledge.root(s) == ((tmp_path / "new" / "vault").resolve(), "config")
    with pytest.raises(KnowledgeError, match="absolute"):
        knowledge.set_root(s, "relative/path")
    knowledge.set_root(s, None)
    assert knowledge.root(s)[1] == "default"

    forced = settings(tmp_path, forced=root)
    assert knowledge.root(forced) == (root, "env")
    with pytest.raises(KnowledgeConflictError, match="HANDLER_KNOWLEDGE_DIR"):
        knowledge.set_root(forced, str(tmp_path))


def test_create_folder(root: Path) -> None:
    knowledge.create_folder(root, "projects/new")
    assert (root / "projects" / "new").is_dir()
    with pytest.raises(KnowledgeConflictError, match="exists"):
        knowledge.create_folder(root, "projects/new")
    for bad in ("../x", ".hidden", "_x", "a/../b", "nope/x"):
        with pytest.raises(KnowledgeError):
            knowledge.create_folder(root, bad)


def test_browse_and_read(root: Path) -> None:
    (root / "me" / "_index.md").write_text("---\nsummary: Me.\n---\n# me\n")
    (root / "me" / "tools.md").write_text("Zed.\n")
    (root / "me" / ".secret.md").write_text("hidden")
    (root / "me" / "picture.png").write_bytes(b"x")
    view = knowledge.browse(root, "me")
    assert (view.path, view.folders, view.notes) == ("me", [], ["tools.md"])
    assert view.index is not None and "summary: Me." in view.index
    top = knowledge.browse(root, ".")
    assert top.folders == ["me", "other", "projects"] and top.index is None
    assert knowledge.read_note(root, "me/tools.md").text == "Zed.\n"
    for bad in ("me/.secret.md", "me/picture.png", "../x.md", "me/missing.md"):
        with pytest.raises(KnowledgeError):
            knowledge.read_note(root, bad)
    with pytest.raises(KnowledgeError):
        knowledge.browse(root, "../")


def test_check_note_for_appends(root: Path) -> None:
    """I.6: the notes an automation may append to (K2, K5)."""
    assert knowledge.check_note(root, "projects/shop/issues.md") == "projects/shop/issues.md"
    assert knowledge.check_note(root, str(root / "me" / "x.md")) == "me/x.md"
    (root / "escape").symlink_to("/tmp")
    for note, error in [
        ("../x.md", "outside"),
        ("escape/x.md", "outside"),
        (".obsidian/x.md", "hidden"),
        ("_drafts/x.md", "starting with _"),
        ("me/x.txt", "not a markdown"),
        ("missing/x.md", "folder does not exist"),
    ]:
        with pytest.raises(KnowledgeError, match=error):
            knowledge.check_note(root, note)
    (root / "dir.md").mkdir()
    with pytest.raises(KnowledgeError, match="not a file"):
        knowledge.check_note(root, "dir.md")


def test_append_note_creates_then_appends(root: Path) -> None:
    knowledge.append_note(root, "me/log.md", "one\n")
    knowledge.append_note(root, "me/log.md", "two\n")
    assert (root / "me" / "log.md").read_text() == "one\ntwo\n"
    with pytest.raises(KnowledgeError):
        knowledge.append_note(root, "../log.md", "x")
