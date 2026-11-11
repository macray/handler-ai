"""Every `handler-sandbox-<name>` executable (contract A): its verbs and their arguments, the
spec read on fd 3, `set-egress`/`set-allow`/`set-blocked`/`set-watched` on a running sandbox's filter
settings (A.4). A
runtime's executable is `main` given what does each verb with its engine: its `Runtime` (launch,
attach, sweep), its `Images` (A.7), its `Caches` (A.9) and its `check` (A.8)."""

import argparse
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import EllipsisType
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from handler_contracts import EgressEntry, SandboxExit, SandboxSpec

from . import egress
from .launch import Runtime, attach, launch, running_filter, sweep

SPEC_FD = 3
APPLY_TIMEOUT = 10  # seconds its filter is given to apply new settings (set-*)
TURN = re.compile(r"[A-Za-z0-9_-]{1,64}")  # set-watched's word for the turn

VERBS = """verbs:
  launch 3< spec.json       run a SandboxSpec; stdio = the process's stdio (with `tty`: it waits
                            for `attach`)
  attach NAME               a `tty` sandbox's process on this terminal; stops it when this ends
                            first
  set-egress NAME enforce|log-only
  set-allow NAME [ENTRY ...]
                            replace the allow-list (the enforcement is kept)
  set-blocked NAME [ENTRY ...]
                            replace the hosts the user kept blocked (refused as unlisted ones,
                            the refusal saying it is their choice)
  set-watched NAME [TURN]   someone watches the session, in turn TURN (a word that changes each
                            turn): the first request to an undecided host waits a while for
                            their answer, once per host and turn; without TURN, nobody does
  sweep                     remove leftovers of dead launchers
  check                     can this host run sandboxes (RuntimeCheck JSON)
  image build CONTEXT --id-file FILE [--build-arg K=V ...] [--pull] [--no-cache]
              [--no-intermediate]
  image inspect REF         its id and build time (ImageInfo JSON)
  image read REF PATH       a file of the image, on stdout
  image extract REF PATH FOLDER
                            the image's folder PATH copied to FOLDER (made)
  image tag SOURCE TARGET
  image remove ID           refused while a container runs from it
  image pull REF
  image proxy               the egress proxy's image, built or not (ProxyImage JSON)
  image build-proxy         build it (base pulled, no cache), check it, switch to it
  cache size PATH ...       bytes on disk of each folder (JSON), inner ids' files too
  cache clear PATH          empty the folder; refused while a sandbox mounts it
"""


class Images(Protocol):
    """A runtime's `image` verbs (A.7), each printing what it answers: its `images` module."""

    def build(
        self, context: Path, id_file: Path, *, build_args: list[str], pull: bool,
        no_cache: bool, no_intermediate: bool,
    ) -> int: ...  # fmt: skip
    def inspect(self, ref: str) -> int: ...
    def read(self, ref: str, path: str) -> int: ...
    def extract(self, ref: str, path: str, folder: Path) -> int: ...
    def tag(self, source: str, target: str) -> int: ...
    def remove(self, image_id: str) -> int: ...
    def pull(self, ref: str) -> int: ...
    def proxy(self) -> int: ...
    def build_proxy(self) -> int: ...


class Caches(Protocol):
    """A runtime's `cache` verbs (A.9): its `caches` module."""

    def size(self, paths: list[Path]) -> int: ...
    def clear(self, path: Path) -> int: ...


def say(prog: str, message: str) -> None:
    print(f"{prog}: {message}", file=sys.stderr)


