"""The person's display a runtime gives a sandbox asking for one (A.6): the host's Wayland socket,
found where the launcher runs (handlerd's session).

Found at each launch and each `check` (a compositor restart may change it), in this order:
    $HANDLER_WAYLAND_SOCKET      an explicit socket path
    $WAYLAND_DISPLAY             a name in $XDG_RUNTIME_DIR, or an absolute path
    $XDG_RUNTIME_DIR/wayland-N   the only one there
    /mnt/wslg/runtime-dir/wayland-0   WSLg's, when the two above find none
handlerd runs as a systemd user service, which only has WAYLAND_DISPLAY if the compositor exported
it to systemd; the third rule covers the usual case of one Wayland session. On WSL with systemd,
$XDG_RUNTIME_DIR is systemd's own folder, where WSLg's socket may be missing: the last rule.
"""

import os
import stat
from pathlib import Path

WSLG_SOCKET = Path("/mnt/wslg/runtime-dir/wayland-0")


class DisplayError(RuntimeError):
    """No usable Wayland display: a sandbox asking for one is never started without."""


def _is_socket(path: Path) -> bool:
    try:
        return stat.S_ISSOCK(path.stat().st_mode)
    except OSError:
        return False


def wayland_socket() -> str:
    """The host's Wayland socket, absolute. Raises DisplayError."""
    env = os.environ
    runtime = Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    if explicit := env.get("HANDLER_WAYLAND_SOCKET"):
        candidates, origin = [Path(explicit)], "HANDLER_WAYLAND_SOCKET"
    elif name := env.get("WAYLAND_DISPLAY"):
        candidates, origin = [runtime / name], "WAYLAND_DISPLAY"  # an absolute name wins the join
    else:
        candidates = sorted(p for p in runtime.glob("wayland-*") if _is_socket(p))
        origin = f"{runtime}/wayland-*"
        if len(candidates) > 1:
            names = ", ".join(p.name for p in candidates)
            raise DisplayError(
                f"several Wayland displays in {runtime} ({names}): set HANDLER_WAYLAND_SOCKET "
                "for handlerd to the one to use"
            )
    if (not candidates or not _is_socket(candidates[0])) and origin != "HANDLER_WAYLAND_SOCKET":
        candidates = [WSLG_SOCKET] if _is_socket(WSLG_SOCKET) else candidates
    if not candidates or not _is_socket(candidates[0]):
        where = candidates[0] if candidates else origin
        raise DisplayError(f"no Wayland display ({where}): is a Wayland session running?")
    return str(candidates[0])


def found() -> bool:
    try:
        wayland_socket()
    except DisplayError:
        return False
    return True
