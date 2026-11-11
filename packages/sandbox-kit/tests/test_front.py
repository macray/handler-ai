"""The filter's front (egress/proxy/front.py): in the filter's own sandbox on Apple container,
the Unix socket the host reaches it through, joined to the proxy's port on loopback.

Spec: contract A.3 "Network semantics" (the `handler-sandbox-apple` row)."""

import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from handler_sandbox_kit import egress


@pytest.fixture
def front(tmp_path: Path) -> Iterator[Path]:
    """front.py joining its socket to a server that answers in upper case; its socket."""
    server = socket.create_server(("127.0.0.1", 0))

    def serve() -> None:
        conn, _ = server.accept()
        with conn:
            while data := conn.recv(65536):
                conn.sendall(data.upper())

    threading.Thread(target=serve, daemon=True).start()
    path = tmp_path / "filter.sock"
    script = Path(str(egress.proxy_dir() / "front.py"))
    port = server.getsockname()[1]
    proc = subprocess.Popen([sys.executable, str(script), str(path), str(port)])
    try:
        deadline = time.monotonic() + 10
        while not path.exists():
            assert time.monotonic() < deadline, "front.py never made its socket"
            time.sleep(0.05)
        yield path
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        server.close()


def test_the_front_joins_its_socket_to_the_proxy_s_port(front: Path) -> None:
    """If this fails: no request of an Apple container sandbox reaches its filter."""
    with socket.socket(socket.AF_UNIX) as c:
        c.settimeout(10)
        c.connect(str(front))
        c.sendall(b"connect example.org:443")
        assert c.recv(100) == b"CONNECT EXAMPLE.ORG:443"
