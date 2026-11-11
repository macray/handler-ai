"""handler-relay (relay/main.go), the command of a sandbox on Apple container, and its host side
(relay/__init__.py): streams from the sandbox's listeners to the host's targets, each a connection
of its own; the other way, the host's clients reaching a socket the sandbox serves, over
connections the relay parks; the command run as the user, without privileges; its exit and signals passed on. Run
here on the host itself: the protocol does not need a sandbox (the runtimes' conformance suites
run it in theirs).

Spec: contract A.3 "Network semantics" (the `handler-sandbox-apple` row), A.10 (socket folders)
and A.2 "Guarantees" (A3, hardening)."""

import os
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from handler_sandbox_kit import relay as relay_module
from handler_sandbox_kit.relay import MAX_NAME, PARKED_MAX, RelayHost, source_dir

SOURCE = Path(str(source_dir()))
GOLANG = "mirror.gcr.io/library/golang:1.25-alpine"  # not Docker Hub: no anonymous pull limit


@pytest.fixture(scope="session")
def relay_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Built with the local Go, else in the golang image (podman); skipped without either, and
    off Linux (the relay is a Linux program: on a Mac, run this file in a Linux container)."""
    if sys.platform != "linux":
        pytest.skip("handler-relay runs on Linux only")
    out = tmp_path_factory.mktemp("relay") / "handler-relay"
    env = {"CGO_ENABLED": "0", "GOFLAGS": "-trimpath"}
    if shutil.which("go"):
        argv = ["go", "build", "-o", str(out), "."]
        r = subprocess.run(argv, cwd=SOURCE, env=os.environ | env, capture_output=True, check=False)
    elif shutil.which("podman"):
        argv = ["podman", "run", "--rm", "-v", f"{SOURCE}:/src:ro", "-v", f"{out.parent}:/out"]
        argv += [a for k, v in env.items() for a in ("-e", f"{k}={v}")]
        argv += [
            "-e",
            "GOCACHE=/tmp/go",
            "-w",
            "/src",
            GOLANG,
            "go",
            "build",
            "-o",
            "/out/handler-relay",
            ".",
        ]
        r = subprocess.run(argv, capture_output=True, check=False, timeout=600)
    else:
        pytest.skip("neither go nor podman to build handler-relay")
    if r.returncode != 0:
        pytest.skip(f"handler-relay not built: {r.stderr.decode()[-300:]}")
    return out


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(path: Path) -> None:
    deadline = time.monotonic() + 10
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.05)


def echo_server(path: Path) -> socket.socket:
    """A Unix socket that sends back what it gets, then ends when its client does."""
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(path))
    server.listen()

    def serve(conn: socket.socket) -> None:
        with conn:
            while data := conn.recv(65536):
                conn.sendall(data)

    def accept() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=serve, args=(conn,), daemon=True).start()

    threading.Thread(target=accept, daemon=True).start()
    return server


def ended(c: socket.socket) -> bool:
    """The other side closed: an end, or a reset when it closed with our bytes still unread."""
    try:
        return c.recv(10) == b""
    except ConnectionResetError:
        return True


def connect_unix(path: Path) -> socket.socket:
    c = socket.socket(socket.AF_UNIX)
    c.settimeout(10)
    c.connect(str(path))
    return c


# --- The host side alone (RelayHost) -------------------------------------------------------------


@pytest.fixture
def relay_host(tmp_path: Path) -> Iterator[Path]:
    """A RelayHost joining the name `echo` to an echo server; its socket."""
    server = echo_server(tmp_path / "echo.sock")
    host = RelayHost(tmp_path / "relay.sock", {"echo": str(tmp_path / "echo.sock")})
    host.start()
    try:
        yield tmp_path / "relay.sock"
    finally:
        host.stop()
        server.close()


def test_the_host_side_joins_a_named_stream_to_its_target(relay_host: Path) -> None:
    """A connection says its target's name on its first line, then carries the stream.
    If this fails: nothing in an Apple container sandbox reaches its filter or handlerd."""
    with connect_unix(relay_host) as c:
        c.sendall(b"echo\nhello")
        assert c.recv(100) == b"hello"


@pytest.mark.parametrize(
    "first_line",
    [
        pytest.param(b"unknown\n", id="name-not-served"),
        pytest.param(b"x" * (MAX_NAME + 1), id="name-too-long-without-its-end"),
    ],
)
def test_the_host_side_ends_a_stream_it_cannot_serve_at_once(
    relay_host: Path, first_line: bytes
) -> None:
    """A name it was not given reaches nothing; a first line past MAX_NAME is not waited for.
    If this fails: a sandbox reaches a host socket it was not given, or holds the host side
    reading a name that never ends."""
    with connect_unix(relay_host) as c:
        c.sendall(first_line)
        assert ended(c)


def test_the_host_side_s_socket_is_the_user_s_only(tmp_path: Path) -> None:
    """Apple's runtime connects to it as the host user; nobody else may.
    If this fails: another user of the Mac reaches the sandbox's filter and handlerd's sockets."""
    host = RelayHost(tmp_path / "relay.sock", {})
    try:
        assert stat.S_IMODE((tmp_path / "relay.sock").stat().st_mode) == 0o600
    finally:
        host.stop()


@pytest.fixture
def serving(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    """A RelayHost serving the name `app` at app.sock: (its socket, app.sock)."""
    host = RelayHost(tmp_path / "relay.sock", {}, {"app": tmp_path / "app.sock"})
    host.start()
    try:
        yield tmp_path / "relay.sock", tmp_path / "app.sock"
    finally:
        host.stop()


def park(relay_socket: Path, name: str = "app") -> socket.socket:
    """What the relay does for a socket it serves: a connection that says `<name` and waits."""
    c = connect_unix(relay_socket)
    c.sendall(f"<{name}\n".encode())
    return c


@pytest.mark.rule("sandbox.its-sockets-cross-as-declared")
def test_a_client_of_a_served_socket_takes_a_parked_connection(
    serving: tuple[Path, Path],
) -> None:
    """The client's connection is joined to one the relay parked, woken by one byte.
    If this fails: handlerd never reaches an app's backend on Apple container."""
    relay_socket, app = serving
    with park(relay_socket) as parked, connect_unix(app) as client:
        assert parked.recv(1) == b"\x01"
        client.sendall(b"GET /api/health")
        assert parked.recv(100) == b"GET /api/health"
        parked.sendall(b"200 ok")
        assert client.recv(100) == b"200 ok"


