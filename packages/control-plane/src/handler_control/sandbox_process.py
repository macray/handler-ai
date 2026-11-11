"""The sandbox's executable — the only way to reach a sandbox (contract A binding), never by import.

handler-sandbox-<impl> launch           with the SandboxSpec JSON on fd 3; its stdin/stdout are
                                        the agent's ACP stream (with `tty`, D.16: none, the
                                        client runs `attach`), stderr carries logs and egress
                                        events
handler-sandbox-<impl> set-allow|set-blocked|set-egress|set-watched on a running sandbox (A.4)
handler-sandbox-<impl> attach NAME      run by `handler terminal` (D.16), never by handlerd
handler-sandbox-<impl> sweep            what launchers that died left behind (daemon.py)
"""

import asyncio
import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from handler_contracts import Enforcement, SandboxSpec

log = logging.getLogger("handler.sandbox")

EXECUTABLE_PREFIX = "handler-sandbox-"  # + the runtime's name: its executable (contract A)
# the runtime handlerd uses when none was chosen: the system's (D.2)
DEFAULT_RUNTIME = "apple" if sys.platform == "darwin" else "podman"
_runtime = [DEFAULT_RUNTIME]  # the one in use (runtime.toml, read at start: runtime.load)
# tests only: another executable in its place (tests/support/fake_sandbox.py, which runs the fake
# harness on the host so the daemon's tests need no container)
TEST_SANDBOX_ENV = "HANDLER_TEST_SANDBOX"
SPEC_FD = 3
EGRESS_PREFIX = "handler-egress "
STOP_TIMEOUT = 20.0
FOLLOW_INTERVAL = 0.2  # seconds between two reads of a detached launcher's output


def give_dev_agent(*folders: Path) -> None:
    """Dev containers (handlerd as root, the sandbox's user HANDLER_SANDBOX_DEV_UID, A3): the
    folders a sandbox writes (an app backend's, a run's output) become that uid's, as they are
    the host user's elsewhere."""
    dev = os.environ.get("HANDLER_SANDBOX_DEV_UID")
    if not dev:
        return
    for folder in folders:
        os.chown(folder, int(dev), int(dev), follow_symlinks=False)
        for parent, dirs, names in os.walk(folder):
            for entry in (*dirs, *names):
                os.chown(Path(parent) / entry, int(dev), int(dev), follow_symlinks=False)


def current() -> str:
    """The sandbox runtime in use, by name ("podman")."""
    return _runtime[0]


def use(name: str) -> None:
    _runtime[0] = name


def executable(name: str) -> str | None:
    """Runtime `name`'s executable: next to our interpreter first (same install), else on PATH;
    None when it is not installed."""
    sibling = Path(sys.executable).parent / f"{EXECUTABLE_PREFIX}{name}"
    if sibling.exists():
        return str(sibling)
    return shutil.which(f"{EXECUTABLE_PREFIX}{name}")


MACOS_ONLY = "apple"  # Apple container: offered on macOS only, never elsewhere (D.2)
NOT_ON_MACOS = "podman"  # rootless Podman: never offered on macOS (Apple container instead)


def for_another_system(name: str) -> str | None:
    """Why runtime `name` is not offered on this system, or None when it is."""
    if name == MACOS_ONLY and sys.platform != "darwin":
        return f"the {name} runtime is for macOS"
    if name == NOT_ON_MACOS and sys.platform == "darwin":
        return f"the {name} runtime is not offered on macOS"
    return None


def installed() -> list[str]:
    """The runtimes installed here, by name: every `handler-sandbox-<name>` executable, but one
    for another system."""
    dirs = [Path(sys.executable).parent, *map(Path, os.environ.get("PATH", "").split(os.pathsep))]
    names = {
        f.name.removeprefix(EXECUTABLE_PREFIX)
        for d in dirs
        if d.is_dir()
        for f in d.glob(f"{EXECUTABLE_PREFIX}*")
        if os.access(f, os.X_OK)
    }
    return sorted(n for n in names if not for_another_system(n))


def binary() -> str:
    """The executable of the runtime in use."""
    if test := os.environ.get(TEST_SANDBOX_ENV):
        return test
    return executable(current()) or f"{EXECUTABLE_PREFIX}{current()}"


def launcher_prefix() -> str:
    """How a line of the launcher's own starts, not of the sandbox's logs."""
    return f"{EXECUTABLE_PREFIX}{current()}: "


def _spec_fd(spec: SandboxSpec) -> int:
    with tempfile.TemporaryFile() as f:
        f.write(spec.model_dump_json(by_alias=True, exclude_none=True).encode())
        f.flush()
        f.seek(0)
        return os.dup(f.fileno())  # the dup keeps the unlinked file alive


# Moves the spec from argv[1] to SPEC_FD, then becomes the runtime (argv[2:]).
_MOVE_SPEC = (
    "import os,sys;f=int(sys.argv[1]);os.dup2(f,%d);os.close(f);os.execvp(sys.argv[2],sys.argv[2:])"
)


def launch_argv(fd: int, runtime: str | None = None) -> list[str]:
    """`launch` with the spec moved from `fd` to SPEC_FD by a small Python program that then becomes
    the runtime. subprocess cannot move it itself (a dup2 in preexec_fn needs SPEC_FD in pass_fds,
    which fails in the child when the parent's SPEC_FD is not inherited by a fork: macOS's kqueue);
    nor can a shell portably: POSIX redirections take one digit (dash, Debian's and Ubuntu's
    /bin/sh, refuses `3<&14`: "Bad fd number")."""
    move = _MOVE_SPEC % SPEC_FD
    return [sys.executable, "-I", "-S", "-c", move, str(fd), runtime or binary(), "launch"]


