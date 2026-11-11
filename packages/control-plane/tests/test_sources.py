"""D.26: sources read from git repositories (local ones here), what they offer, and installing an
addon or agents from one (an app: test_apps.py)."""

import dataclasses
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from dulwich import porcelain
from dulwich.objects import Blob, Commit, Tree
from dulwich.refs import HEADREF, Ref
from dulwich.repo import Repo
from source_repo import TEST_SOURCE, git_repo

from handler_contracts import SOURCE_MANIFEST
from handler_control import addon_install, agents_files, sources
from handler_control.agents import AgentRegistry
from handler_control.app_runs import AppRuns
from handler_control.apps import AppStore
from handler_control.inbox import Inbox
from handler_control.projects import ProjectRegistry
from handler_control.sessions import SessionStore
from handler_control.settings import Settings
from handler_harness import addons
from handler_harness import toolbox as toolbox_parts

SOURCE = 'apiVersion = "handler.source/v1"\nname = "Acme"\n'


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("HANDLER_TOOLS_DIR", str(tmp_path / "config" / "addons"))
    return Settings(
        port=0,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path / "config" / "bindings",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
        official_source=str(git_repo(TEST_SOURCE, tmp_path / "official")),
    )


@pytest.fixture
def https(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    """https://example.com/<name> read from the local repository registered under that URL."""
    repos: dict[str, Path] = {}
    clone = porcelain.clone

    def local(url: str, target: str, **kwargs: Any) -> Repo:
        return clone(str(repos.get(url, tmp_path / "nowhere")), target, **kwargs)

    monkeypatch.setattr(sources.porcelain, "clone", local)
    return repos


def acme(tmp_path: Path) -> Path:
    """A source offering an addon and agents (an agents file's content)."""
    folder = tmp_path / "acme-src"
    (folder / "tools" / "notes" / "skills" / "notes").mkdir(parents=True)
    (folder / SOURCE_MANIFEST).write_text(SOURCE)
    (folder / "tools" / "notes" / "tool.toml").write_text(
        'apiVersion = "handler.tool/v1"\nname = "notes"\ndescription = "take notes"\n'
    )
    (folder / "tools" / "notes" / "skills" / "notes" / "SKILL.md").write_text(
        "---\nname: notes\ndescription: take notes\n---\nTake notes.\n"
    )
    agent = folder / "agents" / "helpers" / "agents" / "writer"
    agent.mkdir(parents=True)
    (folder / "agents" / "helpers" / "agents.toml").write_text(
        'name = "helpers"\ndescription = "two hands"\nversion = 3\nplace = "project"\n'
    )
    (agent / "agent.toml").write_text('[agent]\nname = "Writer"\n')
    (folder / "README.md").write_text("not offered")
    return folder


@pytest.mark.rule("source.a-failed-read-keeps-the-last")
def test_the_official_source_is_read_with_what_it_offers(settings: Settings) -> None:
    [official] = sources.listed(settings)
    assert official.official and official.id == "official"
    assert sources.stale(settings, "official")
    sources.fetch(settings, official)
    state = sources.read(settings, "official")
    assert state.error is None and state.commit and state.manifest
    assert state.manifest.name == "Test source" and not sources.stale(settings, "official")
    offered = {(kind, name) for kind, name, folder, _ in sources.items(settings, "official")}
    assert offered == {
        ("app", "journal"),
        ("addon", "fake-browser"),
        ("addon", "fake-shop"),
        ("addon", "fake-toolchain"),
        ("agents", "helpers"),
        ("system-package", "fake-cc"),
    }
    assert (sources.item(settings, "official", "app", "journal") / "app.toml").is_file()
    with pytest.raises(sources.SourceError, match="offers no addon named nope"):
        sources.item(settings, "official", "addon", "nope")


@pytest.mark.rule("source.added-once-read")
def test_a_source_is_added_named_from_its_url_and_removed(
    settings: Settings, tmp_path: Path, https: dict[str, Path]
) -> None:
    url = "https://example.com/acme/Tools.git"
    https[url] = git_repo(acme(tmp_path), tmp_path / "acme")
    added = sources.add(settings, url)
    assert added.id == "tools" and [s.id for s in sources.listed(settings)] == ["official", "tools"]
    with pytest.raises(sources.SourceError, match=r"example\.com/acme/Tools"):
        sources.add(settings, "https://example.com/acme/Tools/")  # the same repository
    assert sources.new_id("https://example.com/b/tools", {"tools"}) == "tools-2"
    assert sources.new_id("https://example.com/official", set()) == "official-2"
    with pytest.raises(sources.SourceError, match="cannot be removed"):
        sources.remove(settings, "official")
    sources.remove(settings, "tools")
    assert [s.id for s in sources.listed(settings)] == ["official"]
    assert not sources.cache(settings, "tools").exists()


@pytest.mark.rule("source.added-once-read")
def test_a_repository_that_is_no_source_is_not_added(
    settings: Settings, tmp_path: Path, https: dict[str, Path]
) -> None:
    folder = acme(tmp_path)
    (folder / SOURCE_MANIFEST).unlink()
    https["https://example.com/plain"] = git_repo(folder, tmp_path / "plain")
    with pytest.raises(sources.SourceError, match=f"no {SOURCE_MANIFEST}"):
        sources.add(settings, "https://example.com/plain")
    with pytest.raises(sources.SourceError, match="cannot read"):
        sources.add(settings, "https://example.com/missing")
    assert [s.id for s in sources.listed(settings)] == ["official"]
    assert not sources.cache(settings, "plain").exists()


@pytest.mark.rule("source.a-failed-read-keeps-the-last")
def test_a_failed_read_keeps_what_was_read_before(
    settings: Settings, tmp_path: Path, https: dict[str, Path]
) -> None:
    url = "https://example.com/acme"
    https[url] = git_repo(acme(tmp_path), tmp_path / "acme")
    source = sources.add(settings, url)
    before = sources.read(settings, "acme").commit
    shutil.rmtree(https.pop(url))
    sources.fetch(settings, source)
    state = sources.read(settings, "acme")
    assert state.error and "cannot read" in state.error and state.commit == before
    assert sources.item(settings, "acme", "addon", "notes").is_dir()


@pytest.mark.rule("source.nothing-of-it-runs")
def test_an_item_holding_a_link_is_not_offered(
    settings: Settings, tmp_path: Path, https: dict[str, Path]
) -> None:
    folder = acme(tmp_path)
    os.symlink("/etc/passwd", folder / "tools" / "notes" / "passwd")
    https["https://example.com/acme"] = git_repo(folder, tmp_path / "acme")
    sources.add(settings, "https://example.com/acme")
    found = {name: (folder, why) for _, name, folder, why in sources.items(settings, "acme")}
    assert found["notes"] == (None, "it holds a link: passwd")
    assert found["helpers"][0] is not None
    assert not (sources.cache(settings, "acme") / "tree" / "tools" / "notes").exists()
    assert not (sources.cache(settings, "acme") / "tree" / "README.md").exists()
    with pytest.raises(sources.SourceError, match="holds a link"):
        sources.item(settings, "acme", "addon", "notes")


def crafted_repo(path: Path, unsafe: bytes) -> Path:
    """A bare repository whose tree git itself would refuse: `apps/<unsafe>/ESCAPED`, made from
    objects (a malicious server serves such a pack as it is)."""
    repo = Repo.init_bare(str(path), mkdir=True)
    store = repo.object_store

    def add(obj: Any) -> Any:
        store.add_object(obj)
        return obj

    def tree(name: bytes, mode: int, obj: Any) -> Tree:
        t = Tree()
        t.add(name, mode, obj.id)
        return add(t)

    escaped = tree(b"ESCAPED", 0o100755, add(Blob.from_string(b"#!/bin/sh\n")))
    for _ in range(4):  # out of tree/, the source's folder, sources/, state/
        escaped = tree(b"..", 0o040000, escaped)
    apps = tree(unsafe, 0o040000, escaped)
    root = Tree()
    root.add(b"apps", 0o040000, apps.id)
    root.add(SOURCE_MANIFEST.encode(), 0o100644, add(Blob.from_string(SOURCE.encode())).id)
    add(root)
    commit = Commit()
    commit.tree, commit.message = root.id, b"evil"
    commit.author = commit.committer = b"x <x@example.com>"
    commit.commit_time = commit.author_time = 0
    commit.commit_timezone = commit.author_timezone = 0
    repo.refs[Ref(b"refs/heads/main")] = add(commit).id
    repo.refs.set_symbolic_ref(HEADREF, Ref(b"refs/heads/main"))
    return path


@pytest.mark.rule("source.nothing-of-it-runs")
@pytest.mark.parametrize("unsafe", [b"..", b".", b".git", b""])
def test_a_tree_with_an_unsafe_path_is_no_source_and_writes_nothing(
    settings: Settings, tmp_path: Path, https: dict[str, Path], unsafe: bytes
) -> None:
    https["https://example.com/evil"] = crafted_repo(tmp_path / "evil.git", unsafe)
    with pytest.raises(sources.SourceError, match="unsafe path"):
        sources.add(settings, "https://example.com/evil")
    assert not list(tmp_path.rglob("ESCAPED"))
    assert [s.id for s in sources.listed(settings)] == ["official"]


@pytest.mark.rule("tool.installed-as-previewed")
def test_an_addon_from_a_source_is_installed_and_its_update_seen(settings: Settings) -> None:
    sources.fetch(settings, sources.get(settings, "official"))
    seen = addon_install.preview(settings, "source:official/fake-shop")
    assert seen.image == "localhost/handler-ai-tool-fake-shop" and seen.commands == ["fake-shop"]
    addon_install.install(settings, "source:official/fake-shop", seen.digest)
    assert not addons.get("fake-shop").builtin
    assert addon_install.lock()["fake-shop"].source == "source:official/fake-shop"
    assert addon_install.source_digest(settings, "source:official/fake-shop") == seen.digest
    tree = sources.item(settings, "official", "addon", "fake-shop")
    (tree / "tool.toml").write_text((tree / "tool.toml").read_text() + "\n")  # a new commit
    assert addon_install.source_digest(settings, "source:official/fake-shop") != seen.digest
    with pytest.raises(addon_install.AddonInstallError, match="offers no addon named nope"):
        addon_install.preview(settings, "source:official/nope")
    addon_install.remove("fake-shop")


@pytest.mark.rule("source.each-item-by-its-kind-s-rules")
def test_agents_from_a_source_are_read_as_a_file(
    settings: Settings, tmp_path: Path, https: dict[str, Path]
) -> None:
    https["https://example.com/acme"] = git_repo(acme(tmp_path), tmp_path / "acme")
    sources.add(settings, "https://example.com/acme")
    file = agents_files.stage_folder(settings, sources.item(settings, "acme", "agents", "helpers"))
    assert (file.name, file.version, file.description) == ("helpers", 3, "two hands")
    assert agents_files.get(settings, "helpers") == file
    renamed = tmp_path / "other"
    shutil.copytree(sources.item(settings, "acme", "agents", "helpers"), renamed)
    with pytest.raises(agents_files.AgentsFileError, match="names another file, helpers"):
        agents_files.stage_folder(settings, renamed)


@pytest.mark.rule("tool.installed-as-previewed")
def test_an_addon_brings_the_system_package_of_its_source_it_needs(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B.7: what the toolbox lacks that no system package of Handler's or the user's provides
    comes from the addon's own source, shown in its preview (its install script), covered by
    the preview's digest, installed only when confirmed (`toolboxAdds`)."""
    toolbox_dir = tmp_path / "toolbox"
    toolbox_dir.mkdir()
    (toolbox_dir / "toolbox.toml").write_text('distro = "fedora"\n')
    monkeypatch.setenv("HANDLER_TOOLBOX_DIR", str(toolbox_dir))
    sources.fetch(settings, sources.get(settings, "official"))
    offered = {(k, n) for k, n, _, _ in sources.items(settings, "official")}
    assert ("system-package", "fake-cc") in offered
    source = "source:official/fake-toolchain"
    seen = addon_install.preview(settings, source)
    [add] = seen.toolbox.adds
    assert (add.name, add.provides, add.source) == (
        "fake-cc",
        ["fake-cc"],
        "source:official/fake-cc",
    )
    assert add.script and "/usr/local/bin/fake-cc" in add.script
    assert seen.toolbox.has == [] and seen.toolbox.lacking == []
    assert seen.digest != addon_install.digest(
        sources.item(settings, "official", "addon", "fake-toolchain")
    )
    with pytest.raises(addon_install.ToolboxNotConfirmedError) as refused:
        addon_install.install(settings, source, seen.digest)
    assert refused.value.adds == ["fake-cc"]
    assert not (toolbox_parts.user_dir() / "fake-cc").exists()
    installed = addon_install.install(settings, source, seen.digest, ["fake-cc"])
    assert (installed.name, installed.adds, installed.lacking) == (
        "fake-toolchain",
        ["fake-cc"],
        [],
    )
    assert toolbox_parts.get("fake-cc").manifest.provides == ["fake-cc"]
    assert addon_install.packages_lock()["fake-cc"].source == "source:official/fake-cc"
    # installed now: a second addon needing it would find it, nothing more from the source
    again = addon_install.preview(settings, source)
    assert [(a.name, a.source) for a in again.toolbox.adds] == [("fake-cc", None)]


@pytest.mark.rule("source.only-offers")
def test_removing_a_source_keeps_what_came_from_it(
    settings: Settings, tmp_path: Path, https: dict[str, Path]
) -> None:
    """An addon installed from a source and an app taken from it: the source removed, both are
    still there, as they were.

    If this fails: removing a repository you added takes away an addon or an app you use."""
    folder = acme(tmp_path)
    shutil.copytree(TEST_SOURCE / "apps" / "journal", folder / "apps" / "journal")
    https["https://example.com/acme"] = git_repo(folder, tmp_path / "acme")
    sources.add(settings, "https://example.com/acme")
    seen = addon_install.preview(settings, "source:acme/notes")
    addon_install.install(settings, "source:acme/notes", seen.digest)
    settings = dataclasses.replace(settings, data_dir=tmp_path / "data")
    inbox, registry = Inbox(settings), AgentRegistry(settings.state_dir)
    runs = AppRuns(
        settings,
        SessionStore(settings, registry),
        ProjectRegistry(settings.state_dir, registry),
        inbox,
    )
    apps = AppStore(settings, token="t0ken", inbox=inbox, runs=runs)
    apps.add_from_source("acme", sources.item(settings, "acme", "app", "journal"))
    code = apps.source("journal")
    kept = sorted(p.relative_to(code).as_posix() for p in code.rglob("*"))
    sources.remove(settings, "acme")
    assert addons.get("notes").manifest.description == "take notes"
    assert addon_install.lock()["notes"].source == "source:acme/notes"
    assert apps.view("journal").from_source == "acme"
    assert sorted(p.relative_to(code).as_posix() for p in code.rglob("*")) == kept
    addon_install.remove("notes")
