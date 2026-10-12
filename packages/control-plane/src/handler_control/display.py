"""The display an agent may give its sandboxes (contract A.6): the host's Wayland socket.

Found at each agent start (a compositor restart may change it), in this order:
    $HANDLER_WAYLAND_SOCKET      an explicit socket path
    $WAYLAND_DISPLAY             a name in $XDG_RUNTIME_DIR, or an absolute path
    $XDG_RUNTIME_DIR/wayland-N   the only one there
handlerd runs as a systemd user service, which only has WAYLAND_DISPLAY if the compositor exported
it to systemd; the last rule covers the usual case of one Wayland session.
"""

import os
import stat
from collections.abc import Mapping
from pathlib import Path

from handler_contracts import WaylandDisplay


class DisplayError(RuntimeError):
    """No usable Wayland display: the agent asked for one, it is never started without."""


def _is_socket(path: Path) -> bool:
    try:
        return stat.S_ISSOCK(path.stat().st_mode)
    except OSError:
        return False


def wayland_socket(env: Mapping[str, str] | None = None) -> str:
    """The host's Wayland socket, absolute. Raises DisplayError."""
    env = os.environ if env is None else env
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
    if not candidates or not _is_socket(candidates[0]):
        where = candidates[0] if candidates else origin
        raise DisplayError(f"no Wayland display ({where}): is a Wayland session running?")
    return str(candidates[0])


def wayland(env: Mapping[str, str] | None = None) -> WaylandDisplay:
    return WaylandDisplay(mode="wayland", socket=wayland_socket(env))


def available() -> bool:
    try:
        wayland_socket()
    except DisplayError:
        return False
    return True
