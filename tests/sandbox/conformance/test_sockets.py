"""Contract A.10 conformance, every runtime: a socket folder's sockets, each its declared way. The
host connects to a socket the sandbox serves (an app's backend, handlerd its client), and the
sandbox connects to one it reaches (handlerd's for the app), with no network: on Podman and
Docker through the folder's bind mount, on Apple container through the relay (a VM's socket
never reaches the Mac otherwise)."""

import shutil
import socket
import socketserver
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from ...support import dev_env
from ...support.runtimes import Runtime
from ..conftest import popen, run, spec

PYTHON_IMAGE = "mirror.gcr.io/library/python:3.13-alpine"  # a server on a Unix socket
TARGET = "/run/handler-app"


def refused_here(runtime: Runtime, doc: dict) -> bool:
    """Docker in a VM (on a Mac: Desktop, OrbStack) refuses a socket folder: a socket crosses
    neither way there (A1, checked on Docker Desktop). True when it did, as it must."""
    if not (runtime.name == "docker" and sys.platform == "darwin"):
        return False
    r = run(runtime.binary, doc)
    assert r.returncode == 64 and b"a socket cannot cross" in r.stderr, r.stderr
    return True


@pytest.fixture
def source() -> Iterator[Path]:
    """The host's side of the folder: short (a socket's path is at most 103 bytes on macOS)."""
    path = Path(tempfile.mkdtemp(prefix="hs-", dir="/tmp")).resolve()
    yield path
    shutil.rmtree(path, ignore_errors=True)


SERVE_ONCE = f"""
import socket
s = socket.socket(socket.AF_UNIX)
s.bind("{TARGET}/app.sock")
s.listen()
c, _ = s.accept()
c.sendall(b"served:" + c.recv(100))
c.close()
"""


def ask(path: Path, deadline: float) -> bytes:
    """As handlerd asks a backend that is starting: again until it answers."""
    while True:
        assert time.monotonic() < deadline, f"{path} never answered"
        try:
            with socket.socket(socket.AF_UNIX) as c:
                c.settimeout(10)
                c.connect(str(path))
                c.sendall(b"hello")
                if answer := c.recv(100):
                    return answer
        except OSError:
            pass
        time.sleep(0.2)


@pytest.mark.rule("sandbox.its-sockets-cross-as-declared")
def test_the_host_reaches_a_socket_the_sandbox_serves(runtime: Runtime, source: Path) -> None:
    """If this fails: handlerd cannot reach an app's backend on this runtime: no app runs."""
    dev_env.ensure_image(PYTHON_IMAGE, runtime.binary)
    folder = {"source": str(source), "target": TARGET, "serves": ["app.sock"]}
    doc = spec(
        source, ["python3", "-c", SERVE_ONCE], image=PYTHON_IMAGE, socketFolders=[folder]
    ) | {"workdir": str(source), "workFolder": {"path": str(source)}}
    if refused_here(runtime, doc):
        return
    proc = popen(runtime.binary, doc, stdout=-1, stderr=-1)
    try:
        assert ask(source / "app.sock", time.monotonic() + 60) == b"served:hello"
        _, err = proc.communicate(timeout=30)
        assert proc.returncode == 0, err.decode()
    finally:  # stopped as handlerd stops it: the launcher removes what it made (A4)
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=60)


class Answer(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        body = b"reached"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


@pytest.mark.rule("sandbox.its-sockets-cross-as-declared")
def test_the_sandbox_reaches_a_socket_of_the_host(
    runtime: Runtime, scope: Path, source: Path
) -> None:
    """With no network: the socket alone, nothing else.
    If this fails: an app cannot notify nor start agents, a script cannot call models."""
    server = UnixServer(str(source / "handler.sock"), Answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        folder = {"source": str(source), "target": TARGET, "reaches": ["handler.sock"]}
        script = f"curl -s --unix-socket {TARGET}/handler.sock http://handler/; echo"
        doc = spec(scope, ["sh", "-c", script], socketFolders=[folder])
        if refused_here(runtime, doc):
            return
        r = run(runtime.binary, doc)
        assert r.stdout.decode().strip() == "reached", r.stderr.decode()
    finally:
        server.shutdown()
        server.server_close()
