"""`handler ask "…"` — Ask (D.24): say what you want, in your words; Handler picks which of your
apps does it (one of what you can ask them), runs it and says how it went. When it needs to know
more, it asks you (in a terminal: answer, or Enter to stop). An app's agent that takes longer is
waited for, its answer also in your inbox. Ask needs its router, set up once in the web UI's Ask
page (it needs a model on a provider)."""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from .client import Daemon

WAIT = 120.0  # an agent's ask waited for, then left to the inbox


def add_parser(sub: Any) -> None:
    p = sub.add_parser(
        "ask", help="say what you want: Handler picks the app that does it", description=__doc__
    )
    p.add_argument("words", nargs="+", help="what you want, in your words")


def dispatch(args: argparse.Namespace) -> int:
    daemon = Daemon()
    turns: list[dict[str, str]] = [{"who": "you", "text": " ".join(args.words)}]
    while True:
        answer = daemon.call(
            "POST", "/v1/ask", {"turns": turns, "timezone": local_zone()}, timeout=180
        )
        if answer["kind"] == "pick":
            return told(daemon, answer)
        if answer["kind"] == "none":
            print(answer["summary"])
            if answer.get("actions"):
                print("\nwhat you can ask:")
                for o in answer["actions"]:
                    print(f"  {o['app']} · {o['description']}")
            return 1
        print(answer["question"])
        reply = input("> ").strip() if sys.stdin.isatty() else ""
        if not reply:
            return 1
        turns += [{"who": "handler", "text": answer["question"]}, {"who": "you", "text": reply}]


def told(daemon: Daemon, answer: dict[str, Any]) -> int:
    """The pick, then how it went: at once, or once its agent's run ends."""
    why = f"  ({answer['why']})" if answer.get("why") else ""
    print(f"→ {answer['app']} · {answer['action']}{why}")
    run = answer["run"]
    deadline = time.monotonic() + WAIT
    if run["state"] == "running":
        print("its agent is on it…")
    while run["state"] == "running" and time.monotonic() < deadline:
        time.sleep(1)
        run = daemon.call(
            "GET", f"/v1/apps/{answer['app']}/actions/{answer['action']}/runs/{run['runId']}"
        )
    if run["state"] == "running":
        print("still running: its answer will be in your inbox (handler inbox)")
        return 0
    if run["state"] == "failed":
        print(f"failed: {run.get('error') or 'no reason given'}")
        return 1
    print(run["result"]["summary"])
    return 0 if run["result"]["status"] != "failed" else 1


def local_zone() -> str | None:
    """This computer's time zone (IANA): TZ, else what /etc/localtime points to."""
    if zone := os.environ.get("TZ", "").lstrip(":"):
        return zone
    try:
        target = Path("/etc/localtime").resolve()
    except OSError:
        return None
    parts = target.parts
    return "/".join(parts[parts.index("zoneinfo") + 1 :]) if "zoneinfo" in parts else None
