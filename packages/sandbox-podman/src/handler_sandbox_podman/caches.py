"""The `cache` verbs (contract A.9), the kit's: `du` and `find` run from inside the user
namespace (`podman unshare`), where the files of the sandboxes' inner user ids are the user's."""

import os
import subprocess
from pathlib import Path

from handler_sandbox_kit import caches

from .launch import PROG
from .podman import PodmanError, podman


def _in_userns(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """`argv` as the user namespace's root; rootful podman (dev containers) has none to enter."""
    prefix = ["podman", "unshare"] if os.getuid() != 0 else []
    return subprocess.run([*prefix, *argv], capture_output=True, text=True, check=False)


def _run(path: Path, before: list[str], after: list[str]) -> subprocess.CompletedProcess[str]:
    return _in_userns([*before, str(path), *after])


def size(paths: list[Path]) -> int:
    return caches.size(PROG, paths, _run)


def clear(path: Path) -> int:
    return caches.clear(PROG, path, _run, podman, PodmanError)
