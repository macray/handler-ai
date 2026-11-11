"""A file given to a sandbox (an app's file need, H.9: a folder whose source is a file) where the
runtime's engine reaches your files through a share, not your kernel: Apple container (it shares
folders only) and Docker in a VM (Docker Desktop's sharing loses a file replaced on the host:
"no such file" for the container until it starts again).

Each is a hard link to it (the same file, not a copy) in a folder of the instance's, holding only
the files given there, mounted at the file's folder: read-only when they are, the folder itself
0555 (a file written in place both ways, none replaced nor added), the mount points of what is
mounted inside it made there. A file the host replaces (an editor saving by rename) stays the old
one for the sandbox, as with a bind mount on Linux, whose mount holds the old file
(rule `need.a-file-given-is-that-file`).
"""

import itertools
import os
from collections.abc import Callable
from pathlib import Path

from handler_contracts import HostFolder, SandboxSpec, is_within

from .launch import Args, InHome, Instance, UnenforceableError, runtimes_dir

Bind = Callable[[Path, str, bool], Args]  # (source, target, read-only) → the engine's `--mount`


def given_files(spec: SandboxSpec) -> dict[str, list[HostFolder]]:
    """The spec's folders whose source is a file, by the folder of their target."""
    found: dict[str, list[HostFolder]] = {}
    for f in spec.folders:
        if Path(f.source).is_file():
            found.setdefault(os.path.dirname(f.target), []).append(f)
    return found


def check(spec: SandboxSpec, runtime: str) -> None:
    """A1: a link cannot cross volumes, so each file must be on the instances' one; the folder
    holding given files is the instance's, mounted over the file's folder: it may not be in a
    folder given (it would hide part of it), and its files share one mode. A folder given inside
    it gets its mount point there."""
    files = given_files(spec)
    if not files:
        return
    here = runtimes_dir()
    while not here.exists():
        here = here.parent
    others = [
        spec.work_folder.path,
        *(f.target for f in spec.folders if not Path(f.source).is_file()),
    ]
    for folder, given in files.items():
        for f in given:
            if os.stat(f.source).st_dev != os.stat(here).st_dev:
                raise UnenforceableError(
                    f"{f.source} is on another volume than {here}: {runtime} is given a file "
                    "through a link to it, which cannot cross volumes"
                )
        if any(is_within(folder, o) for o in others):
            raise UnenforceableError(f"{folder}: a file given in it, and a folder given around it")
        if len({f.writable for f in given}) > 1:
            raise UnenforceableError(f"{folder}: files given in it read-only and writable both")


def _target(mount: str) -> str:
    """A `--mount` value's target (Apple's `target=`, Docker's `destination=`)."""
    for key in ("target=", "destination=", "dst="):
        if key in mount:
            return mount.split(key, 1)[1].split(",", maxsplit=1)[0]
    raise ValueError(f"no target in {mount}")


def mount_targets(args: Args) -> list[str]:
    """Where each `--mount` is, in order."""
    return [_target(a) for p, a in itertools.pairwise(args) if p == "--mount"]


def parents_first(args: Args) -> Args:
    """The `--mount`s in the order of their targets' depth (a folder before what is mounted in
    it), each in one of their places; the other arguments as they were."""
    places = [i for i, a in enumerate(args) if a == "--mount"]
    mounts = sorted((args[i + 1] for i in places), key=lambda m: _target(m).count("/"))
    ordered = list(args)
    for i, mount in zip(places, mounts, strict=True):
        ordered[i + 1] = mount
    return ordered


class LinkedFiles:
    """One instance's given files: `link` each (its folder's mount the first time), then
    `finish` with every argument of the sandbox, before it is created."""

    def __init__(self, bind: Bind) -> None:
        self.bind = bind
        self.folders: dict[str, Path] = {}  # a folder holding given files → the instance's

    def link(self, need: HostFolder, instance: Instance) -> Args:
        folder = os.path.dirname(need.target)
        args: Args = []
        if folder not in self.folders:
            self.folders[folder] = instance.dir / "given" / str(len(self.folders))
            self.folders[folder].mkdir(parents=True)
            instance.put_in_home(InHome(folder, "folder"))
            args = self.bind(self.folders[folder], folder, not need.writable)
        try:
            os.link(need.source, self.folders[folder] / os.path.basename(need.target))
        except OSError as e:
            raise OSError(f"{need.source} cannot be given: {e.strerror}") from None  # setup failed
        return args

    def finish(self, args: Args) -> Args:
        """The mounts parents first; in each folder, the mount points of what is mounted inside
        it, then the folder made 0555 (its files written in place, none replaced nor added)."""
        args = parents_first(args)
        for folder, linked in self.folders.items():
            for target in mount_targets(args):
                if is_within(target, folder) and target != folder:
                    (linked / os.path.relpath(target, folder)).mkdir(parents=True, exist_ok=True)
            linked.chmod(0o555)
        return args
