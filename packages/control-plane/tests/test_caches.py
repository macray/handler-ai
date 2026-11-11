"""Unit tests of caches.py: the toolbox's caches as a project shares them (D.8)."""

from pathlib import Path

import pytest

from handler_contracts import CacheDeclaration
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


def mounted(found: list[tuple[CacheDeclaration, str]]) -> dict[str, str]:
    return {cache.target: folder for cache, folder in found}


@pytest.mark.rule("project.caches-are-its-own-unless-shared")
def test_the_toolbox_caches_global_kept_by_the_project_or_none(tmp_path: Path) -> None:
    s = settings(tmp_path)
    shared = mounted(caches.mounts(s, "global", "p_1", []))
    assert shared["~/.npm"] == str(tmp_path / "cache" / "npm")
    assert set(shared) == {  # the base's, then podman's (the default toolbox.toml)
        "~/.npm",
        "~/.cache",
        "~/.local",
        "~/.local/share/containers/storage",
    }
    own = mounted(caches.mounts(s, "project", "p_1", []))
    assert own["~/.npm"] == str(tmp_path / "data" / "caches" / "p_1" / "npm")
    assert caches.mounts(s, "off", "p_1", []) == []
    assert mounted(caches.mounts(s, "global", None, [])) == shared  # an ad-hoc agent


JAVA = """apiVersion = "handler.tool/v1"
name = "{name}"
[[caches]]
target = "~/.m2"
about = "{about}"
[[caches]]
target = "~/.java-{name}"
about = "{name}'s own"
bin = "bin"
"""


def test_an_addon_s_caches_for_the_agents_using_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D.8, G.1: an addon declares its caches; an agent gets those of the addons it uses, one
    target is one cache whoever declares it (the first one's words), a commands' folder is on
    PATH."""
    root = tmp_path / "addons"
    for name, about in (("java", "Maven repository"), ("java-21", "Maven's packages")):
        (root / name).mkdir(parents=True)
        (root / name / "tool.toml").write_text(JAVA.format(name=name, about=about))
    monkeypatch.setenv("HANDLER_TOOLS_DIR", str(root))
    s = settings(tmp_path)
    m2 = caches.declared()["m2"]
    assert (m2.about, m2.declared_by) == ("Maven repository", ["addon:java", "addon:java-21"])
    assert "m2" not in mounted(caches.mounts(s, "global", None, []))  # not using java
    with_java = caches.mounts(s, "global", None, ["java"])
    assert mounted(with_java)["~/.m2"] == str(tmp_path / "cache" / "m2")
    assert "~/.java-java-21" not in mounted(with_java)
    [own] = [c for c, _ in with_java if c.target == "~/.java-java"]
    assert own.bin == "bin"


def test_a_deleted_project_loses_its_own_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Emptied through the sandbox (its files may be inner ids'), then removed."""
    emptied: list[Path] = []
    monkeypatch.setattr(caches.runtime, "clear_cache", emptied.append)
    s = settings(tmp_path)
    folder = Path(mounted(caches.mounts(s, "project", "p_1", []))["~/.npm"])
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
