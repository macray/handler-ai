"""Contract A conformance, every runtime (contract A): a spec refused or run, its
process and stdio, its terminal, what it sees of the filesystem, and what it leaves behind."""

import contextlib
import fcntl
import json
import os
import pty
import shutil
import signal
import struct
import subprocess
import termios
import time
from pathlib import Path

import pytest

from handler_harness.render import SANDBOX_ENV, SANDBOX_ENV_SCRIPT

from ...support import dev_env
from ...support.dev_env import sandbox_gid, sandbox_uid
from ...support.runtimes import Runtime
from ..conftest import HOME_IN, popen, requires_internet, run, skip_unless_usable, spec

# Hosts no agent has a secret for: an agent running these tests chains to its own proxy, which
# decrypts its secrets' hosts with a CA these sandboxes do not trust.
ALLOW = {"mode": "filtered", "allow": ["www.example.org:443"], "enforcement": "enforce"}


def sh(script: str) -> list[str]:
    return ["sh", "-c", script]


# ── spec handling (A1) ──────────────────────────────────────────────────


@pytest.mark.rule("sandbox.an-invalid-spec-is-refused")
def test_invalid_spec_is_rejected(runtime: Runtime, scope: Path) -> None:
    doc = spec(scope, ["true"]) | {"workdir": "/etc"}
    assert run(runtime.binary, doc).returncode == 65


@pytest.mark.rule("sandbox.refuses-what-it-cannot-enforce")
def test_refuses_a_missing_folder(runtime: Runtime, scope: Path) -> None:
    folder = {"source": "/nonexistent/x", "target": "/data", "writable": False}
    assert run(runtime.binary, spec(scope, ["true"], folders=[folder])).returncode == 64


@pytest.mark.rule("sandbox.an-invalid-spec-is-refused")
def test_a_file_outside_the_home_is_an_invalid_spec(runtime: Runtime, scope: Path) -> None:
    file = {"target": "/etc/handler.conf", "content": "k=v\n", "mode": "0444"}
    assert run(runtime.binary, spec(scope, ["true"], files=[file])).returncode == 65


# ── confinement (A3, A.5) ───────────────────────────────────────────────

# /dev/fuse: absent (podman), or the root's only (Apple's VMs have one)
CONFINEMENT = (
    "grep -E '^(CapBnd|NoNewPrivs)' /proc/self/status | tr -s '\\t' ' ';"
    " { test -r /dev/fuse || test -w /dev/fuse; } && echo fuse-usable"
)


@pytest.mark.rule("sandbox.hardened-by-default")
def test_strict_confinement_drops_everything(runtime: Runtime, scope: Path) -> None:
    out = run(runtime.binary, spec(scope, sh(CONFINEMENT))).stdout.decode()
    assert "NoNewPrivs: 1" in out
    assert "CapBnd: 0000000000000000" in out
    assert "fuse-usable" not in out


@pytest.mark.rule("confinement.only-the-container-loosens")
@pytest.mark.parametrize("confinement", ["nested", "privileged"])
def test_only_the_container_loosens(runtime: Runtime, scope: Path, confinement: str) -> None:
    """A looser level keeps the user, the mounts and a filtered network's list: a local
    destination listed, one not (the filter's decisions alone, not the internet)."""
    skip_unless_usable(runtime, confinement)
    sibling = scope.parent / (scope.name + "-sibling")
    sibling.mkdir()
    try:
        with runtime.local_server() as listed, runtime.local_server() as unlisted:
            fetch = "curl -s -m 10 -o /dev/null -w '%{http_code}' --retry 5 --retry-connrefused"
            script = (
                "echo uid=$(id -u) gid=$(id -g);"
                f" ls {sibling} >/dev/null 2>&1 && echo sibling=visible || echo sibling=invisible;"
                " touch /x 2>/dev/null && echo root=writable || echo root=ro;"
                f" echo listed=$({fetch} http://{listed}:8000/);"
                f" echo unlisted=$({fetch} http://{unlisted}:8000/);"
                f" curl -s -m 5 --noproxy '*' -o /dev/null http://{listed}:8000/; echo direct=$?"
            )
            network = {"mode": "filtered", "allow": [f"{listed}:8000"], "enforcement": "enforce"}
            doc = spec(scope, sh(script), isolation=confinement, network=network)
            r = run(runtime.binary, doc, unchained=True)
    finally:
        sibling.rmdir()
    assert r.returncode == 0, r.stderr.decode()
    out = dict(line.split("=", 1) for line in r.stdout.decode().split())
    assert out.pop("direct") != "0", r.stderr.decode()  # only its proxy reaches out
    assert out == {
        "uid": str(sandbox_uid()), "gid": str(sandbox_gid()), "sibling": "invisible",
        "root": "ro", "listed": "200", "unlisted": "403",
    }, r.stderr.decode()  # fmt: skip


