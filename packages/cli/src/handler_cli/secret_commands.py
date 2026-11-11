"""`handler secret …` — handler's secret store (contract D.14). A value is named by a path after
what owns it (`providers/openrouter/apiKey`) and referenced from an account, a provider or a connection
with `{ secret = "<path>" }`. Values are written, never read back. An app's secrets are set with
`handler app secret`.

handler secret list                  the secrets handler uses (in its store or kept elsewhere):
                                     where each comes from, what it belongs to, and whether agents
                                     can read it (else handler adds it to their requests to its
                                     hosts)
handler secret set PATH [--description TEXT]
                                     set a value (asked for, or read from stdin)
handler secret rm PATH               forget PATH and everything under it (refused while referenced)
"""

import argparse
import getpass
import sys
from typing import Any

from .client import Daemon
from .output import table


def add_parser(sub: Any) -> None:
    secret = sub.add_parser("secret", help="the secret store", description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    s = secret.add_subparsers(dest="secret_cmd", required=True)
    s.add_parser("list")
    put = s.add_parser("set")
    put.add_argument("path")
    put.add_argument("--description")
    s.add_parser("rm").add_argument("path")


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.secret_cmd == "list":
        rows = [["PATH", "FROM", "USED BY", "AGENTS", "UPDATED"]]
        for s in d.call("GET", "/v1/secrets"):
            source = s["source"] if s["hasValue"] else f"{s['source']} (not set)"
            used = ", ".join(s["usedBy"]) or "nothing"
            rows.append([s["path"], source, used, _given(s), (s.get("updatedAt") or "")[:16]])
        table(rows) if len(rows) > 1 else print("no secret")
        return 0
    if args.secret_cmd == "set":
        prompt = f"{args.path}: "
        value = getpass.getpass(prompt) if sys.stdin.isatty() else sys.stdin.readline()
        body = {"value": value.strip(), "description": args.description}
        s = d.call("PUT", f"/v1/secrets/{args.path}", body)
        print(f"{s['path']}: set (used by {', '.join(s['usedBy']) or 'nothing yet'})")
        return 0
    d.call("DELETE", f"/v1/secrets/{args.path}")
    print(f"{args.path}: removed")
    return 0


def _given(s: dict[str, Any]) -> str:
    """What agents get (E3): a stand-in handler swaps for the value on its way to its hosts, or the
    value itself."""
    if s.get("visible"):
        return f"can read it: {s['visible']}"
    if s["hosts"]:
        return "never see it, handler adds it for " + ", ".join(s["hosts"])
    return "-"
