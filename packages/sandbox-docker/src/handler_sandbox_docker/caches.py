"""The `cache` verbs (contract A.9), the kit's: `du` and `find` run as root in a container of the
filter's image (always built), the folder mounted, without network, where the files of the
sandboxes' inner user ids are root's."""

import subprocess
from pathlib import Path

from handler_sandbox_kit import caches
from handler_sandbox_kit.launcher import LAUNCHER_LABEL, MANAGED_LABEL, launcher_label

from .docker import PROXY_IMAGE, DockerError, docker
from .launch import PROG


def _as_root(path: Path, argv: list[str]) -> subprocess.CompletedProcess[str]:
    """`argv` as root in a container mounting `path` at /c."""
    return subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--user", "0:0",
         "--label", f"{MANAGED_LABEL}=1", "--label", f"{LAUNCHER_LABEL}={launcher_label()}",
         "--mount", f"type=bind,source={path},destination=/c",
         "--entrypoint", argv[0], PROXY_IMAGE, *argv[1:]],
        capture_output=True, text=True, check=False, timeout=600,
    )  # fmt: skip


def _run(path: Path, before: list[str], after: list[str]) -> subprocess.CompletedProcess[str]:
    return _as_root(path, [*before, "/c", *after])


def size(paths: list[Path]) -> int:
    return caches.size(PROG, paths, _run)


def clear(path: Path) -> int:
    return caches.clear(PROG, path, _run, docker, DockerError)
