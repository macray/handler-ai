"""The host's side of `handler-relay` (`main.go` here, built from `source_dir()`): for a sandbox with no route to the host but
one socket of the host it connects to (mounted in Apple container's VM), it joins the sandbox's streams
to their targets here: the network filter's socket, handlerd's for an app.

It listens on that socket; each connection first says its target's name ("egress\\n"), then
carries the stream, copied both ways between it and `targets[name]` (a Unix socket on this
host). A name it was not given ends the stream at once.

The other way, a socket of the sandbox a client here connects to (`serves[name]`, a Unix socket
on this host it listens on): the relay parks connections saying "<name\\n" (at most PARKED_MAX
kept, more closed); a client takes one, which is woken by one byte and joined to it. With none
parked within WAIT_PARKED, the client's connection is closed (the sandbox not started yet, or
gone).
"""

import contextlib
import os
import queue
import socket
import threading
from collections.abc import Mapping
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

CHUNK = 65536
MAX_NAME = 64
PARKED_MAX = 4  # per served socket: the relay parks 2
WAIT_PARKED = 5.0  # seconds a client waits for a parked connection


def source_dir() -> Traversable:
    """handler-relay's source and its recipe (`Containerfile`: a FROM scratch image holding
    `/handler-relay`), built for the runtime's own Linux."""
    return resources.files(__name__)


def _connect(path: Path | str) -> socket.socket:
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(str(path))
    except OSError:
        s.close()
        raise
    return s


def _copy(src: socket.socket, dst: socket.socket) -> None:
    """Until src ends, then dst is told (half close)."""
    with contextlib.suppress(OSError):
        while data := src.recv(CHUNK):
            dst.sendall(data)
    with contextlib.suppress(OSError):
        dst.shutdown(socket.SHUT_WR)


def join(a: socket.socket, b: socket.socket) -> None:
    other = threading.Thread(target=_copy, args=(b, a), daemon=True)
    other.start()
    _copy(a, b)
    other.join()
    a.close()
    b.close()


def _name(conn: socket.socket) -> str | None:
    """The first line, read byte by byte: nothing after it is consumed (the stream follows)."""
    line = b""
    while len(line) <= MAX_NAME:
        one = conn.recv(1)
        if not one:
            return None
        if one == b"\n":
            return line.decode(errors="replace")
        line += one
    return None


def _listen(path: Path) -> socket.socket:
    path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(path))
    os.chmod(path, 0o600)  # the host user's only: Apple's runtime connects as that user
    server.listen(64)
    return server


def _alive(conn: socket.socket) -> bool:
    """A parked connection the relay has not ended (it writes nothing while parked)."""
    try:
        return conn.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT) != b""
    except BlockingIOError:
        return True
    except OSError:
        return False


class RelayHost(threading.Thread):
    """Serves one sandbox's relay on `path` (listening once made, before the sandbox starts)
    until stop(). `targets`: a stream's name → the Unix socket it joins. `serves`: a socket of
    the sandbox's name → the Unix socket here its clients connect to (listening once made)."""

    def __init__(
        self, path: Path, targets: Mapping[str, str], serves: Mapping[str, Path] | None = None
    ) -> None:
        super().__init__(daemon=True, name="handler-relay-host")
        self.path = path
        self.targets = dict(targets)
        self.serves = dict(serves or {})
        self._parked: dict[str, queue.Queue[socket.socket]] = {
            name: queue.Queue() for name in self.serves
        }
        self._parking = threading.Lock()  # the cap, counted by one stream at a time
        self._server = _listen(path)
        self._served = {name: _listen(where) for name, where in self.serves.items()}

    def start(self) -> None:
        super().start()
        for name, server in self._served.items():
            threading.Thread(target=self._clients, args=(name, server), daemon=True).start()

    def stop(self) -> None:
        for server in (self._server, *self._served.values()):
            with contextlib.suppress(OSError):
                server.shutdown(socket.SHUT_RDWR)
            server.close()
        for where in (self.path, *self.serves.values()):
            where.unlink(missing_ok=True)
        for parked in self._parked.values():
            while not parked.empty():
                parked.get_nowait().close()

    def run(self) -> None:
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._stream, args=(conn,), daemon=True).start()

    def _stream(self, conn: socket.socket) -> None:
        try:
            name = _name(conn)
        except OSError:
            conn.close()
            return
        if name is not None and name.startswith("<") and name[1:] in self._parked:
            self._park(name[1:], conn)
            return
        target = self.targets.get(name) if name is not None else None
        if target is None:
            conn.close()
            return
        try:
            there = _connect(target)
        except OSError:
            conn.close()
            return
        join(conn, there)

    def _park(self, name: str, conn: socket.socket) -> None:
        parked = self._parked[name]
        with self._parking:
            if parked.qsize() < PARKED_MAX:
                parked.put(conn)
                return
        conn.close()

    def parked(self, name: str) -> int:
        """How many connections wait for `name`'s clients."""
        return self._parked[name].qsize()

    def _clients(self, name: str, server: socket.socket) -> None:
        while True:
            try:
                client, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(name, client), daemon=True).start()

    def _serve(self, name: str, client: socket.socket) -> None:
        """The client joined to a parked connection, woken; closed when none comes."""
        while True:
            try:
                there = self._parked[name].get(timeout=WAIT_PARKED)
            except queue.Empty:
                client.close()
                return
            if _alive(there):
                with contextlib.suppress(OSError):
                    there.sendall(b"\x01")
                    join(client, there)
                    return
            there.close()
