"""`handler addon …` — addons (contract G.5): a tool for the agent's sandbox (Playwright's browser,
the Shopify CLI) with the hosts, secrets and skills it needs. An agent gets one through a binding
(`handler binding list`).

handler addon list                   the installed addons: where from, commands, image, the settings
                                     and secrets they need, errors, updates
handler addon catalog                the addons handler ships, installed or not
handler addon add NAME|FOLDER|URL [--yes]
                                     what it brings (its hosts, secrets, commands, MCP server,
                                     skills), then, once you agree, install it and build its image:
                                     NAME from the catalog, a FOLDER, an https:// .tar.gz archive
handler addon rm NAME                an installed addon (refused while a binding uses it)
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from . import image_commands
from .client import Daemon
from .output import table


def add_parser(sub: Any) -> None:
    addon = sub.add_parser("addon", help="install and remove addons", description=__doc__,
                           formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    s = addon.add_subparsers(dest="addon_cmd", required=True)
    s.add_parser("list")
    s.add_parser("catalog")
    add = s.add_parser("add")
    add.add_argument("source", metavar="NAME|FOLDER|URL")
    add.add_argument("--yes", action="store_true", help="install without asking")
    s.add_parser("rm").add_argument("name")


def source(arg: str) -> str:
    """What the API calls the source: catalog:NAME, an absolute folder path, or the URL."""
    if arg.startswith(("https://", "http://")):
        return arg
    if "/" in arg or arg.startswith(".") or Path(arg).is_dir():
        return str(Path(arg).resolve())
    return f"catalog:{arg}"


def describe(p: dict[str, Any]) -> str:
    """The trust screen, as text: everything the addon would bring."""
    lines = [f"{p['name']}: {p.get('description') or ''}".rstrip(": "), f"  from    {p['source']}"]
    if replaces := p.get("replaces"):
        lines.append(f"  replaces the {replaces} addon '{p['name']}'")
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
    return "\n".join(lines)


def dispatch(args: argparse.Namespace) -> int:  # noqa: PLR0911 — one branch per subcommand
    d = Daemon()
    if args.addon_cmd == "list":
        print_addons(d)
        return 0
    if args.addon_cmd == "catalog":
        rows = [["NAME", "INSTALLED", "DESCRIPTION"]]
        for e in d.call("GET", "/v1/addon-catalog"):
            rows.append([e["name"], "yes" if e["installed"] else "-", e.get("description", "")])
        table(rows)
        return 0
    if args.addon_cmd == "rm":
        d.call("DELETE", f"/v1/addons/{args.name}")
        print(f"removed {args.name}")
        return 0
    seen = d.call("POST", "/v1/addons/preview", {"source": source(args.source)})
    print(describe(seen))
    if not args.yes:
        if not sys.stdin.isatty():
            print("not installed: run again with --yes to install it")
            return 1
        if input("\nInstall it? [y/N] ").strip().lower() not in ("y", "yes"):
            return 1
    installed = d.call(
        "POST", "/v1/addons/install", {"source": seen["source"], "digest": seen["digest"]}
    )
    print(f"installed {installed['addon']['name']} in {installed['addon']['directory']}")
    if build := installed.get("build"):
        return image_commands.watch(d, build)
    if seen.get("image"):
        print(
            "another build is running: build it later with "
            f"`handler image rebuild addon:{seen['name']}`"
        )
    return 0


def print_addons(d: Daemon) -> None:
    rows = [["NAME", "FROM", "COMMANDS", "VERSION", "BUILT", "SLOTS", "ERROR"]]
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
            origin += " (update: handler addon add " + a["name"] + ")"
        rows.append(
            [
                a["name"],
                origin,
                ", ".join(a.get("commands", [])) or "-",
                version,
                a.get("builtAt", "-")[:16].replace("T", " "),
                ", ".join(slots) or "-",
                a.get("error", "")[:80],
            ]
        )
    table(rows)
