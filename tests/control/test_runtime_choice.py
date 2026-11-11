"""D.2: the sandbox runtime handlerd uses, chosen among those installed (`handler-sandbox-<name>`
executables), kept in runtime.toml; never while something runs in the current one."""

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import terminal_path
from handler_control.sandbox_process import DEFAULT_RUNTIME

from ..support.daemon import Daemon, start_daemon
from ..support.terminal import Attached


@pytest.fixture(scope="module")
def two_runtimes(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Daemon]:
    """A daemon that also finds `handler-sandbox-other` (it only answers `check`; the tests'
    sandboxes stay the fake's, HANDLER_TEST_SANDBOX)."""
    bin_dir = tmp_path_factory.mktemp("bin")
    other = bin_dir / "handler-sandbox-other"
    other.write_text('#!/bin/sh\necho \'{"runtime": "other 1", "ok": true, "items": []}\'\n')
    other.chmod(0o755)
    yield from start_daemon(extra_env={"PATH": f"{bin_dir}:{os.environ['PATH']}"})


def runtimes(daemon: Daemon) -> dict[str, bool]:
    """The system's default's (podman, apple on macOS) and the fake one's (others may be installed
    too)."""
    with daemon.http() as c:
        listed = {r["name"]: r["current"] for r in c.get("/v1/runtimes").json()}
    return {name: listed[name] for name in (DEFAULT_RUNTIME, "other")}


def choose(daemon: Daemon, name: str) -> Any:
    with daemon.http() as c:
        return c.put("/v1/runtime", json={"name": name})


@pytest.mark.rule("runtime.changed-only-when-nothing-runs")
def test_installed_runtimes_and_the_one_in_use(two_runtimes: Daemon) -> None:
    assert runtimes(two_runtimes) == {DEFAULT_RUNTIME: True, "other": False}
    r = choose(two_runtimes, "nowhere")
    assert r.status_code == 404 and "handler-sandbox-nowhere" in r.json()["detail"]
    assert choose(two_runtimes, "bad name").status_code == 422


def test_each_runtime_says_what_it_would_give_here(two_runtimes: Daemon) -> None:
    """Settings → Sandboxes offers another runtime with its own host check (A.8), before it is
    chosen: the one not in use answers too."""
    with two_runtimes.http() as c:
        listed = {r["name"]: r for r in c.get("/v1/runtimes").json()}
    assert listed["other"]["check"] == {"runtime": "other 1", "ok": True, "items": []}
    assert listed[DEFAULT_RUNTIME]["check"]["runtime"]  # the one in use (the tests' fake sandbox)


@pytest.mark.rule("runtime.changed-only-when-nothing-runs")
def test_another_runtime_is_chosen_only_when_nothing_runs(two_runtimes: Daemon) -> None:
    agent = two_runtimes.create_ad_hoc("fake", two_runtimes.make_scope())
    with two_runtimes.http() as c:
        started = c.post(terminal_path(agent["id"]), json={}).json()
    term = Attached(started["attach"])
    try:
        term.until("args:")
        r = choose(two_runtimes, "other")
        assert r.status_code == 409 and "agents" in r.json()["detail"]
    finally:
        term.type("quit")
        term.exit_code()
    choice = Path(two_runtimes.config_dir, "runtime.toml")
    for _ in range(100):  # until handlerd sees the terminal end
        if (r := choose(two_runtimes, "other")).status_code != 409:
            break
        time.sleep(0.2)
    assert r.status_code == 200, r.text
    assert choice.read_text() == 'name = "other"\n'
    assert runtimes(two_runtimes) == {DEFAULT_RUNTIME: False, "other": True}
    assert choose(two_runtimes, DEFAULT_RUNTIME).status_code == 200
    assert runtimes(two_runtimes)[DEFAULT_RUNTIME]


@pytest.mark.rule("runtime.changed-only-when-nothing-runs")
def test_handler_runtime_lists_and_chooses(two_runtimes: Daemon) -> None:
    """The CLI's side (`handler runtime list|use`)."""
    run = [str(Path(sys.executable).parent / "handler"), "runtime"]
    env = os.environ | {
        "HANDLER_URL": two_runtimes.base_url,
        "HANDLER_CONFIG_DIR": str(two_runtimes.config_dir),
    }
    listed = subprocess.run([*run, "list"], env=env, capture_output=True, text=True, check=False)
    assert listed.returncode == 0, listed.stderr
    assert DEFAULT_RUNTIME in listed.stdout and "other" in listed.stdout
    used = subprocess.run(
        [*run, "use", "nowhere"], env=env, capture_output=True, text=True, check=False
    )
    assert used.returncode != 0 and "handler-sandbox-nowhere" in used.stderr


@pytest.mark.skipif(sys.platform == "darwin", reason="the apple runtime is offered on macOS")
def test_the_apple_runtime_is_not_offered_elsewhere(two_runtimes: Daemon) -> None:
    """Installed with Handler (the checkout's `handler-sandbox-apple`), never listed nor chosen
    off macOS."""
    run = [str(Path(sys.executable).parent / "handler"), "runtime"]
    env = os.environ | {
        "HANDLER_URL": two_runtimes.base_url,
        "HANDLER_CONFIG_DIR": str(two_runtimes.config_dir),
    }
    assert (Path(sys.executable).parent / "handler-sandbox-apple").exists()
    listed = subprocess.run([*run, "list"], env=env, capture_output=True, text=True, check=False)
    assert listed.returncode == 0 and "apple" not in listed.stdout, listed.stderr
    used = subprocess.run(
        [*run, "use", "apple"], env=env, capture_output=True, text=True, check=False
    )
    assert used.returncode != 0 and "the apple runtime is for macOS" in used.stderr
