"""`handler image …` — the images agents run in: the toolbox (the base every agent gets), one per
harness and per addon on top of it, and the network filter. Built locally, through handlerd (D.4,
G.4), like the web UI.

    handler image list                 every image: built or not, the harness's version, when built
    handler image rebuild NAME         rebuild a harness image from the files on disk (the
                                       harness's latest release), check it, then switch agents to
                                       it; the log streams to the terminal
    handler image rebuild addon:NAME   same for an addon's image (also its first build)
    handler image rebuild toolbox      same for the toolbox (system updates), then every harness and
                                       addon on top of it: all switch, or none
    handler image rebuild network-filter
                                       the network filter: what checks where agents connect and adds
                                       your secrets to their requests (handlerd builds it when it is
                                       missing)

Ctrl-C during a rebuild cancels it: nothing switches. Running sessions keep the image they started
on.
"""

import argparse
import sys
import time
from typing import Any

from .client import Daemon
from .output import table


def add_parser(sub: Any) -> None:
    image = sub.add_parser("image", help="images", description=__doc__,
                           formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    i = image.add_subparsers(dest="image_cmd", required=True)
    i.add_parser("list")
    i.add_parser("rebuild").add_argument(
        "target", help="a harness name, 'toolbox', 'network-filter', or 'addon:NAME'"
    )


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.image_cmd == "list":
        print_images(d)
        return 0
    return rebuild(d, args.target)


def print_images(d: Daemon) -> None:
    rows = [["NAME", "IMAGE", "VERSION", "BUILT"]]

    def row(name: str, info: dict[str, Any], version: str = "-") -> None:
        built = (info.get("builtAt") or "-")[:16].replace("T", " ")
        rows.append([name, info["image"], version if info["imagePresent"] else "not built", built])

    row("toolbox", d.call("GET", "/v1/toolbox"))
    for h in d.call("GET", "/v1/harnesses"):
        row(h["name"], h, h.get("version", "-"))
    for a in d.call("GET", "/v1/addons"):
        if a.get("image"):
            row(f"addon:{a['name']}", a, a.get("version", "-"))
    row("network-filter", d.call("GET", "/v1/network-filter"))
    table(rows)


def path(name: str) -> str:
    """API path of a harness or `addon:NAME`."""
    if name.startswith("addon:"):
        return f"addons/{name.removeprefix('addon:')}"
    return f"harnesses/{name}"


def rebuild(d: Daemon, target: str) -> int:
    own = target in ("toolbox", "network-filter")
    return watch(d, d.call("POST", f"/v1/{target if own else path(target)}/rebuild"))


def watch(d: Daemon, build: Any) -> int:
    """Stream a started build's log to its end (Ctrl-C cancels it); 0 when it succeeded."""
    try:
        build = follow(d, build["id"])
    except KeyboardInterrupt:
        print("\ncancelling…", file=sys.stderr)
        build = d.call("POST", f"/v1/builds/{build['id']}/cancel")
    for name, version in build.get("versions", {}).items():
        print(f"{name}: {version}")
    error = f" ({build['error']})" if build.get("error") else ""
    print(f"build {build['id']}: {build['state']}{error}")
    return 0 if build["state"] == "succeeded" else 1


def follow(d: Daemon, build_id: str) -> Any:
    """Print the log as it grows; return the build once it has ended."""
    offset = 0
    while True:
        chunk = d.call("GET", f"/v1/builds/{build_id}/log?offset={offset}")
        sys.stdout.write(chunk["text"])
        sys.stdout.flush()
        offset = chunk["nextOffset"]
        if chunk["complete"]:
            return d.call("GET", f"/v1/builds/{build_id}")
        if not chunk["text"]:
            time.sleep(1)
