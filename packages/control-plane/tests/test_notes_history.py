"""Unit tests: the notes history (D.5) of a read-write notes folder, and of a folder given to an
app's files need in rw: committed when it changed, naming who could write, never following a
link, undone, and checked against the Library's schemas after a commit (a warning, never
more)."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from handler_contracts import KnowledgeFolderUse
from handler_control import desktop, notes_history
from handler_control.agents import AgentRecord, AgentRegistry, LiveConnection, RunsAs
from handler_control.apps import WrittenFolder
from handler_control.inbox import Inbox
from handler_control.notes_history import (
    NotesHistories,
    NotesHistoryConflictError,
    NotesHistoryMissingError,
)
from handler_control.settings import Settings

SCHEMA = {
    "$id": "contacts@1",
    "title": "Contacts",
    "item": {"fields": {"email": {"type": "string", "missing": "error"}}},
}
GOOD = "---\nschema: contacts@1\n---\n\n# Contacts\n\n## Ada\nemail: ada@example.org\n"
BROKEN = "---\nschema: contacts@1\n---\n\n# Contacts\n\n## Ada\nphone: 1\n"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setattr(desktop, "notify", lambda *_: None)
    return Settings(
        port=0,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        data_dir=tmp_path / "data",
        bindings_dir=tmp_path / "config",
        schemas_dir=tmp_path / "config" / "schemas",
        knowledge_dir=tmp_path / "notes",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
    )


@pytest.fixture
def folder(settings: Settings) -> Path:
    assert settings.knowledge_dir is not None
    path = settings.knowledge_dir / "people"
    path.mkdir(parents=True)
    (path / "a.md").write_text("first\n")
    return path


@pytest.fixture
def registry(settings: Settings, folder: Path) -> AgentRegistry:
    registry = AgentRegistry(settings.state_dir)
    for name, access in (("writer", "write"), ("reader", "read")):
        uses = [KnowledgeFolderUse(folder="people", access=access)]
        model = RunsAs(harness="claude", account="a")
        registry.add(AgentRecord(scope="/code/x", model=model, name=name, knowledge=uses))
    return registry


@pytest.fixture
def app_folders() -> list[WrittenFolder]:
    """What the apps write (AppStore.written_folders): none until a test gives one."""
    return []


@pytest.fixture
def histories(
    settings: Settings, registry: AgentRegistry, app_folders: list[WrittenFolder]
) -> NotesHistories:
    return NotesHistories(
        settings, registry, Inbox(settings), lambda a: a.name or "", lambda: list(app_folders)
    )


def given(
    path: Path, *, running: bool = False, last_used_at: datetime | None = None
) -> WrittenFolder:
    """A folder given to the app `cv` (its title "CV assistant") for a files need in rw."""
    real = os.path.realpath(path)
    return WrittenFolder("cv", "CV assistant", real, running, last_used_at)


def agent(registry: AgentRegistry, name: str) -> AgentRecord:
    return next(a for a in registry.agents.values() if a.name == name)


def ran(registry: AgentRegistry, name: str) -> None:
    agent(registry, name).last_used_at = datetime.now(UTC) + timedelta(seconds=1)


@pytest.mark.rule("notes.writable-has-a-history")
def test_a_writable_folder_is_committed_when_it_changed(
    histories: NotesHistories, folder: Path, settings: Settings
) -> None:
    """At the first look the history starts; a look finding nothing changed commits nothing;
    each change after is one commit, with what it added, changed and deleted.

    If this fails: a change an agent made is nowhere to be undone, or the history fills with
    empty commits."""
    [first] = histories.commit_all(started=True)
    assert (first.kind, first.file_count, first.files) == ("first", 1, [])
    assert histories.commit_all() == []
    (folder / "a.md").write_text("second\n")
    (folder / "sub").mkdir()
    (folder / "sub" / "b.md").write_text("new\n")
    [changes] = histories.commit_all()
    assert changes.kind == "changes"
    assert [(f.path, f.change) for f in changes.files] == [
        ("a.md", "changed"),
        ("sub/b.md", "added"),
    ]
    (folder / "a.md").unlink()
    [deleted] = histories.commit_all(started=True)
    assert deleted.kind == "while-off" and [(f.path, f.change) for f in deleted.files] == [
        ("a.md", "deleted")
    ]
    listed = histories.history("people")
    assert [c.id for c in listed.commits] == [deleted.id, changes.id, first.id]
    diff = histories.commit("people", changes.id)
    assert diff.files[0].diff == "@@ -1 +1 @@\n-first\n+second\n"


@pytest.mark.rule("notes.history-names-who-could-write")
def test_a_listed_change_says_what_changed_in_its_first_files(
    histories: NotesHistories, folder: Path
) -> None:
    """Each listed change says, for its first files, how many lines were added and removed and
    the heading they are all under; a binary file, or a file past the first ones, says nothing.

    If this fails: the history reads "4 files changed" and you must open each entry to know
    which file, and what changed in it."""
    histories.commit_all(started=True)
    (folder / "a.md").write_text("# Likes\n\n- tea\n- long walks\n")
    (folder / "b.md").write_text("# One\n- x\n# Two\n- y\n")
    (folder / "c.bin").write_bytes(b"\xff\xfe\x00")
    (folder / "d.md").write_text("past the first three\n")
    [changes] = histories.commit_all()
    listed = histories.history("people").commits[0]
    assert [(f.path, f.added, f.removed, f.under) for f in listed.files] == [
        ("a.md", 4, 1, None),  # "first" became the Likes list: also above the heading
        ("b.md", 4, 0, None),  # under two headings: none named
        ("c.bin", None, None, None),  # not text
        ("d.md", None, None, None),  # past FILES_SAID
    ]
    (folder / "a.md").write_text("# Likes\n\n- tea\n- the sea\n- long walks\n")
    [later] = histories.commit_all()
    [a] = histories.history("people").commits[0].files
    assert (a.added, a.removed, a.under) == (1, 0, "Likes")
    assert histories.commit("people", later.id).files[0].under == "Likes"  # opened: the same
    assert changes.id != later.id


@pytest.mark.rule("notes.agents-never-reach-the-history", "notes.writable-has-a-history")
def test_the_history_is_under_handler_s_data_and_leaves_git_out(
    histories: NotesHistories, folder: Path, settings: Settings
) -> None:
    """The history's git dir is under Handler's data, nothing of it in the folder; a vault's own
    `.git` is left out, at any depth.

    If this fails: an agent with write access rewrites the history meant to undo what it did."""
    (folder / ".git").mkdir()
    (folder / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (folder / "sub" / ".git").mkdir(parents=True)
    (folder / "sub" / ".git" / "config").write_text("x")
    [first] = histories.commit_all()
    assert first.file_count == 1  # a.md alone
    assert sorted(os.listdir(folder)) == [".git", "a.md", "sub"]
    [git_dir] = (settings.data_dir / "notes-history").iterdir()
    assert git_dir.name.endswith(".git")
    assert (git_dir / "description").read_text() == f"{os.path.realpath(folder)}\n"


@pytest.mark.rule("notes.history-names-who-could-write")
def test_a_commit_names_the_writers_that_ran_in_its_lapse(
    histories: NotesHistories, registry: AgentRegistry, folder: Path
) -> None:
    """Those that could write and ran in the lapse: started in it, or with a sandbox now or at
    the previous look; never an agent that only reads; none for what changed while handlerd
    was off.

    If this fails: the history blames an agent that could not have written, or hides one that
    could."""
    histories.commit_all()
    (folder / "a.md").write_text("1\n")
    assert histories.commit_all()[0].could_write == []
    writer = agent(registry, "writer")
    ran(registry, "reader")
    ran(registry, "writer")
    (folder / "a.md").write_text("2\n")
    [one] = histories.commit_all()
    assert [w.name for w in one.could_write] == ["writer"]
    assert one.could_write[0].agent_id == writer.id
    writer.last_used_at = datetime.now(UTC) - timedelta(days=1)
    writer.connections["c"] = LiveConnection("c", "s", datetime.now(UTC), None)
    histories.commit_all()  # still running at this look
    writer.connections.clear()
    (folder / "a.md").write_text("3\n")
    [ended] = histories.commit_all()  # it ended in this lapse
    assert [w.name for w in ended.could_write] == ["writer"]
    (folder / "a.md").write_text("4\n")
    assert histories.commit_all()[0].could_write == []
    ran(registry, "writer")
    (folder / "a.md").write_text("5\n")
    assert histories.commit_all(started=True)[0].could_write == []


@pytest.mark.rule("notes.history-never-follows-links")
def test_a_link_is_kept_as_a_link_never_followed(
    histories: NotesHistories, folder: Path, tmp_path: Path
) -> None:
    """A link to a file or a folder outside is committed as a link: its target is never read,
    and undoing never writes through it.

    If this fails: an agent with write access links `~/.ssh` into its folder and Handler copies
    your keys into the history, or an undo writes where the link points."""
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "key").write_text("the-key-content")
    histories.commit_all()
    (folder / "keys").symlink_to(secret)
    (folder / "key.md").symlink_to(secret / "key")
    [linked] = histories.commit_all()
    assert {(f.path, f.change, f.link) for f in linked.files} == {
        ("keys", "added", True),
        ("key.md", "added", True),
    }
    detail = histories.commit("people", linked.id)
    assert {f.link_target for f in detail.files} == {str(secret), str(secret / "key")}
    store = histories._repo(os.path.realpath(folder)).object_store
    assert not any(b"the-key-content" in store[sha].as_raw_string() for sha in store)

    # a folder of the history made a link to outside: undo leaves it, writes nothing there
    (folder / "sub").mkdir()
    (folder / "sub" / "n.md").write_text("one\n")
    histories.commit_all()
    (folder / "sub" / "n.md").write_text("two\n")
    [changed] = histories.commit_all()
    (folder / "sub" / "n.md").unlink()
    (folder / "sub").rmdir()
    (folder / "sub").symlink_to(secret)
    undone = histories.undo("people", changed.id)
    assert undone.skipped == ["sub/n.md"]
    assert sorted(os.listdir(secret)) == ["key"]
    assert (secret / "key").read_text() == "the-key-content"


@pytest.mark.rule("notes.handler-writes-only-what-you-asked", "notes.writable-has-a-history")
def test_undo_puts_back_the_files_as_they_were_before(
    histories: NotesHistories, folder: Path
) -> None:
    """Undo of a change puts its files back as before it (a deleted one back, an added one
    gone), after committing what the folder held, so the undo can be undone too. The first
    state cannot be undone.

    If this fails: undoing an agent's change loses what was written since, or cannot be undone."""
    [first] = histories.commit_all()
    with pytest.raises(NotesHistoryConflictError):
        histories.undo("people", first.id)
    (folder / "a.md").write_text("by an agent\n")
    (folder / "b.md").write_text("added\n")
    [change] = histories.commit_all()
    (folder / "c.md").write_text("later, not committed yet\n")
    undone = histories.undo("people", change.id)
    assert undone.skipped == []
    assert undone.commit is not None and undone.commit.undoes == change.id
    assert (folder / "a.md").read_text() == "first\n"
    assert not (folder / "b.md").exists()
    assert (folder / "c.md").read_text() == "later, not committed yet\n"
    kinds = [c.kind for c in histories.history("people").commits]
    assert kinds == ["undo", "changes", "changes", "first"]
    again = histories.undo("people", undone.commit.id)
    assert (folder / "a.md").read_text() == "by an agent\n" and (folder / "b.md").exists()
    assert again.commit is not None


