"""Whether the launcher that made a sandbox's resources still runs: it is known by its pid and
start time, read from /proc on Linux and from `ps` elsewhere (macOS), both tested here.

Spec: contract A "Sandbox" (the `sweep` verb: never what a live launcher made)."""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from handler_sandbox_kit import launcher


@pytest.fixture(params=["proc", "ps"])
def source(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Each test runs twice: start times read from /proc, then from `ps`."""
    if request.param == "ps":  # as on a system without /proc
        monkeypatch.setattr(launcher, "PROC", Path("/nonexistent-proc"))
    elif not launcher.PROC.is_dir():
        pytest.skip("no /proc here")
    return request.param


def exited_pid() -> int:
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


@pytest.mark.rule("sandbox.sweep-spares-live-launchers")
def test_a_running_launcher_s_label_says_it_is_alive(source: str) -> None:
    """If this fails: sweep removes what a running launcher is still using."""
    assert launcher.launcher_alive(launcher.launcher_label())


def test_a_label_is_one_word(source: str) -> None:
    """It is put on the engines' resources (`--label`) and read back from their listings.
    If this fails: `ps`'s start time ("Sat Oct 25 19:28:34 2026") breaks the label's value."""
    _, _, started = launcher.launcher_label().partition(":")
    assert started and " " not in started


@pytest.mark.rule("sandbox.sweep-spares-live-launchers")
def test_a_reused_pid_is_not_the_launcher(source: str) -> None:
    """Pids are reused: the same pid with another start time is another process.
    If this fails: a dead launcher's leftovers are kept for good, once its pid is reused."""
    pid, _, started = launcher.launcher_label().partition(":")
    assert not launcher.launcher_alive(f"{pid}:{started}0")


@pytest.mark.rule("sandbox.sweep-spares-live-launchers")
@pytest.mark.parametrize(
    "label",
    [
        pytest.param(lambda: f"{exited_pid()}:0", id="exited-process"),
        pytest.param(lambda: "<no value>", id="resource-without-the-label"),
    ],
)
def test_an_exited_launcher_or_a_broken_label_is_dead(
    source: str, label: Callable[[], str]
) -> None:
    """`<no value>` is what an engine lists for a resource without the label.
    If this fails: sweep keeps leftovers forever, or errors on a resource it did not label."""
    assert not launcher.launcher_alive(label())
