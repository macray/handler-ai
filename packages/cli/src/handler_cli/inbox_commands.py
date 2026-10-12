"""`handler inbox` — what handler told you: your apps' notifications, your automations' results and
failures, newest first (the web UI's Inbox)."""

import argparse
from typing import Any

from .automation_commands import when_at
from .client import Daemon
from .output import one_line, table


def add_parser(sub: Any) -> None:
    sub.add_parser("inbox", help="what handler told you", description=__doc__)


def dispatch(_: argparse.Namespace) -> int:
    messages = Daemon().call("GET", "/v1/inbox")
    if not messages:
        print("nothing yet")
        return 0
    rows = [["AT", "FROM", "STATUS", "TITLE", "SUMMARY"]]
    for m in messages:
        source = f"{m['source']} {m['name']}"
        unread = "" if m.get("read") else "• "
        rows.append([
            unread + when_at(m["at"]),
            source,
            m.get("status") or "-",
            one_line(m["title"], 40),
            one_line(m.get("summary") or "", 70),
        ])  # fmt: skip
    table(rows)
    return 0