def start(spec: SandboxSpec, **popen_kwargs: Any) -> subprocess.Popen[bytes]:
    """Launch the sandbox for `spec`; the caller owns the returned process (its stdio)."""
    fd = _spec_fd(spec)
    try:
        return subprocess.Popen(  # ty: ignore[invalid-return-type]
            launch_argv(fd), pass_fds=(fd,), **popen_kwargs
        )
    finally:
        os.close(fd)


async def start_async(spec: SandboxSpec, *, line_limit: int) -> asyncio.subprocess.Process:
    """Same, for asyncio: stdin/stdout/stderr are pipes; `line_limit` bounds one ACP message."""
    fd = _spec_fd(spec)
    try:
        return await asyncio.create_subprocess_exec(
            *launch_argv(fd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=line_limit,
            pass_fds=(fd,),
        )
    finally:
        os.close(fd)


async def start_piped(spec: SandboxSpec, *, line_limit: int) -> asyncio.subprocess.Process:
    """Same, for a process that serves something else than its stdio (an app's backend):
    no stdin, stdout and stderr merged into one pipe for its log."""
    fd = _spec_fd(spec)
    try:
        return await asyncio.create_subprocess_exec(
            *launch_argv(fd),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            limit=line_limit,
            pass_fds=(fd,),
        )
    finally:
        os.close(fd)


def start_detached(spec: SandboxSpec) -> tuple[subprocess.Popen[bytes], int]:
    """Same, for a `tty` spec (D.16), whose launcher outlives handlerd: in a session of its own (out
    of handlerd's process group) and, when handlerd runs as a systemd unit, in a scope of its own
    (the unit's stop or restart kills every process in it); no stdin; its output (stdout and stderr)
    into an unlinked file, as a pipe would break with handlerd. Returns the process and that file,
    for `follow`; the caller closes it."""
    fd = _spec_fd(spec)
    argv = launch_argv(fd)
    if os.environ.get("INVOCATION_ID") and (systemd_run := shutil.which("systemd-run")):
        scope = [systemd_run, "--user", "--scope", "--collect", "--quiet", f"--unit={spec.name}"]
        argv = [*scope, "--", *argv]
    with tempfile.TemporaryFile() as output:
        try:
            proc: subprocess.Popen[bytes] = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=output,
                start_new_session=True,
                pass_fds=(fd,),
            )
        finally:
            os.close(fd)
        return proc, os.dup(output.fileno())


async def follow(proc: subprocess.Popen[bytes], output: int) -> AsyncIterator[str]:
    """The lines of `start_detached`'s output, as they come, until its process ends."""
    offset, partial = 0, b""
    while True:
        ended = proc.poll() is not None
        while chunk := os.pread(output, 65536, offset):
            offset += len(chunk)
            partial += chunk
        *lines, partial = partial.split(b"\n")
        for line in lines:
            yield line.decode(errors="replace")
        if ended:
            if partial:
                yield partial.decode(errors="replace")
            return
        await asyncio.sleep(FOLLOW_INTERVAL)


async def stop(proc: asyncio.subprocess.Process) -> None:
    """Stop a sandbox: SIGTERM, then SIGKILL after a grace period."""
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), STOP_TIMEOUT)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()


async def read_stderr(
    proc: asyncio.subprocess.Process,
    label: str,
    on_egress: Callable[[dict[str, str]], None],
    on_launcher: Callable[[str], None] | None = None,
) -> None:
    """The sandbox's logs, logged under `label`; its egress events go to `on_egress` (A.3
    observability), what its launcher itself says (why it did not start, A.1) to `on_launcher`."""
    assert proc.stderr is not None
    async for raw in proc.stderr:
        line = raw.decode(errors="replace").rstrip()
        if on_launcher is not None and line.startswith(prefix := launcher_prefix()):
            on_launcher(line.removeprefix(prefix))
        log_line(line, label, on_egress)


def log_line(line: str, label: str, on_egress: Callable[[dict[str, str]], None]) -> None:
    """One line of the sandbox's stderr: an egress event to `on_egress`, else logged."""
    if line.startswith(EGRESS_PREFIX):
        with contextlib.suppress(ValueError):
            on_egress(json.loads(line[len(EGRESS_PREFIX) :]))
            return
    log.info("[%s] %s", label, line)


def attach_command(sandbox: str) -> list[str]:
    """What a client runs to attach its terminal to a `tty` sandbox (D.16)."""
    return [binary(), "attach", sandbox]


async def set_allow(sandbox: str, allow: list[str]) -> str | None:
    """A running filtered sandbox's allow-list, replaced (A.4); the error, if any."""
    return await _verb("set-allow", sandbox, *allow)


async def set_blocked(sandbox: str, blocked: list[str]) -> str | None:
    """A running filtered sandbox's hosts kept blocked, replaced (A.4); the error, if any."""
    return await _verb("set-blocked", sandbox, *blocked)


async def set_watched(sandbox: str, turn: str | None) -> str | None:
    """Whether someone watches a running filtered sandbox's session, in which turn (None:
    nobody), so its filter holds a request a while for their answer (A.4); the error, if any."""
    return await _verb("set-watched", sandbox, *([turn] if turn else []))


async def set_egress(sandbox: str, egress: Enforcement) -> str | None:
    """A running filtered sandbox's enforcement, switched (A.4); the error, if any."""
    return await _verb("set-egress", sandbox, egress)


async def _verb(*args: str) -> str | None:
    proc = await asyncio.create_subprocess_exec(
        binary(),
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    return err.decode().strip() or f"exit {proc.returncode}" if proc.returncode else None
