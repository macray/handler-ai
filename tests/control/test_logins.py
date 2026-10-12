"""D.9 through a real handlerd: an account's login, the harness's own command run on the host by
`handler account login` (here in the terminal window handlerd opens), and what it leaves kept as the
account's login."""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from ..support.daemon import Daemon, fake_terminal, start_daemon


@pytest.fixture(scope="module")
def terminal_script(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return fake_terminal(tmp_path_factory.mktemp("terminal"))


@pytest.fixture(scope="module")
def daemon(terminal_script: Path) -> Iterator[Daemon]:
    """With a stand-in for the desktop's terminal (HANDLER_TERMINAL)."""
    yield from start_daemon(extra_env={"HANDLER_TERMINAL": str(terminal_script)})


def test_a_harness_says_where_its_login_leaves_its_file(daemon: Daemon) -> None:
    with daemon.http() as c:
        harnesses = {h["name"]: h for h in c.get("/v1/harnesses").json()}
    assert harnesses["login-box"]["loginFile"] == "credential"
    assert harnesses["login-box"]["login"]["env"] == {"BOX_HOME": "{dir}"}
    assert harnesses["echo-box"].get("loginFile") is None  # a token login


def test_a_terminal_window_runs_the_login(daemon: Daemon, terminal_script: Path) -> None:
    """The web UI's Log in: handlerd opens a terminal window running `handler account login`, which
    runs the harness's login on the host; the account is logged in when it ends."""
    with daemon.http() as c:
        c.post("/v1/accounts", json={"name": "win", "harness": "login-box"}).raise_for_status()
        r = c.post("/v1/accounts/win/login/window")
        assert r.status_code == 201, r.text
        assert r.json() == {
            "terminal": "fake-terminal",
            "command": "handler account login win --keep-open",
        }
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            [account] = [a for a in c.get("/v1/accounts").json() if a["name"] == "win"]
            if account["status"] == "ready":
                break
            time.sleep(0.5)
    log = Path(f"{terminal_script}.log")
    assert account["status"] == "ready", log.read_text() if log.exists() else "no terminal log"
    assert "account login win --keep-open" in Path(f"{terminal_script}.calls").read_text()
    kept = daemon.data_dir / "accounts" / "win" / "credential"
    assert kept.read_text().strip() == "terminal-code"
    assert kept.stat().st_mode & 0o777 == 0o600
    assert "win: logged in" in log.read_text()
