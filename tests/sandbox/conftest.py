"""Shared helpers for the contract A conformance suite."""

import functools
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ..support import dev_env, place, runtimes

CURL_IMAGE = dev_env.CURL_IMAGE
HOME_IN = "/home/agent"


def podman_usable() -> bool:
    if not shutil.which("podman"):
        return False
    return subprocess.run(["podman", "info"], capture_output=True, check=False).returncode == 0


requires_podman = pytest.mark.skipif(not podman_usable(), reason="podman not usable")


@pytest.fixture(params=runtimes.available(), ids=lambda r: r.name)
def runtime(request: pytest.FixtureRequest) -> runtimes.Runtime:
    """Each sandbox runtime installed here (tests/support/runtimes.py): the conformance suite
    (conformance/) runs once per runtime."""
    return request.param


def skip_unless_usable(runtime: runtimes.Runtime, confinement: str) -> None:
    """Skip what the runtime does not give here, or what this place cannot test (place.py); with
    HANDLER_TEST_STRICT, a confinement it gives that fails here is a failure."""
    if confinement != "strict" and confinement not in runtime.abilities:
        pytest.skip(f"{runtime.name} does not give {confinement} confinement here")
    if reason := place.not_here(confinement):
        pytest.skip(reason)
    if not runtime.confinement_usable(confinement):
        message = f"{runtime.name} gives {confinement} confinement, but it fails here"
        if place.STRICT:
            pytest.fail(f"{message} (HANDLER_TEST_STRICT)")
        pytest.skip(message)


def direct_internet() -> bool:
    """A connection out without a proxy: what the egress filter (A.4) makes itself. Not so in a
    sandbox that has only an HTTP proxy out (e.g. a handler agent running these tests)."""
    if os.environ.get("HANDLER_TEST_OFFLINE"):
        return False
    try:
        socket.create_connection(("www.example.org", 443), timeout=3).close()
    except OSError:
        return False
    return True


requires_internet = pytest.mark.skipif(
    not direct_internet(), reason="no direct internet (HANDLER_TEST_OFFLINE, or a proxy only)"
)


@functools.cache
def upstream_env() -> dict[str, str]:
    """Without direct internet but with a proxy out (a handler agent running these tests), the
    sandboxes' proxies go out through it (HANDLER_SANDBOX_DEV_UPSTREAM_PROXY): the filtered network
    is tested there too. Only for these tests' launches: local destinations fail through it."""
    url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if os.environ.get("HANDLER_TEST_OFFLINE") or not url or direct_internet():
        return {}
    # retried: every test worker asks at once when it starts, under load
    retry = ["--retry", "2", "--retry-all-errors", "-m", "10"]
    argv = ["curl", "-s", *retry, "-o", "/dev/null", "-x", url, "https://www.example.org"]
    if subprocess.run(argv, capture_output=True, check=False).returncode != 0:
        return {}
    return {"HANDLER_SANDBOX_DEV_UPSTREAM_PROXY": url}


requires_egress = pytest.mark.skipif(
    not (direct_internet() or upstream_env()), reason="no internet (HANDLER_TEST_OFFLINE)"
)


@pytest.fixture(scope="session", autouse=True)
def _pull_images() -> None:
    """What the suite's sandboxes run, in each runtime's own images (A.7 verbs)."""
    for r in runtimes.available():
        dev_env.ensure_image(CURL_IMAGE, r.binary)
        dev_env.ensure_network_filter(r.binary)


@pytest.fixture
def scope() -> Iterator[Path]:
    """A scope directory outside /tmp (the sandbox mounts its own /tmp)."""
    path = dev_env.make_scope()
    yield path
    dev_env.remove_scope(path)


def on_display(socket: str) -> dict[str, str]:
    """The launcher's environment finding `socket` as its session's display (A.6)."""
    return {"HANDLER_WAYLAND_SOCKET": socket}


def gives_display(binary: str, socket: str) -> bool:
    """Whether the runtime declares `display` (A.8) with `socket` as the session's display."""
    r = subprocess.run([binary, "check"], capture_output=True, text=True, check=False,
                       env=os.environ | on_display(socket))  # fmt: skip
    return "display" in (json.loads(r.stdout).get("supports") or {}).get("abilities", [])


@pytest.fixture
def display_socket() -> Iterator[str]:
    """A stand-in for a Wayland socket (A.6): a Unix socket answering every connection with an
    HTTP 200, so `curl --unix-socket` shows that the sandbox can connect to it."""
    directory = tempfile.mkdtemp(prefix="handler-display-")  # short: socket paths are limited
    path = f"{directory}/wayland-0"
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen()
    if dev_env.DEV_MODE:  # on the host, keep-id: the sandbox user owns the socket, like Wayland's
        os.chown(path, dev_env.sandbox_uid(), dev_env.sandbox_gid())

    def serve() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                conn.recv(4096)
                conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 0\r\n\r\n")

    threading.Thread(target=serve, daemon=True).start()
    yield path
    server.close()
    shutil.rmtree(directory, ignore_errors=True)


def spec(scope: Path, argv: list[str], **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "apiVersion": "handler.sandbox/v2",
        "name": f"handler-test-{uuid.uuid4().hex[:10]}",
        "image": CURL_IMAGE,
        "argv": argv,
        "env": {},
        "workdir": str(scope),
        "home": HOME_IN,
        "workFolder": {"path": str(scope)},
        "network": {"mode": "none"},
    }
    return base | overrides


def _spec_fd(doc: dict[str, Any]) -> int:
    with tempfile.TemporaryFile() as f:
        f.write(json.dumps(doc).encode())
        f.flush()
        f.seek(0)
        return os.dup(f.fileno())  # the dup keeps the (unlinked) file alive


def popen(
    binary: str,
    doc: dict[str, Any],
    unchained: bool = False,
    env: dict[str, str] | None = None,
    **kwargs: Any,
) -> subprocess.Popen[bytes]:
    """Start `<binary> launch` with the spec on fd 3; `unchained`: its proxy never goes out through
    the upstream one (as on every real host: for local destinations); `env`: added to ours (what
    the launcher's session has, e.g. its display)."""
    fd = _spec_fd(doc)
    try:
        return subprocess.Popen(  # ty: ignore[invalid-return-type]
            # a shell moves the spec to fd 3, as handlerd does (sandbox_process._launch_argv)
            ["/bin/sh", "-c", f'exec "$0" launch 3<&{fd} {fd}<&-', binary],
            pass_fds=(fd,),
            env=os.environ | ({} if unchained else upstream_env()) | (env or {}),
            **kwargs,
        )
    finally:
        os.close(fd)


def run(
    binary: str,
    doc: dict[str, Any],
    stdin: bytes = b"",
    timeout: float = 120,
    *,
    unchained: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    pipes = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    proc = popen(binary, doc, unchained=unchained, env=env, **pipes)
    out, err = proc.communicate(stdin, timeout=timeout)
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)
