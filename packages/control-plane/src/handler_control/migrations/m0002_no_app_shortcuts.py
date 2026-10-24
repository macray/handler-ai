"""Apps no longer have a keyboard shortcut (H.7): the GNOME keybindings Handler made for them are
removed, and so is their record.

    <state>/apps.json   each app: - "shortcut"
    GNOME               …/media-keys/custom-keybindings/handler-<app>/ removed from the list and
                        reset (the person's own keybindings are left alone)

When GNOME cannot be reached (no gsettings, no desktop session), the keybinding is left and the
log says how to remove it by hand: it still opens the app.
"""

import json
import logging
import re
import shutil
import subprocess

from ..files import write_private
from ..settings import Settings

log = logging.getLogger("handler.migrations")

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"


def _gsettings(*args: str) -> str:
    r = subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=10, check=True)
    return r.stdout.strip()


def _unbind(app: str) -> None:
    path = f"{BASE}handler-{app}/"
    listed = _gsettings("get", SCHEMA, "custom-keybindings")
    entries = [m.replace("\\'", "'") for m in re.findall(r"'((?:[^'\\]|\\.)*)'", listed)]
    if path in entries:
        rest = [p for p in entries if p != path]
        value = "[" + ", ".join("'" + p.replace("'", "\\'") + "'" for p in rest) + "]"
        _gsettings("set", SCHEMA, "custom-keybindings", value if rest else "@as []")
    _gsettings("reset-recursively", f"{SCHEMA}.custom-keybinding:{path}")


def migrate(settings: Settings) -> None:
    path = settings.state_dir / "apps.json"
    if not path.exists():
        return
    state = json.loads(path.read_text())
    for name, record in state.get("apps", {}).items():
        if record.pop("shortcut", None):
            try:
                if not shutil.which("gsettings"):
                    raise FileNotFoundError("gsettings not found")
                _unbind(name)
            except (OSError, subprocess.SubprocessError) as e:
                log.warning(
                    "the keyboard shortcut of the app %s is left (%s): remove “handler: %s” in "
                    "GNOME's Settings → Keyboard → Custom Shortcuts",
                    name,
                    e,
                    name,
                )
    write_private(path, json.dumps(state, indent=2))
