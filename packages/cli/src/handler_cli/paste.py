"""Pasting an image into a harness's terminal program (D.16): when the paste key is typed,
the image this computer's clipboard holds goes into the terminal's paste folder before the key
does, so the program in its sandbox reads it as its clipboard. No image: the folder is emptied,
so an image pasted before is not pasted again.

The clipboard is read with the system's own tools: `wl-paste` (Wayland, WSLg), `xclip` (X11),
`osascript` (macOS); on WSL, when those find no image, Windows' own clipboard through
`powershell.exe` (an image copied in Windows may not reach WSLg's). None of them, or no image:
nothing is pasted, the key still goes through.
"""

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from handler_contracts import PASTE_IMAGE

from . import daemon_commands

# Ctrl+V as terminals send it: plain, with the kitty keyboard protocol (which Claude Code turns
# on), with xterm's modifyOtherKeys
PASTE_KEYS = (b"\x16", b"\x1b[118;5u", b"\x1b[27;5;118~")
TIMEOUT = 5.0

# the image Windows' clipboard holds, as PNG on stdout; nothing when it holds none
WINDOWS_PNG = (
    "Add-Type -AssemblyName System.Windows.Forms, System.Drawing; "
    "$i = [Windows.Forms.Clipboard]::GetImage(); "
    "if ($i) { $m = New-Object IO.MemoryStream; "
    "$i.Save($m, [Drawing.Imaging.ImageFormat]::Png); "
    "$o = [Console]::OpenStandardOutput(); $o.Write($m.ToArray(), 0, $m.Length); $o.Flush() }"
)


def is_paste(typed: bytes) -> bool:
    return any(key in typed for key in PASTE_KEYS)


def _run(argv: list[str]) -> bytes | None:
    """`argv`'s output, None when it fails or is missing."""
    try:
        r = subprocess.run(argv, capture_output=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _macos_png() -> bytes | None:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / PASTE_IMAGE
        script = [
            f'set f to (open for access POSIX file "{target}" with write permission)',
            "set eof f to 0",
            "write (the clipboard as «class PNGf») to f",
            "close access f",
        ]
        if _run(["osascript", *[a for line in script for a in ("-e", line)]]) is None:
            return None
        return target.read_bytes() or None


def _windows_png() -> bytes | None:
    if powershell := shutil.which("powershell.exe"):
        return _run([powershell, "-NoProfile", "-NonInteractive", "-STA", "-Command", WINDOWS_PNG])
    return None


def clipboard_png() -> bytes | None:
    """The PNG image the clipboard holds, None when it holds none (or cannot be read)."""
    if sys.platform == "darwin":
        return _macos_png()
    png = _linux_png()
    if png is None and daemon_commands.wsl():
        png = _windows_png() or None
    return png


def _linux_png() -> bytes | None:
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        types = _run(["wl-paste", "--list-types"]) or b""
        if b"image/png" in types.split():
            return _run(["wl-paste", "--no-newline", "--type", "image/png"]) or None
        return None
    if os.environ.get("DISPLAY") and shutil.which("xclip"):
        types = _run(["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"]) or b""
        if b"image/png" in types.split():
            return _run(["xclip", "-selection", "clipboard", "-t", "image/png", "-o"]) or None
    return None


def put(folder: Path, png: bytes | None) -> None:
    """The image the program reads next, replaced whole; None: none any more."""
    target = folder / PASTE_IMAGE
    if png is None:
        with contextlib.suppress(FileNotFoundError):
            target.unlink()
        return
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".paste-")
    with os.fdopen(fd, "wb") as f:
        f.write(png)
    os.chmod(tmp, 0o644)  # the sandbox reads it, maybe as another uid
    os.replace(tmp, target)


def watcher(folder: Path) -> Callable[[bytes], None]:
    """What sees what is typed (on_terminal's `on_input`): on the paste key, the clipboard's image
    goes into the paste folder first."""

    def on_input(typed: bytes) -> None:
        if is_paste(typed):
            with contextlib.suppress(OSError):  # its folder gone (the sandbox ending): no image
                put(folder, clipboard_png())

    return on_input
