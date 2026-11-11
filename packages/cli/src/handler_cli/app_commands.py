"""`handler app …` — apps (contract H, apps design): small web apps written by
an agent, run by handlerd on demand, each at its own origin (http://<name>.localhost:<port>/).

handler app list                   your apps, their versions and state
handler app add [PATH]             give Handler an app's code: an app file (.zip, an export) or
                                   the folder holding its app.toml (default: here), zipped
                                   without .git and node_modules; a new app, or the next version
                                   of one you have (Handler keeps its own copy: changing the
                                   folder afterwards changes nothing until you add it again)
handler app add NAME --from SOURCE an app a source offers (`handler source list`; "official":
                                   Handler's), its code taken the same way
handler app export NAME [-o FILE]  its code as one file, NAME-VERSION.zip (never its data, what
                                   you gave it or its secrets)
handler app show NAME              what it needs and what you gave it: folders, agents (with
                                   yours that fit), secrets
handler app folder NAME NEED PATH [--new]
                                   give one of its folder needs a folder (--new: make it)
handler app agent NAME NEED AGENT_ID
                                   give one of its agent needs one of your agents that fits it
                                   (`handler app show`; a new one is set up in the web UI)
handler app deploy NAME [--yes]    install its code as last added: tests, health check on a
                                   copy of the data, then switch (asks first when it may reach
                                   more than before)
handler app rollback NAME          back to the previous version and its data as it was then
handler app open NAME [--print]    open it in its own window (a one-time link): Firefox with
                                   the handler-apps profile, else Chromium's app mode, else the
                                   default browser (HANDLER_APP_BROWSER=firefox|chromium|default)
handler app stop NAME              stop its backend now (it starts again when used)
handler app log NAME               its last deploys and its backend's output
handler app secret NAME SECRET [--unset]
                                   set a secret the app declares (asked for, or read from stdin);
                                   the backend restarts with it
handler app uninstall NAME [--yes] uninstall it: its code, its own data, its agents and what
                                   runs them are deleted (your folders stay); asks first
"""

import argparse
import getpass
import io
import os
import sys
import zipfile
from collections.abc import Callable
from typing import Any

from . import app_window
from .client import ClientError, Daemon
from .output import table


def add_parser(sub: Any) -> None:
    app = sub.add_parser("app", help="apps", description=__doc__,
                         formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    a = app.add_subparsers(dest="app_cmd", required=True)
    a.add_parser("list")
    add_app = a.add_parser("add")
    add_app.add_argument("path", nargs="?", default=".", metavar="PATH|NAME")
    add_app.add_argument("--from", dest="source_id", metavar="SOURCE", help="the source of NAME")
    e = a.add_parser("export")
    e.add_argument("name")
    e.add_argument("-o", "--output", help="the file to write (default: NAME-VERSION.zip here)")
    a.add_parser("show").add_argument("name")
    f = a.add_parser("folder")
    for arg in ("name", "need", "path"):
        f.add_argument(arg)
    f.add_argument("--new", action="store_true", help="make the folder")
    ag = a.add_parser("agent")
    for arg in ("name", "need", "agent_id"):
        ag.add_argument(arg)
    d = a.add_parser("deploy")
    d.add_argument("name")
    d.add_argument("--yes", action="store_true", help="do not ask about new needs")
    o = a.add_parser("open")
    o.add_argument("name")
    o.add_argument("--print", action="store_true", help="only print the link")
    sec = a.add_parser("secret")
    sec.add_argument("name")
    sec.add_argument("secret")
    sec.add_argument("--unset", action="store_true")
    for name in ("rollback", "stop", "log"):
        a.add_parser(name).add_argument("name")
    u = a.add_parser("uninstall")
    u.add_argument("name")
    u.add_argument("--yes", action="store_true", help="do not ask")


def describe(app: dict[str, Any], names: dict[str, str] | None = None) -> str:
    """The app in a few lines; `names`: agent id → name, to name the agents of its needs."""
    names = names or {}
    current = app.get("current")
    installed = current["version"] if current else "not deployed"
    lines = [f"{app['name']} {installed} ({app['state']}) — {app['url']}"]
    source = app["source"]
    if source.get("error"):
        lines.append(f"  source: {source['error']}")
    elif not current or source.get("version") != current["version"]:
        lines.append(f"  source: {source.get('version')} ready to deploy")
    for f in app.get("files", []):
        given = f.get("path") or "not given (handler app folder)"
        lines.append(f"  folder {f['name']} ({f['mode']}): {given}")
    for a in app.get("agents", []):
        given = a.get("agentId")
        if given and not a.get("problem"):
            lines.append(f"  agent {a['name']}: {names.get(given, given)} ({given})")
            continue
        why = f"{names.get(given, given)}: {a['problem']}" if given else a.get("problem")
        fits = ", ".join(f"{names.get(i, i)} ({i})" for i in a.get("fits", [])) or "none yet"
        lines.append(f"  agent {a['name']}: {why or 'not given'} (handler app agent; fit: {fits})")
    if missing := [s["name"] for s in app.get("secrets", []) if not s["set"]]:
        lines.append(f"  secrets not set: {', '.join(missing)} (handler app secret)")
    if app.get("error"):
        lines.append(f"  error: {app['error']}")
    return "\n".join(lines)


def list_apps(d: Daemon, _: argparse.Namespace) -> int:
    rows = [["NAME", "VERSION", "STATE", "SOURCE", "URL"]]
    for app in d.call("GET", "/v1/apps"):
        current = app.get("current")
        source = app["source"].get("version") or "invalid"
        rows.append(
            [
                app["name"],
                current["version"] if current else "-",
                app["state"],
                source if not current or source != current["version"] else "=",
                app["url"],
            ]
        )
    table(rows)
    return 0


def agent_names(d: Daemon) -> dict[str, str]:
    agents = d.call("GET", "/v1/agents")
    return {a["id"]: a.get("name") or a.get("scope") or a["id"] for a in agents}


def app_file(path: str) -> bytes:
    """An app file (H.15): the .zip as it is, or the folder zipped, without .git and
    node_modules (what is rebuilt), links followed."""
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read()
    if not os.path.isfile(os.path.join(path, "app.toml")):
        raise ClientError(f"no app.toml in {os.path.abspath(path)}")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(x for x in dirs if x not in (".git", "node_modules"))
            for name in sorted(files):
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, path))
    return buffer.getvalue()


