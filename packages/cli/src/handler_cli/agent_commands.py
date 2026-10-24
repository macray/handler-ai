"""`handler agent …` — every agent, of projects and outside them (contract D.1, D.8). Agents of
projects are created and edited in the web UI; agents outside projects are made by `handler run`,
`terminal` and `acp` in a folder.

handler agent list                   every agent, most recently used first, with its id
handler agent show ID                its settings, models, folder, live sandboxes, the apps using it
handler agent rm ID [--yes]          delete an agent outside projects (stops its sandboxes); asks
                                     first when an app uses it
handler agent network ID [log-only|enforce]
                                     its network mode and recent connections (allowed, denied,
                                     unlisted: let through in log-only, enforcing would deny); with
                                     a mode, switch a filtered agent to it, live (log-only: every
                                     host goes through and is logged, to learn which it needs)
handler agent checks ID [--run]      a job's checks (D.20: runs kept with their right answer) and
                                     their last results; --run runs them all and waits: exit 1
                                     when one does not pass
"""

import argparse
import time
from typing import Any

from .client import Daemon
from .output import table


def add_parser(sub: Any) -> None:
    agent = sub.add_parser("agent", help="agents", description=__doc__,
                           formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    a = agent.add_subparsers(dest="agent_cmd", required=True)
    a.add_parser("list")
    a.add_parser("show").add_argument("id")
    rm = a.add_parser("rm")
    rm.add_argument("id")
    rm.add_argument("--yes", action="store_true", help="do not ask when an app uses it")
    network = a.add_parser("network")
    network.add_argument("id")
    network.add_argument("mode", nargs="?", choices=["log-only", "enforce"])
    checks = a.add_parser("checks")
    checks.add_argument("id")
    checks.add_argument("--run", action="store_true", help="run them all, and wait")


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.agent_cmd == "list":
        print_agents(d)
    elif args.agent_cmd == "show":
        show(d, d.call("GET", f"/v1/agents/{args.id}"))
    elif args.agent_cmd == "rm":
        if (uses := used_by(d, args.id)) and not args.yes:
            print(f"{args.id} is used by {', '.join(uses)}: they stop until you give them another.")
            if input("Delete it? [y/N] ").strip().lower() != "y":
                return 1
        d.call("DELETE", f"/v1/agents/{args.id}")
        print(f"{args.id}: removed")
    elif args.agent_cmd == "checks":
        return agent_checks(d, args.id, run=args.run)
    elif args.mode:
        w = d.call("PATCH", f"/v1/agents/{args.id}", {"egress": args.mode})
        print(f"agent {w['id']}: network {network_mode(w)}")
    else:
        print_network(d, d.call("GET", f"/v1/agents/{args.id}"))
    return 0


def agent_checks(d: Daemon, agent_id: str, *, run: bool) -> int:
    """Its checks and their last results; with `run`, run them first and wait for the end. 1
    when one did not pass (a script can stop on it)."""
    path = f"/v1/agents/{agent_id}/checks"
    if run:
        d.call("POST", f"{path}/run")
        while not d.call("GET", path)["last"].get("endedAt"):
            time.sleep(1)
    seen = d.call("GET", path)
    if not seen["checks"]:
        print("No check: keep a run whose answer is right (its page in the web UI).")
        return 0
    results = {r["checkId"]: r for r in (seen.get("last") or {}).get("results", [])}
    rows = [["CHECK", "COMPARES", "LAST"]]
    for c in seen["checks"]:
        r = results.get(c["id"])
        last = c.get("problem") or (
            r["state"] + (f": {r['why']}" if r.get("why") else "") if r else "never run"
        )
        rows.append([c["name"], ", ".join(c["compare"]), last])
    table(rows)
    if seen.get("changed"):
        print(f"Not run since you changed {' and '.join(seen['changed'])}.")
    return (
        0 if all(results.get(c["id"], {}).get("state") == "passed" for c in seen["checks"]) else 1
    )


def print_agents(d: Daemon) -> None:
    projects = {p["id"]: p["name"] for p in d.call("GET", "/v1/projects")}
    rows = [["ID", "HOME", "NAME", "RUNS", "SETTINGS", "LIVE", "FOLDER"]]
    listed = d.call("GET", "/v1/agents")
    listed.sort(key=lambda a: a.get("lastUsedAt") or a["createdAt"], reverse=True)
    for a in listed:
        rows.append(
            [
                a["id"],
                home(a, projects),
                (a.get("name") or "-") + set_up_from(a),
                runs(a),
                describe_agent(a, runs_too=False),
                str(len(a["connections"])),
                a.get("scope") or "(a folder per session)",
            ]
        )
    table(rows)


def home(a: dict[str, Any], projects: dict[str, str]) -> str:
    """Where it lives (D.1): `project NAME`, `app NAME`, `Chat`, `outside projects`."""
    if a.get("projectId"):
        return f"project {projects.get(a['projectId'], a['projectId'])}"
    if a.get("chat"):
        return "Chat"
    return f"app {a['app']}" if a.get("app") else "outside projects"


def set_up_from(a: dict[str, Any]) -> str:
    """` (from planner/planner)`: what it was set up from (D.18, D.23, H.2), if anything."""
    origin = a.get("origin")
    if not origin:
        return ""
    part = f"/{origin['agent']}" if origin.get("agent") else ""
    return f" (from {origin['name']}{part})"


def show(d: Daemon, a: dict[str, Any]) -> None:
    projects = {p["id"]: p["name"] for p in d.call("GET", "/v1/projects")}
    print(f"{a.get('name') or program(a['model'])} · {a['id']} · {home(a, projects)}")
    if a.get("description"):
        print(f"  {a['description']}")
    print(f"  folder       {a.get('scope') or '(a folder per session)'}")
    print(f"  runs         {model_label(a['model'])}")
    print(f"  network      {network_mode(a)}")
    if a.get("allow"):
        print(f"  its hosts    {', '.join(a['allow'])}")
    print(f"  permissions  {a['permissions']}")
    for key, label in (("bindings", "bindings"), ("knowledge", "knowledge"), ("skills", "skills")):
        if a.get(key):
            print(f"  {label:<12} {', '.join(a[key])}")
    if a.get("confinement", "strict") != "strict":
        print(f"  containers   {'yes' if a['confinement'] == 'nested' else a['confinement']}")
    if a.get("display"):
        print("  display      yes")
    print(f"  live         {len(a['connections'])} sandbox(es)")
    if uses := used_by(d, a["id"]):
        print(f"  used by      {', '.join(uses)}")


def used_by(d: Daemon, agent_id: str) -> list[str]:
    """What runs it and stops when it is deleted (D.22): Handler's roles, apps, automations:
    "the app planner (needs it: plans your day)"."""
    refs = d.call("GET", f"/v1/uses/agent/{agent_id}").get("usedBy", [])
    return [
        f"{'Handler' if r['kind'] == 'handler' else f'the {r["kind"]} {r["label"]}'} ({r['how']})"
        for r in refs
        if r["kind"] in ("handler", "app", "automation")
    ]


def network_mode(a: dict[str, Any]) -> str:
    """`filtered, log-only` / `filtered, enforce` / `open` / `none`."""
    if a["network"] != "filtered":
        return a["network"]
    return f"filtered, {a.get('egress') or 'enforce'}"


def print_network(d: Daemon, a: dict[str, Any]) -> None:
    print(f"network {network_mode(a)}" + (f" + {', '.join(a['allow'])}" if a.get("allow") else ""))
    events = d.call("GET", f"/v1/agents/{a['id']}/egress-events")
    if not events:
        print("no connection yet")
        return
    rows = [["TIME", "DECISION", "HOST", "CONNECTION"]]
    rows += [[e["t"][11:19], e["decision"], e["host"], e["connection"]] for e in events]
    table(rows)


def runs(w: dict[str, Any]) -> str:
    """Its model: `claude-code · account claude-pro`, `codex · provider llamacpp · qwen3`."""
    return model_label(w["model"])


def program(m: dict[str, Any]) -> str:
    """What does the work: its harness, or the model alone (D.18: none)."""
    return m.get("harness") or "the model alone"


def model_label(m: dict[str, Any]) -> str:
    access = f"account {m['account']}" if m.get("account") else f"provider {m.get('provider')}"
    return " · ".join([program(m), access, *([m["model"]] if m.get("model") else [])])


def describe_agent(w: dict[str, Any], *, runs_too: bool = True) -> str:
    """Its settings in one line, the defaults left out: `runs=… network=filtered/log-only
    +2 hosts bindings=… knowledge=… containers display`."""
    network = w["network"] + (f"/{w['egress']}" if w.get("egress") == "log-only" else "")
    parts = [f"runs={runs(w)}"] if runs_too else []
    parts.append(f"network={network}" + (f" +{len(w['allow'])} hosts" if w.get("allow") else ""))
    if w["permissions"] != "bypass":
        parts.append(f"permissions={w['permissions']}")
    if w.get("bindings"):
        parts.append(f"bindings={','.join(w['bindings'])}")
    if w.get("knowledge"):
        parts.append(f"knowledge={','.join(w['knowledge'])}")
    if w.get("confinement", "strict") != "strict":
        parts.append("containers" if w["confinement"] == "nested" else w["confinement"])
    if w.get("display"):
        parts.append("display")
    return "  ".join(parts)
