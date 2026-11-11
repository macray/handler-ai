"""Addons' tools as agents get them (G.4, A.1): an addon's image, once built, is extracted into a
folder Handler keeps, checked there, and that folder is what agents mount, read-only, on every
runtime; the image is only how it is built, removed once extracted.

    <data>/addons/<name>/<image id>/   the image's files (the installed tree, G.1), read-only
    <data>/addons/<name>/current       the id agents get, written when a build switches to it

A folder that is not current (the one a build replaced, a failed build's) is removed once no
sandbox mounts it (`sweep`): at the switch, when a sandbox ends, at handlerd's start. Under
Handler's data, no sandbox ever reaches these folders but read-only (invariant 6).
"""

import contextlib
import logging
import os
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path

from handler_contracts import ADDON_VERSION_FILE
from handler_harness import addons

from . import runtime
from .files import write_private
from .settings import Settings

log = logging.getLogger("handler.addons")

CURRENT = "current"
NOT_BUILT = "not-built"  # what `folder` names for an addon without one: it does not exist

_sweeping = threading.Lock()
_pending: set[Path] = set()  # folders a build is extracting or checking: `sweep` leaves them


class ExtractError(RuntimeError):
    """The image could not be extracted (the runtime's reason)."""


def root(settings: Settings, name: str) -> Path:
    return settings.data_dir / "addons" / name


def current_id(settings: Settings, name: str) -> str | None:
    with contextlib.suppress(FileNotFoundError):
        return (root(settings, name) / CURRENT).read_text().strip() or None
    return None


def folder(settings: Settings, name: str) -> Path:
    """The folder agents of addon `name` mount; one that does not exist when it is not built."""
    return root(settings, name) / (current_id(settings, name) or NOT_BUILT)


def built(settings: Settings, name: str) -> bool:
    return folder(settings, name).is_dir()


def built_at(settings: Settings, name: str) -> datetime | None:
    """When a build switched to its folder."""
    with contextlib.suppress(FileNotFoundError):
        mtime = (root(settings, name) / CURRENT).stat().st_mtime
        return datetime.fromtimestamp(mtime, UTC)
    return None


def version(settings: Settings, addon: addons.Addon) -> str | None:
    """The first line its image recorded (G.4), None when not built or not readable."""
    with contextlib.suppress(OSError):
        text = (folder(settings, addon.name) / ADDON_VERSION_FILE).read_text().strip()
        return text.splitlines()[0] if text else None
    return None


def extract(settings: Settings, addon: addons.Addon, image_id: str) -> Path:
    """The image's tools copied to their folder, read-only (not current yet: `switch`). Raises
    ExtractError."""
    target = root(settings, addon.name) / image_id
    partial = target.with_name(f".{image_id}.partial")
    with _sweeping:
        _pending.update((target, partial))
    if target.is_dir():  # the same image again (an Apply that changed nothing of it)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    _remove_own(partial)
    if reason := runtime.extract(image_id, "/", partial):  # the image is the installed tree
        release(settings, addon.name, image_id)
        raise ExtractError(f"{addon.name}: {reason}")
    for path, dirs, files in os.walk(partial):
        for name in [*dirs, *files]:
            entry = Path(path) / name
            if not entry.is_symlink():
                entry.chmod(entry.stat().st_mode & ~0o222)
    partial.rename(target)
    target.chmod(0o555)
    return target


def switch(settings: Settings, name: str, image_id: str) -> None:
    """Agents of addon `name` get the folder of `image_id` from now on; the one it replaces goes
    when no sandbox mounts it any more."""
    write_private(root(settings, name) / CURRENT, f"{image_id}\n")
    release(settings, name, image_id)
    sweep(settings)


def release(settings: Settings, name: str, image_id: str) -> None:
    """The build that extracted `image_id` is done with it: `sweep` may remove it if it did not
    become current (a failed build's)."""
    target = root(settings, name) / image_id
    with _sweeping:
        _pending.difference_update((target, target.with_name(f".{image_id}.partial")))


def forget(settings: Settings, name: str) -> None:
    """An uninstalled addon: none of its folders is current any more."""
    (root(settings, name) / CURRENT).unlink(missing_ok=True)
    sweep(settings)


def sweep(settings: Settings) -> None:
    """Remove every folder that is not current, unless a sandbox mounts it (then later). Cheap
    when there is none."""
    base = settings.data_dir / "addons"
    if not base.is_dir():
        return
    with _sweeping:
        for addon in base.iterdir():
            current = current_id(settings, addon.name)
            for entry in addon.iterdir():
                if entry.name not in (CURRENT, current) and entry not in _pending:
                    if reason := runtime.clear_cache(entry):
                        log.info("tool folder %s kept: %s", entry, reason)
                        continue
                    _remove_own(entry)
            with contextlib.suppress(OSError):
                addon.rmdir()  # an uninstalled addon's, once empty


def sweep_soon(settings: Settings) -> None:
    """`sweep`, in the background (a sandbox just ended: a folder it mounted may be free)."""
    base = settings.data_dir / "addons"
    if base.is_dir():
        threading.Thread(target=sweep, args=(settings,), daemon=True).start()


def _remove_own(path: Path) -> None:
    """A folder of Handler's, read-only on purpose: writable again first, then removed."""
    if not path.exists():
        return
    path.chmod(0o755)
    for parent, dirs, _ in os.walk(path):
        for name in dirs:
            entry = Path(parent) / name
            if not entry.is_symlink():
                entry.chmod(0o755)
    shutil.rmtree(path)
