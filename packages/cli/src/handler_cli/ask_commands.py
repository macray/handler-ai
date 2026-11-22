"""`handler ask "…"` — Ask (D.24): say what you want, in your words; Handler picks which of your
apps does it (one of what you can ask them), runs it and says how it went. When it needs to know
more, it asks you (in a terminal: answer, or Enter to stop). An app's job that takes longer is
waited for, its answer also in your inbox. Ask needs its router, set up once in the web UI's Ask
page (it needs a model on a provider).

By voice, `--listen`: what you say is written down by your speech model (Settings → Expert → Voice), then
asked the same way; `--toggle` is for a key (a Stream Deck): press to start, press to stop, and how
it went is a sound and a notification (listen.py).

`--history`: what you asked lately, from anywhere (the web UI, a phone, here, a key), where it
went and how it ended: Ask's history, also on Chat's Ask tab."""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import listen
from .client import Daemon

WAIT = 120.0  # a job's action waited for, then left to the inbox


def add_parser(sub: Any) -> None:
    p = sub.add_parser(
        "ask", help="say what you want: Handler picks the app that does it", description=__doc__
    )
    p.add_argument("words", nargs="*", help="what you want, in your words")
    p.add_argument(
        "--listen", action="store_true", help="say it: records until Enter, then asks what it heard"
    )
    p.add_argument(
        "--toggle",
        action="store_true",
        help="with --listen, for a key: a press starts, the next stops; the outcome is a sound "
        "and a notification; a question back: the next press answers it",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="with --listen: what this computer will use to record, and what is missing",
    )
    p.add_argument(
        "--history",
        action="store_true",
        help="what you asked lately, from anywhere, where it went and how it ended",
    )


def dispatch(args: argparse.Namespace) -> int:
    if args.history:
        if args.words or args.listen:
            raise SystemExit("handler ask: --history lists what you asked: nothing else with it")
        return history(Daemon())
    if args.listen:
        if args.words:
            raise SystemExit("handler ask: --listen hears what you say: no words with it")
        return listen.run(toggle=args.toggle, check=args.check)
    if args.toggle or args.check:
        raise SystemExit("handler ask: --toggle and --check go with --listen")
    if not args.words:
        raise SystemExit("handler ask: what do you want? (or --listen to say it)")
    return answered(Daemon(), [{"who": "you", "text": " ".join(args.words)}])


def answered(daemon: Daemon, turns: list[dict[str, str]], spoken: bool = False) -> int:
    """Ask until it is done: a pick runs, nothing fits, or its question is answered here."""
    while True:
        body = {"turns": turns, "timezone": local_zone(), "via": "cli", "spoken": spoken}
        answer = daemon.call("POST", "/v1/ask", body, timeout=180)
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


OUTCOME = {
    "done": "✓",
    "attention": "!",
    "failed": "✕",
    "running": "…",
    "question": "?",
    "none": "✕ no app does that:",
}
VIA = {"web": "web", "phone": "phone", "cli": "terminal", "key": "key"}


def history(daemon: Daemon, limit: int = 20) -> int:
    """The last asks, newest first: when, from where, what was said, where it went, how it ended."""
    kept = daemon.call("GET", "/v1/ask/history")
    if not kept["keep"]:
        print("Ask's history is off (Chat → Ask, in the web UI)")
        return 0
    if not kept["asks"]:
        print("nothing asked yet")
        return 0
    for a in kept["asks"][:limit]:
        at = f"{datetime.fromisoformat(a['at']).astimezone():%Y-%m-%d %H:%M}"
        said = " / ".join(t["text"] for t in a["turns"] if t["who"] == "you") or "(nothing heard)"
        print(f"{at}  {VIA[a['via']]:<8}  “{said}”")
        answer = a.get("answer") or {}
        where = f"→ {answer['app']} · {answer['action']}  " if answer.get("app") else ""
        print(f"{'':16}    {where}{OUTCOME[a['outcome']]} {a['summary']}")
    return 0


def told(daemon: Daemon, answer: dict[str, Any]) -> int:
    """The pick, then how it went: at once, or once its job's run ends."""
    why = f"  ({answer['why']})" if answer.get("why") else ""
    print(f"→ {answer['app']} · {answer['action']}{why}")
    run = answer["run"]
    deadline = time.monotonic() + WAIT
    if run["state"] == "running":
        print("its job is on it…")
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
