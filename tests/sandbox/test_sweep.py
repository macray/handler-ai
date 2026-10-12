"""A: `sweep` tells a dead launcher from a live one by its pid and start time, and removes only
what dead launchers left."""

import subprocess
import uuid
from pathlib import Path

import pytest

from handler_sandbox_podman import cli
from handler_sandbox_podman.launch import LAUNCHER_FILE
from handler_sandbox_podman.podman import (
    LAUNCHER_LABEL,
    MANAGED_LABEL,
    launcher_alive,
    launcher_label,
    podman,
    quiet,
)

from .conftest import requires_podman


def test_a_launcher_is_its_pid_and_start_time() -> None:
    assert launcher_alive(launcher_label())
    pid, _, started = launcher_label().partition(":")
    assert not launcher_alive(f"{pid}:{int(started) + 1}")  # its pid, another process (reused)


def test_an_exited_launcher_or_no_label_is_dead() -> None:
    proc = subprocess.Popen(["true"])
    proc.wait()
    assert not launcher_alive(f"{proc.pid}:0")
    assert not launcher_alive("<no value>")  # a container without the label


@requires_podman
def test_sweep_keeps_what_a_live_launcher_sets_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Between its network and its container a sandbox has no container yet: another daemon's
    sweep (at its start) must leave it alone, and remove what dead launchers left."""
    monkeypatch.setattr(cli, "state_root", lambda: tmp_path)
    tag = uuid.uuid4().hex[:8]
    launchers = {"live": launcher_label(), "dead": "1:0"}
    for who, launcher in launchers.items():
        (tmp_path / who).mkdir()
        (tmp_path / who / LAUNCHER_FILE).write_text(launcher)
        labels = [f"{MANAGED_LABEL}=1", f"{LAUNCHER_LABEL}={launcher}"]
        podman("network", "create", *[a for la in labels for a in ("--label", la)], f"{who}-{tag}")
    (tmp_path / "being-made").mkdir()  # its launcher has not written the file yet
    try:
        assert cli.cmd_sweep() == 0
        nets = podman("network", "ls", "--format", "{{.Name}}").split()
        assert f"live-{tag}" in nets and f"dead-{tag}" not in nets
        assert sorted(p.name for p in tmp_path.iterdir()) == ["being-made", "live"]
    finally:
        for who in launchers:
            quiet("network", "rm", "--force", f"{who}-{tag}")
