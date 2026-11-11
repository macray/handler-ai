"""A Unix socket of the Mac given to a sandbox's VM, run on each `container` release: what a host
socket mounted with `--volume` does (Apple's relay over vsock, one host connection per VM
connection), what it does not, and `--publish-socket`'s other direction. Display forwarding and
apps' sockets would rest on it; today the filtered network rests on `--ssh`, the same relay."""

import os
import shutil
import socket
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from ...support.runtimes import RUNTIMES

APPLE = RUNTIMES["apple"]
pytestmark = pytest.mark.skipif(not APPLE.usable(), reason="Apple container not usable")

# in the VM: one connection to argv[1], `size` bytes sent then a half close or not, what came back
CLIENT = """
import socket, sys
c = socket.socket(socket.AF_UNIX)
c.settimeout(8)
try:
    c.connect(sys.argv[1])
    size, half_close = int(sys.argv[2]), sys.argv[3] == "half-close"
    announced = 2**62 if half_close else size  # after a half close: answered at the end
    c.sendall(announced.to_bytes(8, "big") + b"x" * size)
    if half_close:
        c.shutdown(socket.SHUT_WR)
    got = b""
    while not got.endswith(b"."):
        d = c.recv(100)
        if not d:
            break
        got += d
    print(got.decode() or "closed")
except OSError as e:
    print(e.__class__.__name__, e.errno)
"""


