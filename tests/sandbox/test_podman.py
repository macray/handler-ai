"""Contract A conformance: handler-sandbox-podman (docs/dev/contracts.md §A)."""

import contextlib
import fcntl
import json
import os
import pty
import signal
import struct
import subprocess
import termios
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from handler_sandbox_podman.launch import instance_dir

from ..support import dev_env
from ..support.dev_env import sandbox_gid, sandbox_uid
from .conftest import (
    HOME_IN,
    leftovers,
    podman_usable,
    popen,
    requires_egress,
    requires_internet,
    requires_podman,
    run,
    skip_unless_usable,
    spec,
)

BIN = "handler-sandbox-podman"
pytestmark = requires_podman

# Hosts no agent has a secret for: an agent running these tests chains to its own proxy, which
# decrypts its secrets' hosts with a CA these sandboxes do not trust.
ALLOW = {"mode": "filtered", "allow": ["www.example.org:443"], "enforcement": "enforce"}
CURL = "curl -s -m 10 -o /dev/null -w '%{http_code}'"


def sh(script: str) -> list[str]:
    return ["sh", "-c", script]


# ── spec handling (A1) ──────────────────────────────────────────────────


def test_invalid_spec_is_rejected(scope: Path) -> None:
    doc = spec(scope, ["true"]) | {"workdir": "/etc"}
    assert run(BIN, doc).returncode == 65


def test_refuses_missing_mount_source(scope: Path) -> None:
    extra = {"source": "/nonexistent/x", "target": "/data", "readOnly": True, "kind": "cache"}
    doc = spec(scope, ["true"])
    doc["mounts"].append(extra)
    assert run(BIN, doc).returncode == 64


# ── confinement (A3, A.5) ───────────────────────────────────────────────

CONFINEMENT = "grep -E '^(CapBnd|NoNewPrivs)' /proc/self/status | tr -s '\\t' ' '; ls /dev/fuse"


def test_strict_confinement_drops_everything(scope: Path) -> None:
    out = run(BIN, spec(scope, sh(CONFINEMENT))).stdout.decode()
    assert "NoNewPrivs: 1" in out
    assert "CapBnd: 0000000000000000" in out
    assert "/dev/fuse" not in out


def test_nested_confinement_keeps_what_inner_podman_needs(scope: Path) -> None:
    r = run(
        BIN,
        spec(
            scope,
            sh(CONFINEMENT + "; touch /x 2>/dev/null || echo rootfs-ro"),
            confinement="nested",
        ),
    )
    out = r.stdout.decode()
    assert "NoNewPrivs: 0" in out
    assert "CapBnd: 0000000000000000" not in out
    assert "/dev/fuse" in out
    assert "rootfs-ro" in out


@pytest.mark.parametrize("confinement", ["nested", "privileged"])
def test_nested_confinement_gives_the_agent_subordinate_ids(scope: Path, confinement: str) -> None:
    skip_unless_usable(confinement)
    script = "cat /etc/subuid /etc/subgid"
    out = run(BIN, spec(scope, sh(script), confinement=confinement)).stdout.decode().split()
    uid, gid = sandbox_uid(), sandbox_gid()
    assert [line.split(":")[:2] for line in out] == [
        [str(uid), "1"], [str(uid), str(uid + 1)], [str(gid), "1"], [str(gid), str(gid + 1)],
    ]  # fmt: skip


@pytest.mark.parametrize("confinement", ["nested", "privileged"])
def test_nested_confinement_gives_inner_podman_its_configuration(
    scope: Path, confinement: str
) -> None:
    """A.5: from the sandbox, not the image (any toolbox with podman works nested), read-only."""
    skip_unless_usable(confinement)
    conf = "/etc/containers/storage.conf /etc/containers/containers.conf"
    script = f"cat {conf}; touch /etc/containers/x"
    r = run(BIN, spec(scope, sh(script), confinement=confinement))
    out = r.stdout.decode()
    assert 'mount_program = "/usr/bin/fuse-overlayfs"' in out and 'utsns = "host"' in out
    assert 'log_driver = "k8s-file"' in out  # `podman logs` without journald
    assert 'static_dir = "/tmp/podman/libpod"' in out  # the image store may be a shared cache
    assert r.returncode != 0  # the touch: read-only


