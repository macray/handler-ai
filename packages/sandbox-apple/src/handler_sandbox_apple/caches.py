"""The `cache` verbs (contract A.9) on Apple container: the folders are the user's own on the Mac
(no inner user ids: no `nested` here yet), so they are measured and emptied directly.
`clear` is refused while a sandbox mounts the folder or one inside it, or an ended sandbox's
additions to it are still to merge (its disk)."""

import json
import os
import shutil
import sys
from pathlib import Path

from handler_contracts import is_within
from handler_sandbox_kit.launcher import MANAGED_LABEL, SANDBOX_LABEL

from .container import container, containers, labels_of
from .launch import CACHES_LABEL, PROG, disks


def _fail(message: str) -> int:
    print(f"{PROG}: {message}", file=sys.stderr)
    return 1


def _bytes(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_blocks * 512
            except OSError:
                continue
    return total


def size(paths: list[Path]) -> int:
    print(json.dumps({str(p): _bytes(p) if p.exists() else 0 for p in paths}))
    return 0


def _in_use(path: Path) -> list[str]:
    """Managed sandboxes whose configuration names `path` or a folder inside it (the
    inspect document's layout is not documented, its text is searched), and ended ones whose
    additions to it are still on their disk, to merge."""
    found = []
    for c in containers():
        name = labels_of(c).get(SANDBOX_LABEL, "")
        if labels_of(c).get(MANAGED_LABEL) != "1" or not name:
            continue
        if str(path) in container("inspect", name, check=False):
            found.append(name)
    for _, labels in disks():
        sources = json.loads(labels.get(CACHES_LABEL, "[]") or "[]")
        name = labels.get(SANDBOX_LABEL, "")
        if name not in found and any(is_within(s, str(path)) for s in sources):
            found.append(name)
    return found


def clear(path: Path) -> int:
    if not path.is_dir():
        return 0
    if users := _in_use(path):
        return _fail(f"{path} in use by {', '.join(users)}")
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    return 0
