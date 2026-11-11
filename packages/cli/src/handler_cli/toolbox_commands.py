"""`handler toolbox …` — the system every agent works in: Handler's base, the system packages you
turn on, your own lines (contract B.7). A change is applied by a toolbox build: the toolbox, then
every agent program and tool image already built on it, checked; all switch, or none.

    handler toolbox                  what it is made of: the system packages on and who needs
                                     each, what is needed from it and what gives it
    handler toolbox packages         the system packages you can turn on
    handler toolbox add PACKAGE…     turn system packages on (with those they need), then apply;
                                     each runs as root in the toolbox's build, and every agent
                                     gets what it installs
    handler toolbox rm PACKAGE…      turn them off (refused while one alone gives what is needed),
                                     then apply
    handler toolbox lines            edit your own lines (custom.containerfile) in $EDITOR; apply
                                     them with `handler image rebuild toolbox`

A build prints one line per image and writes its log to a file it names (--verbose: the log
here). Ctrl-C during a build cancels it: nothing switches.
"""

import argparse
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import image_commands
from .client import Daemon
from .output import table


def add_parser(sub: Any) -> None:
    toolbox = sub.add_parser("toolbox", help="the system every agent works in",
                             description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    t = toolbox.add_subparsers(dest="toolbox_cmd")
    t.add_parser("packages")
    for verb in ("add", "rm"):
        changes = t.add_parser(verb)
        changes.add_argument("packages", nargs="+", metavar="PACKAGE")
        image_commands.verbose_flag(changes)
    t.add_parser("lines")


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.toolbox_cmd is None:
        show(d)
        return 0
    if args.toolbox_cmd == "packages":
        rows = [["PACKAGE", "PROVIDES", "WHAT IT IS"]]
        for p in d.call("GET", "/v1/toolbox/system-packages"):
            mine = " (yours)" if not p["builtin"] else ""
            about = f"invalid: {p['error']}" if p.get("error") else p.get("description", "")
            for daemon in p.get("daemons", []):  # B.7
                where = " or ".join(daemon["abilities"])
                about += f"; starts {daemon['command']} in {where} sandboxes"
            rows.append([p["name"] + mine, ", ".join(p.get("provides", [])), about])
        table(rows)
        return 0
    if args.toolbox_cmd == "lines":
        return edit_lines(d)
    on = [p["name"] for p in d.call("GET", "/v1/toolbox")["systemPackages"]]
    if args.toolbox_cmd == "add":
        on += [p for p in args.packages if p not in on]
    else:
        on = [p for p in on if p not in args.packages]
    d.call("PUT", "/v1/toolbox/system-packages", {"systemPackages": on})
    return image_commands.rebuild(d, "toolbox", verbose=args.verbose)


def who(entries: list[str], agents: dict[str, str]) -> str:
    """`neededBy` in words: Handler, a harness by its name, an agent by its name."""
    words = []
    for entry in entries:
        kind, _, name = entry.partition(":")
        agent = f"agent {agents.get(name, name)}"
        words.append({"handler": "Handler", "agent": agent}.get(kind, name))
    return ", ".join(words)


def show(d: Daemon) -> None:
    info = d.call("GET", "/v1/toolbox")
    agents = {a["id"]: a.get("name") or a["id"] for a in d.call("GET", "/v1/agents")}
    built = (info.get("builtAt") or "")[:16].replace("T", " ")
    print(f"toolbox: {info.get('distro') or '?'}, {'built ' + built if built else 'not built yet'}")
    print(f"yours:   {info['directory']}")
    if info.get("problem"):
        print(f"problem: {info['problem']}", file=sys.stderr)
    print()
    rows = [["SYSTEM PACKAGE", "VERSION", "NEEDED BY"]]
    for p in info["systemPackages"]:
        version = str(p.get("version") or "?")
        if p.get("builtVersion") != p.get("version"):
            version += " (not applied yet)" if info["imagePresent"] else ""
        rows.append([p["name"], version, who(p.get("neededBy", []), agents) or "-"])
    table(rows)
    print()
    rows = [["NEEDED", "BY", "GIVEN BY"]]
    for n in info["needs"]:
        given = n.get("providedBy") or "nothing: missing"
        given = {"lines": "your lines"}.get(given, given.removeprefix("system-package:"))
        rows.append([" or ".join(n["commands"]), who(n["neededBy"], agents), given])
    table(rows)


def edit_lines(d: Daemon) -> int:
    before = d.call("GET", "/v1/toolbox/lines")["content"]
    editor = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "custom.containerfile"
        path.write_text(before)
        if subprocess.run([*editor, str(path)], check=False).returncode != 0:
            print("editor failed: nothing saved", file=sys.stderr)
            return 1
        after = path.read_text()
    if after == before:
        print("unchanged")
        return 0
    d.call("PUT", "/v1/toolbox/lines", {"content": after})
    print("saved; apply them with `handler image rebuild toolbox`")
    return 0
