"""On a Mac, an account's login opens in Terminal.app (D.9): `open -a Terminal` runs a
`.command` file, which gets none of handlerd's environment but what it sets itself."""

import os
import subprocess
from pathlib import Path

import pytest

from handler_control import terminal


def _fake_open(folder: Path, log: Path) -> None:
    """An `open` that runs the file it is given, as Terminal.app would, its output in `log`."""
    fake = folder / "open"
    fake.write_text(
        f'#!/bin/sh\n[ "$1 $2" = "-a Terminal" ] || exit 2\nenv -i sh "$3" > {log} 2>&1\n'
    )
    fake.chmod(0o755)


def test_a_mac_opens_the_login_in_terminal_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = tmp_path / "window.log"
    _fake_open(tmp_path, log)
    monkeypatch.setattr(terminal, "_macos", lambda: True)
    monkeypatch.delenv("HANDLER_TERMINAL", raising=False)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    argv = ["/bin/sh", "-c", 'echo "$HANDLER_URL|$HANDLER_CONFIG_DIR|$0"', "an 'odd' name"]
    env = {"HANDLER_URL": "http://127.0.0.1:7499", "HANDLER_CONFIG_DIR": "/tmp/a dir"}
    assert terminal.open_window(argv, env) == "Terminal"
    assert log.read_text() == "http://127.0.0.1:7499|/tmp/a dir|an 'odd' name\n"
    assert not list(Path(os.environ.get("TMPDIR", "/tmp")).glob("handler-login-*.command"))


def test_handler_terminal_comes_before_terminal_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = tmp_path / "calls"
    mine = tmp_path / "my-terminal"
    mine.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" > {calls}\n')  # echo would take -e
    mine.chmod(0o755)
    monkeypatch.setattr(terminal, "_macos", lambda: True)
    monkeypatch.setenv("HANDLER_TERMINAL", f"{mine} -e")
    assert terminal.open_window(["handler", "account", "login", "x"], {}) == "my-terminal"
    for _ in range(50):
        if calls.exists():
            break
        subprocess.run(["sleep", "0.1"], check=True)
    assert calls.read_text() == "-e handler account login x\n"


def test_terminal_app_refusing_is_said(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "open"
    fake.write_text("#!/bin/sh\necho 'Unable to find application named Terminal' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setattr(terminal, "_macos", lambda: True)
    monkeypatch.delenv("HANDLER_TERMINAL", raising=False)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    with pytest.raises(terminal.TerminalError, match="cannot open Terminal: Unable to find"):
        terminal.open_window(["true"], {})
