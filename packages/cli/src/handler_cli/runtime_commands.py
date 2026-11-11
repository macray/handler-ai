"""`handler runtime …` — the sandbox runtime handlerd runs agents with (D.2, A.8): one of those
installed on this computer (a `handler-sandbox-<name>` executable), unless another was chosen:
podman on Linux, apple on macOS (`handler setup` asks there).

    handler runtime list         the runtimes installed, the one in use marked, and what it gives
    handler runtime use NAME     use another from now on: refused while agents, apps or an image
                                 build run; its images are its own (build them again there)
"""

import argparse
from typing import Any

from handler_contracts import ABILITIES

from .client import Daemon
from .output import table


def add_parser(sub: Any) -> None:
    runtime = sub.add_parser("runtime", help="the sandbox runtime", description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    r = runtime.add_subparsers(dest="runtime_cmd", required=True)
    r.add_parser("list")
    r.add_parser("use").add_argument("name", help="a runtime `handler runtime list` shows")


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.runtime_cmd == "use":
        check = d.call("PUT", "/v1/runtime", {"name": args.name})
        print(f"handlerd now uses {check['runtime']}")
        print_supports(check)
        return 0
    rows = [["RUNTIME", "IN USE"]]
    rows += [[r["name"], "yes" if r["current"] else ""] for r in d.call("GET", "/v1/runtimes")]
    table(rows)
    print_supports(d.call("GET", "/v1/runtime"))
    return 0


def not_given(supports: dict[str, Any]) -> str:
    """What a sandbox may need that this runtime lacks here (A.8), in the person's words."""
    missing = [words for a, words in ABILITIES.items() if a not in supports["abilities"]]
    return f"not on this computer: {', '.join(missing)}" if missing else "everything Handler offers"


def print_supports(check: dict[str, Any]) -> None:
    if supports := check.get("supports"):
        print(f"each sandbox is {supports['isolation']}")
        print(not_given(supports))
        if not supports["limits"]:
            print("memory and CPU limits: not applied on this computer (`handler setup` says why)")
    else:
        print("it cannot run sandboxes here:")
        for item in check["items"]:
            if item["required"] and not item["ok"]:
                print(f"  {item['name']}: {item['detail']}")