TOOLBOX = os.environ.get("HANDLER_TEST_TOOLBOX_IMAGE", "localhost/handler-ai-toolbox:latest")


@pytest.mark.rule("confinement.nested-gives-only-the-host-s-part")
@requires_internet
@pytest.mark.timeout(dev_env.IMAGE_TIMEOUT)
def test_containers_run_inside_a_nested_toolbox_sandbox(runtime: Runtime, scope: Path) -> None:
    skip_unless_usable(runtime, "nested")
    if run(runtime.binary, spec(scope, ["which", "podman"], image=TOOLBOX)).returncode != 0:
        pytest.skip(f"{TOOLBOX} not built, or without podman")
    inner = f"podman run --rm -q {dev_env.ALPINE_IMAGE} sh -c 'echo inner-ok'"
    doc = spec(scope, sh(inner), isolation="nested", image=TOOLBOX, network={"mode": "open"})
    r = run(runtime.binary, doc, timeout=300)
    assert "inner-ok" in r.stdout.decode(), r.stderr.decode()


# ── process & stdio (A5) ────────────────────────────────────────────────


@pytest.mark.rule("sandbox.stdio-is-the-agent-s-stream")
def test_stdio_roundtrip_1mb(runtime: Runtime, scope: Path) -> None:
    line = json.dumps({"jsonrpc": "2.0", "method": "x", "params": {"p": "a" * 1_048_576}}) + "\n"
    r = run(runtime.binary, spec(scope, ["cat"]), stdin=line.encode())
    assert r.returncode == 0
    assert r.stdout == line.encode()


@pytest.mark.rule("sandbox.stdio-is-the-agent-s-stream")
def test_exit_code_propagates(runtime: Runtime, scope: Path) -> None:
    assert run(runtime.binary, spec(scope, sh("exit 7"))).returncode == 7


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


