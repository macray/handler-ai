"""The `xclip` a sandbox gets with the paste need: it answers what Claude Code asks the clipboard
(`-t TARGETS -o`, then `-t image/png -o`) from the image `handler terminal` put in the paste
folder, and fails as xclip with an empty clipboard does otherwise.

Spec: contract D.16 "Terminal" (pasting images)."""

import subprocess
from pathlib import Path

import pytest

from handler_contracts import PASTE_DIR, PASTE_IMAGE
from handler_sandbox_kit.launch import PASTE_XCLIP

TARGETS = ("-selection", "clipboard", "-t", "TARGETS", "-o")
PNG = ("-selection", "clipboard", "-t", "image/png", "-o")
IMAGE = b"\x89PNG-bytes"


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """The paste folder, empty: nothing pasted yet."""
    (tmp_path / "paste").mkdir()
    return tmp_path / "paste"


def xclip(folder: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """The script as the sandbox gets it, its folder pointed at `folder`."""
    script = folder.parent / "xclip"
    script.write_text(PASTE_XCLIP.replace(PASTE_DIR, str(folder)))
    return subprocess.run(["sh", str(script), *args], capture_output=True, check=False)


@pytest.mark.rule("terminal.only-what-you-paste")
def test_with_nothing_pasted_the_clipboard_is_empty(folder: Path) -> None:
    """If this fails: Claude Code believes an image is there and pastes an error or nothing."""
    assert xclip(folder, *TARGETS).returncode == 1
    assert xclip(folder, *PNG).returncode == 1


def test_a_pasted_image_is_offered_as_png(folder: Path) -> None:
    """If this fails: Claude Code finds no image to paste."""
    (folder / PASTE_IMAGE).write_bytes(IMAGE)
    assert xclip(folder, *TARGETS).stdout == b"image/png\n"


def test_a_pasted_image_is_read_as_it_was_written(folder: Path) -> None:
    """If this fails: the harness gets a broken image."""
    (folder / PASTE_IMAGE).write_bytes(IMAGE)
    assert xclip(folder, *PNG).stdout == IMAGE


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(("-selection", "clipboard", "-t", "image/jpeg", "-o"), id="other-type"),
        pytest.param(("-selection", "clipboard", "-i"), id="writing"),
        pytest.param(("-selection", "clipboard", "-t", "TARGETS"), id="no-output-flag"),
    ],
)
@pytest.mark.rule("terminal.only-what-you-paste")
def test_anything_else_fails_even_with_an_image(folder: Path, args: tuple[str, ...]) -> None:
    """Only the two reads above are answered; the sandbox cannot write the host's clipboard.
    If this fails: a program in the sandbox gets wrong data, or believes it wrote a clipboard."""
    (folder / PASTE_IMAGE).write_bytes(IMAGE)
    assert xclip(folder, *args).returncode == 1
