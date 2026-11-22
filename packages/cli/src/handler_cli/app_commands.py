"""`handler app …` — apps (contract H, apps design): small web apps written by
an agent, run by handlerd on demand, each at its own origin (http://<name>.localhost:<port>/).

handler app list                   your apps, their versions and state, and where each comes
                                   from: a source's id, or "yours" (a file or a draft: no source
                                   offers it a new version)
handler app add [PATH]             give Handler an app's code: an app file (.zip, an export) or
                                   the folder holding its app.toml (default: here), zipped
                                   without .git and node_modules; a new app, or the next version
                                   of one you have (Handler keeps its own copy: changing the
                                   folder afterwards changes nothing until you add it again)
handler app add NAME --from SOURCE an app a source offers (`handler source list`; "official":
                                   Handler's), its code taken the same way
handler app export NAME [-o FILE]  its code as one file, NAME-VERSION.zip (never its data, what
                                   you gave it or its secrets)
handler app show NAME              what it needs and what you gave it: folders, secrets
handler app folder NAME NEED PATH [--new]
                                   give one of its folder needs a folder (--new: make it)
handler app deploy NAME [--yes] [--automation AUTOMATION]…
                                   install its code as last added: tests, health check on a
                                   copy of the data, then switch (asks first when it may reach
                                   more than before); installing it, the automations it
                                   suggests are listed and none is turned on unless you say so:
                                   asked one by one on a terminal, else only those named with
                                   --automation (repeatable) are made and turned on
handler app update NAME [--yes]    the version its source offers (an app from a source): taken,
                                   then deployed as above (asks first when it may reach more)
handler app rollback NAME          back to the previous version and its data as it was then
handler app open NAME [--print]    open it in its own window (a one-time link): Firefox with
                                   the handler-apps profile, else Chromium's app mode, else the
                                   default browser (HANDLER_APP_BROWSER=firefox|chromium|default)
handler app stop NAME              stop its backend now (it starts again when used)
handler app log NAME               its last deploys and its backend's output
handler app secret NAME SECRET [--unset]
                                   set a secret the app declares (asked for, or read from stdin);
                                   the backend restarts with it
handler app uninstall NAME [--yes] uninstall it: its code, its own data, its jobs' runs and the
                                   automations running them are deleted (your folders stay);
                                   asks first
"""

import argparse
import getpass
import io
import os
import re
import sys
import zipfile
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from . import app_window
from .client import ClientError, Daemon
from .output import table
from .source_commands import source_id


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
    d = a.add_parser("deploy")
    d.add_argument("name")
    d.add_argument("--yes", action="store_true", help="do not ask about new needs")
    d.add_argument("--automation", action="append", default=[], metavar="AUTOMATION",
                   help="make and turn on this suggested automation (repeatable)")  # fmt: skip
    u = a.add_parser("update")
    u.add_argument("name")
    u.add_argument("--yes", action="store_true", help="do not ask about new needs")
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


def describe(app: dict[str, Any]) -> str:
    """The app in a few lines."""
    current = app.get("current")
    installed = current["version"] if current else "not deployed"
    lines = [f"{app['name']} {installed} ({app['state']}) — {app['url']}"]
    source = app["source"]
    if source.get("error"):
        lines.append(f"  source: {source['error']}")
    elif not current or source.get("version") != current["version"]:
        lines.append(f"  source: {source.get('version')} ready to deploy")
    if offered := app.get("offered"):
        lines.append(f"  {offered['version']} offered by {offered['source']} (handler app update)")
        if offered.get("changes"):
            lines.append(f"    {offered['changes']}")
    for f in app.get("files", []):
        given = f.get("path") or "not given (handler app folder)"
        lines.append(f"  folder {f['name']} ({f['mode']}): {given}")
    if missing := [s["name"] for s in app.get("secrets", []) if not s["set"]]:
        lines.append(f"  secrets not set: {', '.join(missing)} (handler app secret)")
    if app.get("error"):
        lines.append(f"  error: {app['error']}")
    return "\n".join(lines)


def list_apps(d: Daemon, _: argparse.Namespace) -> int:
    rows = [["NAME", "VERSION", "STATE", "SOURCE", "FROM", "URL"]]
    for app in d.call("GET", "/v1/apps"):
        current = app.get("current")
        source = app["source"].get("version") or "invalid"
        rows.append(
            [
                app["name"],
                current["version"] if current else "-",
                app["state"],
                source if not current or source != current["version"] else "=",
                app.get("fromSource") or "yours",
                app["url"],
            ]
        )
    table(rows)
    return 0


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
        where = f"/v1/sources/{quote(source_id(d, args.source_id), safe='')}"
        r = d.request("POST", f"{where}/apps/{quote(args.path, safe='')}", timeout=300)
    else:
        r = d.request("POST", "/v1/apps", content=app_file(args.path), timeout=300)
    app = r.json()
    print(describe(app))
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
    print(describe(d.call("GET", f"/v1/apps/{args.name}")))
    return 0


def folder(d: Daemon, args: argparse.Namespace) -> int:
    body = {"path": os.path.abspath(os.path.expanduser(args.path)), "create": args.new}
    print(describe(d.call("PUT", f"/v1/apps/{args.name}/files/{args.need}", body)))
    return 0


