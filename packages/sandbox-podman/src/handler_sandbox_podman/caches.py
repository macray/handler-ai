"""The `cache` verbs (contract A.9): how much a cache folder takes, and emptying it.

A cache a sandbox mounts holds files of its inner user ids too (inner podman's image store: the
host's subordinate ids), which the host user can neither always read nor remove: both verbs work
from inside the user namespace (`podman unshare`), where they are the user's.

Exit 0 when done, 1 otherwise with the reason on stderr.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from .podman import MANAGED_LABEL, PodmanError, podman


def _fail(message: str) -> int:
    print(f"handler-sandbox-podman: {message}", file=sys.stderr)
    return 1


def _in_userns(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """`argv` as the user namespace's root; rootful podman (dev containers) has none to enter."""
    prefix = ["podman", "unshare"] if os.getuid() != 0 else []
    return subprocess.run([*prefix, *argv], capture_output=True, text=True, check=False)


def size(paths: list[Path]) -> int:
    """Prints `{path: bytes on disk}` as JSON, a path that does not exist: 0."""
    sizes = dict.fromkeys(map(str, paths), 0)
    for path in paths:  # one `du` each: hard links shared between two are counted in both
        if not path.exists():
            continue
        result = _in_userns(["du", "-s", "--block-size=1", str(path)])
        if result.returncode != 0 or not result.stdout:
            return _fail(f"cannot measure {path}: {result.stderr.strip()}")
        sizes[str(path)] = int(result.stdout.split()[0])
    print(json.dumps(sizes))
    return 0


def _mounted(path: Path) -> list[str]:
    """The handler sandboxes (live or starting) that mount `path` or a folder inside it."""
    ids = podman("ps", "-a", "-q", "--filter", f"label={MANAGED_LABEL}=1").split()
    if not ids:
        return []
    found = []
    fmt = "{{.Name}}\t{{range .Mounts}}{{.Source}}\t{{end}}"
    # not checked: one gone since `ps` (it mounts nothing any more) fails the call, the others
    # are still printed
    for line in podman("inspect", "--format", fmt, *ids, check=False).splitlines():
        name, *sources = line.rstrip("\t").split("\t")
        if any(Path(s) == path or Path(s).is_relative_to(path) for s in sources):
            found.append(name)
    return found


def _mount_points(path: Path) -> list[str]:
    """Mount points of this namespace at `path` or inside it."""
    found = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        # field 5, octal-escaped (a space is \040)
        point = Path(line.split()[4].encode().decode("unicode_escape"))
        if point == path or point.is_relative_to(path):
            found.append(str(point))
    return found


def _refusal(path: Path) -> str | None:
    """Why `path` must not be emptied now, or None."""
    if not path.is_absolute() or path == Path("/"):
        return f"not a cache folder: {path}"
    if points := _mount_points(path):
        return f"{path} is or holds a mount point here ({points[0]}): not cleared"
    try:
        users = _mounted(path)
    except PodmanError as e:
        return str(e)
    return f"{path} is in use by a running sandbox ({', '.join(sorted(users))})" if users else None


def clear(path: Path) -> int:
    """Empties `path` (the folder itself stays), refused while a sandbox mounts it or a folder
    inside it: its agent would see the files go. Refused too when it is, or holds, a mount point
    here: mounted from elsewhere (this runs in a container), the sandboxes using it may be ones
    this podman cannot see."""
    if not path.exists():
        return 0
    if reason := _refusal(path):
        return _fail(reason)
    entries = ["find", str(path), "-mindepth", "1", "-maxdepth", "1"]
    result = _in_userns([*entries, "-exec", "rm", "-rf", "{}", "+"])
    if result.returncode != 0:
        return _fail(f"cannot clear {path}: {result.stderr.strip()}")
    return 0