def test_what_has_no_history(histories: NotesHistories, settings: Settings) -> None:
    assert settings.knowledge_dir is not None
    (settings.knowledge_dir / "other").mkdir()
    with pytest.raises(NotesHistoryMissingError):
        histories.history("other")
    histories.commit_all()
    with pytest.raises(NotesHistoryMissingError):
        histories.commit("people", "0" * 40)


@pytest.mark.rule("knowledge.history-check-only-warns")
def test_a_broken_document_is_a_warning_in_the_inbox(
    histories: NotesHistories, folder: Path, settings: Settings
) -> None:
    """After a commit, the documents it added or changed that name a schema are checked against
    the Library's: a broken one is one warning in the inbox; a plain note, a good document or
    one only deleted are not; the file stays as written.

    If this fails: a document an agent broke goes unseen, or a check blocks or rewrites it."""
    settings.schemas_dir.mkdir(parents=True)
    (settings.schemas_dir / "contacts@1.schema.json").write_text(json.dumps(SCHEMA))

    async def look() -> list[str]:
        histories.commit_all()
        (folder / "plain.md").write_text("# no schema\n")
        (folder / "good.md").write_text(GOOD)
        histories.commit_all()
        (folder / "bad.md").write_text(BROKEN)
        histories.commit_all()
        (folder / "bad.md").unlink()
        histories.commit_all()
        return [m.summary or "" for m in histories.inbox.list() if m.source == "notes"]

    [warning] = asyncio.run(look())
    assert warning.startswith("bad.md:")
    [message] = histories.inbox.list()
    assert (message.name, message.status, message.person) == ("people", "attention", "owner")


