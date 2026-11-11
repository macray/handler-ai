"""`handler app open`: which window an app opens in (apps design §5.1), with
fake browsers."""

import time
from pathlib import Path

import pytest

from handler_cli import app_window


def fake(bin_dir: Path, name: str, record: Path) -> None:
    exe = bin_dir / name
    exe.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {record}\n')
    exe.chmod(0o755)


@pytest.fixture
def path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("HANDLER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("HANDLER_APP_BROWSER", raising=False)
    return bin_dir


@pytest.mark.rule("app.opens-in-its-own-window")
def test_firefox_first_with_its_own_profile(path: Path, tmp_path: Path) -> None:
    record = tmp_path / "argv"
    fake(path, "firefox", record)
    fake(path, "chromium", tmp_path / "unused")
    app_window.open_window("http://notes.localhost:7430/_handler/login?code=x")
    for _ in range(50):
        if record.exists():
            break
        time.sleep(0.1)
    profile = tmp_path / "data" / "firefox-apps"
    assert record.read_text().split() == [
        "--profile", str(profile), "--name", "handler-apps",
        "--new-window", "http://notes.localhost:7430/_handler/login?code=x",
    ]  # fmt: skip
    assert "legacyUserProfileCustomizations" in (profile / "user.js").read_text()
    assert "#nav-bar" in (profile / "chrome" / "userChrome.css").read_text()


@pytest.mark.rule("app.opens-in-its-own-window")
def test_chromium_app_mode(path: Path, tmp_path: Path) -> None:
    fake(path, "chromium", tmp_path / "unused")
    assert app_window.choose() == "chromium"
    command = app_window.argv("http://a.localhost:1/", "chromium", tmp_path)
    assert command is not None
    assert command[1:] == [
        f"--user-data-dir={tmp_path / 'chromium-apps'}", "--class=handler-apps",
        "--app=http://a.localhost:1/",
    ]  # fmt: skip


@pytest.mark.rule("app.opens-in-its-own-window")
def test_default_browser_otherwise(
    path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert app_window.choose() == "default"
    assert app_window.argv("http://a.localhost:1/", "default", tmp_path) is None
    monkeypatch.setenv("HANDLER_APP_BROWSER", "firefox")
    assert app_window.choose() == "firefox"
    assert app_window.argv("http://a.localhost:1/", "firefox", tmp_path) is None  # not installed
