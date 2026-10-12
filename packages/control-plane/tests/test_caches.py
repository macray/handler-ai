"""Unit tests of caches.py: the toolbox's caches as a project shares them (D.8)."""

from pathlib import Path

import pytest

from handler_control import caches
from handler_control.settings import Settings


def settings(tmp_path: Path) -> Settings:
    return Settings(
        port=0,
        config_dir=tmp_path,
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path,
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )


def test_the_toolbox_caches_global_kept_by_the_project_or_none(tmp_path: Path) -> None:
    s = settings(tmp_path)
    shared = caches.mounts(s, "global", "p_1")
    assert shared["~/.cargo"] == str(tmp_path / "cache" / "cargo")
    assert set(shared) == {  # the default toolbox.toml
        "~/.cargo",
        "~/.rustup",
        "~/.bun",
        "~/.m2",
        "~/.npm",
        "~/.cache",
        "~/.local",
        "~/.local/share/containers/storage",
    }
    own = caches.mounts(s, "project", "p_1")
    assert own["~/.cargo"] == str(tmp_path / "data" / "caches" / "p_1" / "cargo")
    assert caches.mounts(s, "off", "p_1") == {}
    assert caches.mounts(s, "global", None) == shared  # an ad-hoc agent


def test_a_deleted_project_loses_its_own_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Emptied through the sandbox (its files may be inner ids'), then removed."""
    emptied: list[Path] = []
    monkeypatch.setattr(caches.runtime, "clear_cache", emptied.append)
    s = settings(tmp_path)
    folder = Path(caches.mounts(s, "project", "p_1")["~/.cargo"])
    folder.mkdir(parents=True)
    caches.remove_project(s, "p_1")
    assert not caches.project_dir(s, "p_1").exists()
    assert emptied == [caches.project_dir(s, "p_1")]


def test_a_project_still_in_use_keeps_its_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(caches.runtime, "clear_cache", lambda folder: "in use by a sandbox")
    s = settings(tmp_path)
    caches.project_dir(s, "p_1").mkdir(parents=True)
    caches.remove_project(s, "p_1")
    assert caches.project_dir(s, "p_1").exists()
