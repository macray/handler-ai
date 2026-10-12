"""Unit tests: which terminal handlerd opens a window with (D.9)."""

from pathlib import Path

import pytest

from handler_control import terminal


def executable(folder: Path, name: str) -> Path:
    path = folder / name
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_handler_terminal_wins_then_the_first_known_one(tmp_path: Path) -> None:
    assert terminal.command({"HANDLER_TERMINAL": "foot --app-id handler", "PATH": ""}) == [
        "foot",
        "--app-id",
        "handler",
    ]
    kgx = executable(tmp_path, "kgx")
    executable(tmp_path, "xterm")
    assert terminal.command({"PATH": str(tmp_path)}) == [str(kgx), "--"]


def test_no_terminal_says_how_to_set_one(tmp_path: Path) -> None:
    with pytest.raises(terminal.TerminalError, match="HANDLER_TERMINAL"):
        terminal.command({"PATH": str(tmp_path)})
