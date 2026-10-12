"""handler-sandbox-podman — contract A implementation on rootless podman.

handler-sandbox-podman launch 3< spec.json  run a SandboxSpec; stdio = the process's stdio
                                            (with `tty`: it waits for `attach`)
handler-sandbox-podman attach NAME          a `tty` sandbox's process on this terminal; stops it
                                            when this ends first
handler-sandbox-podman set-egress NAME enforce|log-only
handler-sandbox-podman set-allow NAME [ENTRY ...]  replace the allow-list (the enforcement is kept)
handler-sandbox-podman sweep                remove leftovers of dead launchers
handler-sandbox-podman check                can this host run sandboxes (RuntimeCheck JSON)
handler-sandbox-podman image build CONTEXT --id-file FILE [--build-arg K=V ...] [--pull]
                                            [--no-cache] [--no-intermediate]
handler-sandbox-podman image inspect REF    its id and build time (ImageInfo JSON)
handler-sandbox-podman image read REF PATH  a file of the image, on stdout
handler-sandbox-podman image tag SOURCE TARGET
handler-sandbox-podman image remove ID      refused while a container uses or mounts it
handler-sandbox-podman image pull REF
handler-sandbox-podman image proxy          the egress proxy's image, built or not (ProxyImage JSON)
handler-sandbox-podman image build-proxy    build it (base pulled, no cache), check it, switch to it
handler-sandbox-podman cache size PATH ...  bytes on disk of each folder (JSON), inner ids' files
                                            too
handler-sandbox-podman cache clear PATH     empty the folder; refused while a sandbox mounts it
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from handler_contracts import EgressEntry, SandboxExit, SandboxSpec

from . import caches, check, egress, images
from .launch import (
    LAUNCHER_FILE,
    PROXY_DIR,
    PROXY_READY,
    instance_dir,
    launch,
    state_root,
)
from .podman import (
    LAUNCHER_LABEL,
    MANAGED_LABEL,
    launcher_alive,
    podman,
    quiet,
)

SPEC_FD = 3
PROXY_START_TIMEOUT = 60  # seconds a starting sandbox's proxy is waited for (set-*)


def _read_spec() -> SandboxSpec | None:
    try:
        with os.fdopen(SPEC_FD, "rb") as f:
            raw = f.read()
    except OSError as e:
        print(f"handler-sandbox-podman: cannot read spec on fd {SPEC_FD}: {e}", file=sys.stderr)
        return None
    try:
        return SandboxSpec.model_validate_json(raw)
    except ValidationError as e:
        print(f"handler-sandbox-podman: invalid spec: {e}", file=sys.stderr)
        return None


def cmd_launch() -> int:
    spec = _read_spec()
    return launch(spec) if spec else SandboxExit.INVALID_SPEC


def cmd_attach(name: str) -> int:
    """A `tty` sandbox (D.16): start its process on this terminal (raw, resized with it, podman
    passing our signals on), its exit code ours. When this terminal goes away first (a hang-up),
    the process gets it too; whatever still runs then is stopped."""
    proc: subprocess.Popen[bytes] | None = None

    def pass_on(signum: int, _frame: object) -> None:
        # a hang-up is the session leader's (this process), not podman's: podman passes it in
        if proc is not None:
            proc.send_signal(signum)

    for sig in (signal.SIGHUP, signal.SIGTERM):  # not to die before the stop below
        signal.signal(sig, pass_on)
    proc = subprocess.Popen(["podman", "start", "--attach", "--interactive", name])
    code = proc.wait()
    quiet("stop", "--time", "5", name)
    return code


def cmd_set_egress(
    name: str, enforcement: egress.Enforcement | None = None, allow: list[str] | None = None
) -> int:
    """Rewrite a running instance's settings (A.4): its enforcement, or its allow-list. One still
    starting is waited for: its connection is already the agent's."""
    cfg = instance_dir(name) / PROXY_DIR
    deadline = time.monotonic() + PROXY_START_TIMEOUT
    while cfg.is_dir() and not (cfg / PROXY_READY).exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not (cfg / PROXY_READY).exists():
        print(f"handler-sandbox-podman: {name} is not a running filtered sandbox", file=sys.stderr)
        return SandboxExit.UNENFORCEABLE
    if allow is not None:
        try:  # each entry becomes one filter line: never trust it unchecked
            allow = sorted(set(TypeAdapter(list[EgressEntry]).validate_python(allow)))
        except ValidationError as e:
            print(f"handler-sandbox-podman: invalid allow-list entry: {e}", file=sys.stderr)
            return SandboxExit.INVALID_SPEC
    state = egress.EgressState(cfg)  # the proxy reads it again for its next request
    current_allow, current_enforcement = state.read()
    if current_enforcement == "open":  # its proxy is there for its secrets only
        print(f"handler-sandbox-podman: {name} is not a filtered sandbox", file=sys.stderr)
        return SandboxExit.UNENFORCEABLE
    state.write(current_allow if allow is None else allow, enforcement or current_enforcement)
    return 0


