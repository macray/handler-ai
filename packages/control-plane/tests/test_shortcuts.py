"""Unit tests: GNOME keyboard shortcuts (H.7), with the real gsettings on a keyfile backend and
the part of GNOME's schema handler uses."""

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from handler_control import shortcuts

FIXTURE = Path(__file__).parent / "fixtures" / f"{shortcuts.SCHEMA}.gschema.xml"
USERS = f"['{shortcuts.BASE}custom0/']"

pytestmark = pytest.mark.skipif(
    not (shutil.which("gsettings") and shutil.which("glib-compile-schemas")),
    reason="gsettings not installed",
)


@pytest.fixture
def gnome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    shutil.copy(FIXTURE, schemas)
    subprocess.run(["glib-compile-schemas", str(schemas)], check=True)
    monkeypatch.setenv("GSETTINGS_SCHEMA_DIR", str(schemas))
    monkeypatch.setenv("GSETTINGS_BACKEND", "keyfile")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    subprocess.run(["gsettings", "set", shortcuts.SCHEMA, "custom-keybindings", USERS], check=True)
    yield


def get(path: str, key: str) -> str:
    schema = f"{shortcuts.SCHEMA}.custom-keybinding:{path}"
    return subprocess.run(
        ["gsettings", "get", schema, key], check=True, capture_output=True, text=True
    ).stdout.strip()


def entries() -> str:
    return subprocess.run(
        ["gsettings", "get", shortcuts.SCHEMA, "custom-keybindings"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip


def test_install_keeps_the_persons_own(gnome: None) -> None:
    shortcuts.install("notes", "<Super>n")
    path = shortcuts.entry_path("notes")
    assert entries() == f"['{shortcuts.BASE}custom0/', '{path}']"
    assert get(path, "binding") == "'<Super>n'"
    assert get(path, "name") == "'handler: notes'"
    assert get(path, "command").endswith(" app open notes'")
    shortcuts.install("notes", "<Super><Shift>n")  # again: changed, not added twice
    assert entries().count(path) == 1
    assert get(path, "binding") == "'<Super><Shift>n'"


def test_remove(gnome: None) -> None:
    shortcuts.install("notes", "<Super>n")
    shortcuts.install("coach", "<Super>c")
    shortcuts.remove("notes")
    assert entries() == f"['{shortcuts.BASE}custom0/', '{shortcuts.entry_path('coach')}']"
    assert get(shortcuts.entry_path("notes"), "binding") == "''"
    shortcuts.remove("coach")
    assert entries() == USERS


def test_quotes_survive(gnome: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shortcuts, "handler_command", lambda app: f"/home/o'brien/handler app open {app}"
    )
    shortcuts.install("notes", "<Super>n")
    assert (
        get(shortcuts.entry_path("notes"), "command") == '"/home/o\'brien/handler app open notes"'
    )


def test_without_gnome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shortcuts.shutil, "which", lambda _: None)
    with pytest.raises(shortcuts.ShortcutError, match="need GNOME"):
        shortcuts.install("notes", "<Super>n")