@pytest.mark.rule("knowledge.history-check-only-warns")
def test_a_broken_document_in_an_app_s_folder_is_the_app_s_warning(
    histories: NotesHistories,
    app_folders: list[WrittenFolder],
    settings: Settings,
    tmp_path: Path,
) -> None:
    """A broken document in an app's folder outside the notes is a warning from the app (its
    page holds that folder's history), never one naming a notes folder that is not one.

    If this fails: the inbox's warning leads to a notes folder that does not exist."""
    settings.schemas_dir.mkdir(parents=True)
    (settings.schemas_dir / "contacts@1.schema.json").write_text(json.dumps(SCHEMA))
    cv = tmp_path / "home" / "cv"
    cv.mkdir(parents=True)
    app_folders.append(given(cv))

    async def look() -> None:
        histories.begin_new()
        (cv / "bad.md").write_text(BROKEN)
        histories.commit_all()

    asyncio.run(look())
    [message] = histories.inbox.list()
    assert (message.source, message.name, message.status) == ("app", "cv", "attention")
    assert (message.summary or "").startswith("bad.md:")


@pytest.mark.rule("notes.writable-has-a-history")
def test_a_large_file_is_left_out(
    histories: NotesHistories, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notes_history, "MAX_FILE_BYTES", 10)
    (folder / "big.bin").write_bytes(b"12345678901")
    [first] = histories.commit_all()
    assert first.file_count == 1


