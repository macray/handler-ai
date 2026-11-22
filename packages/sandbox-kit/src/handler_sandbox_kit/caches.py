"""The `cache` verbs (contract A.9) of an engine with Docker's CLI (Podman, Docker): how much a
cache folder takes, and emptying it. A cache a sandbox mounts holds files of its inner user ids
too (an inner engine's image store), which the host user can neither always read nor remove: the
runtime gives how it runs `du` and `find` where they are its own.

Exit 0 when done, 1 otherwise with the reason on stderr.
"""

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from .launcher import MANAGED_LABEL

# runs `[*before, <the folders as the command sees them>, *after]` (folders, before, after), in
# one call: entering the runtime's place (`podman unshare`, a container) costs more than `du`
Run = Callable[[list[Path], list[str], list[str]], subprocess.CompletedProcess[str]]
Engine = Callable[..., str]  # the engine's CLI: `podman(*args, check=…)`


def _fail(prog: str, message: str) -> int:
    print(f"{prog}: {message}", file=sys.stderr)
    return 1


def size(prog: str, paths: list[Path], run: Run) -> int:
    """Prints `{path: bytes on disk}` as JSON, a path that does not exist: 0. One `du` for them
    all (`-l`: a hard link shared between two is counted in both, as one `du` each would)."""
    sizes = dict.fromkeys(map(str, paths), 0)
    found = [p for p in dict.fromkeys(paths) if p.exists()]
    if not found:
        print(json.dumps(sizes))
        return 0
    result = run(found, ["du", "-s", "-l", "--block-size=1"], [])
    lines = result.stdout.splitlines()
    if result.returncode != 0 or len(lines) != len(found):
        return _fail(prog, f"cannot measure {', '.join(map(str, found))}: {result.stderr.strip()}")
    for path, line in zip(found, lines, strict=True):  # in the order given
        sizes[str(path)] = int(line.split()[0])
    print(json.dumps(sizes))
    return 0


def _mounted(engine: Engine, path: Path) -> list[str]:
    """The handler sandboxes (live or starting) that mount `path` or a folder inside it."""
    ids = engine("ps", "-a", "-q", "--filter", f"label={MANAGED_LABEL}=1").split()
    if not ids:
        return []
    found = []
    fmt = "{{.Name}}\t{{range .Mounts}}{{.Source}}\t{{end}}"
    # not checked: one gone since `ps` (it mounts nothing any more) fails the call, the others
    # are still printed
    for line in engine("inspect", "--format", fmt, *ids, check=False).splitlines():
        name, *sources = line.rstrip("\t").split("\t")
        if any(Path(s) == path or Path(s).is_relative_to(path) for s in sources):
            found.append(name.lstrip("/"))  # Docker's names start with "/"
    return found


def _mount_points(path: Path) -> list[str]:
    """Mount points of this namespace at `path` or inside it (none to read off Linux)."""
    found = []
    mountinfo = Path("/proc/self/mountinfo")
    lines = mountinfo.read_text().splitlines() if mountinfo.exists() else []
    for line in lines:
        # field 5, octal-escaped (a space is \040)
        point = Path(line.split()[4].encode().decode("unicode_escape"))
        if point == path or point.is_relative_to(path):
            found.append(str(point))
    return found


def _refusal(path: Path, engine: Engine, errors: type[Exception]) -> str | None:
    """Why `path` must not be emptied now, or None."""
    if not path.is_absolute() or path == Path("/"):
        return f"not a cache folder: {path}"
    if points := _mount_points(path):
        return f"{path} is or holds a mount point here ({points[0]}): not cleared"
    try:
        users = _mounted(engine, path)
    except errors as e:
        return str(e)
    return f"{path} is in use by a running sandbox ({', '.join(sorted(users))})" if users else None


def clear(prog: str, path: Path, run: Run, engine: Engine, errors: type[Exception]) -> int:
    """Empties `path` (the folder itself stays), refused while a sandbox mounts it or a folder
    inside it: its agent would see the files go. Refused too when it is, or holds, a mount point
    here: mounted from elsewhere (this runs in a container), the sandboxes using it may be ones
    this engine cannot see."""
    if not path.exists():
        return 0
    if reason := _refusal(path, engine, errors):
        return _fail(prog, reason)
    entries = ["-mindepth", "1", "-maxdepth", "1"]
    result = run([path], ["find"], [*entries, "-exec", "rm", "-rf", "{}", "+"])
    if result.returncode != 0:
        return _fail(prog, f"cannot clear {path}: {result.stderr.strip()}")
    return 0
