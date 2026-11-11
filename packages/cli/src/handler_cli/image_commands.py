"""`handler image …` — the images agents run in: the toolbox (the system every agent gets), one per
harness and per tool on top of it, and the network filter. Built locally, through handlerd (D.4,
G.4), like the web UI.

    handler image list                 every image: built or not, the harness's version, when built
    handler image rebuild NAME         build an agent program's image from the files on disk (its
                                       latest release; also its first build), check it, then switch
                                       agents to it
    handler image rebuild tool:NAME    same for a tool's image (also its first build)
    handler image rebuild toolbox [--update]
                                       the toolbox with what changed in it (`handler toolbox`;
                                       --update: system updates, a large download), then every
                                       agent program and tool already built on top of it: all
                                       switch, or none
    handler image rebuild network-filter
                                       the network filter: what checks where agents connect and adds
                                       your secrets to their requests (handlerd builds it when it is
                                       missing)

A build prints one line per image, with a time estimate; its full log goes to a file it names
(--verbose: the log on the terminal instead). Ctrl-C during a rebuild cancels it: nothing
switches. Running sessions keep the image they started on.
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from .client import Daemon
from .output import table


def add_parser(sub: Any) -> None:
    image = sub.add_parser("image", help="images", description=__doc__,
                           formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    i = image.add_subparsers(dest="image_cmd", required=True)
    i.add_parser("list")
    r = i.add_parser("rebuild")
    r.add_argument("target", help="a harness name, 'toolbox', 'network-filter', or 'tool:NAME'")
    r.add_argument("--update", action="store_true", help="the toolbox: system updates")
    verbose_flag(r)


def verbose_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--verbose", action="store_true", help="the build's full log here, as it is written"
    )


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.image_cmd == "list":
        print_images(d)
        return 0
    if args.update and args.target != "toolbox":
        print("--update is the toolbox's", file=sys.stderr)
        return 2
    return rebuild(d, args.target, update=args.update, verbose=args.verbose)


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
            row(f"tool:{a['name']}", a, a.get("version", "-"))
    row("network-filter", d.call("GET", "/v1/network-filter"))
    table(rows)


def path(name: str) -> str:
    """API path of a harness or `tool:NAME` (`addon:NAME` to the API, D.4)."""
    if name.startswith("tool:"):
        return f"addons/{name.removeprefix('tool:')}"
    return f"harnesses/{name}"


def rebuild(d: Daemon, target: str, update: bool = False, verbose: bool = False) -> int:
    own = target in ("toolbox", "network-filter")
    body = {"update": True} if update else None
    build = d.call("POST", f"/v1/{target if own else path(target)}/rebuild", body)
    return watch(d, build, verbose=verbose)


# a stage's time when nothing was measured here: a fresh build on an ordinary network (the toolbox
# and Claude Code's image make about 1 GB: a minute on a fast one, a quarter of an hour on a slow one)
ESTIMATES = {"toolbox": 3, "network filter": 1}  # minutes
PROGRAM_ESTIMATE = 2  # an agent program's or a tool's image


class Stages:
    """The images of one or more builds, numbered across them: "toolbox 1/2 · ~3 min"."""

    def __init__(self, d: Daemon) -> None:
        self.products = {h["name"]: h["product"] for h in d.call("GET", "/v1/harnesses")}
        self.done = 0  # images of the builds watched before
        self.after = 0  # images of the builds to come

    def images(self, build: Any) -> list[str]:
        """What `build` builds, in its order (D.4: the toolbox first, then what is on it)."""
        target = build["target"]
        if target == "toolbox":
            return [
                "toolbox",
                *build.get("harnesses", []),
                *(f"addon:{a}" for a in build.get("addons", [])),
            ]
        return [target]

    def name(self, image: str) -> str:
        if image.startswith("addon:"):  # the API's target (D.4)
            return f"tool {image.removeprefix('addon:')}"
        return {"network-filter": "network filter"}.get(image) or self.products.get(image, image)

    def line(self, build: Any, image: str) -> str:
        images = self.images(build)
        n = self.done + images.index(image) + 1
        total = self.done + len(images) + self.after
        name = self.name(image)
        minutes = ESTIMATES.get(name, PROGRAM_ESTIMATE)
        return f"{name} {n}/{total} · ~{minutes} min" if total > 1 else f"{name} · ~{minutes} min"

    def of(self, build: Any) -> str | None:
        """The image the build's stage works on ("build codex", "check addon:x"), None between."""
        stage = build.get("stage") or ""
        verb, _, image = stage.partition(" ")
        if verb not in ("build", "update", "check") or not image:
            return None
        image = image.replace(" ", "-")  # "build network filter"
        return image if image in self.images(build) else None


def log_file(build_id: str) -> Path:
    """Where a quiet build's full log is written: in Handler's cache folder."""
    xdg = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    folder = Path(os.environ.get("HANDLER_CACHE_DIR", xdg / "handler-ai")) / "build-logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{build_id}.log"


def watch(d: Daemon, build: Any, verbose: bool = False, stages: Stages | None = None) -> int:
    """Follow a started build to its end (Ctrl-C cancels it): its log streamed (`verbose`), else
    one line per image and the log in a file; 0 when it succeeded."""
    began = time.monotonic()
    stages = stages or Stages(d)
    log = None if verbose else log_file(build["id"])
    if log is not None:
        print(f"The full log: {log}")
    try:
        build = follow(d, build["id"], log, stages)
    except KeyboardInterrupt:
        print("\ncancelling…", file=sys.stderr)
        build = d.call("POST", f"/v1/builds/{build['id']}/cancel")
    stages.done += len(stages.images(build))
    for name, version in build.get("versions", {}).items():
        print(f"{name}: {version}")
    if build["state"] == "succeeded":
        if verbose:
            print(f"build {build['id']}: succeeded")
        else:
            seconds = round(time.monotonic() - began)
            print(f"  done in {seconds // 60}:{seconds % 60:02d}")
        return 0
    error = f" ({build['error']})" if build.get("error") else ""
    if log is not None and build["state"] == "failed":
        lines = log.read_text(errors="replace").splitlines()[-20:]
        print("\n".join(f"  {line}" for line in lines))
    print(f"build {build['id']}: {build['state']}{error}")
    if log is not None:
        print(f"The full log: {log}")
    return 1


def follow(d: Daemon, build_id: str, log: Path | None = None, stages: Stages | None = None) -> Any:
    """The log as it grows, printed or written to `log` (then a line per image of `stages`);
    return the build once it has ended."""
    offset, shown = 0, None
    out = log.open("w") if log is not None else None
    try:
        while True:
            chunk = d.call("GET", f"/v1/builds/{build_id}/log?offset={offset}")
            if out is not None:
                out.write(chunk["text"])
                out.flush()
            else:
                sys.stdout.write(chunk["text"])
                sys.stdout.flush()
            offset = chunk["nextOffset"]
            if chunk["complete"]:
                return d.call("GET", f"/v1/builds/{build_id}")
            if out is not None and stages is not None:
                image = stages.of(build := d.call("GET", f"/v1/builds/{build_id}"))
                if image is not None and image != shown:
                    print(stages.line(build, image), flush=True)
                    shown = image
            if not chunk["text"]:
                time.sleep(1)
    finally:
        if out is not None:
            out.close()
