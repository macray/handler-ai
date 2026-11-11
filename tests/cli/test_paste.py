"""D.16: the paste key in `handler terminal` puts the clipboard's image where the program in its
sandbox reads it, before the key reaches it (handler_cli/paste.py)."""

from pathlib import Path

import pytest

from handler_cli import paste
from handler_contracts import PASTE_IMAGE


@pytest.mark.parametrize("typed", [b"\x16", b"\x1b[118;5u", b"\x1b[27;5;118~", b"ab\x16"])
def test_the_paste_key_as_terminals_send_it(typed: bytes) -> None:
    assert paste.is_paste(typed)


@pytest.mark.parametrize("typed", [b"v", b"\x1b[118u", b"\x1b[200~text\x1b[201~", b"\x03"])
def test_other_keys_are_not_the_paste_key(typed: bytes) -> None:
    assert not paste.is_paste(typed)


@pytest.mark.rule("terminal.only-what-you-paste")
def test_the_clipboard_s_image_goes_first_and_none_empties(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clipboard: list[bytes | None] = [b"\x89PNG-1"]
    monkeypatch.setattr(paste, "clipboard_png", lambda: clipboard[0])
    on_input = paste.watcher(tmp_path)
    on_input(b"hello")  # not the paste key: the clipboard is not read
    assert not (tmp_path / PASTE_IMAGE).exists()
    on_input(b"\x16")
    assert (tmp_path / PASTE_IMAGE).read_bytes() == b"\x89PNG-1"
    assert (tmp_path / PASTE_IMAGE).stat().st_mode & 0o777 == 0o644
    clipboard[0] = b"\x89PNG-2"
    on_input(b"\x1b[118;5u")
    assert (tmp_path / PASTE_IMAGE).read_bytes() == b"\x89PNG-2"
    clipboard[0] = None  # text copied since: the old image is not pasted again
    on_input(b"\x16")
    assert list(tmp_path.iterdir()) == []


def test_a_folder_gone_pastes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paste, "clipboard_png", lambda: b"\x89PNG")
    paste.watcher(tmp_path / "gone")(b"\x16")  # the sandbox ended: no error


def test_on_wsl_windows_clipboard_when_linux_s_has_no_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An image copied in Windows may not reach WSLg's clipboard: powershell.exe reads it."""
    monkeypatch.setattr(paste.sys, "platform", "linux")
    monkeypatch.setattr(paste, "_linux_png", lambda: None)
    monkeypatch.setattr(paste.shutil, "which", lambda name: f"/win/{name}")
    ran: list[list[str]] = []
    monkeypatch.setattr(paste, "_run", lambda argv: ran.append(argv) or b"\x89PNG-win")
    monkeypatch.setattr(paste.daemon_commands, "wsl", lambda: False)
    assert paste.clipboard_png() is None and ran == []
    monkeypatch.setattr(paste.daemon_commands, "wsl", lambda: True)
    assert paste.clipboard_png() == b"\x89PNG-win"
    assert ran[0][0] == "/win/powershell.exe" and "GetImage()" in ran[0][-1]
    monkeypatch.setattr(paste, "_run", lambda argv: b"")  # no image there either
    assert paste.clipboard_png() is None