def suggested(app: dict[str, Any], s: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """A suggested automation's name and definition (I.1), as the web UI makes it: the app's
    name and its description's words, and the app's results opening it."""
    words = re.sub(r"[^a-z0-9]+", "-", s["description"].lower()).strip("-")
    name = f"{app['name']}-{words}"[:64].rstrip("-")
    definition = {"apiVersion": "handler.automation/v1", "description": s["description"],
                  "when": s["when"]}  # fmt: skip
    # one of the app's jobs (H.1), or one of its routes (I.3): its results open the app
    run = s["run"]
    if run.get("call"):
        definition["run"] = {"app": app["name"], "call": run["call"]}
    else:
        definition["run"] = {"app": app["name"], "job": run["job"], "input": run.get("input", {})}
    return name, definition


def when_words(when: dict[str, Any]) -> str:
    if when.get("every"):
        return f"every {when['every']}"
    return f"at {when['at']}" + (f" on {','.join(when['days'])}" if when.get("days") else "")


Offered = tuple[str, dict[str, Any], str, dict[str, Any]]


def offered_of(app: dict[str, Any]) -> list[Offered]:
    """Each suggested automation: its name, definition, when and what in words."""
    offered = []
    for s in app.get("suggests", []):
        name, definition = suggested(app, s)
        does = (
            f"calls {s['run']['call']}"
            if s["run"].get("call")
            else f"runs its job {s['run']['job']}"
        )
        words = f"{when_words(s['when'])}, {does}"
        offered.append((name, definition, words, s))
    return offered


def problems_of(d: Daemon, offered: list[Offered]) -> dict[str, list[str]]:
    """Why each that cannot be turned on cannot (`POST /v1/automations/check`, I.9)."""
    problems = {}
    for name, definition, *_ in offered:
        body = {"definition": definition}
        if found := d.call("POST", "/v1/automations/check", body).get("problems"):
            problems[name] = found
    return problems


def to_turn_on(d: Daemon, app: dict[str, Any], named: list[str]) -> list[dict[str, Any]]:
    """The suggested automations to make and turn on (contract H.1): listed when installing,
    each asked on a terminal (none by default), else those `named` alone; any deploy makes those
    named (one not made yet). One that cannot be turned on (its problems, I.9: an account whose
    terms refuse runs nobody follows, say) is not offered, its problems said; named, it is an
    error before anything is deployed. Each is the body of its `POST /v1/automations`."""
    made = {v["name"] for v in d.call("GET", "/v1/automations")}
    offered = offered_of(app)
    if unknown := sorted(set(named) - {o[0] for o in offered}):
        known = ", ".join(o[0] for o in offered) or "none"
        raise ClientError(f"{app['name']} suggests no automation {', '.join(unknown)} ({known})")
    waiting = [o for o in offered if o[0] not in made]
    if not waiting or (app.get("current") and not named):
        return []
    problems = problems_of(d, waiting)
    if cannot := sorted(set(named) & problems.keys()):
        raise ClientError(
            "; ".join(f"cannot turn on {n}: {'; '.join(problems[n])}" for n in cannot)
        )
    asking = not named and sys.stdin.isatty()
    jobs = any(not s["run"].get("call") for *_, s in waiting)  # a call is its code: no model
    advice = " (an API key is recommended rather than your subscription)" if jobs else ""
    print(f"{app['name']} suggests runs of its own, with nobody following{advice}:")
    for name, _, words, s in waiting:
        print(f"  {name}: {s['description']} ({words})")
        for problem in problems.get(name, []):
            print(f"    cannot be turned on: {problem}")
    chosen = []
    for name, definition, words, _ in waiting:
        if name in problems:
            on = False
        elif asking:
            on = input(f"Turn on {name}: {words}? [y/N] ").strip().lower() == "y"
        else:
            on = name in named
        if on:
            chosen.append({"name": name, "definition": definition, "enable": True})
    if left := [n for n, *_ in waiting if n not in {c["name"] for c in chosen}]:
        print(f"not turned on: {', '.join(left)}; make one later from {app['name']}'s page in "
              "the web UI, then turn it on there or with handler automation enable NAME")  # fmt: skip
    return chosen


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
    turn_on = to_turn_on(d, app, args.automation)
    print(f"deploying {args.name} {app['source']['version']} (tests, health check)…")
    print(describe(d.call("POST", f"/v1/apps/{args.name}/deploy")))
    for body in turn_on:
        made = d.call("POST", "/v1/automations", body)
        print(f"{made['name']}: made, {'on' if made.get('enabled') else 'off'}")
    return 0


def update(d: Daemon, args: argparse.Namespace) -> int:
    """The version its source offers, taken then deployed (H.6)."""
    app = d.call("GET", f"/v1/apps/{args.name}")
    offered = app.get("offered")
    if not offered:
        raise ClientError(f"{args.name}: its source offers no other version")
    if offered.get("changes"):
        print(f"{args.name} {offered['version']}: {offered['changes']}")
    if (added := offered.get("addedNeeds")) and not args.yes:
        print(f"{args.name} {offered['version']} may reach more than before:")
        for need in added:
            print(f"  + {need}")
        if input("Update? [y/N] ").strip().lower() != "y":
            return 1
    print(f"updating {args.name} to {offered['version']} (tests, health check)…")
    print(describe(d.call("POST", f"/v1/apps/{args.name}/update")))
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
    print(f"Uninstalling {args.name} deletes its code, the data it keeps for itself, its jobs'")
    print("runs and the automations running them. Your folders stay:")
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
    "deploy": deploy,
    "update": update,
    "open": open_app,
    "log": log,
    "secret": secret,
    "uninstall": uninstall,
    "rollback": action,
    "stop": action,
}


def dispatch(args: argparse.Namespace) -> int:
    return COMMANDS[args.app_cmd](Daemon(), args)