def parser(prog: str, about: str) -> argparse.ArgumentParser:
    """Every verb of contract A, with its arguments (A, A.7, A.8, A.9)."""
    p = argparse.ArgumentParser(
        prog=prog,
        description=about,
        epilog=VERBS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("launch")
    sub.add_parser("attach").add_argument("name")
    se = sub.add_parser("set-egress")
    se.add_argument("name")
    se.add_argument("enforcement", choices=["enforce", "log-only"])
    sa = sub.add_parser("set-allow")
    sa.add_argument("name")
    sa.add_argument("allow", nargs="*")
    sb = sub.add_parser("set-blocked")
    sb.add_argument("name")
    sb.add_argument("blocked", nargs="*")
    sw = sub.add_parser("set-watched")
    sw.add_argument("name")
    sw.add_argument("turn", nargs="?")
    sub.add_parser("sweep")
    sub.add_parser("check")
    image = sub.add_parser("image").add_subparsers(dest="verb", required=True)
    b = image.add_parser("build")
    b.add_argument("context", type=Path)
    b.add_argument("--id-file", type=Path, required=True)
    b.add_argument("--build-arg", action="append", default=[])
    b.add_argument("--pull", action="store_true", help="pull the base image again")
    b.add_argument("--no-cache", action="store_true")
    b.add_argument("--no-intermediate", action="store_true", help="keep only the final image")
    image.add_parser("inspect").add_argument("ref")
    r = image.add_parser("read")
    r.add_argument("ref")
    r.add_argument("path")
    x = image.add_parser("extract")
    x.add_argument("ref")
    x.add_argument("path")
    x.add_argument("folder", type=Path)
    t = image.add_parser("tag")
    t.add_argument("source")
    t.add_argument("target")
    image.add_parser("remove").add_argument("image_id")
    image.add_parser("pull").add_argument("ref")
    image.add_parser("proxy")
    image.add_parser("build-proxy")
    cache = sub.add_parser("cache").add_subparsers(dest="verb", required=True)
    cache.add_parser("size").add_argument("paths", type=Path, nargs="+")
    cache.add_parser("clear").add_argument("path", type=Path)
    return p


def read_spec(prog: str) -> SandboxSpec | None:
    """The SandboxSpec on fd 3; None (said) when there is none or it is invalid."""
    try:
        with os.fdopen(SPEC_FD, "rb") as f:
            raw = f.read()
    except OSError as e:
        say(prog, f"cannot read spec on fd {SPEC_FD}: {e}")
        return None
    try:
        return SandboxSpec.model_validate_json(raw)
    except ValidationError as e:
        say(prog, f"invalid spec: {e}")
        return None


def set_egress(
    prog: str,
    name: str,
    *,
    enforcement: egress.Enforcement | None = None,
    allow: list[str] | None = None,
    blocked: list[str] | None = None,
    watched: str | EllipsisType | None = ...,
) -> int:
    """Rewrite a running sandbox's filter settings (A.4): its enforcement, its allow-list, the
    hosts the user kept blocked, or whether someone watches (`...`: unchanged). One still
    starting is waited for: its connection is already the agent's."""
    cfg = running_filter(name)
    if cfg is None:
        say(prog, f"{name} is not a running filtered sandbox")
        return SandboxExit.UNENFORCEABLE
    try:  # each entry becomes one filter line: never trust it unchecked
        entries = TypeAdapter(list[EgressEntry])
        allow = None if allow is None else sorted(set(entries.validate_python(allow)))
        blocked = None if blocked is None else sorted(set(entries.validate_python(blocked)))
    except ValidationError as e:
        say(prog, f"invalid allow-list entry: {e}")
        return SandboxExit.INVALID_SPEC
    if isinstance(watched, str) and not TURN.fullmatch(watched):
        say(prog, f"invalid turn: {watched!r}")
        return SandboxExit.INVALID_SPEC
    state = egress.EgressState(cfg)
    current_allow, current_blocked, current_enforcement, current_watched = state.read()
    if current_enforcement == "open":  # its filter is there for its secrets only
        say(prog, f"{name} is not a filtered sandbox")
        return SandboxExit.UNENFORCEABLE
    version = state.write(
        current_allow if allow is None else allow,
        current_blocked if blocked is None else blocked,
        enforcement or current_enforcement,
        current_watched if watched is ... else watched,
    )
    if not state.wait_applied(version, APPLY_TIMEOUT):  # in force once this returns (A.4)
        say(prog, f"{name}'s filter did not apply its new settings")
        return SandboxExit.SETUP_FAILED
    return 0


def image(images: Images, args: argparse.Namespace) -> int:  # noqa: PLR0911 — one branch per verb
    if args.verb == "build":
        return images.build(
            args.context, args.id_file, build_args=args.build_arg, pull=args.pull,
            no_cache=args.no_cache, no_intermediate=args.no_intermediate,
        )  # fmt: skip
    if args.verb == "inspect":
        return images.inspect(args.ref)
    if args.verb == "read":
        return images.read(args.ref, args.path)
    if args.verb == "extract":
        return images.extract(args.ref, args.path, args.folder)
    if args.verb == "tag":
        return images.tag(args.source, args.target)
    if args.verb == "remove":
        return images.remove(args.image_id)
    if args.verb == "proxy":
        return images.proxy()
    if args.verb == "build-proxy":
        return images.build_proxy()
    return images.pull(args.ref)


def main(  # noqa: PLR0911 — one branch per verb
    runtime: Runtime,
    *,
    images: Images,
    caches: Caches,
    check: Callable[[], int],
    about: str,
    argv: list[str] | None = None,
) -> int:
    """`handler-sandbox-<name>`: `about` says which runtime it is."""
    args = parser(runtime.prog, about).parse_args(argv)
    if args.cmd == "launch":
        spec = read_spec(runtime.prog)
        return launch(runtime, spec) if spec else SandboxExit.INVALID_SPEC
    if args.cmd == "attach":
        return attach(runtime, args.name)
    if args.cmd == "set-egress":
        return set_egress(runtime.prog, args.name, enforcement=args.enforcement)
    if args.cmd == "set-allow":
        return set_egress(runtime.prog, args.name, allow=args.allow)
    if args.cmd == "set-blocked":
        return set_egress(runtime.prog, args.name, blocked=args.blocked)
    if args.cmd == "set-watched":
        return set_egress(runtime.prog, args.name, watched=args.turn)
    if args.cmd == "sweep":
        return sweep(runtime)
    if args.cmd == "check":
        return check()
    if args.cmd == "image":
        return image(images, args)
    return caches.size(args.paths) if args.verb == "size" else caches.clear(args.path)
