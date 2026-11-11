"""Where the harnesses, the toolbox and the addons are found (B.6, G.1)."""

from pathlib import Path

import pytest

from handler_harness import addons, catalog, toolbox


@pytest.mark.rule("toolbox.made-of-its-three-parts")
def test_seeding_writes_the_default_toolbox_toml_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HANDLER_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("HANDLER_TOOLBOX_DIR", raising=False)
    assert catalog.toolbox_dir() == tmp_path / "toolbox"
    assert catalog.seed_toolbox()
    written = tmp_path / "toolbox" / "toolbox.toml"
    assert written.read_text() == (catalog.DEFAULT_TOOLBOX / "toolbox.toml").read_text()
    assert [p.name for p in (tmp_path / "toolbox").iterdir()] == ["toolbox.toml"]
    written.write_text('distro = "fedora"\n')  # the user's choice now
    assert not catalog.seed_toolbox()
    assert catalog.toolbox().system_packages == {}


@pytest.mark.rule("toolbox.nothing-of-handler-in-it")
def test_the_default_toolbox_holds_nothing_of_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """handler-sandbox-env comes with the launch: no file of Handler is copied into the toolbox."""
    monkeypatch.setenv("HANDLER_TOOLBOX_DIR", str(catalog.DEFAULT_TOOLBOX))
    text = toolbox.containerfile(catalog.toolbox(), "")
    assert "COPY" not in text and "ADD" not in text


def test_a_users_addon_replaces_a_builtin_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HANDLER_TOOLS_DIR", str(tmp_path))
    builtin = addons.get("app-builder")
    assert builtin.builtin and builtin.directory == addons.BUILTIN_DIR / "app-builder"
    mine = tmp_path / "app-builder"
    mine.mkdir()
    (mine / "tool.toml").write_text('apiVersion = "handler.tool/v1"\nname = "app-builder"\n')
    replaced = addons.get("app-builder")
    assert replaced.directory == mine and replaced.overrides_builtin and not replaced.builtin
    assert addons.names().count("app-builder") == 1


def test_the_default_toolbox_toml_is_as_handler_writes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings → Caches rewrites it (D.8): the default reads the same, comments included."""
    monkeypatch.setenv("HANDLER_TOOLBOX_DIR", str(tmp_path))
    default = (catalog.DEFAULT_TOOLBOX / "toolbox.toml").read_text()
    (tmp_path / "toolbox.toml").write_text(default)
    catalog.save_toolbox(catalog.toolbox())
    assert (tmp_path / "toolbox.toml").read_text() == default