@pytest.mark.rule("sandbox.its-sockets-cross-as-declared")
def test_a_served_socket_is_the_user_s_only_and_goes_with_the_host_side(
    serving: tuple[Path, Path], tmp_path: Path
) -> None:
    """If this fails: another user of the Mac reaches an app's backend, or a stopped sandbox
    leaves a socket that accepts and answers nothing."""
    _, app = serving
    assert stat.S_IMODE(app.stat().st_mode) == 0o600
    host = RelayHost(tmp_path / "other.sock", {}, {"x": tmp_path / "x.sock"})
    host.stop()
    assert not (tmp_path / "x.sock").exists() and not (tmp_path / "other.sock").exists()


@pytest.mark.rule("sandbox.its-sockets-cross-as-declared")
def test_only_a_few_parked_connections_are_kept_and_not_for_names_not_served(
    tmp_path: Path,
) -> None:
    """If this fails: a sandbox holds the launcher with connections it never uses, or parks for
    a socket it does not serve."""
    relay_socket = tmp_path / "relay.sock"
    host = RelayHost(relay_socket, {}, {"app": tmp_path / "app.sock"})
    host.start()
    kept = [park(relay_socket) for _ in range(PARKED_MAX)]
    deadline = time.monotonic() + 10
    while host.parked("app") < PARKED_MAX:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    with park(relay_socket) as one_more, park(relay_socket, "other") as not_served:
        assert ended(one_more) and ended(not_served)
    for c in kept:
        c.close()
    host.stop()


