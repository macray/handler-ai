"""`handler setup`: from an installed handler to a working one, safe to run again.

1. handlerd as a systemd user service (`handler daemon install`), started; on its first start it
   writes the token and copies the default toolbox to ~/.config/handler-ai/toolbox/
2. what the container runtime finds missing on this machine (GET /v1/runtime, A.8)
3. the network filter (D.4), when it is not built: handlerd builds it as it starts, this follows
   that build (or starts it)
4. the images, when the toolbox is not built yet: the toolbox then every harness image,
   checked (`handler image rebuild toolbox`); skipped with --no-build
5. where the web UI is (`handler ui`)
"""

import argparse
import sys
import time
from typing import Any

from . import daemon_commands, image_commands
from .client import ClientError, Daemon, base_url

START_TIMEOUT = 60.0


def add_parser(sub: Any) -> None:
    s = sub.add_parser("setup", help="install and start handlerd, check this machine, build images")
    s.add_argument("--no-build", action="store_true", help="do not build the images now")
    s.add_argument("--yes", action="store_true", help="build the images without asking")


def _daemon() -> Daemon:
    """handlerd, once it answers (it writes its token on its first start)."""
    deadline = time.monotonic() + START_TIMEOUT
    while True:
        try:
            d = Daemon()
            d.call("GET", "/v1/health")
            return d
        except ClientError:
            if time.monotonic() > deadline:
                raise ClientError(
                    f"handlerd did not start within {START_TIMEOUT:.0f} s: "
                    "journalctl --user -u handler-ai shows why"
                ) from None
            time.sleep(1)


def _runtime(d: Daemon) -> bool:
    check = d.call("GET", "/v1/runtime")
    print(f"\n{check['runtime']}")
    for item in check["items"]:
        mark = "ok  " if item["ok"] else ("FAIL" if item["required"] else "warn")
        print(f"  {mark} {item['name']}: {item['detail']}")
    if not check["ok"]:
        print("\nAgents cannot run here yet: fix what FAIL says, then run `handler setup` again.")
    return bool(check["ok"])


def _network_filter(d: Daemon) -> int:
    """Follow handlerd's build of the network filter, or start it; 0 once it is built."""
    if d.call("GET", "/v1/network-filter")["imagePresent"]:
        return 0
    print(
        "\nBuilding the network filter: it checks where agents connect and adds your secrets to "
        "their requests (about 240 MB, a minute or two)."
    )
    while True:
        for build in d.call("GET", "/v1/builds"):
            if build["target"] == "network-filter" and build["state"] == "running":
                return image_commands.watch(d, build)
        try:
            return image_commands.watch(d, d.call("POST", "/v1/network-filter/rebuild"))
        except ClientError as e:  # handlerd started its own meanwhile, or another build runs
            if e.status != 409:
                raise
            time.sleep(1)


def _wants_build(args: argparse.Namespace) -> bool:
    if args.yes:
        return True
    if not sys.stdin.isatty():
        print("Images not built: run `handler setup --yes` or `handler image rebuild toolbox`.")
        return False
    answer = input(
        "\nBuild the images now? The toolbox, then every harness on it: a large download "
        "(about 2.5 GB) and 10 to 20 minutes. [Y/n] "
    )
    return answer.strip().lower() in ("", "y", "yes")


def dispatch(args: argparse.Namespace) -> int:
    print("Installing handlerd as a systemd user service…")
    try:
        code = daemon_commands.install(dry_run=False)
    except OSError as e:  # no systemctl
        code = 1
        print(e)
    if code:
        print("systemctl failed: without a systemd user session, run `handlerd` yourself.")
        return code
    d = _daemon()
    print(f"handlerd {d.call('GET', '/v1/health')['version']} is running at {base_url()}")
    if not _runtime(d):
        return 1
    if code := _network_filter(d):
        print(
            "The network filter could not be built: "
            "`handler image rebuild network-filter` tries again."
        )
        return code
    toolbox = d.call("GET", "/v1/toolbox")
    print(f"\nYour toolbox (the tools every agent gets): {toolbox['directory']}")
    if not toolbox["imagePresent"] and not args.no_build and _wants_build(args):
        build = image_commands.rebuild(d, "toolbox")
        if build:
            return build
    print(
        "\nDone. Open the web UI with `handler ui`: first Settings → Model access, then a project."
    )
    return 0
