"""GNOME keyboard shortcuts that open mini apps (H.7): one custom keybinding per app, at
…/custom-keybindings/handler-<app>/, running `handler app open <app>`. Set through `gsettings`, as
the daemon's user, in the desktop session it runs in; the person's own keybindings are left alone.
"""

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
TIMEOUT = 10


class ShortcutError(RuntimeError):
    pass


def entry_path(app: str) -> str:
    return f"{BASE}handler-{app}/"


def handler_command(app: str) -> str:
    """What the shortcut runs: this install's `handler`, next to the daemon's interpreter."""
    sibling = Path(sys.executable).parent / "handler"
    return shlex.join([str(sibling) if sibling.exists() else "handler", "app", "open", app])


def _gvariant_string(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _gsettings(*args: str) -> str:
    if not shutil.which("gsettings"):
        raise ShortcutError("gsettings not found: keyboard shortcuts need GNOME")
    try:
        r = subprocess.run(
            ["gsettings", *args], capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired:
        raise ShortcutError("gsettings did not answer (no desktop session?)") from None
    if r.returncode:
        raise ShortcutError(r.stderr.strip() or f"gsettings exited {r.returncode}")
    return r.stdout.strip()


def _entries() -> list[str]:
    out = _gsettings("get", SCHEMA, "custom-keybindings")
    return [m.replace("\\'", "'") for m in re.findall(r"'((?:[^'\\]|\\.)*)'", out)]


def _set_entries(paths: list[str]) -> None:
    value = "[" + ", ".join(_gvariant_string(p) for p in paths) + "]" if paths else "@as []"
    _gsettings("set", SCHEMA, "custom-keybindings", value)


def install(app: str, binding: str) -> None:
    """Bind `binding` (GNOME accelerator syntax, e.g. <Super>n) to opening `app`."""
    path = entry_path(app)
    relocatable = f"{SCHEMA}.custom-keybinding:{path}"
    for key, value in (
        ("name", f"handler: {app}"),
        ("command", handler_command(app)),
        ("binding", binding),
    ):
        _gsettings("set", relocatable, key, _gvariant_string(value))
    entries = _entries()
    if path not in entries:
        _set_entries([*entries, path])


def remove(app: str) -> None:
    path = entry_path(app)
    entries = _entries()
    if path in entries:
        _set_entries([p for p in entries if p != path])
    _gsettings("reset-recursively", f"{SCHEMA}.custom-keybinding:{path}")