def test_a_client_with_nothing_parked_is_closed_and_a_dead_one_skipped(
    serving: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sandbox not started yet, or gone: the client's connection ends (handlerd tries again).
    If this fails: handlerd's health check hangs on a backend that is not there."""
    monkeypatch.setattr(relay_module, "WAIT_PARKED", 0.3)
    relay_socket, app = serving
    park(relay_socket).close()  # parked, then the relay went away
    time.sleep(0.1)
    with connect_unix(app) as client:
        assert ended(client)


# --- handler-relay with its host side: streams ---------------------------------------------------


@pytest.fixture
def relayed(relay_binary: Path, tmp_path: Path) -> Iterator[tuple[int, Path]]:
    """A relay listening on a TCP port (name `echo`) and a Unix socket (name `unknown`), its
    host side joining `echo` to an echo server: (port, the unknown's socket)."""
    port, host_socket, unknown = free_port(), tmp_path / "relay.sock", tmp_path / "unknown.sock"
    server = echo_server(tmp_path / "echo.sock")
    host = RelayHost(host_socket, {"echo": str(tmp_path / "echo.sock")})
    host.start()
    relay = subprocess.Popen([
        str(relay_binary), "--host", str(host_socket),
        "--listen", f"tcp:127.0.0.1:{port}=echo", "--listen", f"unix:{unknown}=unknown",
        "--", "sleep", "600",
    ])  # fmt: skip
    try:
        yield port, unknown
    finally:
        relay.terminate()
        relay.wait(timeout=10)
        host.stop()
        server.close()


def connect(port: int) -> socket.socket:
    deadline = time.monotonic() + 10
    while True:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=10)
        except OSError:
            assert time.monotonic() < deadline
            time.sleep(0.05)


def test_a_stream_reaches_its_target_whole_and_ends_as_it_does(relayed: tuple[int, Path]) -> None:
    """1 MiB both ways (as the conformance suite's stdio line), then the end passed on.
    If this fails: large requests through the filter are cut, or connections never end."""
    port, _ = relayed
    payload = os.urandom(1 << 20)
    with connect(port) as c:
        received = bytearray()
        sender = threading.Thread(target=lambda: (c.sendall(payload), c.shutdown(socket.SHUT_WR)))
        sender.start()
        while data := c.recv(65536):  # the echo, then its end once ours reached it
            received += data
        sender.join()
    assert bytes(received) == payload


def test_streams_are_independent(relayed: tuple[int, Path]) -> None:
    """Each connection is a connection of its own to the host.
    If this fails: one slow request (a model's long answer) blocks every other."""
    port, _ = relayed
    a, b = connect(port), connect(port)
    with a, b:
        b.sendall(b"second")
        assert b.recv(100) == b"second"  # not behind a, which says nothing yet
        a.sendall(b"first")
        assert a.recv(100) == b"first"


@pytest.mark.rule("sandbox.its-sockets-cross-as-declared")
def test_the_host_reaches_a_socket_the_sandbox_serves(relay_binary: Path, tmp_path: Path) -> None:
    """--serve: the relay parks connections, the host's clients reach the sandbox's socket
    through them, several at once, each a connection of its own.
    If this fails: handlerd never reaches an app's backend on Apple container."""
    host_socket, served, app = (
        tmp_path / "relay.sock",
        tmp_path / "in-vm.sock",
        tmp_path / "app.sock",
    )
    server = echo_server(served)
    host = RelayHost(host_socket, {}, {"s0/app.sock": app})
    host.start()
    relay = subprocess.Popen([
        str(relay_binary), "--host", str(host_socket),
        "--serve", f"unix:{served}=s0/app.sock", "--", "sleep", "600",
    ])  # fmt: skip
    try:
        clients = [connect_unix(app) for _ in range(5)]  # more than are parked: replaced
        for i, c in enumerate(clients):
            c.sendall(b"%d" % i)
        assert [c.recv(10) for c in clients] == [b"%d" % i for i in range(5)]
        for c in clients:
            c.close()
    finally:
        relay.terminate()
        relay.wait(timeout=10)
        host.stop()
        server.close()


