"""`handler schema …` — the Library's schemas (contract D.29): each one kind of document an agent
reads or writes in its notes folders, found by its `$id` (`contacts@1`) alone. An agent gets those
it uses (`--schema ID`), read-only.

handler schema list                  the Library's schemas, and why one cannot be used
handler schema show ID               one schema's file
handler schema add FILE [--replace]  a schema file into the Library, under its `$id`; one of that
                                     `$id` already there and different is kept unless --replace
handler schema rm ID                 remove one (refused while an agent uses it)
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from .client import ClientError, Daemon
from .output import table


def add_parser(sub: Any) -> None:
    schema = sub.add_parser("schema", help="the schemas of structured notes", description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    s = schema.add_subparsers(dest="schema_cmd", required=True)
    s.add_parser("list")
    s.add_parser("show").add_argument("id")
    add = s.add_parser("add")
    add.add_argument("file", type=Path)
    add.add_argument(
        "--replace", action="store_true", help="replace one of that `$id` that differs"
    )
    s.add_parser("rm").add_argument("id")


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.schema_cmd == "list":
        rows = [["SCHEMA", "TITLE", "PROBLEM"]]
        for s in d.call("GET", "/v1/schemas"):
            rows.append([s["id"], s.get("title") or "", s.get("error") or ""])
        table(rows) if len(rows) > 1 else print("no schema (handler schema add FILE)")
        return 0
    if args.schema_cmd == "show":
        sys.stdout.write(d.call("GET", f"/v1/schemas/{args.id}")["content"])
        return 0
    if args.schema_cmd == "add":
        try:
            content = args.file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise ClientError(f"{args.file}: {e}") from None
        s = d.call("POST", "/v1/schemas", {"content": content, "replace": args.replace})
        print(f"{s['id']}: in the Library")
        return 0
    d.call("DELETE", f"/v1/schemas/{args.id}")
    print(f"{args.id}: removed")
    return 0
