"""`handler tool …` — tools (contract G.5): programs for the agent's sandbox (Playwright's browser,
the Shopify CLI) with the hosts, secrets and skills they need. An agent gets one by its name
(`--tool NAME`), with a connection filling its settings when it has some (`--tool
NAME=CONNECTION`, `handler connection list`); a project gives some to all its agents.

handler tool list                    the installed tools: where from, commands, whether ready, the
                                     settings and secrets they need, errors, updates
handler tool add NAME|FOLDER|URL [--from SOURCE] [--yes]
                                     what it brings (its hosts, secrets, commands, MCP server,
                                     skills, what it adds to the toolbox), then, once you agree,
                                     install it and build its image (the toolbox first, with what
                                     it adds): NAME from a source (`handler source list`; the
                                     official one without --from), a FOLDER, an https:// .tar.gz
                                     archive
handler tool rm NAME                 an installed tool (refused while an agent, a project or a
                                     connection uses it)
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from . import image_commands
from .client import Daemon
from .output import table


def add_parser(sub: Any) -> None:
    tool = sub.add_parser("tool", help="install and remove tools", description=__doc__,
                          formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    s = tool.add_subparsers(dest="tool_cmd", required=True)
    s.add_parser("list")
    add = s.add_parser("add")
    add.add_argument("source", metavar="NAME|FOLDER|URL")
    add.add_argument("--from", dest="source_id", metavar="SOURCE", help="the source offering NAME")
    add.add_argument("--yes", action="store_true", help="install without asking")
    image_commands.verbose_flag(add)
    s.add_parser("rm").add_argument("name")


def source(arg: str, source_id: str | None) -> str:
    """What the API calls the source: source:SOURCE/NAME (D.26), an absolute folder path, or the
    URL."""
    if source_id is not None:
        return f"source:{source_id}/{arg}"
    if arg.startswith(("https://", "http://")):
        return arg
    if "/" in arg or arg.startswith(".") or Path(arg).is_dir():
        return str(Path(arg).resolve())
    return f"source:official/{arg}"


def describe(p: dict[str, Any]) -> str:
    """The trust screen, as text: everything the tool would bring."""
    lines = [f"{p['name']}: {p.get('description') or ''}".rstrip(": "), f"  from    {p['source']}"]
    if replaces := p.get("replaces"):
        lines.append(f"  replaces the {replaces} tool '{p['name']}'")
    rows = [
        ("hosts", ", ".join(p.get("egress", []))),
        ("secrets", ", ".join(s["name"] for s in p.get("secretSlots", []))),
        ("settings", ", ".join(s["name"] for s in p.get("settings", []))),
        ("env", ", ".join(p.get("env", []))),
        ("commands", ", ".join(p.get("commands", []))),
        ("MCP", " ".join(p.get("mcp") or [])),
        ("skills", ", ".join(p.get("skills", []))),
    ]
    lines += [f"  {k:<8}{v}" for k, v in rows if v]
    if image := p.get("image"):
        lines.append(f"  image   {image}: its Containerfile runs code on this machine when built")
    toolbox = p.get("toolbox", {})
    if has := toolbox.get("has"):
        lines.append(f"  uses    {', '.join(has)} (from the toolbox)")
    for add in toolbox.get("adds", []):
        where = (
            f"from {add['source'].removeprefix('source:')}" if add.get("source") else "installed"
        )
        lines.append(
            f"  adds    {add['name']} to the toolbox, for {', '.join(add.get('provides', []))} "
            f"({where}): its script runs as root when the toolbox is built, every agent gets it"
        )
    if lacking := toolbox.get("lacking"):
        lines.append(
            f"  lacks   {', '.join(lacking)}: no system package gives it; add it to your own lines "
            "(handler toolbox lines), then apply them. Until then it is not ready"
        )
    return "\n".join(lines)


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.tool_cmd == "list":
        print_tools(d)
        return 0
    if args.tool_cmd == "rm":
        d.call("DELETE", f"/v1/addons/{args.name}")
        print(f"removed {args.name}")
        return 0
    seen = d.call("POST", "/v1/addons/preview", {"source": source(args.source, args.source_id)})
    print(describe(seen))
    if not args.yes:
        if not sys.stdin.isatty():
            print("not installed: run again with --yes to install it")
            return 1
        if input("\nInstall it? [y/N] ").strip().lower() not in ("y", "yes"):
            return 1
    adds = [a["name"] for a in seen.get("toolbox", {}).get("adds", [])]
    body = {"source": seen["source"], "digest": seen["digest"], "toolboxAdds": adds}
    installed = d.call("POST", "/v1/addons/install", body)
    print(f"installed {installed['addon']['name']} in {installed['addon']['directory']}")
    if build := installed.get("build"):
        if build["target"] == "toolbox":
            print(f"the toolbox is rebuilt with {', '.join(adds)}; its tools are prepared after it")
        return image_commands.watch(d, build, args.verbose)
    if adds:  # another build is running: the toolbox's comes after it
        print(f"the toolbox is rebuilt with {', '.join(adds)} after the build running now")
    elif state := installed["addon"].get("stateDetail"):
        print(f"not ready: {state}")
    elif seen.get("image"):
        print(
            "another build is running: build it later with "
            f"`handler image rebuild tool:{seen['name']}`"
        )
    return 0


def print_tools(d: Daemon) -> None:
    rows = [["NAME", "FROM", "COMMANDS", "STATE", "VERSION", "BUILT", "SLOTS", "ERROR"]]
    for a in d.call("GET", "/v1/addons"):
        if a.get("image"):
            version = a.get("version", "-") if a["imagePresent"] else "not built"
        else:
            version = "(no image)"
        slots = [
            *(s["name"] for s in a.get("settings", [])),
            *(f"{s['name']} (secret)" for s in a.get("secretSlots", [])),
        ]
        origin = "built-in" if a.get("builtin") else a.get("source", "yours")
        if a.get("updateAvailable"):
            source_id = a["source"].removeprefix("source:").split("/")[0]
            origin += f" (update: handler tool add {a['name']} --from {source_id})"
        rows.append(
            [
                a["name"],
                origin,
                ", ".join(a.get("commands", [])) or "-",
                a.get("state", "-"),
                version,
                a.get("builtAt", "-")[:16].replace("T", " "),
                ", ".join(slots) or "-",
                (a.get("error") or a.get("stateDetail") or "")[:80],
            ]
        )
    table(rows)
