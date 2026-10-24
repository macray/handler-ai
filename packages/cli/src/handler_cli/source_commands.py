"""`handler source …` — sources (contract D.26): git repositories Handler reads to offer apps,
agents and addons. The official one is Handler's; one you add is yours to trust: Handler does not
check what is in it.

handler source list                 each source, when it was read, and what it offers (installed,
                                    an update)
handler source add URL [--yes]      add a git repository (https://), read first: it must be a
                                    source (a handler-source.toml at its root); asks first
handler source refresh [ID]         read it again (all of them without ID)
handler source rm ID                remove one you added (what you installed from it stays)

Install what one offers with `handler app add NAME --from ID`, `handler addon add NAME --from ID`
or `handler project import-agents NAME --from ID` (ID: "official" for Handler's).
"""

import argparse
import sys
from typing import Any

from .client import Daemon
from .output import table

TRUST = (
    "Handler does not check what is in a source you add: what you install from it runs on this "
    "computer, within what its install page shows. Add only a source you trust."
)


def add_parser(sub: Any) -> None:
    source = sub.add_parser("source", help="where apps, agents and addons come from",
                            description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    s = source.add_subparsers(dest="source_cmd", required=True)
    s.add_parser("list")
    add = s.add_parser("add")
    add.add_argument("url")
    add.add_argument("--yes", action="store_true", help="add it without asking")
    s.add_parser("refresh").add_argument("id", nargs="?")
    s.add_parser("rm").add_argument("id")


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.source_cmd == "add":
        print(TRUST)
        if not args.yes:
            if not sys.stdin.isatty():
                print("not added: run again with --yes to add it")
                return 1
            if input(f"\nAdd {args.url}? [y/N] ").strip().lower() not in ("y", "yes"):
                return 1
        show([d.call("POST", "/v1/sources", {"url": args.url}, timeout=120)])
        return 0
    if args.source_cmd == "rm":
        d.call("DELETE", f"/v1/sources/{args.id}")
        print(f"removed {args.id}")
        return 0
    if args.source_cmd == "refresh":
        ids = [args.id] if args.id else [s["id"] for s in d.call("GET", "/v1/sources")]
        show([d.call("POST", f"/v1/sources/{i}/refresh", timeout=120) for i in ids])
        return 0
    show(d.call("GET", "/v1/sources", timeout=120))
    return 0


def show(sources: list[dict[str, Any]]) -> None:
    for source in sources:
        who = "Handler's" if source.get("official") else "added by you"
        read = (
            f"read {source['fetchedAt'][:16].replace('T', ' ')}"
            if source.get("fetchedAt")
            else "never read"
        )
        print(f"{source['id']} · {source['url']} · {who} · {read}")
        if source.get("error"):
            print(f"  error: {source['error']}")
        rows = [["  KIND", "NAME", "VERSION", "STATE", "DESCRIPTION"]]
        for item in source.get("items", []):
            if item.get("error"):
                state = "not offered: " + item["error"]
            elif item.get("update"):
                state = "update"
            else:
                state = "installed" if item.get("installed") else "-"
            rows.append(
                [
                    f"  {item['kind']}",
                    item["name"],
                    item.get("version") or "-",
                    state[:80],
                    (item.get("description") or "")[:60],
                ]
            )
        if len(rows) > 1:
            table(rows)
