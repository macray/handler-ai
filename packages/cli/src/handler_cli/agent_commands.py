"""`handler agent …` — every agent, of projects and outside them (contract D.1, D.8). Agents of
projects are created and edited in the web UI; agents outside projects are made by `handler run`,
`terminal` and `acp` in a folder.

handler agent list                   every agent, most recently used first, with its id
handler agent show ID                its settings, models, folder and live sandboxes
handler agent rm ID                  delete an agent outside projects (stops its sandboxes)
handler agent network ID [log-only|enforce]
                                     its network mode and recent connections (allowed, denied,
                                     unlisted: let through in log-only, enforcing would deny); with
                                     a mode, switch a filtered agent to it, live (log-only: every
                                     host goes through and is logged, to learn which it needs)
"""

import argparse
from typing import Any

from .client import Daemon
from .output import table


def add_parser(sub: Any) -> None:
    agent = sub.add_parser("agent", help="agents", description=__doc__,
                           formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    a = agent.add_subparsers(dest="agent_cmd", required=True)
    a.add_parser("list")
    a.add_parser("show").add_argument("id")
    a.add_parser("rm").add_argument("id")
    network = a.add_parser("network")
    network.add_argument("id")
    network.add_argument("mode", nargs="?", choices=["log-only", "enforce"])


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.agent_cmd == "list":
        print_agents(d)
    elif args.agent_cmd == "show":
        show(d, d.call("GET", f"/v1/agents/{args.id}"))
    elif args.agent_cmd == "rm":
        d.call("DELETE", f"/v1/agents/{args.id}")
        print(f"{args.id}: removed")
    elif args.mode:
        w = d.call("PATCH", f"/v1/agents/{args.id}", {"egress": args.mode})
        print(f"agent {w['id']}: network {network_mode(w)}")
    else:
        print_network(d, d.call("GET", f"/v1/agents/{args.id}"))
    return 0


def print_agents(d: Daemon) -> None:
    projects = {p["id"]: p["name"] for p in d.call("GET", "/v1/projects")}
    rows = [["ID", "PROJECT", "NAME", "RUNS", "SETTINGS", "LIVE", "FOLDER"]]
    listed = d.call("GET", "/v1/agents")
    listed.sort(key=lambda a: a.get("lastUsedAt") or a["createdAt"], reverse=True)
    for a in listed:
        rows.append(
            [
                a["id"],
                projects.get(a.get("projectId") or "", "(ad hoc)"),
                (a.get("name") or "-") + (f" (built-in {a['origin']})" if a.get("origin") else ""),
                runs(a),
                describe_agent(a, runs_too=False),
                str(len(a["connections"])),
                a.get("scope") or "(a folder per session)",
            ]
        )
    table(rows)


def show(d: Daemon, a: dict[str, Any]) -> None:
    projects = {p["id"]: p["name"] for p in d.call("GET", "/v1/projects")}
    project = projects.get(a.get("projectId") or "", "ad hoc")
    print(f"{a.get('name') or a['models'][0]['harness']} · {a['id']} · {project}")
    if a.get("description"):
        print(f"  {a['description']}")
    print(f"  folder       {a.get('scope') or '(a folder per session)'}")
    for i, m in enumerate(a["models"]):
        print(f"  {'runs' if i == 0 else '':<12} {model_label(m)}")
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
    """Its models, the default first: `claude-code · account claude-pro`, `codex · provider
    llamacpp · qwen3`."""
    return " | ".join(model_label(m) for m in w["models"])


def model_label(m: dict[str, Any]) -> str:
    access = f"account {m['account']}" if m.get("account") else f"provider {m.get('provider')}"
    return " · ".join([m["harness"], access, *([m["model"]] if m.get("model") else [])])


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
