"""`handler app …` — mini apps (contract H, docs/dev/design/miniapps.md): small web apps written by
an agent, run by handlerd on demand, each at its own origin (http://<name>.localhost:<port>/).

handler app list                   registered apps, their versions and state
handler app add [DIR]              register the app whose app.toml is in DIR (default: here)
handler app deploy NAME [--yes]    install what its folder holds now: tests, health check on a
                                   copy of the data, then switch (asks first when it may reach
                                   more than before)
handler app rollback NAME          back to the previous version and its data as it was then
handler app open NAME [--print]    open it in its own window (a one-time link): Firefox with
                                   the handler-apps profile, else Chromium's app mode, else the
                                   default browser (HANDLER_APP_BROWSER=firefox|chromium|default)
handler app shortcut NAME KEYS|--none  the GNOME keyboard shortcut that opens it, e.g. "<Super>n"
handler app stop NAME              stop its backend now (it starts again when used)
handler app log NAME               its last deploys and its backend's output
handler app secret NAME SECRET [--unset]
                                   set a secret the app declares (asked for, or read from stdin);
                                   the backend restarts with it
handler app rm NAME                unregister it; its data folder is kept
"""

import argparse
import getpass
import os
import sys
from collections.abc import Callable
from typing import Any

from . import app_window
from .client import ClientError, Daemon
from .output import table


def add_parser(sub: Any) -> None:
    app = sub.add_parser("app", help="mini apps", description=__doc__,
                         formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    a = app.add_subparsers(dest="app_cmd", required=True)
    a.add_parser("list")
    a.add_parser("add").add_argument("dir", nargs="?", default=".")
    d = a.add_parser("deploy")
    d.add_argument("name")
    d.add_argument("--yes", action="store_true", help="do not ask about new needs")
    o = a.add_parser("open")
    o.add_argument("name")
    o.add_argument("--print", action="store_true", help="only print the link")
    sc = a.add_parser("shortcut")
    sc.add_argument("name")
    keys = sc.add_mutually_exclusive_group(required=True)
    keys.add_argument("keys", nargs="?", help='GNOME accelerator, e.g. "<Super>n"')
    keys.add_argument("--none", action="store_true", help="remove its shortcut")
    sec = a.add_parser("secret")
    sec.add_argument("name")
    sec.add_argument("secret")
    sec.add_argument("--unset", action="store_true")
    for name in ("rollback", "stop", "log", "rm"):
        a.add_parser(name).add_argument("name")


def describe(app: dict[str, Any]) -> str:
    current = app.get("current")
    installed = current["version"] if current else "not deployed"
    lines = [f"{app['name']} {installed} ({app['state']}) — {app['url']}"]
    source = app["source"]
    if source.get("error"):
        lines.append(f"  source: {source['error']}")
    elif not current or source.get("version") != current["version"]:
        lines.append(f"  source: {source.get('version')} ready to deploy")
    if missing := [s["name"] for s in app.get("secrets", []) if not s["set"]]:
        lines.append(f"  secrets not set: {', '.join(missing)} (handler app secret)")
    if app.get("shortcut"):
        lines.append(f"  shortcut: {app['shortcut']}")
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


def add(d: Daemon, args: argparse.Namespace) -> int:
    print(describe(d.call("POST", "/v1/apps", {"sourceDir": os.path.abspath(args.dir)})))
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


def shortcut(d: Daemon, args: argparse.Namespace) -> int:
    keys = None if args.none else args.keys
    app = d.call("PUT", f"/v1/apps/{args.name}/shortcut", {"shortcut": keys})
    print(f"{args.name}: {app.get('shortcut') or 'no shortcut'}")
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


def remove(d: Daemon, args: argparse.Namespace) -> int:
    d.call("DELETE", f"/v1/apps/{args.name}")
    print(f"{args.name}: removed (its data folder is kept)")
    return 0


def action(d: Daemon, args: argparse.Namespace) -> int:
    """rollback, stop: a POST that answers the app."""
    print(describe(d.call("POST", f"/v1/apps/{args.name}/{args.app_cmd}")))
    return 0


COMMANDS: dict[str, Callable[[Daemon, argparse.Namespace], int]] = {
    "list": list_apps,
    "add": add,
    "deploy": deploy,
    "open": open_app,
    "log": log,
    "secret": secret,
    "shortcut": shortcut,
    "rm": remove,
    "rollback": action,
    "stop": action,
}


def dispatch(args: argparse.Namespace) -> int:
    return COMMANDS[args.app_cmd](Daemon(), args)
