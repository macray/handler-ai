"""The sandbox's executable — the only way to reach a sandbox (contract A binding), never by import.

handler-sandbox-<impl> launch           with the SandboxSpec JSON on fd 3; its stdin/stdout are
                                        the agent's ACP stream (with `tty`, D.16: none, the
                                        client runs `attach`), stderr carries logs and egress
                                        events
handler-sandbox-<impl> set-allow|set-egress on a running sandbox (A.4)
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

IMPLEMENTATION = "handler-sandbox-podman"
LAUNCHER_PREFIX = f"{IMPLEMENTATION}: "  # a line of the launcher's own, not the sandbox's logs
# tests only: another executable in its place (tests/support/fake_sandbox.py, which runs the fake
# harness on the host so the daemon's tests need no container)
TEST_SANDBOX_ENV = "HANDLER_TEST_SANDBOX"
SPEC_FD = 3
EGRESS_PREFIX = "handler-egress "
STOP_TIMEOUT = 20.0
FOLLOW_INTERVAL = 0.2  # seconds between two reads of a detached launcher's output


def binary() -> str:
    """The implementation's executable: next to our interpreter first (same install), else PATH."""
    if test := os.environ.get(TEST_SANDBOX_ENV):
        return test
    name = IMPLEMENTATION
    sibling = Path(sys.executable).parent / name
    if sibling.exists():
        return str(sibling)
    return shutil.which(name) or name


def prepare_host_dirs(spec: SandboxSpec) -> None:
    """Create cache directories that do not exist yet (a project's own are made on first use).

    Only `cache` mounts: a missing scope or state path is an error the sandbox must report (A1).
    """
    for m in spec.mounts:
        if m.kind == "cache":
            Path(m.source).mkdir(parents=True, exist_ok=True)


def _spec_fd(spec: SandboxSpec) -> int:
    with tempfile.TemporaryFile() as f:
        f.write(spec.model_dump_json(by_alias=True, exclude_none=True).encode())
        f.flush()
        f.seek(0)
        return os.dup(f.fileno())  # the dup keeps the unlinked file alive


def _fd_kwargs(fd: int) -> dict[str, Any]:
    return {
        "pass_fds": (fd, SPEC_FD),  # SPEC_FD must survive close_fds, which runs after preexec_fn
        "preexec_fn": lambda: os.dup2(fd, SPEC_FD),
    }


def start(spec: SandboxSpec, **popen_kwargs: Any) -> subprocess.Popen[bytes]:
    """Launch the sandbox for `spec`; the caller owns the returned process (its stdio)."""
    prepare_host_dirs(spec)
    fd = _spec_fd(spec)
    try:
        return subprocess.Popen(  # ty: ignore[invalid-return-type]
            [binary(), "launch"], **_fd_kwargs(fd), **popen_kwargs
        )
    finally:
        os.close(fd)


async def start_async(spec: SandboxSpec, *, line_limit: int) -> asyncio.subprocess.Process:
    """Same, for asyncio: stdin/stdout/stderr are pipes; `line_limit` bounds one ACP message."""
    prepare_host_dirs(spec)
    fd = _spec_fd(spec)
    try:
        return await asyncio.create_subprocess_exec(
            binary(),
            "launch",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=line_limit,
            **_fd_kwargs(fd),
        )
    finally:
        os.close(fd)


async def start_piped(spec: SandboxSpec, *, line_limit: int) -> asyncio.subprocess.Process:
    """Same, for a process that serves something else than its stdio (an app's backend):
    no stdin, stdout and stderr merged into one pipe for its log."""
    prepare_host_dirs(spec)
    fd = _spec_fd(spec)
    try:
        return await asyncio.create_subprocess_exec(
            binary(),
            "launch",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            limit=line_limit,
            **_fd_kwargs(fd),
        )
    finally:
        os.close(fd)


def start_detached(spec: SandboxSpec) -> tuple[subprocess.Popen[bytes], int]:
    """Same, for a `tty` spec (D.16), whose launcher outlives handlerd: in a session of its own (out
    of handlerd's process group) and, when handlerd runs as a systemd unit, in a scope of its own
    (the unit's stop or restart kills every process in it); no stdin; its output (stdout and stderr)
    into an unlinked file, as a pipe would break with handlerd. Returns the process and that file,
    for `follow`; the caller closes it."""
    prepare_host_dirs(spec)
    fd = _spec_fd(spec)
    argv = [binary(), "launch"]
    if os.environ.get("INVOCATION_ID") and (systemd_run := shutil.which("systemd-run")):
        scope = [systemd_run, "--user", "--scope", "--collect", "--quiet", f"--unit={spec.name}"]
        argv = [*scope, "--", *argv]
    with tempfile.TemporaryFile() as output:
        try:
            proc: subprocess.Popen[bytes] = subprocess.Popen(  # ty: ignore[invalid-assignment]
                argv,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=output,
                start_new_session=True,
                **_fd_kwargs(fd),
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
        if on_launcher is not None and line.startswith(LAUNCHER_PREFIX):
            on_launcher(line.removeprefix(LAUNCHER_PREFIX))
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
