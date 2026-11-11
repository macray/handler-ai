"""A: podman's `sweep` removes only what dead launchers left (a launcher:
handler_sandbox_kit.launcher); the instance folders are the kit's (its own tests)."""

import uuid

import pytest

from handler_sandbox_kit.launcher import LAUNCHER_LABEL, MANAGED_LABEL, launcher_label
from handler_sandbox_podman.launch import Podman
from handler_sandbox_podman.podman import (
    podman,
    quiet,
)

from ..conftest import requires_podman


@pytest.mark.rule("sandbox.sweep-spares-live-launchers")
@requires_podman
def test_sweep_keeps_what_a_live_launcher_sets_up() -> None:
    """Between its network and its container a sandbox has no container yet: another daemon's
    sweep (at its start) must leave it alone, and remove what dead launchers left."""
    tag = uuid.uuid4().hex[:8]
    launchers = {"live": launcher_label(), "dead": "1:0"}
    for who, launcher in launchers.items():
        labels = [f"{MANAGED_LABEL}=1", f"{LAUNCHER_LABEL}={launcher}"]
        podman("network", "create", *[a for la in labels for a in ("--label", la)], f"{who}-{tag}")
    try:
        Podman().sweep()
        nets = podman("network", "ls", "--format", "{{.Name}}").split()
        assert f"live-{tag}" in nets and f"dead-{tag}" not in nets
    finally:
        for who in launchers:
            quiet("network", "rm", "--force", f"{who}-{tag}")