def test_tty_is_a_terminal_attached_to_that_follows_resizes(runtime: Runtime, scope: Path) -> None:
    """D.16: with `tty`, launch's stdio is not the process's: it says it is ready, then `attach`
    runs the process on the caller's terminal, its size, resized with it, nothing else drawn
    there (Apple's start spinner); the exit code is attach's; launch cleans up once it ends."""
    # the resize reaches the process when the runtime has forwarded it (SIGWINCH, asynchronous):
    # waited for in the sandbox, at most 30 s, not guessed by the test
    script = (
        "[ -t 0 ] && echo on-a-tty; stty size; read -r x; i=0;"
        ' while [ "$(stty size)" = "30 100" ] && [ $i -lt 300 ]; do sleep 0.1; i=$((i+1)); done;'
        " stty size; exit 5"
    )
    doc = spec(scope, sh(script), tty=True)
    launcher = popen(runtime.binary, doc, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _ready(launcher)
    pid, master = pty.fork()
    if pid == 0:  # its terminal's size set before attach reads it
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        os.execvp(runtime.binary, [runtime.binary, "attach", doc["name"]])
    output, resized = b"", False
    with contextlib.suppress(OSError):  # EIO once it is gone
        while chunk := os.read(master, 4096):
            output += chunk
            if b"30 100" in output and not resized:
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
                os.write(master, b"go\r")
                resized = True
    os.close(master)
    assert _exit_code(pid) == 5, output
    assert b"on-a-tty" in output and b"40 120" in output, output
    assert output.startswith(b"on-a-tty"), output  # nothing of the runtime's own on it first
    launcher.wait(timeout=60)
    assert runtime.leftovers(doc["name"]) == []


def test_tty_hang_up_stops_the_sandbox(runtime: Runtime, scope: Path) -> None:
    """Closing the attached terminal (its hang-up) stops the sandbox, and launch cleans up."""
    doc = spec(scope, sh("echo started; sleep 600"), tty=True)
    launcher = popen(runtime.binary, doc, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _ready(launcher)
    pid, master = pty.fork()
    if pid == 0:
        os.execvp(runtime.binary, [runtime.binary, "attach", doc["name"]])
    output = b""
    while b"started" not in output:
        output += os.read(master, 4096)
    os.close(master)  # the terminal goes away: SIGHUP to its session leader, attach
    _exit_code(pid)
    launcher.wait(timeout=60)
    assert runtime.leftovers(doc["name"]) == []


@pytest.mark.rule("sandbox.stdio-is-the-agent-s-stream")
def test_a_terminal_s_exit_code_is_launch_s(runtime: Runtime, scope: Path) -> None:
    """With `tty`, `launch` too exits with the process's code, not only its `attach` (what
    handlerd reads of a terminal's end)."""
    doc = spec(scope, sh("echo started; exit 5"), tty=True)
    launcher = popen(runtime.binary, doc, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _ready(launcher)
    pid, master = pty.fork()
    if pid == 0:
        os.execvp(runtime.binary, [runtime.binary, "attach", doc["name"]])
    with contextlib.suppress(OSError):  # EIO once it is gone
        while os.read(master, 4096):
            pass
    os.close(master)
    assert _exit_code(pid) == 5
    assert launcher.wait(timeout=60) == 5
    assert runtime.leftovers(doc["name"]) == []


# ── identity, home, filesystem (A2, A3) ────────────────────────────────


@pytest.mark.rule(
    "sandbox.read-only-stays-read-only",
    "sandbox.runs-as-the-host-user",
    "sandbox.hardened-by-default",
)
def test_identity_home_and_readonly_rootfs(runtime: Runtime, scope: Path) -> None:
    script = (
        'id -u; id -g; echo "$HOME"; touch "$HOME/x" && echo home-ok;'
        " touch /x 2>/dev/null || echo rootfs-ro"
    )
    r = run(runtime.binary, spec(scope, sh(script)))
    out = r.stdout.decode().split()
    uid, gid = str(sandbox_uid()), str(sandbox_gid())
    assert out == [uid, gid, HOME_IN, "home-ok", "rootfs-ro"]


@pytest.mark.rule("sandbox.home-starts-empty")
def test_the_home_starts_empty_over_image_content(runtime: Runtime, scope: Path) -> None:
    """The home is empty, even where the image has files (e.g. a build-time ~/.cache)."""
    doc = spec(scope, sh('ls -A "$HOME"; echo end'), home="/etc/ssl")
    assert run(runtime.binary, doc).stdout.decode().split() == ["end"]


@pytest.mark.rule("sandbox.work-folder-at-the-same-path", "sandbox.runs-as-the-host-user")
def test_scope_same_path_and_ownership(runtime: Runtime, scope: Path) -> None:
    r = run(runtime.binary, spec(scope, sh("pwd; echo data > written.txt")))
    assert r.stdout.decode().strip() == str(scope)
    written = scope / "written.txt"
    assert written.read_text() == "data\n"
    assert (written.stat().st_uid, written.stat().st_gid) == (sandbox_uid(), sandbox_gid())


@pytest.mark.rule("sandbox.sees-only-what-it-is-given")
def test_paths_outside_mounts_are_invisible(runtime: Runtime, scope: Path) -> None:
    sibling = scope.parent / (scope.name + "-sibling")
    sibling.mkdir()
    try:
        script = f"ls {sibling} >/dev/null 2>&1 && echo visible || echo invisible"
        r = run(runtime.binary, spec(scope, sh(script)))
        assert r.stdout.decode().strip() == "invisible"
    finally:
        sibling.rmdir()


@pytest.mark.rule("sandbox.read-only-stays-read-only")
def test_read_only_folder(runtime: Runtime, scope: Path) -> None:
    ro = scope.parent / (scope.name + "-ro")
    ro.mkdir()
    (ro / "f").write_text("keep\n")
    try:
        folder = {"source": str(ro), "target": "/data", "writable": False}
        script = "cat /data/f; echo x > /data/f 2>/dev/null || echo ro-ok"
        r = run(runtime.binary, spec(scope, sh(script), folders=[folder]))
        assert r.stdout.decode().split() == ["keep", "ro-ok"]
        assert (ro / "f").read_text() == "keep\n"
    finally:
        (ro / "f").unlink()
        ro.rmdir()


@pytest.mark.rule(
    "sandbox.sees-only-what-it-is-given",
    "sandbox.read-only-stays-read-only",
    "need.a-file-given-is-that-file",
)
def test_a_file_is_given_alone_at_its_path(runtime: Runtime, scope: Path) -> None:
    """An app's file need (H.9): a folder whose source is a file. The sandbox sees that file
    only (not what is beside it), writes in it when writable, never when read-only; on Apple
    container, through a link in a folder of its own (it mounts folders only).
    If this fails: an app reads the files next to the one you gave, or writes one given
    read-only; or no app with a file need runs on this runtime."""
    mine = scope.parent / (scope.name + "-files")
    (mine / "ro").mkdir(parents=True)
    (mine / "rw").mkdir()
    (mine / "ro" / "agenda.md").write_text("a\n")
    (mine / "rw" / "notes.md").write_text("n\n")
    (mine / "ro" / "secret.txt").write_text("s\n")
    try:
        folders = [
            {"source": str(mine / "ro" / "agenda.md"), "target": str(mine / "ro" / "agenda.md"),
             "writable": False},
            {"source": str(mine / "rw" / "notes.md"), "target": str(mine / "rw" / "notes.md"),
             "writable": True},
        ]  # fmt: skip
        script = (
            f"cat {mine}/ro/agenda.md; ls {mine}/ro; "
            f"echo x >> {mine}/ro/agenda.md 2>/dev/null || echo ro-refused; "
            f"echo m >> {mine}/rw/notes.md && echo rw-written"
        )
        r = run(runtime.binary, spec(scope, sh(script), folders=folders))
        assert r.stdout.decode().split() == ["a", "agenda.md", "ro-refused", "rw-written"], (
            r.stderr.decode()
        )
        assert (mine / "ro" / "agenda.md").read_text() == "a\n"
        assert (mine / "rw" / "notes.md").read_text() == "n\nm\n"
        assert sorted(p.name for p in (mine / "ro").iterdir()) == ["agenda.md", "secret.txt"]
    finally:
        shutil.rmtree(mine, ignore_errors=True)


@pytest.mark.rule("need.a-file-given-is-that-file")
def test_a_file_given_is_that_file_until_replaced(runtime: Runtime, scope: Path) -> None:
    """The sandbox reads what the host writes in place; once the host replaces the file (an
    editor saving by rename), the sandbox keeps the one it was given: a Linux bind mount holds
    it; Apple container and Docker in a VM (whose sharing would lose it: "no such file") link it.
    If this fails: an app works on a copy of your file, or the limit the docs say changed
    (then say it again: known limitations, "A file you give an app")."""
    mine = scope.parent / (scope.name + "-file")
    mine.mkdir()
    agenda = mine / "agenda.md"
    agenda.write_text("a\n")
    try:
        given = {"source": str(agenda), "target": str(agenda), "writable": False}
        # `-` once the first cat has ended: written to before, it reads on and prints `b` too
        script = f"cat {agenda}; echo -; sleep 3; cat {agenda}; sleep 3; cat {agenda}"
        proc = popen(runtime.binary, spec(scope, sh(script), folders=[given]), stdout=-1, stderr=-1)
        assert proc.stdout is not None
        assert proc.stdout.readline() == b"a\n"
        assert proc.stdout.readline() == b"-\n"
        with agenda.open("a") as f:  # in place
            f.write("b\n")
        time.sleep(4)  # its second read
        new = mine / "agenda.md.new"
        new.write_text("replaced\n")
        new.replace(agenda)  # as an editor saves
        out, err = proc.communicate(timeout=60)
        assert out.decode().split() == ["a", "b", "a", "b"], err.decode()
        assert agenda.read_text() == "replaced\n"
    finally:
        shutil.rmtree(mine, ignore_errors=True)


def test_a_cache_folder_is_created_if_missing(
    runtime: Runtime, scope: Path, tmp_path: Path
) -> None:
    cache = tmp_path / "new" / "cargo"
    caches = [{"source": str(cache), "target": f"{HOME_IN}/.cargo"}]
    doc = spec(scope, sh('echo kept > "$HOME/.cargo/x"; echo ok'), caches=caches)
    r = run(runtime.binary, doc)
    assert r.stdout.decode().strip() == "ok", r.stderr
    assert (cache / "x").read_text() == "kept\n"


def test_a_cache_s_commands_are_on_path(runtime: Runtime, scope: Path, tmp_path: Path) -> None:
    """B.6: a cache's folder of commands (`~/.bun/bin`) after the image's PATH."""
    cache = tmp_path / "bun"
    (cache / "bin").mkdir(parents=True)
    (cache / "bin" / "hello-cache").write_text("#!/bin/sh\necho from-the-cache\n")
    (cache / "bin" / "hello-cache").chmod(0o755)
    target = f"{HOME_IN}/.bun"
    caches = [{"source": str(cache), "target": target, "path": f"{target}/bin"}]
    r = run(runtime.binary, spec(scope, sh('hello-cache; echo "$PATH"'), caches=caches))
    said, path = r.stdout.decode().split()
    assert said == "from-the-cache", r.stderr
    assert path.endswith(f":{target}/bin")


def test_a_tool_is_an_executable_in_handler_s_folder(runtime: Runtime, scope: Path) -> None:
    tool = {"target": "/run/handler/bin/hello", "content": "#!/bin/sh\necho hello\n"}
    script = "/run/handler/bin/hello; echo x >> /run/handler/bin/hello 2>/dev/null || echo ro-ok"
    r = run(runtime.binary, spec(scope, sh(script), tools=[tool]))
    assert r.stdout.decode().split() == ["hello", "ro-ok"], r.stderr


# What a process started with an empty environment finds as the sandbox's (A8): the environment
# of the outermost process of the sandbox it can read. The argv's own shell holds the spec's
# environment (the harness, in a session); `env -i` starts a child without it (an MCP server).
_EMPTY_CHILD = 'env -i sh -c "$1"; exit $?'
_OUTERMOST = (
    'p=$$; last=$$; while [ "$p" -gt 0 ] && cat /proc/$p/environ >/dev/null 2>&1; do'
    " last=$p; p=$(awk '/^PPid:/{print $2}' /proc/$p/status); done;"
    " tr '\\0' '\\n' < /proc/$last/environ"
)


@pytest.mark.rule("launch.stdio-mcp-servers-see-the-sandbox")
def test_the_sandbox_s_environment_is_readable_by_its_user(runtime: Runtime, scope: Path) -> None:
    """A8, on every runtime and any image: the spec's environment is where handler-sandbox-env
    looks (on Apple container, PID 1 is root's: the relay's child holds it)."""
    doc = spec(scope, ["sh", "-c", _EMPTY_CHILD, "sh", _OUTERMOST], env={"HANDLER_A8": "spec"})
    r = run(runtime.binary, doc)
    assert "HANDLER_A8=spec" in r.stdout.decode().splitlines(), r.stderr.decode()


@pytest.mark.rule("launch.stdio-mcp-servers-see-the-sandbox")
def test_handler_sandbox_env_restores_the_sandbox_s_environment(
    runtime: Runtime, scope: Path
) -> None:
    """The wrapper itself (it needs python3: the toolbox), as MCP servers are started: from an
    empty environment, it gets the spec's, minus what it is told to drop."""
    if run(runtime.binary, spec(scope, ["which", "python3"], image=TOOLBOX)).returncode != 0:
        pytest.skip(f"{TOOLBOX} not built")
    tool = {"target": SANDBOX_ENV, "content": SANDBOX_ENV_SCRIPT}
    wrapped = f"{SANDBOX_ENV} --drop HANDLER_SECRET -- env"
    doc = spec(
        scope,
        ["sh", "-c", _EMPTY_CHILD, "sh", wrapped],
        image=TOOLBOX,
        tools=[tool],
        env={"HANDLER_A8": "spec", "HANDLER_SECRET": "token"},
    )
    r = run(runtime.binary, doc)
    lines = r.stdout.decode().splitlines()
    assert "HANDLER_A8=spec" in lines, r.stderr.decode()
    assert not any(line.startswith("HANDLER_SECRET=") for line in lines)


@pytest.mark.rule("sandbox.read-only-stays-read-only")
def test_a_read_only_file_keeps_its_parents_writable(runtime: Runtime, scope: Path) -> None:
    """A file Handler gives in a folder the home does not have yet (pi's ~/.config/mcp/mcp.json):
    read-only, and ~/.config stays the sandbox user's, so e.g. Chromium can create
    ~/.config/chromium."""
    script = (
        'cat "$HOME/.config/mcp/mcp.json"; mkdir "$HOME/.config/chromium" && echo parent-ok;'
        ' echo x >> "$HOME/.config/mcp/mcp.json" 2>/dev/null || echo ro-ok'
    )
    doc = spec(scope, sh(script))
    doc["files"] = [
        {"target": f"{HOME_IN}/.config/mcp/mcp.json", "content": "{}\n", "mode": "0444"}
    ]
    r = run(runtime.binary, doc)
    assert r.stdout.decode().split() == ["{}", "parent-ok", "ro-ok"], r.stderr
    assert runtime.leftovers(doc["name"]) == []


def test_a_writable_file_is_replaceable(runtime: Runtime, scope: Path) -> None:
    """A writable file can be rewritten atomically (temp file + rename), unlike a mounted one."""
    script = (
        'cat "$HOME/.app/conf.toml"; echo "b = 2" > "$HOME/.app/.conf.tmp";'
        ' mv "$HOME/.app/.conf.tmp" "$HOME/.app/conf.toml" && cat "$HOME/.app/conf.toml"'
    )
    conf = {"target": f"{HOME_IN}/.app/conf.toml", "content": "a = 1\n", "mode": "0600"}
    doc = spec(scope, sh(script), files=[conf | {"writable": True}])
    r = run(runtime.binary, doc)
    assert r.stdout.decode().split("\n")[:2] == ["a = 1", "b = 2"], r.stderr
    assert runtime.leftovers(doc["name"]) == []  # the per-instance copy is gone


@pytest.mark.parametrize("written", [True, False])
def test_a_folder_in_the_home_keeps_its_parents_writable(
    runtime: Runtime, scope: Path, tmp_path: Path, written: bool
) -> None:
    """A folder deep in the home (e.g. a per-session folder at ~/.vibe/logs/session): the
    folders the runtime would create for it (~/.vibe/logs) stay writable by the sandbox user,
    a writable file next to them or not."""
    state = tmp_path / "state"
    state.mkdir()
    state.chmod(0o777)  # tests may run as another user than the sandbox (dev_env)
    script = 'touch "$HOME/.app/logs/app.log" && touch "$HOME/.app/logs/session/s" && echo ok'
    folder = {"source": str(state), "target": f"{HOME_IN}/.app/logs/session", "writable": True}
    doc = spec(scope, sh(script), folders=[folder])
    if written:
        conf = {"target": f"{HOME_IN}/.app/conf.toml", "content": "a = 1\n", "mode": "0600"}
        doc["files"] = [conf | {"writable": True}]
    r = run(runtime.binary, doc)
    assert r.stdout.decode().strip() == "ok", r.stderr.decode()
    assert (state / "s").exists()


@pytest.mark.rule("need.a-file-given-is-that-file")
def test_a_file_given_in_the_home_is_mounted_as_a_file(runtime: Runtime, scope: Path) -> None:
    """An app's file need whose path is in the sandbox's home (a person whose own home is
    where the sandbox's is): its mount point there is a file, not a folder.
    If this fails: such an app does not start ("Not a directory")."""
    mine = scope.parent / (scope.name + "-in-home")  # beside the scope: Apple's links need it
    mine.mkdir()
    given = mine / "agenda.md"
    given.write_text("a\n")
    try:
        target = f"{HOME_IN}/notes/agenda.md"
        folder = {"source": str(given), "target": target, "writable": False}
        r = run(runtime.binary, spec(scope, sh(f"cat {target}"), folders=[folder]))
        assert r.stdout.decode() == "a\n", r.stderr.decode()
    finally:
        shutil.rmtree(mine, ignore_errors=True)


def test_a_kept_file_alone_in_its_folder(runtime: Runtime, scope: Path, tmp_path: Path) -> None:
    """A state file the harness rewrites (Claude Code's ~/.claude.json), alone in its folder
    (A.1): what the sandbox writes in it is on the host after."""
    (tmp_path / "config_json").mkdir()
    state = tmp_path / "config_json" / "config_json"
    state.write_text("{}\n")
    state.chmod(0o666)  # tests may run as another user than the sandbox (dev_env)
    target = f"{HOME_IN}/.claude.json"
    script = f"cat {target}; echo '{{\"kept\": 1}}' > {target}; echo done"
    doc = spec(scope, sh(script), keptFiles=[{"source": str(state), "target": target}])
    r = run(runtime.binary, doc)
    assert r.stdout.decode().split() == ["{}", "done"], r.stderr
    assert state.read_text() == '{"kept": 1}\n'


def test_env_is_passed(runtime: Runtime, scope: Path) -> None:
    doc = spec(scope, sh('echo "$SECRET_X"'), env={"SECRET_X": "s3cr3t"})
    assert run(runtime.binary, doc).stdout.decode().strip() == "s3cr3t"


# ── lifecycle (A4) ─────────────────────────────────────────────────────


@pytest.mark.rule("sandbox.leaves-nothing-behind")
def test_normal_exit_leaves_nothing(runtime: Runtime, scope: Path) -> None:
    doc = spec(scope, ["true"], network=ALLOW)
    assert run(runtime.binary, doc).returncode == 0
    assert runtime.leftovers(doc["name"]) == []


@pytest.mark.rule("sandbox.leaves-nothing-behind")
def test_sigterm_stops_and_cleans_up(runtime: Runtime, scope: Path) -> None:
    doc = spec(scope, ["sleep", "300"], network=ALLOW)
    proc = popen(
        runtime.binary,
        doc,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while not runtime.running(doc["name"]):
            if time.monotonic() > deadline:
                pytest.fail("sandbox never started")
            time.sleep(0.2)
        start = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=30)
        assert time.monotonic() - start < 15
        assert runtime.leftovers(doc["name"]) == []
    finally:
        proc.kill()
