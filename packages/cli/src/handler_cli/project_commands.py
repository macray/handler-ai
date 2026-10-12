"""`handler project …` — projects: a folder and its agents (contract D.8), created and edited in
the web UI. In a project's folder, `handler run`, `terminal` and `acp` use its agents.

handler project list                 projects, most recently used first: context, agents, folder
handler project show NAME            its agents (`*`: the default one), what each runs on and its
                                     settings
"""

import argparse
from typing import Any

from .agent_commands import describe_agent, runs
from .client import ClientError, Daemon
from .output import table
from .session_commands import agent_label


def add_parser(sub: Any) -> None:
    project = sub.add_parser("project", help="projects", description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    p = project.add_subparsers(dest="project_cmd", required=True)
    p.add_parser("list")
    p.add_parser("show").add_argument("name")


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    projects = d.call("GET", "/v1/projects")
    if args.project_cmd == "list":
        rows = [["PROJECT", "CONTEXT", "AGENTS", "FOLDER"]]
        for p in projects:
            agents = ", ".join(agent_label(a) for a in p["agents"])
            rows.append([p["name"], p.get("context") or "-", agents, p["folder"]])
        table(rows) if len(rows) > 1 else print("no project: create one in the web UI (handler ui)")
        return 0
    wanted = args.name.lower()
    found = next((p for p in projects if wanted in (p["name"].lower(), p["id"])), None)
    if found is None:
        names = ", ".join(p["name"] for p in projects) or "none"
        raise ClientError(f"no project '{args.name}': {names}")
    show(found)
    return 0


def show(p: dict[str, Any]) -> None:
    context = f" · {p['context']}" if p.get("context") else ""
    print(f"{p['name']}{context} · {p['folder']}")
    if p.get("description"):
        print(f"  {p['description']}")
    rows = [["AGENT", "ID", "RUNS", "SETTINGS", "LIVE"]]
    for a in p["agents"]:
        default = " *" if a["id"] == p.get("defaultAgent") else ""
        rows.append(
            [
                f"{agent_label(a)}{default}",
                a["id"],
                runs(a),
                describe_agent(a, runs_too=False),
                str(len(a["connections"])),
            ]
        )
    table(rows)
    print("* the project's default agent")
