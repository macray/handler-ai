"""handler-sandbox-podman's own choices (the contracts: the podman rows of A.4, A.5,
A.6): what its `nested` confinement gives an engine inside, where it puts the display, and its
instance folder. What every runtime must do is in ../conformance."""

import subprocess
import time
from pathlib import Path

import pytest

from handler_sandbox_kit import launch
from handler_sandbox_podman.check import limit_controllers, podman_info
from handler_sandbox_podman.launch import CONTAINERS_PIDS_LIMIT

from ...support.dev_env import sandbox_gid, sandbox_uid
from ...support.runtimes import RUNTIMES
from ..conftest import (
    on_display,
    popen,
    requires_podman,
    run,
    skip_unless_usable,
    spec,
)

BIN = "handler-sandbox-podman"
PODMAN = RUNTIMES["podman"]
pytestmark = requires_podman

CURL = "curl -s -m 10 -o /dev/null -w '%{http_code}'"


def sh(script: str) -> list[str]:
    return ["sh", "-c", script]


# ── confinement (A.5, the podman row) ───────────────────────────────────

CONFINEMENT = "grep -E '^(CapBnd|NoNewPrivs)' /proc/self/status | tr -s '\\t' ' '; ls /dev/fuse"


@pytest.mark.rule(
    "confinement.only-the-container-loosens", "confinement.nested-gives-only-the-host-s-part"
)
def test_nested_confinement_keeps_what_inner_podman_needs(scope: Path) -> None:
    script = CONFINEMENT + "; touch /x 2>/dev/null || echo rootfs-ro"
    r = run(BIN, spec(scope, sh(script), isolation="nested"))
    out = r.stdout.decode()
    assert "NoNewPrivs: 0" in out
    assert "CapBnd: 0000000000000000" not in out
    assert "/dev/fuse" in out
    assert "rootfs-ro" in out


@pytest.mark.rule("confinement.nested-gives-only-the-host-s-part")
@pytest.mark.parametrize("confinement", ["strict", "nested", "privileged"])
def test_a_sandbox_running_containers_gets_more_processes(scope: Path, confinement: str) -> None:
    skip_unless_usable(PODMAN, confinement)
    if not limit_controllers(podman_info(), ("pids",)):
        pytest.skip("podman sets no process limit here (no pids controller delegated)")
    r = run(BIN, spec(scope, ["cat", "/sys/fs/cgroup/pids.max"], isolation=confinement))
    assert r.returncode == 0, r.stderr
    limit = r.stdout.decode().strip()
    if confinement == "strict":
        assert limit != str(CONTAINERS_PIDS_LIMIT)  # podman's own default, or the user's
    else:
        assert limit == str(CONTAINERS_PIDS_LIMIT)


@pytest.mark.rule("confinement.nested-gives-only-the-host-s-part")
@pytest.mark.parametrize("confinement", ["nested", "privileged"])
def test_nested_confinement_gives_the_agent_subordinate_ids(scope: Path, confinement: str) -> None:
    skip_unless_usable(PODMAN, confinement)
    script = "cat /etc/subuid /etc/subgid"
    out = run(BIN, spec(scope, sh(script), isolation=confinement)).stdout.decode().split()
    uid, gid = sandbox_uid(), sandbox_gid()
    assert [line.split(":")[:2] for line in out] == [
        [str(uid), "1"], [str(uid), str(uid + 1)], [str(gid), "1"], [str(gid), str(gid + 1)],
    ]  # fmt: skip


@pytest.mark.rule("confinement.nested-gives-only-the-host-s-part")
@pytest.mark.parametrize("confinement", ["nested", "privileged"])
def test_the_engine_inside_is_configured_by_the_image_not_the_sandbox(
    scope: Path, confinement: str
) -> None:
    """A.5: the inner engine's configuration is the toolbox's (the podman system package's,
    B.7): the sandbox adds none, so another engine inside needs nothing of the runtime."""
    skip_unless_usable(PODMAN, confinement)
    script = "ls /etc/containers/storage.conf /etc/containers/containers.conf || echo none"
    out = run(BIN, spec(scope, sh(script), isolation=confinement)).stdout.decode()
    assert out.strip().endswith("none")


# ── display (A.6, the podman row) ──────────────────────────────────────

DISPLAY_PROBE = (
    'echo "$WAYLAND_DISPLAY $XDG_RUNTIME_DIR ${DISPLAY-unset}"; stat -c %a "$XDG_RUNTIME_DIR";'
    ' ls -A /run/handler | tr "\\n" " "; echo;'
    ' curl -s -o /dev/null -w "%{http_code}" --unix-socket "$WAYLAND_DISPLAY" http://display/'
)


@pytest.mark.rule("display.only-the-wayland-socket")
def test_display_is_mounted_in_run_handler(scope: Path, display_socket: str) -> None:
    r = run(BIN, spec(scope, sh(DISPLAY_PROBE), display=True), env=on_display(display_socket))
    assert r.returncode == 0, r.stderr
    assert r.stdout.decode().splitlines() == [
        "/run/handler/wayland-0 /run/handler/runtime unset",
        "700",
        "runtime wayland-0 ",
        "200",
    ]


@pytest.mark.rule("display.only-when-asked")
def test_no_run_handler_without_display(scope: Path) -> None:
    r = run(BIN, spec(scope, sh("ls /run/handler 2>/dev/null; echo end")))
    assert r.stdout.decode().split() == ["end"]


# ── its instance folder (A.4: set-allow while starting) ─────────────────


@pytest.mark.rule("network.live-changes-apply-at-the-next-request")
def test_set_allow_while_starting(scope: Path) -> None:
    """`set-allow` on an instance still starting (its proxy not up yet; handlerd already counts it
    as the agent's connection) waits for its proxy, then applies (A.4). A local destination: the
    filter's decision alone is tested, not the internet."""
    with PODMAN.local_server() as server:
        fetch = f"{CURL} --retry 5 --retry-connrefused http://{server}:8000/"
        network = {"mode": "filtered", "allow": ["www.example.org:443"], "enforcement": "enforce"}
        doc = spec(scope, sh(f"read x; {fetch}"), network=network)
        proc = popen(
            BIN, doc, unchained=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )  # fmt: skip
        assert proc.stdin is not None and proc.stdout is not None
        try:
            deadline = time.monotonic() + 30
            instance = launch._instance_dir(doc["name"])  # the kit's own: still starting?
            while not instance.exists():
                assert time.monotonic() < deadline
                time.sleep(0.01)
            assert not (instance / launch._FILTER_DIR / launch._FILTER_READY).exists()
            allow = [BIN, "set-allow", doc["name"], f"{server}:8000", *network["allow"]]
            assert subprocess.run(allow, timeout=90, check=False).returncode == 0
            out, _ = proc.communicate(b"go\n", timeout=60)
            assert out.decode().strip() == "200"  # denied: the proxy's 403
        finally:
            proc.kill()
