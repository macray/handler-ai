"""Opening an address in the person's browser: Python's `webbrowser`, except on WSL, where it is
Windows' default browser. A WSL distribution usually has no browser of its own (and often no
`xdg-open`), and Windows reaches handlerd's port on its own localhost (WSL forwards it).
`$BROWSER` set: `webbrowser`, which follows it, everywhere.
"""

import os
import shutil
import subprocess
import webbrowser

from . import daemon_commands

RUNDLL32 = "/mnt/c/Windows/System32/rundll32.exe"


def wsl_argv(url: str) -> list[str] | None:
    """The command opening `url` in Windows' default browser, None when Windows cannot be run
    (WSL's interop turned off). wslu's `wslview` first; else `rundll32`'s URL handler, which
    takes the address as one argument (no cmd.exe quoting) and keeps its fragment."""
    if wslview := shutil.which("wslview"):
        return [wslview, url]
    rundll32 = shutil.which("rundll32.exe") or shutil.which(RUNDLL32)  # Windows' PATH not added
    return [rundll32, "url.dll,FileProtocolHandler", url] if rundll32 else None


def open_url(url: str) -> None:
    command = wsl_argv(url) if daemon_commands.wsl() and not os.environ.get("BROWSER") else None
    if command is None:
        webbrowser.open(url)
        return
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        webbrowser.open(url)
