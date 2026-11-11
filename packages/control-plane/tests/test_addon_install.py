"""G.5: installing addons from a folder or an archive, and removing them (from a source:
test_sources.py)."""

import contextlib
import io
import tarfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from handler_control import addon_install
from handler_control.addon_install import AddonInstallError
from handler_control.settings import Settings
from handler_harness import addons

MANIFEST = 'apiVersion = "handler.tool/v1"\nname = "notes"\ndescription = "take notes"\n'


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
    )


def own_addon(root: Path) -> Path:
    folder = root / "notes"
    (folder / "skills" / "notes").mkdir(parents=True)
    (folder / "tool.toml").write_text(MANIFEST)
    (folder / "skills" / "notes" / "SKILL.md").write_text("---\nname: notes\n---\nTake notes.\n")
    return folder


@pytest.mark.rule("tool.installed-as-previewed")
def test_preview_then_install_from_a_folder(settings: Settings, tmp_path: Path) -> None:
    source = str(own_addon(tmp_path / "src"))
    seen = addon_install.preview(settings, source)
    assert (seen.name, seen.description, seen.skills, seen.replaces) == (
        "notes", "take notes", ["notes"], None,
    )  # fmt: skip
    assert addon_install.install(settings, source, seen.digest).name == "notes"
    assert addons.get("notes").directory == addons.user_dir() / "notes"
    [entry] = addon_install.lock().values()
    assert (entry.source, entry.digest) == (source, seen.digest)
    assert addon_install.preview(settings, source).replaces == "installed"


@pytest.mark.rule("tool.installed-as-previewed")
def test_install_refuses_content_other_than_the_preview(settings: Settings, tmp_path: Path) -> None:
    folder = own_addon(tmp_path / "src")
    seen = addon_install.preview(settings, str(folder))
    (folder / "tool.toml").write_text(MANIFEST + 'egress = ["evil.example.com:443"]\n')
    with pytest.raises(AddonInstallError, match="changed since its preview"):
        addon_install.install(settings, str(folder), seen.digest)
    assert not (addons.user_dir() / "notes").exists()


@pytest.mark.rule("tool.an-install-stays-in-its-folder")
def test_a_link_out_of_the_folder_is_refused(settings: Settings, tmp_path: Path) -> None:
    folder = own_addon(tmp_path / "src")
    (tmp_path / "secret").write_text("key")
    (folder / "skills" / "notes" / "key").symlink_to(tmp_path / "secret")
    with pytest.raises(AddonInstallError, match="links outside the tool"):
        addon_install.preview(settings, str(folder))


@pytest.mark.rule("tool.an-install-stays-in-its-folder")
def test_a_name_that_is_a_path_is_refused_before_anything_is_copied(
    settings: Settings, tmp_path: Path
) -> None:
    folder = own_addon(tmp_path / "src")
    (folder / "tool.toml").write_text(MANIFEST.replace('"notes"', '"../../../ESCAPED"', 1))
    with pytest.raises(AddonInstallError, match="name"):
        addon_install.preview(settings, str(folder))
    assert not list(tmp_path.rglob("ESCAPED"))


@pytest.mark.rule("tool.yours-is-never-replaced")
def test_the_users_own_addon_is_never_replaced_nor_removed(
    settings: Settings, tmp_path: Path
) -> None:
    own_addon(addons.user_dir())  # written by the user: not in the lock
    source = str(own_addon(tmp_path / "src"))
    seen = addon_install.preview(settings, source)
    assert seen.replaces == "own"
    with pytest.raises(AddonInstallError, match="your own tool"):
        addon_install.install(settings, source, seen.digest)
    with pytest.raises(AddonInstallError, match="not installed by handler"):
        addon_install.remove("notes")
    assert (addons.user_dir() / "notes" / "tool.toml").is_file()


@pytest.mark.rule("tool.an-install-stays-in-its-folder")
def test_a_relative_folder_or_plain_http_is_refused(settings: Settings) -> None:
    with pytest.raises(AddonInstallError, match="absolute path"):
        addon_install.preview(settings, "src/notes")
    with pytest.raises(AddonInstallError, match="https:// only"):
        addon_install.preview(settings, "http://example.com/notes.tar.gz")


@pytest.mark.rule("tool.an-install-stays-in-its-folder")
def test_an_archive_unpacks_with_its_top_folder(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A forge's archive of an addon repository: one top folder, tool.toml in it."""
    folder = own_addon(tmp_path / "src")
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        tar.add(folder, arcname="notes-main")
    archive = data.getvalue()

    class Answer:
        def raise_for_status(self) -> None:
            pass

        def iter_bytes(self) -> Iterator[bytes]:
            yield archive

    @contextlib.contextmanager
    def stream(method: str, url: str, **_: object) -> Iterator[Answer]:
        assert (method, url) == ("GET", "https://forge.example/notes/archive/main.tar.gz")
        yield Answer()

    monkeypatch.setattr(addon_install.httpx, "stream", stream)
    seen = addon_install.preview(settings, "https://forge.example/notes/archive/main.tar.gz")
    assert seen.name == "notes" and seen.digest == addon_install.digest(folder)
