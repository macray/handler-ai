"""D.16: a harness's own terminal program, started with `POST /v1/agents/{id}/terminal` against a
real handlerd, then attached to on a terminal of the test's. The fake harness's terminal program
(tests/support/daemon.py) runs on the host (the fake sandbox), on the attaching process's
terminal."""

import time
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

import pytest

from handler_contracts import terminal_path

from ..support.daemon import Daemon, start_daemon
from ..support.terminal import Attached


@pytest.fixture
def ad_hoc(daemon: Daemon) -> dict[str, Any]:
    return daemon.create_ad_hoc("fake", daemon.make_scope(), model="big-model")


def _start(daemon: Daemon, agent_id: str, **body: Any) -> dict[str, Any]:
    with daemon.http() as c:
        r = c.post(terminal_path(agent_id), json={"term": "xterm-test"} | body)
    assert r.status_code == 201, r.text
    return r.json()


def _connections(daemon: Daemon, agent_id: str) -> list[Any]:
    with daemon.http() as c:
        return c.get(f"/v1/agents/{agent_id}").json()["connections"]


def _until_no_connection(daemon: Daemon, agent_id: str) -> None:
    deadline = time.monotonic() + 30
    while _connections(daemon, agent_id):
        assert time.monotonic() < deadline, "the connection is still live"
        time.sleep(0.2)


def test_auth_and_unknown_agent(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    with daemon.http(token=None) as c:
        assert c.post(terminal_path(ad_hoc["id"]), json={}).status_code == 401
    with daemon.http() as c:
        assert c.post(terminal_path("nope"), json={}).status_code == 404


def test_runs_on_the_client_s_terminal_with_its_settings_as_flags(
    daemon: Daemon, ad_hoc: dict[str, Any]
) -> None:
    started = _start(daemon, ad_hoc["id"], args=["--resume", "a b"])
    assert started["sandbox"] in started["attach"]
    [conn] = _connections(daemon, ad_hoc["id"])
    assert conn["sandbox"] == started["sandbox"]
    # shown as a terminal, with what it runs as (the web UI's terminal view)
    assert (conn["terminal"]["account"], conn["terminal"]["model"]) == ("fake", "big-model")
    term = Attached(started["attach"])
    shown = term.until("a b\r\n")
    assert "on-a-tty" in shown
    assert "size:30 100" in shown
    assert "TERM=xterm-test" in shown
    assert "args:--yolo --model big-model --resume a b" in shown  # bypass, model, then ours
    term.type("hello")
    term.until("got:hello")
    term.resize(40, 120)
    term.type("resize")
    term.until("size:40 120")
    term.type("quit")
    assert term.exit_code() == 3
    _until_no_connection(daemon, ad_hoc["id"])


def test_a_folder_inside_the_agent_s_is_the_only_one_mounted(
    daemon: Daemon, ad_hoc: dict[str, Any]
) -> None:
    """`handler terminal` in a project's sub-folder: that folder, not the project's."""
    sub = Path(ad_hoc["scope"], "sub")
    sub.mkdir()
    started = _start(daemon, ad_hoc["id"], folder=str(sub))
    term = Attached(started["attach"])
    assert f"pwd:{sub}\r\n" in term.until("args:")
    term.type("quit")
    assert term.exit_code() == 3
    _until_no_connection(daemon, ad_hoc["id"])


def test_a_folder_outside_the_agent_s_is_refused(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    with daemon.http() as c:
        outside = c.post(terminal_path(ad_hoc["id"]), json={"folder": str(daemon.make_scope())})
        missing = c.post(terminal_path(ad_hoc["id"]), json={"folder": ad_hoc["scope"] + "/nope"})
    assert outside.status_code == 409
    assert "outside the agent's folder" in outside.json()["detail"]
    assert missing.status_code == 409
    assert "not a directory" in missing.json()["detail"]
    assert not _connections(daemon, ad_hoc["id"])


def test_stopping_handlerd_leaves_the_program_running() -> None:
    """A daemon of its own: the module's goes on."""
    running = cast(Generator[Daemon], start_daemon())
    daemon = next(running)
    try:
        agent = daemon.create_ad_hoc("fake", daemon.make_scope(), model="big-model")
        term = Attached(_start(daemon, agent["id"])["attach"])
        term.until("args:")
        daemon.process.terminate()
        daemon.process.wait(timeout=30)
        term.type("hello")
        term.until("got:hello")
        term.type("quit")
        assert term.exit_code() == 3
    finally:
        running.close()


def test_an_invalid_start_is_refused(daemon: Daemon, ad_hoc: dict[str, Any]) -> None:
    with daemon.http() as c:
        r = c.post(terminal_path(ad_hoc["id"]), json={"term": "bad term"})
    assert r.status_code == 422


def test_what_cannot_run_says_why(daemon: Daemon) -> None:
    ad_hoc = daemon.create_ad_hoc("echo-box", daemon.make_scope())
    with daemon.http() as c:
        r = c.post(terminal_path(ad_hoc["id"]), json={})
    assert r.status_code == 409
    assert "has no terminal program" in r.json()["detail"]
