"""Unit tests: a file shown in the desktop's file manager, never opened (F.8)."""

import time
from pathlib import Path

import pytest

from handler_control import desktop


def fake(bin_dir: Path, name: str, status: int) -> Path:
    """A program that records its arguments, one per line, and exits with `status`."""
    log = bin_dir / f"{name}.log"
    script = bin_dir / name
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {log}\nexit {status}\n')
    script.chmod(0o755)
    return log


def logged(log: Path) -> list[str]:
    for _ in range(50):  # xdg-open is not waited for
        if log.exists() and log.read_text():
            return log.read_text().splitlines()
        time.sleep(0.05)
    return []


def test_a_file_is_selected_in_its_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    gdbus = fake(tmp_path, "gdbus", 0)
    opener = fake(tmp_path, "xdg-open", 0)
    target = Path("/work/it's here.desktop")
    assert desktop.reveal(target, is_folder=False)
    args = logged(gdbus)
    assert "org.freedesktop.FileManager1.ShowItems" in args
    assert "['file:///work/it%27s%20here.desktop']" in args
    assert not opener.exists()


def test_without_the_service_its_folder_is_opened_never_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    fake(tmp_path, "gdbus", 1)  # no FileManager1 on the bus
    opener = fake(tmp_path, "xdg-open", 0)
    assert desktop.reveal(Path("/work/run.sh"), is_folder=False)
    assert logged(opener) == ["/work"]


def test_nothing_to_show_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert not desktop.reveal(Path("/work"), is_folder=True)
