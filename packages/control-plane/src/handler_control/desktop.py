"""The person's desktop. Notifications (H.9): `notify-send`, else the freedesktop notification
service over `gdbus`; nothing when neither works (no desktop session). Best effort: a
notification is in handler's inbox anyway. A file or folder shown in the file manager (F.8)."""

import shutil
import subprocess
from pathlib import Path

TIMEOUT = 5


def notify(title: str, body: str | None) -> bool:
    if sender := shutil.which("notify-send"):
        argv = [sender, "--app-name=handler", title, *([body] if body else [])]
    elif gdbus := shutil.which("gdbus"):
        argv = [
            gdbus, "call", "--session",
            "--dest", "org.freedesktop.Notifications",
            "--object-path", "/org/freedesktop/Notifications",
            "--method", "org.freedesktop.Notifications.Notify",
            "handler", "0", "", _gvariant(title), _gvariant(body or ""), "[]", "{}", "-1",
        ]  # fmt: skip
    else:
        return False
    try:
        r = subprocess.run(argv, capture_output=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def reveal(path: Path, is_folder: bool) -> bool:
    """`path` shown in the file manager, selected in its folder (freedesktop `FileManager1`),
    never opened: a file the agent wrote could be a program. Without that service, its folder
    (or itself, a folder) opened with `xdg-open`. False when nothing could show it."""
    method = "ShowFolders" if is_folder else "ShowItems"
    if gdbus := shutil.which("gdbus"):
        argv = [
            gdbus, "call", "--session",
            "--dest", "org.freedesktop.FileManager1",
            "--object-path", "/org/freedesktop/FileManager1",
            "--method", f"org.freedesktop.FileManager1.{method}",
            f"[{_gvariant(path.as_uri())}]", "''",
        ]  # fmt: skip
        try:
            r = subprocess.run(argv, capture_output=True, timeout=TIMEOUT, check=False)
            if r.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    if opener := shutil.which("xdg-open"):
        folder = path if is_folder else path.parent
        try:  # it may wait for the file manager to exit
            subprocess.Popen(
                [opener, str(folder)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return False
        return True
    return False


def _gvariant(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"