class Server:
    """A Unix socket server on the Mac answering each connection with the number of bytes it
    received and a dot, once it has as many as the first eight announced, or at their end."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.sock: socket.socket | None = None

    def start(self) -> None:
        self.path.unlink(missing_ok=True)
        self.sock = socket.socket(socket.AF_UNIX)
        cwd = os.getcwd()
        os.chdir(self.path.parent)  # bind's limit (104 bytes) is the path given, not the Mac's
        try:
            self.sock.bind(self.path.name)
        finally:
            os.chdir(cwd)
        # in the VM the socket is root's with the Mac's mode: the sandbox's user needs it writable
        self.path.chmod(0o666)
        self.sock.listen(8)
        threading.Thread(target=self._serve, args=(self.sock,), daemon=True).start()

    def _serve(self, sock: socket.socket) -> None:
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            threading.Thread(target=self._answer, args=(conn,), daemon=True).start()

    @staticmethod
    def _answer(conn: socket.socket) -> None:
        with conn:
            data = b""
            while len(data) < 8 or len(data) - 8 < int.from_bytes(data[:8], "big"):
                d = conn.recv(65536)
                if not d:
                    break
                data += d
            conn.sendall(f"{len(data) - 8}.".encode())

    def stop(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None


@pytest.fixture
def short() -> Iterator[Path]:
    """A folder with a short path for the Mac's sockets: Apple's relay connects to the absolute
    path, which a Unix socket's address limits to 104 bytes."""
    path = Path(tempfile.mkdtemp(prefix="hs-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def vm(*args: str) -> list[str]:
    """`container run` of a VM as an unprivileged user, its root read-only, as a sandbox's."""
    return ["container", "run", "--rm", "--user", "1000:1000", "--read-only", *args]


def connect(run: list[str], target: str, size: int = 10, close: str = "no") -> str:
    argv = [*run, "--entrypoint", "python3", APPLE.server_image, "-c", CLIENT, target]
    r = subprocess.run(
        [*argv, str(size), close], capture_output=True, text=True, timeout=120, check=False
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_a_mac_socket_mounted_into_a_vm_answers_and_survives_its_server_restarting(
    short: Path,
) -> None:
    """Mounted with `--volume` (not `--mount`: a directory only), the VM's user reaches it when
    the Mac's socket lets others write; the relay looks the path up on each connection: a server
    stopped is a connection closed at once (never refused), started again it answers, the VM
    untouched."""
    server = Server(short / "s.sock")
    server.start()
    name = f"handler-test-sock-{os.urandom(3).hex()}"
    held = ["container", "run", "--detach", "--rm", "--name", name, "--read-only"]
    subprocess.run(
        [*held, "--volume", f"{server.path}:/run/s.sock", "--entrypoint", "sleep",
         APPLE.server_image, "300"],
        check=True, capture_output=True,
    )  # fmt: skip
    exec_ = ["container", "exec", "--user", "1000:1000", name]
    try:
        assert connect_in(exec_) == "10."
        server.stop()
        assert connect_in(exec_) == "closed"
        server.start()
        assert connect_in(exec_) == "10."
    finally:
        server.stop()
        subprocess.run(["container", "delete", "--force", name], capture_output=True, check=False)


def connect_in(exec_: list[str]) -> str:
    r = subprocess.run(
        [*exec_, "python3", "-c", CLIENT, "/run/s.sock", "10", "no"],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_a_mac_socket_in_a_shared_folder_is_seen_but_not_usable(short: Path) -> None:
    """virtiofs shows the socket but cannot connect to it (EOPNOTSUPP): a socket reaches a VM
    only mounted by itself."""
    server = Server(short / "s.sock")
    server.start()
    try:
        assert connect(vm("--volume", f"{short}:/w"), "/w/s.sock") == "OSError 95"
    finally:
        server.stop()


# in the VM: a server on a socket in the shared folder /w, reached from the VM, then from the Mac
VM_SERVER = """
import socket, sys, threading
s = socket.socket(socket.AF_UNIX)
s.bind("/w/v.sock")
s.listen(2)
def serve():
    for _ in range(2):
        c, _ = s.accept()
        c.sendall(b"vm.")
        c.close()
threading.Thread(target=serve, daemon=True).start()
c = socket.socket(socket.AF_UNIX)
c.connect("/w/v.sock")
print(c.recv(10).decode(), flush=True)
sys.stdin.readline()
"""


def test_a_vm_socket_in_a_shared_folder_serves_the_vm_only(short: Path) -> None:
    """Made in the VM in a folder of the Mac, a socket serves the VM's own programs (a relay's
    listener there works); the Mac sees its file, and its connections are refused."""
    short.chmod(0o777)
    proc = subprocess.Popen(
        [*vm("--interactive", "--volume", f"{short}:/w"), "--entrypoint", "python3",
         APPLE.server_image, "-c", VM_SERVER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )  # fmt: skip
    assert proc.stdin is not None and proc.stdout is not None
    try:
        assert proc.stdout.readline().strip() == "vm."
        assert (short / "v.sock").is_socket()
        with socket.socket(socket.AF_UNIX) as c, pytest.raises(ConnectionRefusedError):
            c.connect(str(short / "v.sock"))
        proc.stdin.write("done\n")
        proc.stdin.flush()
        assert proc.wait(timeout=60) == 0
    finally:
        proc.kill()


def test_a_mac_socket_path_too_long_is_a_connection_closed_at_once(short: Path) -> None:
    """Over 104 bytes Apple's relay cannot connect (its log says so), yet the VM starts and its
    socket accepts, then closes: who mounts a socket checks its path's length first."""
    deep = short / ("d" * 100)
    deep.mkdir()
    server = Server(deep / "s.sock")
    server.start()
    try:
        assert len(str(server.path)) > 104
        assert connect(vm("--volume", f"{server.path}:/run/s.sock"), "/run/s.sock") == "closed"
    finally:
        server.stop()


@pytest.mark.xfail(
    strict=True,
    reason="Apple's host-socket relay (1.7.1, `--volume` and `--ssh` alike): a half close while "
    "data is still in flight loses the answer, which the Mac sent; fixed when this passes",
)
def test_an_answer_after_a_half_close_reaches_the_vm(short: Path) -> None:
    server = Server(short / "s.sock")
    server.start()
    try:
        run = vm("--volume", f"{server.path}:/run/s.sock")
        assert connect(run, "/run/s.sock", 1000, "half-close") == "1000."  # small: in time
        assert connect(run, "/run/s.sock", 65536, "half-close") == "65536."
    finally:
        server.stop()


@pytest.mark.xfail(
    strict=True,
    reason="apple/container#2101 (1.7.1): a socket published from a tmpfs closes every "
    "connection; from the VM's root disk it works; fixed when this passes",
)
def test_a_vm_socket_on_a_tmpfs_published_to_the_mac_answers(short: Path) -> None:
    published = short / "p.sock"
    serve = (
        "import socket\ns = socket.socket(socket.AF_UNIX); s.bind('/t/p.sock'); s.listen(1)\n"
        "c, _ = s.accept(); c.sendall(b'up.'); c.close()"
    )
    name = f"handler-test-pub-{os.urandom(3).hex()}"
    subprocess.run(
        ["container", "run", "--detach", "--rm", "--name", name, "--read-only", "--tmpfs", "/t",
         "--publish-socket", f"{published}:/t/p.sock", "--entrypoint", "python3",
         APPLE.server_image, "-c", serve],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
        got = b""
        for _ in range(20):  # until the VM's server listens
            with socket.socket(socket.AF_UNIX) as c:
                c.settimeout(5)
                try:
                    c.connect(str(published))
                    got = c.recv(10)
                except OSError:
                    got = b""
            if got:
                break
            threading.Event().wait(0.5)
        assert got == b"up."
    finally:
        subprocess.run(["container", "delete", "--force", name], capture_output=True, check=False)