def test_a_name_the_host_does_not_serve_ends_at_once(relayed: tuple[int, Path]) -> None:
    """If this fails: a program in the sandbox hangs on a listener whose target is missing."""
    _, unknown = relayed
    wait_for(unknown)
    with connect_unix(unknown) as c:
        assert c.recv(10) == b""


# --- handler-relay as the sandbox's command: exit, signals, user ---------------------------------


def test_it_exits_with_its_command_s_code(relay_binary: Path) -> None:
    """If this fails: the sandbox's exit code (the harness's) is lost."""
    argv = [str(relay_binary), "--", "sh", "-c", "exit 7"]
    assert subprocess.run(argv, timeout=30, check=False).returncode == 7


def test_stopping_it_stops_its_command(relay_binary: Path) -> None:
    """SIGTERM (a runtime stopping the sandbox) is passed on; the command's death is reported as
    128 + its signal.
    If this fails: stopping a sandbox leaves the harness running until it is killed."""
    proc = subprocess.Popen([str(relay_binary), "--", "sleep", "60"])
    time.sleep(0.5)
    proc.terminate()
    assert proc.wait(timeout=10) == 128 + 15


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["--"], id="no-command"),
        pytest.param(["--listen", "tcp:127.0.0.1:0=x", "--", "true"], id="listen-without-host"),
        pytest.param(["--host", "/x", "--listen", "udp:1=x", "--", "true"], id="bad-listen"),
        pytest.param(["--user", "me", "--", "true"], id="bad-user"),
        pytest.param(["--serve", "unix:/x=x", "--", "true"], id="serve-without-host"),
        pytest.param(["--host", "/x", "--serve", "tcp:1=x", "--", "true"], id="bad-serve"),
    ],
)
def test_a_wrong_command_line_fails_before_running_anything(
    relay_binary: Path, args: list[str]
) -> None:
    """125, the relay's own failure, distinct from any exit code of the command.
    If this fails: a mistake in the runtime's command line starts a sandbox half set up."""
    r = subprocess.run([str(relay_binary), *args], capture_output=True, timeout=30, check=False)
    assert r.returncode == 125
    assert r.stderr.startswith(b"handler-relay: ")


@pytest.mark.skipif(os.geteuid() != 0, reason="--user is for a relay started as root")
def test_it_becomes_the_user_for_good(relay_binary: Path, tmp_path: Path) -> None:
    """--user: the command runs as that uid/gid, with no capability left nor any to gain, and
    the host's socket is given to the user.
    If this fails: on Apple container the harness runs as root or can become root again."""
    host_socket = tmp_path / "relay.sock"
    host = RelayHost(host_socket, {})
    host.start()
    try:
        argv = [str(relay_binary), "--user", "1234:5678", "--host", str(host_socket), "--"]
        argv += ["sh", "-c", "id -u; id -g; id -G; cat /proc/self/status"]
        out = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=True).stdout
        owner = (host_socket.stat().st_uid, host_socket.stat().st_gid)
    finally:
        host.stop()
    lines = out.splitlines()
    assert lines[:3] == ["1234", "5678", "5678"]
    status = dict(line.split(":\t", 1) for line in lines[3:] if ":\t" in line)
    assert status["CapEff"].strip() == status["CapBnd"].strip() == "0" * 16
    assert status["NoNewPrivs"].strip() == "1"
    assert owner == (1234, 5678)
