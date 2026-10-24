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

from ..support import dev_env

CURL_IMAGE = "docker.io/curlimages/curl:8.11.1"
HOME_IN = "/home/agent"


def podman_usable() -> bool:
    if not shutil.which("podman"):
        return False
    return subprocess.run(["podman", "info"], capture_output=True, check=False).returncode == 0


requires_podman = pytest.mark.skipif(not podman_usable(), reason="podman not usable")


@functools.cache
def privileged_usable() -> bool:
    """`--privileged` needs a fresh sysfs mount, refused when podman itself runs in a container
    (e.g. a handler agent running these tests)."""
    argv = ["podman", "run", "--rm", "--privileged", CURL_IMAGE, "true"]
    return subprocess.run(argv, capture_output=True, check=False).returncode == 0


def skip_unless_usable(confinement: str) -> None:
    if confinement == "privileged" and not privileged_usable():
        pytest.skip("podman cannot start a privileged container here")


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
    argv = ["curl", "-s", "-m", "5", "-o", "/dev/null", "-x", url, "https://www.example.org"]
    if subprocess.run(argv, capture_output=True, check=False).returncode != 0:
        return {}
    return {"HANDLER_SANDBOX_DEV_UPSTREAM_PROXY": url}


requires_egress = pytest.mark.skipif(
    not (direct_internet() or upstream_env()), reason="no internet (HANDLER_TEST_OFFLINE)"
)


@pytest.fixture(scope="session", autouse=True)
def _pull_images() -> None:
    if podman_usable():
        subprocess.run(["podman", "pull", "-q", CURL_IMAGE], capture_output=True, check=False)
        dev_env.ensure_network_filter()


@pytest.fixture
def scope() -> Iterator[Path]:
    """A scope directory outside /tmp (the sandbox mounts its own /tmp)."""
    path = dev_env.make_scope()
    yield path
    dev_env.remove_scope(path)


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
        "apiVersion": "handler.sandbox/v1",
        "name": f"handler-test-{uuid.uuid4().hex[:10]}",
        "image": CURL_IMAGE,
        "argv": argv,
        "env": {},
        "workdir": str(scope),
        "user": {"mode": "host-user", "home": HOME_IN},
        "mounts": [
            {"source": str(scope), "target": str(scope), "readOnly": False, "kind": "scope"}
        ],
        "files": [],
        "writablePaths": [],
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
    binary: str, doc: dict[str, Any], unchained: bool = False, **kwargs: Any
) -> subprocess.Popen[bytes]:
    """Start `<binary> launch` with the spec on fd 3; `unchained`: its proxy never goes out through
    the upstream one (as on every real host: for local destinations)."""
    fd = _spec_fd(doc)

    def setup() -> None:
        os.dup2(fd, 3)

    try:
        return subprocess.Popen(  # ty: ignore[invalid-return-type]
            [binary, "launch"],
            pass_fds=(fd, 3),  # 3 must survive close_fds, which runs after preexec_fn
            preexec_fn=setup,  # noqa: PLW1509 — fd 3 is the contract
            env=os.environ | ({} if unchained else upstream_env()),
            **kwargs,
        )
    finally:
        os.close(fd)


def run(
    binary: str,
    doc: dict[str, Any],
    stdin: bytes = b"",
    timeout: float = 120,
    unchained: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    pipes = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    proc = popen(binary, doc, unchained=unchained, **pipes)
    out, err = proc.communicate(stdin, timeout=timeout)
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def leftovers(name: str) -> list[str]:
    """Anything a sandbox named `name` could have left behind."""
    found = []
    names = subprocess.run(
        ["podman", "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    found += [n for n in names if n.startswith(name)]
    nets = subprocess.run(
        ["podman", "network", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    found += [n for n in nets if n.startswith(name)]
    base = os.environ.get("XDG_RUNTIME_DIR") or str(Path.home() / ".local" / "state")
    if (Path(base) / "handler-ai" / "sandboxes" / name).exists():
        found.append("instance dir")
    return found
