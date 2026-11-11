"""`handler inbox` — what handler told you: your apps' notifications, your agents' results (run by
an automation or by one of your apps), the runs and plans that failed, and the hosts the network
filter refused while you were away, newest first (the web UI's Inbox, where you allow them or keep
them blocked). OPENS: the app a message opens (`handler app open NAME`)."""

import argparse
from typing import Any

from .automation_commands import when_at
from .client import Daemon
from .output import one_line, refused_hosts, table


def add_parser(sub: Any) -> None:
    sub.add_parser("inbox", help="what handler told you", description=__doc__)


def dispatch(_: argparse.Namespace) -> int:
    messages = Daemon().call("GET", "/v1/inbox")
    if not messages:
        print("nothing yet")
        return 0
    rows = [["AT", "FROM", "STATUS", "TITLE", "SUMMARY", "OPENS"]]
    for m in messages:
        source = f"{m['source']} {m['name']}"
        unread = "" if m.get("read") else "• "
        rows.append([
            unread + when_at(m["at"]),
            source,
            m.get("status") or "-",
            one_line(m["title"], 40),
            one_line(m.get("summary") or "", 70),
            m.get("app") or "-",
        ])  # fmt: skip
    table(rows)
    if asking := [m for m in messages if any(not h.get("decision") for h in m.get("refused", []))]:
        print("\nhosts refused, to allow or keep blocked (the web UI's Inbox):")
        for m in asking:
            print(f"  {one_line(m['title'], 60)}: {refused_hosts(m['refused'])}")
    if any(m.get("app") for m in messages):
        print("\nopen an app: handler app open NAME")
    return 0