def add(d: Daemon, args: argparse.Namespace) -> int:
    if args.source_id is not None:
        r = d.request("POST", f"/v1/sources/{args.source_id}/apps/{args.path}", timeout=300)
    else:
        r = d.request("POST", "/v1/apps", content=app_file(args.path), timeout=300)
    app = r.json()
    print(describe(app, agent_names(d)))
    if r.status_code == 200:
        print(f"the next version of {app['name']}: handler app deploy {app['name']}")
    return 0


def export(d: Daemon, args: argparse.Namespace) -> int:
    r = d.request("GET", f"/v1/apps/{args.name}/export")
    disposition = r.headers.get("content-disposition", "")
    named = disposition.partition('filename="')[2].rstrip('"') or f"{args.name}.zip"
    target = args.output or named
    with open(target, "wb") as f:
        f.write(r.content)
    print(f"wrote {target}")
    return 0


def show(d: Daemon, args: argparse.Namespace) -> int:
    print(describe(d.call("GET", f"/v1/apps/{args.name}"), agent_names(d)))
    return 0


def folder(d: Daemon, args: argparse.Namespace) -> int:
    body = {"path": os.path.abspath(os.path.expanduser(args.path)), "create": args.new}
    print(describe(d.call("PUT", f"/v1/apps/{args.name}/files/{args.need}", body), agent_names(d)))
    return 0


def agent(d: Daemon, args: argparse.Namespace) -> int:
    body = {"agentId": args.agent_id}
    app = d.call("PUT", f"/v1/apps/{args.name}/agents/{args.need}", body)
    print(describe(app, agent_names(d)))
    return 0


def deploy(d: Daemon, args: argparse.Namespace) -> int:
    app = d.call("GET", f"/v1/apps/{args.name}")
    if app["source"].get("error"):
        raise ClientError(app["source"]["error"])
    if (added := app["source"].get("addedNeeds")) and not args.yes:
        print(f"{args.name} {app['source']['version']} may reach more than before:")
        for need in added:
            print(f"  + {need}")
        if input("Deploy? [y/N] ").strip().lower() != "y":
            return 1
    print(f"deploying {args.name} {app['source']['version']} (tests, health check)…")
    print(describe(d.call("POST", f"/v1/apps/{args.name}/deploy")))
    return 0


def open_app(d: Daemon, args: argparse.Namespace) -> int:
    url = d.call("POST", f"/v1/apps/{args.name}/open")["url"]
    print(url)
    if not args.print:
        app_window.open_window(url)
    return 0


def log(d: Daemon, args: argparse.Namespace) -> int:
    print(d.call("GET", f"/v1/apps/{args.name}/log")["text"], end="")
    return 0


def secret(d: Daemon, args: argparse.Namespace) -> int:
    path = f"/v1/apps/{args.name}/secrets/{args.secret}"
    if args.unset:
        app = d.call("DELETE", path)
    else:
        prompt = f"{args.secret} for {args.name}: "
        value = getpass.getpass(prompt) if sys.stdin.isatty() else sys.stdin.readline()
        app = d.call("PUT", path, {"value": value.strip()})
    state = {s["name"]: s["set"] for s in app.get("secrets", [])}
    print(f"{args.secret}: {'set' if state.get(args.secret) else 'not set'}")
    return 0


def uninstall(d: Daemon, args: argparse.Namespace) -> int:
    app = d.call("GET", f"/v1/apps/{args.name}")
    print(f"Uninstalling {args.name} deletes its code, the data it keeps for itself, its agents")
    print("and what runs them. Your folders stay:")
    for f in app.get("files", []):
        if f.get("path"):
            print(f"  {f['path']}")
    if not args.yes and input("Uninstall it? [y/N] ").strip().lower() != "y":
        return 1
    d.call("DELETE", f"/v1/apps/{args.name}")
    print(f"{args.name}: uninstalled")
    return 0


def action(d: Daemon, args: argparse.Namespace) -> int:
    """rollback, stop: a POST that answers the app."""
    print(describe(d.call("POST", f"/v1/apps/{args.name}/{args.app_cmd}")))
    return 0


COMMANDS: dict[str, Callable[[Daemon, argparse.Namespace], int]] = {
    "list": list_apps,
    "add": add,
    "export": export,
    "show": show,
    "folder": folder,
    "agent": agent,
    "deploy": deploy,
    "open": open_app,
    "log": log,
    "secret": secret,
    "uninstall": uninstall,
    "rollback": action,
    "stop": action,
}


def dispatch(args: argparse.Namespace) -> int:
    return COMMANDS[args.app_cmd](Daemon(), args)
