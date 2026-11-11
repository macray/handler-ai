"""Opening the web UI and apps in a browser (handler_cli/browser.py): on WSL, Windows' own."""

import pytest

from handler_cli import browser


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    seen: dict[str, list] = {"popen": [], "webbrowser": []}
    monkeypatch.setattr(browser.subprocess, "Popen", lambda argv, **_: seen["popen"].append(argv))
    monkeypatch.setattr(browser.webbrowser, "open", seen["webbrowser"].append)
    monkeypatch.delenv("BROWSER", raising=False)
    return seen


def test_outside_wsl_python_s_webbrowser(
    opened: dict[str, list], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser.daemon_commands, "wsl", lambda: False)
    browser.open_url("http://127.0.0.1:7430/#token=t")
    assert opened == {"popen": [], "webbrowser": ["http://127.0.0.1:7430/#token=t"]}


def test_on_wsl_windows_default_browser(
    opened: dict[str, list], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser.daemon_commands, "wsl", lambda: True)
    found = {"rundll32.exe": "/win/rundll32.exe"}
    monkeypatch.setattr(browser.shutil, "which", found.get)
    browser.open_url("http://127.0.0.1:7430/#token=t")
    found["wslview"] = "/usr/bin/wslview"
    browser.open_url("http://127.0.0.1:7430/#token=t")
    assert opened["popen"] == [
        ["/win/rundll32.exe", "url.dll,FileProtocolHandler", "http://127.0.0.1:7430/#token=t"],
        ["/usr/bin/wslview", "http://127.0.0.1:7430/#token=t"],
    ]
    found.clear()  # interop turned off: no Windows program to run
    browser.open_url("http://x/")
    assert opened["webbrowser"] == ["http://x/"]


def test_browser_set_is_followed_on_wsl_too(
    opened: dict[str, list], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser.daemon_commands, "wsl", lambda: True)
    monkeypatch.setenv("BROWSER", "firefox")
    browser.open_url("http://x/")
    assert opened == {"popen": [], "webbrowser": ["http://x/"]}
