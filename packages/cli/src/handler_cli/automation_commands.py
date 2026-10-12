"""`handler automation …` — automations (docs/user/automations.md): when a
session stops or at a time you set, handler runs your script in a sandbox (it may call the models
you chose, what it writes is added to a knowledge note), one of your agents (its result goes to your
inbox: `handler inbox`), or a route of one of your apps. Each is a folder of
~/.config/handler-ai/automations/<name>/: edit its files in your editor.

handler automation list                 every automation: on or off, when, last run, problems
handler automation show NAME            what it may touch, its files, its problems, its next run
handler automation new NAME --from EXAMPLE  copy an example handler ships (env-issues), off
handler automation examples             the examples handler ships
handler automation try NAME [--session ID|last]
                                        run it now, on or off (one on a session that stopped:
                                        on that session's whole conversation, default the one
                                        that stopped last; a script's try adds nothing)
handler automation enable NAME [--yes]  turn it on: shows what it may touch and asks first
handler automation disable NAME         turn it off
handler automation delete NAME [--yes]  delete it: its folder (its files) and its runs; asks first
handler automation runs NAME            its runs, most recent first
handler automation log RUN              a script run's output
handler automation cancel RUN           stop a run
"""

import argparse
import sys
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .client import ClientError, Daemon
from .output import one_line, table

WATCH_INTERVAL = 0.5


