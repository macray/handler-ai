"""Unit tests of addon_folders.py: an addon's image extracted into the folder agents mount, the
current one switched by a build, the others removed once no sandbox mounts them (G.4, A.1)."""

from pathlib import Path

import pytest

from handler_control import addon_folders
from handler_control.settings import Settings
from handler_harness import addons as catalog


@pytest.fixture
def tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> catalog.Addon:
    root = tmp_path / "addons" / "tool"
    root.mkdir(parents=True)
    (root / "tool.toml").write_text(
        'apiVersion = "handler.tool/v1"\nname = "tool"\n'
        'image = "localhost/handler-ai-tool-tool"\ncommands = ["tool"]\n'
    )
    (root / "Containerfile").write_text("FROM scratch\n")
    monkeypatch.setenv("HANDLER_TOOLS_DIR", str(root.parent))
    return catalog.get("tool")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        port=0,
        config_dir=tmp_path,
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path / "bindings",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
        data_dir=tmp_path / "data",
    )


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The runtime's `image extract` (a version file and a command per image) and `cache clear`
    (refused for the folders in `mounted`: folder → the sandbox mounting it)."""
    mounted: dict[str, str] = {}

    def extract(ref: str, path: str, folder: Path) -> str | None:
        assert path == "/"  # the image is the installed tree (G.1)
        (folder / "bin").mkdir(parents=True)
        (folder / "bin" / "tool").write_text("#!/bin/sh\n")
        (folder / "version").write_text(f"tool {ref}\n")
        return None

    def clear_cache(folder: Path) -> str | None:
        if str(folder) in mounted:
            return f"in use by {mounted[str(folder)]}"
        return None

    monkeypatch.setattr(addon_folders.runtime, "extract", extract)
    monkeypatch.setattr(addon_folders.runtime, "clear_cache", clear_cache)
    return mounted


@pytest.mark.rule("tool.runs-from-a-read-only-folder")
def test_a_build_s_folder_is_current_once_switched(
    settings: Settings, tool: catalog.Addon, runtime: dict[str, str]
) -> None:
    assert not addon_folders.built(settings, "tool")
    assert addon_folders.folder(settings, "tool").name == "not-built"  # does not exist
    one = addon_folders.extract(settings, tool, "aaa")
    assert not addon_folders.built(settings, "tool")  # extracted, not current yet
    assert not (one / "version").stat().st_mode & 0o222  # read-only
    addon_folders.switch(settings, "tool", "aaa")
    assert addon_folders.folder(settings, "tool") == one
    assert addon_folders.version(settings, tool) == "tool aaa"
    assert addon_folders.built_at(settings, "tool") is not None


@pytest.mark.rule("tool.runs-from-a-read-only-folder")
def test_the_folders_no_sandbox_mounts_go(
    settings: Settings, tool: catalog.Addon, runtime: dict[str, str]
) -> None:
    one = addon_folders.extract(settings, tool, "aaa")
    addon_folders.switch(settings, "tool", "aaa")
    runtime[str(one)] = "handler-a1-c1"  # a running sandbox mounts it
    two = addon_folders.extract(settings, tool, "bbb")
    addon_folders.switch(settings, "tool", "bbb")
    assert one.is_dir() and addon_folders.folder(settings, "tool") == two  # kept while mounted
    del runtime[str(one)]  # that sandbox ended
    addon_folders.sweep(settings)
    assert not one.exists() and two.is_dir()
    failed = addon_folders.extract(settings, tool, "ccc")  # a build that failed its check
    addon_folders.sweep(settings)  # a sandbox ending while it is checked
    assert failed.is_dir()
    addon_folders.release(settings, "tool", "ccc")  # that build ended
    addon_folders.sweep(settings)
    assert not failed.exists() and two.is_dir()


@pytest.mark.rule("tool.runs-from-a-read-only-folder")
def test_an_uninstalled_addon_s_folders_go(
    settings: Settings, tool: catalog.Addon, runtime: dict[str, str]
) -> None:
    addon_folders.extract(settings, tool, "aaa")
    addon_folders.switch(settings, "tool", "aaa")
    addon_folders.forget(settings, "tool")
    assert not addon_folders.root(settings, "tool").exists()


@pytest.mark.rule("tool.runs-from-a-read-only-folder")
def test_a_partial_extraction_is_redone(
    settings: Settings, tool: catalog.Addon, runtime: dict[str, str]
) -> None:
    partial = addon_folders.root(settings, "tool") / ".aaa.partial"
    partial.mkdir(parents=True)
    (partial / "half").write_text("x")
    folder = addon_folders.extract(settings, tool, "aaa")
    assert sorted(p.name for p in folder.iterdir()) == ["bin", "version"]
    assert not partial.exists()
