"""A client's terminal for `handler terminal`'s sandbox (D.16): its `attach` command on a PTY."""

import fcntl
import os
import pty
import struct
import termios
import time


class Attached:
    """The `attach` command handlerd gave, run on a PTY of 30 rows and 100 columns."""

    def __init__(self, attach: list[str]) -> None:
        self.pid, self.master = pty.fork()
        if self.pid == 0:
            os.execv(attach[0], attach)
        os.set_blocking(self.master, False)
        self.resize(30, 100)
        self.shown = b""

    def resize(self, rows: int, cols: int) -> None:
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def until(self, text: str, timeout: float = 20) -> str:
        deadline = time.monotonic() + timeout
        while text.encode() not in self.shown:
            assert time.monotonic() < deadline, self.shown
            try:
                self.shown += os.read(self.master, 4096)
            except BlockingIOError:
                time.sleep(0.05)
        return self.shown.decode(errors="replace")

    def type(self, line: str) -> None:
        os.write(self.master, line.encode() + b"\r")

    def exit_code(self) -> int:
        _, status = os.waitpid(self.pid, 0)
        os.close(self.master)
        return os.waitstatus_to_exitcode(status)
