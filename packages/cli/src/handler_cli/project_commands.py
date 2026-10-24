"""`handler project …` — projects: a folder and its agents (contract D.8), created and edited in
the web UI. In a project's folder, `handler run`, `terminal` and `acp` use its agents.

handler project list                 projects, most recently used first: area, agents, folder
handler project show NAME            its agents (`*`: the default one), what each runs on and its
                                     settings
handler project export-agents NAME   its agents (all, or those named with --agent) as one file,
    [--agent AGENT]... [-o FILE]     NAME-agents.zip, to set them up in another project or to
                                     share (D.23): never their models, folder, addon
                                     configurations, knowledge folders or conversations. Says what
                                     it leaves out
handler project import-agents FILE   read an agents file: its agents are then set up in the web
                                     UI (it asks each one's model): the page's address is printed
handler project import-agents NAME --from SOURCE
                                     the same, for agents a source offers (`handler source list`)
"""

import argparse
import re
from pathlib import Path
from typing import Any

from .agent_commands import describe_agent, runs
from .client import ClientError, Daemon, base_url, read_token
from .output import table
from .session_commands import agent_label


def add_parser(sub: Any) -> None:
    project = sub.add_parser("project", help="projects", description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    p = project.add_subparsers(dest="project_cmd", required=True)
    p.add_parser("list")
    p.add_parser("show").add_argument("name")
    export = p.add_parser("export-agents")
    export.add_argument("name")
    export.add_argument("--agent", action="append", default=[], help="one of its agents (repeat)")
    export.add_argument("-o", "--output", help="the file to write (default: NAME-agents.zip)")
    imports = p.add_parser("import-agents")
    imports.add_argument("file", metavar="FILE|NAME")
    imports.add_argument("--from", dest="source_id", metavar="SOURCE", help="the source of NAME")


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.project_cmd == "import-agents":
        return import_agents(d, args.file, args.source_id)
    projects = d.call("GET", "/v1/projects")
    if args.project_cmd == "list":
        rows = [["PROJECT", "AREA", "AGENTS", "FOLDER"]]
        for p in projects:
            agents = ", ".join(agent_label(a) for a in p["agents"])
            rows.append([p["name"], p.get("area") or "-", agents, p["folder"]])
        table(rows) if len(rows) > 1 else print("no project: create one in the web UI (handler ui)")
        return 0
    wanted = args.name.lower()
    found = next((p for p in projects if wanted in (p["name"].lower(), p["id"])), None)
    if found is None:
        names = ", ".join(p["name"] for p in projects) or "none"
        raise ClientError(f"no project '{args.name}': {names}")
    if args.project_cmd == "export-agents":
        return export_agents(d, found, args)
    show(found)
    return 0


def show(p: dict[str, Any]) -> None:
    area = f" · {p['area']}" if p.get("area") else ""
    print(f"{p['name']}{area} · {p['folder']}")
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


def file_name(project: str) -> str:
    """A project's name as an agents file's (a skill's rules): "My shop" → "my-shop"."""
    return "-".join(re.findall(r"[a-z0-9]+", project.lower()))[:60] or "agents"


def export_agents(d: Daemon, project: dict[str, Any], args: argparse.Namespace) -> int:
    ids = [a["id"] for a in project["agents"]]
    if args.agent:
        ids = [find_agent(project, name)["id"] for name in args.agent]
    body = {"name": file_name(project["name"]), "projectId": project["id"], "agentIds": ids}
    draft = d.call("POST", "/v1/agents-files/export", body | {"dryRun": True})
    r = d.request("POST", "/v1/agents-files/export", body)
    named = r.headers.get("content-disposition", "").partition('filename="')[2].rstrip('"')
    target = args.output or named
    Path(target).write_bytes(r.content)
    names = ", ".join(a["definition"]["agentName"] for a in draft["file"]["agents"])
    print(f"wrote {target}: {names}")
    print("left out, as yours:")
    for line in draft["replaced"]:
        print(f"  {line}")
    return 0


def import_agents(d: Daemon, file: str, source_id: str | None) -> int:
    if source_id is not None:
        read = d.call("POST", f"/v1/sources/{source_id}/agents/{file}")
    else:
        path = Path(file)
        if not path.is_file():
            raise ClientError(f"{path}: no such file")
        read = d.request("POST", "/v1/agents-files/import", content=path.read_bytes()).json()
    for a in read["agents"]:
        print(f"  {a['definition']['agentName']}: {a['definition'].get('agentDescription') or ''}")
    url = f"{base_url()}/#token={read_token()}&then=/setup/{read['name']}"
    print(f"set them up in the web UI (it asks each one's model): {url}")
    return 0


def find_agent(project: dict[str, Any], wanted: str) -> dict[str, Any]:
    for a in project["agents"]:
        if wanted.lower() in (agent_label(a).lower(), a["id"]):
            return a
    names = ", ".join(agent_label(a) for a in project["agents"])
    raise ClientError(f"no agent '{wanted}' in {project['name']}: {names}")