def cmd_sweep() -> int:
    """Remove containers, networks and instance dirs whose launcher process is gone (another
    launcher may be setting its sandbox up meanwhile: its network and dir exist, no container)."""
    # json, not a `{{index .Labels …}}` template: that one fails on a container being removed
    rows = podman("ps", "-a", "--filter", f"label={MANAGED_LABEL}=1", "--format", "json")
    dead_sandboxes: set[str] = set()
    for row in json.loads(rows or "[]"):
        name = row["Names"][0]
        if not launcher_alive((row.get("Labels") or {}).get(LAUNCHER_LABEL, "")):
            quiet("rm", "--force", "--time", "0", name)
            dead_sandboxes.add(name.removesuffix("-proxy"))
    nets = json.loads(
        podman("network", "ls", "--filter", f"label={MANAGED_LABEL}=1", "--format", "json") or "[]"
    )
    for net in nets:
        if not launcher_alive(net.get("labels", {}).get(LAUNCHER_LABEL, "")):
            quiet("network", "rm", "--force", net["name"])
    root = state_root()
    if root.exists():
        for d in root.iterdir():
            try:
                launcher = (d / LAUNCHER_FILE).read_text()
            except FileNotFoundError:
                continue  # just made: its launcher writes the file right after the dir
            if not launcher_alive(launcher):
                shutil.rmtree(d, ignore_errors=True)
    if dead_sandboxes:
        print(f"swept: {', '.join(sorted(dead_sandboxes))}", file=sys.stderr)
    return 0


def cmd_image(args: argparse.Namespace) -> int:  # noqa: PLR0911 — one branch per verb
    if args.verb == "build":
        return images.build(
            args.context,
            args.id_file,
            build_args=args.build_arg,
            pull=args.pull,
            no_cache=args.no_cache,
            no_intermediate=args.no_intermediate,
        )
    if args.verb == "inspect":
        return images.inspect(args.ref)
    if args.verb == "read":
        return images.read(args.ref, args.path)
    if args.verb == "tag":
        return images.tag(args.source, args.target)
    if args.verb == "remove":
        return images.remove(args.image_id)
    if args.verb == "proxy":
        return images.proxy()
    if args.verb == "build-proxy":
        return images.build_proxy()
    return images.pull(args.ref)


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0911 — one branch per verb
    parser = argparse.ArgumentParser(
        prog="handler-sandbox-podman",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("launch")
    sub.add_parser("attach").add_argument("name")
    se = sub.add_parser("set-egress")
    se.add_argument("name")
    se.add_argument("enforcement", choices=["enforce", "log-only"])
    sa = sub.add_parser("set-allow")
    sa.add_argument("name")
    sa.add_argument("allow", nargs="*")
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
    args = parser.parse_args(argv)
    if args.cmd == "cache":
        return caches.size(args.paths) if args.verb == "size" else caches.clear(args.path)
    if args.cmd == "image":
        return cmd_image(args)
    if args.cmd == "check":
        return check.check()
    if args.cmd == "launch":
        return cmd_launch()
    if args.cmd == "attach":
        return cmd_attach(args.name)
    if args.cmd == "set-egress":
        return cmd_set_egress(args.name, args.enforcement)
    if args.cmd == "set-allow":
        return cmd_set_egress(args.name, allow=args.allow)
    return cmd_sweep()


if __name__ == "__main__":
    sys.exit(main())