@pytest.mark.rule("notes.writable-has-a-history")
def test_a_folder_given_read_write_keeps_its_state_before_any_write(
    histories: NotesHistories, registry: AgentRegistry, folder: Path, settings: Settings
) -> None:
    """When an agent is saved with a folder read-write, a folder with no history yet gets its
    first state then, not at the next look: what it held before any agent wrote is kept.

    If this fails: an agent given write access changes a file in its first minutes and the
    version you wrote is nowhere."""
    assert settings.knowledge_dir is not None
    (settings.knowledge_dir / "later").mkdir()
    (settings.knowledge_dir / "later" / "mine.md").write_text("mine\n")
    registry.listeners.append(histories.begin_new)
    reader = agent(registry, "reader")
    reader.knowledge = [*reader.knowledge, KnowledgeFolderUse(folder="later", access="write")]
    registry.save()
    [first] = histories.history("later").commits
    assert (first.kind, first.file_count) == ("first", 1)
    assert histories.history("people").commits[0].kind == "first"
    registry.save()  # nothing new: nothing more
    assert len(histories.history("later").commits) == 1


@pytest.mark.rule("notes.writable-has-a-history", "notes.history-names-who-could-write")
def test_an_app_s_folder_has_a_history_named_after_the_app(
    histories: NotesHistories,
    registry: AgentRegistry,
    app_folders: list[WrittenFolder],
    tmp_path: Path,
) -> None:
    """A folder given to an app's files need in rw, outside the notes, has a history like a
    notes folder's, named by its full path: its commits name the app when it ran in the lapse;
    its changes are undone the same way.

    If this fails: what an app changed in your files is nowhere to be undone, or the history
    does not say the app could have done it."""
    cv = tmp_path / "home" / "cv"
    cv.mkdir(parents=True)
    (cv / "roles.md").write_text("mine\n")
    app_folders.append(given(cv, last_used_at=datetime.now(UTC)))
    histories.begin_new()
    [first] = histories.history(str(cv)).commits
    assert (first.kind, first.file_count) == ("first", 1)
    (cv / "roles.md").write_text("by the app\n")
    ran(registry, "writer")  # an agent not given the folder: not one of its writers
    [changed] = [c for c in histories.commit_all() if c.files[0].path == "roles.md"]
    assert [(w.app, w.agent_id, w.name) for w in changed.could_write] == [
        ("cv", None, "CV assistant")
    ]
    listed = histories.history(str(cv)).commits
    assert listed[0].could_write == changed.could_write  # read back from the commit
    assert (
        histories.commit(str(cv), changed.id).files[0].diff == "@@ -1 +1 @@\n-mine\n+by the app\n"
    )
    histories.undo(str(cv), changed.id)
    assert (cv / "roles.md").read_text() == "mine\n"

    # the app no longer given it: the history stays, nothing to undo there
    app_folders.clear()
    assert str(cv) not in histories.writable()
    kinds = [c.kind for c in histories.history(str(cv)).commits]
    assert kinds == ["undo", "changes", "first"]
    with pytest.raises(NotesHistoryConflictError):
        histories.undo(str(cv), changed.id)
    with pytest.raises(NotesHistoryMissingError):
        histories.history(str(tmp_path / "home"))


@pytest.mark.rule("notes.writable-has-a-history")
def test_a_notes_folder_given_to_an_app_has_one_history(
    histories: NotesHistories,
    app_folders: list[WrittenFolder],
    folder: Path,
) -> None:
    """A notes folder an agent writes and an app is given in rw has one history, named as a
    notes folder, its writers both; asked by its full path, it is the same.

    If this fails: two histories of one folder, each blaming half its writers."""
    app_folders.append(given(folder, running=True))
    assert list(histories.writable()) == ["people"]
    histories.commit_all()
    (folder / "a.md").write_text("changed\n")
    [changed] = histories.commit_all()
    assert [w.name for w in changed.could_write] == ["CV assistant"]  # the agent did not run
    assert histories.history(str(folder)).commits == histories.history("people").commits
