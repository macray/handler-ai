"""A command on a terminal of its own, relayed to this one: what `handler account login` runs a
harness's login on, and `handler terminal` a sandbox's `attach` (to see the paste key, D.16)."""

import fcntl
import os
import pty
import select
import shutil
import signal
import struct
import sys
import termios
import tty
from collections.abc import Callable, Mapping


def on_terminal(
    argv: list[str],
    env: Mapping[str, str],
    cwd: str,
    on_input: Callable[[bytes], None] | None = None,
) -> int:
    """Run `argv` on a terminal of its own, relayed to this one (raw while it runs, resized with
    it): its exit code. `on_input` sees what is typed before the command does."""
    pid, master = pty.fork()
    if pid == 0:  # the child, on the new terminal
        os.chdir(cwd)
        os.execve(argv[0], argv, env)
    interactive = sys.stdin.isatty()
    saved = termios.tcgetattr(0) if interactive else None

    def resize(*_: object) -> None:
        cols, rows = shutil.get_terminal_size()
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    resize()
    inputs = [0, master]
    try:
        if interactive:
            tty.setraw(0)
            signal.signal(signal.SIGWINCH, resize)
        while True:
            ready, _, _ = select.select(inputs, [], [])
            if master in ready:
                try:
                    data = os.read(master, 65536)
                except OSError:  # EIO: the command and all it started are gone
                    data = b""
                if not data:
                    break
                os.write(1, data)
            if 0 in ready:
                data = os.read(0, 4096)
                if data:
                    if on_input is not None:
                        on_input(data)
                    os.write(master, data)
                else:  # stdin ended (piped): the command goes on without it
                    inputs.remove(0)
    finally:
        if saved is not None:
            termios.tcsetattr(0, termios.TCSADRAIN, saved)
            signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        os.close(master)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)