TOOLBOX = os.environ.get("HANDLER_TEST_TOOLBOX_IMAGE", "localhost/handler-ai-toolbox:latest")


def toolbox_has_podman() -> bool:
    argv = ["podman", "run", "--rm", TOOLBOX, "which", "podman"]
    if not podman_usable():
        return False
    return subprocess.run(argv, capture_output=True, check=False).returncode == 0


@requires_internet
@pytest.mark.timeout(dev_env.IMAGE_TIMEOUT)
@pytest.mark.skipif(not toolbox_has_podman(), reason=f"{TOOLBOX} not built, or without podman")
def test_podman_runs_inside_a_nested_toolbox_sandbox(scope: Path) -> None:
    inner = "podman run --rm -q docker.io/library/alpine:3.22 sh -c 'echo inner-ok'"
    doc = spec(scope, sh(inner), confinement="nested", image=TOOLBOX, network={"mode": "open"})
    r = run(BIN, doc, timeout=300)
    assert "inner-ok" in r.stdout.decode(), r.stderr.decode()


# ── process & stdio (A5) ────────────────────────────────────────────────


def test_stdio_roundtrip_1mb(scope: Path) -> None:
    line = json.dumps({"jsonrpc": "2.0", "method": "x", "params": {"p": "a" * 1_048_576}}) + "\n"
    r = run(BIN, spec(scope, ["cat"]), stdin=line.encode())
    assert r.returncode == 0
    assert r.stdout == line.encode()


def test_exit_code_propagates(scope: Path) -> None:
    assert run(BIN, spec(scope, sh("exit 7"))).returncode == 7


def _ready(proc: subprocess.Popen[bytes]) -> None:
    """A `tty` launch: until it says it waits for its `attach`."""
    assert proc.stderr is not None
    for line in proc.stderr:
        if line.strip() == b"handler-ready":
            return
    raise AssertionError(f"ended without being ready: {proc.wait()}")