def add_parser(sub: Any) -> None:
    auto = sub.add_parser("automation", help="automations", description=__doc__,
                          formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    a = auto.add_subparsers(dest="automation_cmd", required=True)
    a.add_parser("list")
    a.add_parser("examples")
    new = a.add_parser("new")
    new.add_argument("name")
    new.add_argument("--from", dest="example", required=True, help="an example (env-issues)")
    t = a.add_parser("try")
    t.add_argument("name")
    t.add_argument("--session", default="last", help="a session's id, or last (the default)")
    e = a.add_parser("enable")
    e.add_argument("name")
    e.add_argument("--yes", action="store_true", help="do not ask")
    rm = a.add_parser("delete")
    rm.add_argument("name")
    rm.add_argument("--yes", action="store_true", help="do not ask")
    for name in ("show", "disable", "runs"):
        a.add_parser(name).add_argument("name")
    for name in ("log", "cancel"):
        a.add_parser(name).add_argument("run")


def sentence(definition: dict[str, Any] | None) -> str:
    """When it runs, in words."""
    if not definition:
        return "-"
    when = definition["when"]
    if isinstance(when, dict):
        if when.get("every"):
            return f"every {when['every']}"
        days = f" on {','.join(when['days'])}" if when.get("days") else ""
        return f"at {when['at']}{days}"
    only = definition.get("only") or {}
    who = [f"project {', '.join(only['project'])}"] if only.get("project") else []
    who += [f"agent {', '.join(only['agent'])}"] if only.get("agent") else []
    return "when a session stops" + (f" ({'; '.join(who)})" if who else "")


def what(definition: dict[str, Any] | None) -> str:
    """What it runs, in a few words."""
    if not definition:
        return "-"
    run = definition["run"]
    if isinstance(run, str):
        return "a script"
    if "agent" in run:
        return f"agent {run['agent']}" + (f" ({run['project']})" if run.get("project") else "")
    return f"app {run['app']}"


def last_run(view: dict[str, Any]) -> str:
    run = view.get("lastRun")
    if not run:
        return "-"
    return f"{run['state']} {run['createdAt'][:16].replace('T', ' ')}"


def list_automations(d: Daemon, _: argparse.Namespace) -> int:
    views = d.call("GET", "/v1/automations")
    if not views:
        print("no automation: handler automation new NAME --from env-issues")
        return 0
    rows = [["NAME", "", "WHEN", "RUNS", "LAST RUN", "PROBLEMS"]]
    for v in views:
        state = "on" if v.get("enabled") else "off"
        problems = one_line("; ".join(v.get("problems") or []), 60) or "-"
        definition = v.get("definition")
        rows.append([v["name"], state, sentence(definition), what(definition), last_run(v),
                     problems])  # fmt: skip
    table(rows)
    return 0


def show(d: Daemon, args: argparse.Namespace) -> int:
    v = d.call("GET", f"/v1/automations/{args.name}")
    print(f"{v['name']}: {'on' if v.get('enabled') else 'off'}"
          + (f" — {v['description']}" if v.get("description") else ""))  # fmt: skip
    if permissions := v.get("permissions"):
        print("What it does:")
        for line in permissions:
            print(f"  {line}")
    for warning in v.get("warnings") or []:
        print(f"warning: {warning}")
    for problem in v.get("problems") or []:
        print(f"problem: {problem}")
    print(f"Files, in {v['directory']}:")
    for file in v.get("files") or []:
        print(f"  {file}")
    if v.get("pending"):
        capped = " (daily cap reached)" if v.get("capped") else ""
        behind = f", behind {v['behind']} (one run at a time)" if v.get("behind") else ""
        print(f"{v['pending']} run(s) waiting{capped}{behind}")
    if v.get("nextAt"):
        print(f"Next run: {when_at(v['nextAt'])}")
    print(f"Last run: {last_run(v)}")
    return 0


def when_at(t: str) -> str:
    """A time of the API (UTC) as the local time, to the minute."""
    return datetime.fromisoformat(t).astimezone().strftime("%Y-%m-%d %H:%M")


def examples(d: Daemon, _: argparse.Namespace) -> int:
    table([["EXAMPLE", "DESCRIPTION"]] + [[e["name"], e.get("description") or ""]
          for e in d.call("GET", "/v1/automation-examples")])  # fmt: skip
    return 0


def new(d: Daemon, args: argparse.Namespace) -> int:
    v = d.call("POST", "/v1/automations", {"name": args.name, "from": args.example})
    print(f"{args.name}: created, off, in {v['directory']}")
    for problem in v.get("problems") or []:
        print(f"problem: {problem}")
    print(f"Edit its files, try it (handler automation try {args.name}), then turn it on "
          f"(handler automation enable {args.name}).")  # fmt: skip
    return 0


def last_session(d: Daemon) -> str:
    sessions = d.call("GET", "/v1/sessions")
    stopped = [s for s in sessions if s["state"] == "stopped" and not s.get("input")]
    if not stopped:
        raise ClientError("no stopped session to try it on (--session ID)")
    return max(stopped, key=lambda s: s["lastActivityAt"])["id"]


def wait(d: Daemon, name: str, run: dict[str, Any]) -> dict[str, Any]:
    while run["state"] in ("queued", "running"):
        time.sleep(WATCH_INTERVAL)
        run = d.call("GET", f"/v1/automations/{name}/runs/{run['id']}")
    return run


def run_for(run: dict[str, Any]) -> str:
    """What a run was for: the session that stopped, or the schedule's slot (and those missed)."""
    if run.get("sessionId"):
        return f"session {run['sessionId']}, events {run['seqFrom']} to {run['seqTo']}"
    if run.get("slot"):
        missed = run.get("missed") or 0
        return f"slot {when_at(run['slot'])}" + (f", {missed} missed before" if missed else "")
    return "now"


def describe_run(run: dict[str, Any]) -> list[str]:
    llm = run.get("llm") or {}
    lines = [f"{run['id']} {run['state']}{' (try)' if run.get('trial') else ''}: {run_for(run)}"]
    if run.get("agentSessionId"):
        lines.append(f"  the agent's session: {run['agentSessionId']}")
    if run.get("error"):
        lines.append(f"  error: {run['error']}")
    if llm.get("calls"):
        lines.append(f"  {llm['calls']} model call(s), {llm['inTokens']} tokens in, "
                     f"{llm['outTokens']} out")  # fmt: skip
    for appended in run.get("appended") or []:
        verb = "would add" if run.get("trial") else "added"
        lines.append(f"  {verb} {appended['bytes']} bytes to {appended['to']}")
    return lines


def try_it(d: Daemon, args: argparse.Namespace) -> int:
    v = d.call("GET", f"/v1/automations/{args.name}")
    if (v.get("definition") or {}).get("when") == "session.stopped":
        session = last_session(d) if args.session == "last" else args.session
        run = d.call("POST", f"/v1/automations/{args.name}/try", {"sessionId": session})
        print(f"trying {args.name} on session {session} ({run['id']})…", file=sys.stderr)
    else:
        run = d.call("POST", f"/v1/automations/{args.name}/try", {})
        print(f"trying {args.name} ({run['id']})…", file=sys.stderr)
    run = wait(d, args.name, run)
    print("\n".join(describe_run(run)))
    if run.get("agentSessionId") and run["state"] == "succeeded":
        output = d.call("GET", f"/v1/sessions/{run['agentSessionId']}").get("output") or {}
        value = output.get("value") or {}
        print(f"  {value.get('status')}: {value.get('summary')} (in your inbox: handler inbox)")
    for appended in run.get("appended") or []:
        print(f"\n--- {appended['to']} would get:\n{appended.get('text', '')}", end="")
    if run["state"] != "succeeded":
        print(f"(its output: handler automation log {run['id']})", file=sys.stderr)
        return 1
    return 0


def enable(d: Daemon, args: argparse.Namespace) -> int:
    v = d.call("GET", f"/v1/automations/{args.name}")
    if v.get("problems"):
        raise ClientError(f"{args.name} has problems: {'; '.join(v['problems'])}")
    print(f"{args.name}, once on:")
    for line in v.get("permissions") or []:
        print(f"  {line}")
    for warning in v.get("warnings") or []:
        print(f"warning: {warning}")
    if not args.yes and input("Turn it on? [y/N] ").strip().lower() != "y":
        return 1
    v = d.call("POST", f"/v1/automations/{args.name}/enable")
    if v.get("nextAt"):
        print(f"{args.name}: on, next run {when_at(v['nextAt'])}")
    else:
        print(f"{args.name}: on (sessions that stop from now on)")
    return 0


def disable(d: Daemon, args: argparse.Namespace) -> int:
    d.call("POST", f"/v1/automations/{args.name}/disable")
    print(f"{args.name}: off")
    return 0


def delete(d: Daemon, args: argparse.Namespace) -> int:
    v = d.call("GET", f"/v1/automations/{args.name}")
    count = len(d.call("GET", f"/v1/automations/{args.name}/runs"))
    print(f"{args.name}: {'on' if v.get('enabled') else 'off'}; deleting it removes")
    print(f"  its folder, with every file in it: {v['directory']}")
    runs_of = f"{count} run{'' if count == 1 else 's'}"
    print(f"  its {runs_of} and their logs (what it told your inbox stays)")
    if v.get("enabled"):
        print("  and stops it (a run in progress is cancelled)")
    if not args.yes and input("Delete it? [y/N] ").strip().lower() != "y":
        return 1
    d.call("DELETE", f"/v1/automations/{args.name}")
    print(f"{args.name}: deleted")
    return 0


def runs(d: Daemon, args: argparse.Namespace) -> int:
    rows = [["RUN", "STATE", "FOR", "STARTED", "ADDED"]]
    for run in d.call("GET", f"/v1/automations/{args.name}/runs"):
        state = run["state"] + (" (try)" if run.get("trial") else "")
        added = ", ".join(a["to"] for a in run.get("appended") or []) or "-"
        rows.append([run["id"], state, run_for(run), when_at(run["createdAt"]), added])
    table(rows)
    return 0


def find_run(d: Daemon, run_id: str) -> str:
    """The automation `run_id` is a run of."""
    for v in d.call("GET", "/v1/automations"):
        if any(r["id"] == run_id for r in d.call("GET", f"/v1/automations/{v['name']}/runs")):
            return v["name"]
    raise ClientError(f"no run {run_id}")


def log(d: Daemon, args: argparse.Namespace) -> int:
    name = find_run(d, args.run)
    print(d.text(f"/v1/automations/{name}/runs/{args.run}/log"), end="")
    return 0


def cancel(d: Daemon, args: argparse.Namespace) -> int:
    name = find_run(d, args.run)
    run = d.call("POST", f"/v1/automations/{name}/runs/{args.run}/cancel")
    print("\n".join(describe_run(wait(d, name, run))))
    return 0


COMMANDS: dict[str, Callable[[Daemon, argparse.Namespace], int]] = {
    "list": list_automations,
    "show": show,
    "examples": examples,
    "new": new,
    "try": try_it,
    "enable": enable,
    "disable": disable,
    "runs": runs,
    "log": log,
    "cancel": cancel,
    "delete": delete,
}


def dispatch(args: argparse.Namespace) -> int:
    return COMMANDS[args.automation_cmd](Daemon(), args)
