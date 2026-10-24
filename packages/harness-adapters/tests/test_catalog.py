"""Where the harnesses, the toolbox and the addons are found (B.6, G.1)."""

from pathlib import Path

import pytest

from handler_harness import addons, catalog


def test_seeding_copies_the_default_toolbox_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HANDLER_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("HANDLER_TOOLBOX_DIR", raising=False)
    assert catalog.toolbox_dir() == tmp_path / "toolbox"
    assert catalog.seed_toolbox()
    containerfile = tmp_path / "toolbox" / "Containerfile"
    assert containerfile.read_text() == (catalog.DEFAULT_TOOLBOX / "Containerfile").read_text()
    containerfile.write_text("FROM scratch\n")  # the user's now
    assert not catalog.seed_toolbox()
    assert containerfile.read_text() == "FROM scratch\n"
    assert catalog.toolbox().caches  # its toolbox.toml


def test_the_default_toolbox_holds_nothing_of_handler() -> None:
    """handler-sandbox-env comes with the launch, inner podman's configuration with the sandbox."""
    text = (catalog.DEFAULT_TOOLBOX / "Containerfile").read_text()
    assert "COPY" not in text and "/etc/containers" not in text


def test_a_users_addon_replaces_a_builtin_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HANDLER_ADDONS_DIR", str(tmp_path))
    builtin = addons.get("app-builder")
    assert builtin.builtin and builtin.directory == addons.BUILTIN_DIR / "app-builder"
    mine = tmp_path / "app-builder"
    mine.mkdir()
    (mine / "addon.toml").write_text('apiVersion = "handler.addon/v1"\nname = "app-builder"\n')
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