def _exit_code(pid: int, timeout: float = 30) -> int:
    """The forked `attach`'s exit code; killed (and the test failed) if it outlives `timeout`,
    not to wait for the sandbox's own end."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            return os.waitstatus_to_exitcode(status)
        time.sleep(0.1)
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    raise AssertionError(f"attach still running after {timeout}s")


def test_tty_is_a_terminal_attached_to_that_follows_resizes(scope: Path) -> None:
    """D.16: with `tty`, launch's stdio is not the process's: it says it is ready, then `attach`
    runs the process on the caller's terminal, its size, resized with it; the exit code is
    attach's; launch cleans up once it ends."""
    script = "[ -t 0 ] && echo on-a-tty; stty size; read -r x; stty size; exit 5"
    doc = spec(scope, sh(script), tty=True)
    launcher = popen(BIN, doc, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _ready(launcher)
    pid, master = pty.fork()
    if pid == 0:
        os.execvp(BIN, [BIN, "attach", doc["name"]])
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
    output = b""
    with contextlib.suppress(OSError):  # EIO once it is gone
        while chunk := os.read(master, 4096):
            output += chunk
            if b"30 100" in output and b"go" not in output:
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
                time.sleep(1)  # podman forwards the resize on SIGWINCH
                os.write(master, b"go\r")
    os.close(master)
    assert _exit_code(pid) == 5, output
    assert b"on-a-tty" in output and b"40 120" in output, output
    launcher.wait(timeout=60)
    assert leftovers(doc["name"]) == []


def test_tty_hang_up_stops_the_sandbox(scope: Path) -> None:
    """Closing the attached terminal (its hang-up) stops the sandbox, and launch cleans up."""
    doc = spec(scope, sh("echo started; sleep 600"), tty=True)
    launcher = popen(BIN, doc, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _ready(launcher)
    pid, master = pty.fork()
    if pid == 0:
        os.execvp(BIN, [BIN, "attach", doc["name"]])
    output = b""
    while b"started" not in output:
        output += os.read(master, 4096)
    os.close(master)  # the terminal goes away: SIGHUP to its session leader, attach
    _exit_code(pid)
    launcher.wait(timeout=60)
    assert leftovers(doc["name"]) == []


# ── display (A.6) ───────────────────────────────────────────────────────

DISPLAY_PROBE = (
    'echo "$WAYLAND_DISPLAY $XDG_RUNTIME_DIR ${DISPLAY-unset}"; stat -c %a "$XDG_RUNTIME_DIR";'
    ' ls -A /run/handler | tr "\\n" " "; echo;'
    ' curl -s -o /dev/null -w "%{http_code}" --unix-socket "$WAYLAND_DISPLAY" http://display/'
)


def test_display_is_only_the_wayland_socket(scope: Path, display_socket: str) -> None:
    """Works with network none: the display is not egress."""
    doc = spec(scope, sh(DISPLAY_PROBE), display={"mode": "wayland", "socket": display_socket})
    r = run(BIN, doc)
    assert r.returncode == 0, r.stderr
    assert r.stdout.decode().splitlines() == [
        "/run/handler/wayland-0 /run/handler/runtime unset",
        "700",
        "runtime wayland-0 ",
        "200",
    ]


def test_no_display_unless_asked(scope: Path) -> None:
    r = run(BIN, spec(scope, sh('echo "${WAYLAND_DISPLAY-unset}"; ls /run/handler 2>/dev/null')))
    assert r.stdout.decode().split() == ["unset"]


def test_refuses_missing_display_socket(scope: Path, tmp_path: Path) -> None:
    doc = spec(scope, ["true"], display={"mode": "wayland", "socket": str(tmp_path / "none")})
    r = run(BIN, doc)
    assert r.returncode == 64 and b"no display socket" in r.stderr


def test_display_env_is_the_implementation_s(scope: Path, display_socket: str) -> None:
    display = {"mode": "wayland", "socket": display_socket}
    doc = spec(scope, ["true"], display=display, env={"WAYLAND_DISPLAY": "wayland-1"})
    assert run(BIN, doc).returncode == 65


# ── identity, home, filesystem (A2, A3) ────────────────────────────────


def test_identity_home_and_readonly_rootfs(scope: Path) -> None:
    script = (
        'id -u; id -g; echo "$HOME"; touch "$HOME/x" && echo home-ok;'
        " touch /x 2>/dev/null || echo rootfs-ro"
    )
    r = run(BIN, spec(scope, sh(script)))
    out = r.stdout.decode().split()
    uid, gid = str(sandbox_uid()), str(sandbox_gid())
    assert out == [uid, gid, HOME_IN, "home-ok", "rootfs-ro"]


def test_writable_paths_start_empty_over_image_content(scope: Path) -> None:
    """A private tmpfs is empty, even where the image has files (e.g. a build-time ~/.cache)."""
    doc = spec(scope, sh("ls -A /etc/ssl; echo end"), writablePaths=["/etc/ssl"])
    assert run(BIN, doc).stdout.decode().split() == ["end"]


def test_scope_same_path_and_ownership(scope: Path) -> None:
    r = run(BIN, spec(scope, sh("pwd; echo data > written.txt")))
    assert r.stdout.decode().strip() == str(scope)
    written = scope / "written.txt"
    assert written.read_text() == "data\n"
    assert (written.stat().st_uid, written.stat().st_gid) == (sandbox_uid(), sandbox_gid())


def test_paths_outside_mounts_are_invisible(scope: Path) -> None:
    sibling = scope.parent / (scope.name + "-sibling")
    sibling.mkdir()
    try:
        r = run(
            BIN, spec(scope, sh(f"ls {sibling} >/dev/null 2>&1 && echo visible || echo invisible"))
        )
        assert r.stdout.decode().strip() == "invisible"
    finally:
        sibling.rmdir()


def test_read_only_mount(scope: Path) -> None:
    ro = scope.parent / (scope.name + "-ro")
    ro.mkdir()
    (ro / "f").write_text("keep\n")
    try:
        doc = spec(scope, sh("cat /data/f; echo x > /data/f 2>/dev/null || echo ro-ok"))
        doc["mounts"].append(
            {"source": str(ro), "target": "/data", "readOnly": True, "kind": "cache"}
        )
        r = run(BIN, doc)
        assert r.stdout.decode().split() == ["keep", "ro-ok"]
        assert (ro / "f").read_text() == "keep\n"
    finally:
        (ro / "f").unlink()
        ro.rmdir()


def test_generated_file_is_mounted_read_only(scope: Path) -> None:
    doc = spec(
        scope, sh("cat /etc/handler.conf; echo y >> /etc/handler.conf 2>/dev/null || echo ro-ok")
    )
    doc["files"] = [{"target": "/etc/handler.conf", "content": "k=v\n"}]
    assert run(BIN, doc).stdout.decode().split() == ["k=v", "ro-ok"]


def test_generated_file_in_home_keeps_its_parents_writable(scope: Path) -> None:
    """A generated file in a folder the home does not have yet (pi's ~/.config/mcp/mcp.json):
    ~/.config stays the sandbox user's, so e.g. Chromium can create ~/.config/chromium."""
    script = (
        'cat "$HOME/.config/mcp/mcp.json"; mkdir "$HOME/.config/chromium" && echo parent-ok;'
        ' echo x >> "$HOME/.config/mcp/mcp.json" 2>/dev/null || echo ro-ok'
    )
    doc = spec(scope, sh(script))
    doc["files"] = [
        {"target": f"{HOME_IN}/.config/mcp/mcp.json", "content": "{}\n", "mode": "0444"}
    ]
    r = run(BIN, doc)
    assert r.stdout.decode().split() == ["{}", "parent-ok", "ro-ok"], r.stderr
    assert leftovers(doc["name"]) == []


def test_seeded_file_is_writable_and_replaceable(scope: Path) -> None:
    """A seeded file can be rewritten atomically (temp file + rename), unlike a mounted one."""
    script = (
        'cat "$HOME/.app/conf.toml"; echo "b = 2" > "$HOME/.app/.conf.tmp";'
        ' mv "$HOME/.app/.conf.tmp" "$HOME/.app/conf.toml" && cat "$HOME/.app/conf.toml"'
    )
    doc = spec(scope, sh(script), writablePaths=[f"{HOME_IN}/.app"])
    doc["files"] = [{"target": f"{HOME_IN}/.app/conf.toml", "content": "a = 1\n", "seed": True}]
    r = run(BIN, doc)
    assert r.stdout.decode().split("\n")[:2] == ["a = 1", "b = 2"], r.stderr
    assert leftovers(doc["name"]) == []  # the per-instance copy is gone


@pytest.mark.parametrize("seeded", [True, False])
def test_mount_inside_a_writable_path_keeps_parents_writable(
    scope: Path, tmp_path: Path, seeded: bool
) -> None:
    """A mount nested in a writable path (e.g. a per-session folder at ~/.vibe/logs/session): the
    directories podman would create for it (~/.vibe/logs) stay writable by the sandbox user."""
    state = tmp_path / "state"
    state.mkdir()
    state.chmod(0o777)  # tests may run as another user than the sandbox (dev_env)
    script = 'touch "$HOME/.app/logs/app.log" && touch "$HOME/.app/logs/session/s" && echo ok'
    doc = spec(scope, sh(script), writablePaths=[f"{HOME_IN}/.app"])
    doc["mounts"].append(
        {
            "source": str(state),
            "target": f"{HOME_IN}/.app/logs/session",
            "readOnly": False,
            "kind": "state",
        }
    )
    if seeded:
        doc["files"] = [{"target": f"{HOME_IN}/.app/conf.toml", "content": "a = 1\n", "seed": True}]
    r = run(BIN, doc)
    assert r.stdout.decode().strip() == "ok", r.stderr.decode()
    assert (state / "s").exists()


# ── image mounts (A6) ─────────────────────────────────────────────────────

ADDON_TARGET = "/opt/addons/handler-test"


def build_addon(directory: Path, tag: str, version: str) -> None:
    """A tiny addon image: `bin/handler-hello`, a `bin/ls` that must not win over the image's, and
    a version file."""
    (directory / "bin").mkdir(parents=True, exist_ok=True)
    (directory / "bin" / "handler-hello").write_text("#!/bin/sh\necho hello from the addon\n")
    (directory / "bin" / "ls").write_text("#!/bin/sh\necho addon-ls\n")
    for f in (directory / "bin").iterdir():
        f.chmod(0o755)
    (directory / "version").write_text(f"{version}\n")
    (directory / "Containerfile").write_text("FROM scratch\nCOPY bin /bin\nCOPY version /version\n")
    subprocess.run(
        ["podman", "build", "-q", "-t", tag, str(directory)], check=True, capture_output=True
    )


@pytest.fixture(scope="module")
def addon_image(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    tag = "localhost/handler-ai-test-addon:latest"
    build_addon(tmp_path_factory.mktemp("addon"), tag, "1")
    yield tag
    subprocess.run(["podman", "rmi", "-f", tag], capture_output=True, check=False)


def with_addon(doc: dict[str, Any], image: str) -> dict[str, Any]:
    return doc | {
        "imageMounts": [{"image": image, "target": ADDON_TARGET}],
        "pathAppend": [f"{ADDON_TARGET}/bin"],
    }


def test_image_mount_is_read_only_and_appended_to_path(scope: Path, addon_image: str) -> None:
    script = (
        "handler-hello; command -v ls;"
        " echo x > /opt/addons/handler-test/x 2>/dev/null || echo ro-ok;"
        ' echo "$PATH"'
    )
    r = run(BIN, with_addon(spec(scope, sh(script)), addon_image))
    hello, ls, ro, path = r.stdout.decode().splitlines()
    assert hello == "hello from the addon", r.stderr
    assert ls != f"{ADDON_TARGET}/bin/ls"  # the image's own commands win
    assert ro == "ro-ok"
    assert path.endswith(f":{ADDON_TARGET}/bin")
    assert path.split(":")[0] != f"{ADDON_TARGET}/bin"


def test_missing_mounted_image_is_a_clear_setup_failure(scope: Path) -> None:
    doc = with_addon(spec(scope, ["true"]), "localhost/handler-ai-test-never-built:latest")
    r = run(BIN, doc)
    assert r.returncode == 66
    assert b"handler-test-never-built:latest (for /opt/addons/handler-test) is missing" in r.stderr
    assert leftovers(doc["name"]) == []


def test_image_mount_is_pinned_and_labelled(scope: Path, addon_image: str, tmp_path: Path) -> None:
    """Moving the tag while the instance runs changes nothing for it, and the instance carries
    the label of the image id it mounts."""
    image_id = subprocess.run(
        ["podman", "image", "inspect", "-f", "{{.Id}}", addon_image],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    doc = with_addon(spec(scope, sh("read x; cat /opt/addons/handler-test/version")), addon_image)
    proc = popen(BIN, doc, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            labels = subprocess.run(
                ["podman", "inspect", "-f", "{{json .Config.Labels}}", doc["name"]],
                capture_output=True, text=True, check=False,
            )  # fmt: skip
            if labels.returncode == 0:
                break
            time.sleep(0.1)
        assert json.loads(labels.stdout).get(f"handler.image-mount.{image_id}") == ADDON_TARGET
        build_addon(tmp_path, addon_image, "2")  # the tag now names another image
        out, err = proc.communicate(b"go\n", timeout=60)
        assert out.decode().strip() == "1", err
    finally:
        if proc.poll() is None:
            proc.kill()
        subprocess.run(["podman", "tag", image_id, addon_image], capture_output=True, check=False)


def test_env_is_passed(scope: Path) -> None:
    doc = spec(scope, sh('echo "$SECRET_X"'), env={"SECRET_X": "s3cr3t"})
    assert run(BIN, doc).stdout.decode().strip() == "s3cr3t"


# ── network (A.3, A.4) ─────────────────────────────────────────────────


def test_network_none_has_no_egress(scope: Path) -> None:
    r = run(BIN, spec(scope, sh("curl -s -m 5 -o /dev/null https://1.1.1.1; echo rc=$?")))
    assert r.stdout.decode().strip() not in ("", "rc=0")


@requires_internet
def test_network_open_has_egress(scope: Path) -> None:
    r = run(BIN, spec(scope, sh(f"{CURL} https://www.example.org"), network={"mode": "open"}))
    assert r.stdout.decode() not in ("", "000")


@requires_egress
def test_filtered_enforce(scope: Path) -> None:
    script = (
        f"echo allowed=$({CURL} https://www.example.org);"
        f"{CURL} https://example.com >/dev/null; echo denied_rc=$?;"
        f"curl -s -m 5 --noproxy '*' -o /dev/null https://1.1.1.1; echo direct_rc=$?"
    )
    r = run(BIN, spec(scope, sh(script), network=ALLOW))
    out = dict(line.split("=", 1) for line in r.stdout.decode().split())
    assert out["allowed"] not in ("", "000")
    assert out["denied_rc"] != "0"
    assert out["direct_rc"] != "0"
    events = [
        json.loads(line.removeprefix("handler-egress "))
        for line in r.stderr.decode().splitlines()
        if line.startswith("handler-egress ")
    ]
    assert {"decision": "denied", "host": "example.com:443"} in events
    assert {"decision": "allowed", "host": "www.example.org:443"} in events


@requires_egress
def test_filtered_log_only_reports_unlisted(scope: Path) -> None:
    """Log only lets everything through, and reports what enforcing would deny (A.3, A.4)."""
    net = {**ALLOW, "enforcement": "log-only"}
    script = f"{CURL} https://www.example.org; echo; {CURL} https://example.com"
    r = run(BIN, spec(scope, sh(script), network=net))
    listed, unlisted = r.stdout.decode().split()
    assert listed not in ("", "000") and unlisted not in ("", "000")  # both went through
    events = [
        json.loads(line.removeprefix("handler-egress "))
        for line in r.stderr.decode().splitlines()
        if line.startswith("handler-egress ")
    ]
    assert {"decision": "allowed", "host": "www.example.org:443"} in events
    assert {"decision": "unlisted", "host": "example.com:443"} in events


@requires_egress
def test_filtered_plain_http_goes_through_the_proxy(scope: Path) -> None:
    """http:// (e.g. a local model server) uses the sandbox's proxy variables like https://, and
    an entry allows its own port only (A.3): ':80' is not ':443', nor the reverse."""
    http_only = {"mode": "filtered", "allow": ["www.example.org:80"], "enforcement": "enforce"}
    probes = [
        f"{CURL} http://www.example.org",  # :80 listed
        f"{CURL} https://www.example.org",  # :443 not listed
        f"{CURL} http://example.com",  # not listed
        f"{CURL} -p http://www.example.org:80",  # tunnel to :80: the entry's port, allowed
    ]
    r = run(BIN, spec(scope, sh("; echo; ".join(probes)), network=http_only))
    allowed, https, other, tunnel = r.stdout.decode().split()
    assert allowed not in ("", "000")  # reached through the proxy
    assert https == "000" and other in ("000", "403")  # refused by the proxy
    assert tunnel not in ("", "000")
    r = run(BIN, spec(scope, sh(f"{CURL} http://www.example.org"), network=ALLOW))
    assert r.stdout.decode() in ("000", "403")  # only :443 listed


@requires_egress
def test_filtered_wildcard(scope: Path) -> None:
    net = {"mode": "filtered", "allow": ["*.example.org:443"], "enforcement": "enforce"}
    r = run(BIN, spec(scope, sh(f"{CURL} https://www.example.org"), network=net))
    assert r.stdout.decode() not in ("", "000")
    exact = {"mode": "filtered", "allow": ["example.org:443"], "enforcement": "enforce"}
    r = run(BIN, spec(scope, sh(f"{CURL} https://www.example.org; echo rc=$?"), network=exact))
    assert "rc=0" not in r.stdout.decode()


@requires_egress
def test_set_egress_live_switch(scope: Path) -> None:
    probe = f"{CURL} https://example.com >/dev/null; echo rc=$?"
    doc = spec(scope, sh(f"read a; {probe}; read b; {probe}; read c; {probe}"), network=ALLOW)
    proc = popen(BIN, doc, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdin is not None and proc.stdout is not None
    stdin, stdout = proc.stdin, proc.stdout

    def step() -> str:
        stdin.write(b"go\n")
        stdin.flush()
        line: bytes = stdout.readline()
        return line.decode().strip()

    def set_egress(mode: str) -> None:
        subprocess.run([BIN, "set-egress", doc["name"], mode], check=True, timeout=30)
        time.sleep(0.5)

    try:
        assert step() != "rc=0"  # enforce
        set_egress("log-only")
        assert step() == "rc=0"  # log only: everything allowed, still logged
        set_egress("enforce")
        assert step() != "rc=0"  # back to enforce, same running process
        assert proc.wait(timeout=30) == 0
    finally:
        proc.kill()


@requires_egress
def test_set_allow_live(scope: Path) -> None:
    """`set-allow` replaces a running instance's allow-list, enforcement kept (A.4)."""
    probe = f"{CURL} https://example.com >/dev/null; echo rc=$?"
    steps = "; ".join(f"read x; {probe}" for _ in range(4))
    doc = spec(scope, sh(steps), network=ALLOW)
    proc = popen(BIN, doc, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdin is not None and proc.stdout is not None
    stdin, stdout = proc.stdin, proc.stdout

    def step() -> str:
        stdin.write(b"go\n")
        stdin.flush()
        line: bytes = stdout.readline()
        return line.decode().strip()

    def set_allow(*entries: str) -> None:
        subprocess.run([BIN, "set-allow", doc["name"], *entries], check=True, timeout=30)
        time.sleep(0.5)

    try:
        assert step() != "rc=0"  # example.com is not listed
        for entry in ("a.com\n.*:443", "example.com"):  # never written into the filter
            bad = subprocess.run([BIN, "set-allow", doc["name"], entry], timeout=30, check=False)
            assert bad.returncode == 65
        set_allow("example.com:80", *ALLOW["allow"])
        assert step() != "rc=0"  # the https port is not listed
        set_allow("example.com:443", *ALLOW["allow"])
        assert step() == "rc=0"  # listed now, same running process
        set_allow(*ALLOW["allow"])
        assert step() != "rc=0"  # removed again
        assert proc.wait(timeout=30) == 0
    finally:
        proc.kill()


@requires_egress
def test_set_allow_while_starting(scope: Path) -> None:
    """`set-allow` on an instance still starting (its proxy not up yet; handlerd already counts it
    as the agent's connection) waits for its proxy, then applies (A.4)."""
    doc = spec(
        scope, sh(f"read x; {CURL} https://example.com >/dev/null; echo rc=$?"), network=ALLOW
    )
    proc = popen(BIN, doc, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdin is not None and proc.stdout is not None
    try:
        deadline = time.monotonic() + 30
        while not instance_dir(doc["name"]).exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert not (instance_dir(doc["name"]) / "proxy" / "ready").exists()  # still starting
        allow = [BIN, "set-allow", doc["name"], "example.com:443", *ALLOW["allow"]]
        assert subprocess.run(allow, timeout=90, check=False).returncode == 0
        out, _ = proc.communicate(b"go\n", timeout=60)
        assert out.decode().strip() == "rc=0"
    finally:
        proc.kill()


# ── lifecycle (A4) ─────────────────────────────────────────────────────


def test_normal_exit_leaves_nothing(scope: Path) -> None:
    doc = spec(scope, ["true"], network=ALLOW)
    assert run(BIN, doc).returncode == 0
    assert leftovers(doc["name"]) == []


def test_sigterm_stops_and_cleans_up(scope: Path) -> None:
    doc = spec(scope, ["sleep", "300"], network=ALLOW)
    proc = popen(
        BIN, doc, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            running = subprocess.run(
                ["podman", "ps", "--filter", f"name=^{doc['name']}$", "--format", "{{.Names}}"],
                capture_output=True, text=True, check=False,
            ).stdout.strip()  # fmt: skip
            if running:
                break
            time.sleep(0.2)
        else:
            pytest.fail("sandbox never started")
        start = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=30)
        assert time.monotonic() - start < 15
        assert leftovers(doc["name"]) == []
    finally:
        proc.kill()
