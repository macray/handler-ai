"""`handler plan …` — plans (docs/plans.md): long work in steps, written by the plan builder in a
draft Handler keeps (`d_…`, made with New plan in the web UI) or by an agent in its folder
(`plans/<name>.md`), which you review and approve; Handler then runs the steps one after another,
each a new session of an agent of the project, and stops at the first step not done.

handler plan check PATH|DRAFT    read a plan (a file of an agent's folder, or a draft): its steps,
                                 its problems
handler plan run PATH|DRAFT [--yes]  show its steps, ask, then approve it as read and run it
handler plan run ID --from N     run a plan again from step N (once you fixed what failed);
                                 --allow HOST first allows a host the network filter refused to it
handler plan list                every plan: its state, its agent, its steps done
handler plan show ID             its steps, their state and summary, their sessions
handler plan cancel ID           stop the step running; the plan stops
handler plan delete ID [--yes]   forget a plan that is not running (its sessions stay)
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

from handler_contracts import is_within

from .automation_commands import when_at
from .client import ClientError, Daemon
from .output import one_line, refused_hosts, table


def add_parser(sub: Any) -> None:
    plan = sub.add_parser("plan", help="plans: steps an agent wrote, run one after another",
                          description=__doc__,
                          formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    p = plan.add_subparsers(dest="plan_cmd", required=True)
    p.add_parser("check").add_argument("path", help="the plan file, or a draft's id")
    run = p.add_parser("run")
    run.add_argument("target", help="the plan file, or a draft's id; with --from, a plan's id")
    run.add_argument(
        "--from", dest="start", type=int, metavar="N", help="run plan ID again from step N"
    )
    run.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="HOST",
        help="with --from: allow this host refused to that step first (HOST:PORT; repeatable)",
    )
    run.add_argument("--yes", action="store_true", help="do not ask")
    p.add_parser("list")
    for name in ("show", "cancel"):
        p.add_parser(name).add_argument("id")
    rm = p.add_parser("delete")
    rm.add_argument("id")
    rm.add_argument("--yes", action="store_true", help="do not ask")


DRAFT = re.compile(r"^d_[0-9a-f]{16}$")


def where(d: Daemon, path: str) -> dict[str, str]:
    """The plan as the API names it: a draft by its id, else the file by an agent whose folder
    holds it, and its path there."""
    if DRAFT.fullmatch(path) and not Path(path).exists():
        return {"draftId": path}
    file = Path(path)
    absolute = Path(os.path.realpath(file.parent)) / file.name
    found = [
        a
        for a in d.call("GET", "/v1/agents")
        if a.get("scope") and is_within(str(absolute), a["scope"])
    ]
    if not found:
        raise ClientError(f"{path}: no agent of yours works in a folder holding it")
    agent = max(found, key=lambda a: len(a["scope"]))  # the deepest folder
    return {"agentId": agent["id"], "path": str(absolute.relative_to(agent["scope"]))}


def print_read(read: dict[str, Any]) -> None:
    print(f"Plan: {read.get('title') or '(no title)'}   ({read['path']})")
    limit = read["stepTimeoutSec"]
    print(f"Agent: {read.get('agent') or '-'} · each step at most {duration(limit)}")
    if read.get("context"):
        print(f"Context: {one_line(read['context'], 200)}")
    for step in read.get("steps") or []:
        print(f"\n  {step['n']}. {step['title']}")
        print(f"     Goal: {one_line(step['goal'], 200)}")
        print(f"     Done when: {one_line(step['doneWhen'], 200)}")
    if read.get("recommendation"):
        print(f"\nwarning: {read['recommendation']}")
    for problem in read.get("problems") or []:
        print(f"problem: {problem}")


def check(d: Daemon, args: argparse.Namespace) -> int:
    read = d.call("POST", "/v1/plans/read", where(d, args.path))
    print_read(read)
    return 1 if read.get("problems") else 0


def run(d: Daemon, args: argparse.Namespace) -> int:
    if args.allow and args.start is None:
        print(
            "error: --allow goes with --from: the step the hosts were refused to", file=sys.stderr
        )
        return 2
    if args.start is not None:
        body = {"from": args.start} | ({"allow": args.allow} if args.allow else {})
        plan = d.call("POST", f"/v1/plans/{args.target}/run", body)
        print(f"{plan['title']}: running again from step {args.start}")
        print(f"follow it: handler plan show {plan['id']}")
        return 0
    file = where(d, args.target)
    read = d.call("POST", "/v1/plans/read", file)
    print_read(read)
    if read.get("problems"):
        return 1
    print(
        "\nEach step is a new session of its agent, unattended: nobody answers it, and it runs "
        "until it says it is done or failed."
    )
    if not args.yes and input("Approve and run it? [y/N] ").strip().lower() != "y":
        return 1
    plan = d.call("POST", "/v1/plans", file | {"digest": read["digest"]})
    print(f"running: {plan['title']} ({plan['id']})")
    print(f"follow it: handler plan show {plan['id']}")
    return 0


def progress(plan: dict[str, Any]) -> str:
    done = sum(s["state"] == "done" for s in plan["steps"])
    return f"{done}/{len(plan['steps'])}"


def list_plans(d: Daemon, _: argparse.Namespace) -> int:
    plans = d.call("GET", "/v1/plans")
    if not plans:
        print("no plan: New plan in the web UI (the plan builder), then handler plan run")
        return 0
    rows = [["ID", "STATE", "STEPS DONE", "AGENT", "APPROVED", "TITLE"]]
    for p in plans:
        rows.append([p["id"], p["state"], progress(p), p.get("agent") or "(deleted)",
                     when_at(p["approvedAt"]), one_line(p["title"], 50)])  # fmt: skip
    table(rows)
    return 0


def show(d: Daemon, args: argparse.Namespace) -> int:
    p = d.call("GET", f"/v1/plans/{args.id}")
    print(f"Plan: {p['title']}   ({p['id']})")
    agent = p.get("agent") or "(deleted)"
    source = f"{p['folder']}/{p['source']}" if p.get("source") else f"{p['folder']}, a draft"
    print(f"Agent: {agent} · {source} · approved {when_at(p['approvedAt'])}")
    state = p["state"] + (f": {p['stoppedBecause']}" if p.get("stoppedBecause") else "")
    print(f"State: {state} ({progress(p)} steps done)")
    for step in p["steps"]:
        print(f"\n  {step['n']}. {step['state']:<9} {step['title']}")
        if step.get("summary"):
            print(f"     {one_line(step['summary'], 200)}")
        if step.get("error"):
            print(f"     why: {one_line(step['error'], 200)}")
        if step.get("refused"):
            print(f"     hosts refused: {refused_hosts(step['refused'])}")
            if step.get("said"):
                print(f"     the agent said: {one_line(step['said'], 200)}")
        if step.get("sessionId"):
            print(f"     its session: handler attach {step['sessionId']}")
    if p["state"] == "stopped":
        first = next((s for s in p["steps"] if s["state"] != "done"), p["steps"][0])
        allow = "".join(
            f" --allow {h['host']}" for h in first.get("refused", []) if not h.get("decision")
        )
        print(f"\nrun it again: handler plan run {p['id']} --from {first['n']}{allow}")
    return 0


def cancel(d: Daemon, args: argparse.Namespace) -> int:
    p = d.call("POST", f"/v1/plans/{args.id}/cancel")
    print(f"{p['title']}: stopped")
    return 0


def delete(d: Daemon, args: argparse.Namespace) -> int:
    p = d.call("GET", f"/v1/plans/{args.id}")
    if not args.yes and input(f"Forget the plan {p['title']}? [y/N] ").strip().lower() != "y":
        return 1
    d.call("DELETE", f"/v1/plans/{args.id}")
    print(f"{p['title']}: deleted (its sessions stay with its agent)")
    return 0


def duration(seconds: int) -> str:
    return f"{seconds // 3600} h" if seconds % 3600 == 0 else f"{seconds // 60} min"


COMMANDS = {
    "check": check,
    "run": run,
    "list": list_plans,
    "show": show,
    "cancel": cancel,
    "delete": delete,
}


def dispatch(args: argparse.Namespace) -> int:
    return COMMANDS[args.plan_cmd](Daemon(), args)
