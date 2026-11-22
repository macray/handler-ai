"""The `cache` verbs (contract A.9), the kit's: `du` and `find` run as root in a container of the
filter's image (always built), the folder mounted, without network, where the files of the
sandboxes' inner user ids are root's."""

import subprocess
from pathlib import Path

from handler_sandbox_kit import caches
from handler_sandbox_kit.launcher import LAUNCHER_LABEL, MANAGED_LABEL, launcher_label

from .docker import PROXY_IMAGE, DockerError, docker
from .launch import PROG


def _as_root(paths: list[Path], argv: list[str]) -> subprocess.CompletedProcess[str]:
    """`argv` as root in one container mounting the n-th of `paths` at /c<n>."""
    mounts = [
        arg
        for n, path in enumerate(paths)
        for arg in ("--mount", f"type=bind,source={path},destination=/c{n}")
    ]
    return subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--user", "0:0",
         "--label", f"{MANAGED_LABEL}=1", "--label", f"{LAUNCHER_LABEL}={launcher_label()}",
         *mounts, "--entrypoint", argv[0], PROXY_IMAGE, *argv[1:]],
        capture_output=True, text=True, check=False, timeout=600,
    )  # fmt: skip


def _run(
    paths: list[Path], before: list[str], after: list[str]
) -> subprocess.CompletedProcess[str]:
    return _as_root(paths, [*before, *(f"/c{n}" for n in range(len(paths))), *after])


def size(paths: list[Path]) -> int:
    return caches.size(PROG, paths, _run)


def clear(path: Path) -> int:
    return caches.clear(PROG, path, _run, docker, DockerError)
