"""handler — run coding agents in sandboxes on your machine. Each command talks to handlerd,
the daemon that keeps the agents running (`handler setup` installs it).

Working with agents:
    handler run [AGENT|ACCOUNT|PROVIDER] [-p REQUEST] [agent options] [--remote] [--detach]
                [--anyway]                   a session in the current directory, in the terminal
                                             (also shown in the web UI): the project's agent in a
                                             project's folder, else ad hoc (`handler run -h`)
    handler attach [SESSION] [--stdio]       back to a session: a running one is joined, a stopped
                                             one resumed
    handler terminal AGENT|ACCOUNT|PROVIDER [FOLDER] [agent options] [--anyway] [-- ARGS …]
                                             the harness's own terminal UI (e.g. Claude Code's) in
                                             its sandbox, ARGS given to it; not a session: one
                                             sandbox, gone when it exits
    handler acp AGENT|ACCOUNT|PROVIDER [FOLDER] [agent options] [--anyway]
                                             ACP on stdio, for editors (e.g. Zed): an agent of the
                                             folder's project (a session shown in the web UI), else
                                             an account or a provider (one sandbox for this
                                             connection)

What exists (`handler NOUN -h` for each):
    handler session list | show | stop | share   sessions
    handler agent list | show | rm | network | checks
                                                 agents, their network (log-only, enforce),
                                                 their checks
    handler project list | show | export-agents | import-agents
                                                 projects (created and edited in the web UI),
                                                 their agents to a file and back
    handler account list | add | token | login | import | rm
                                                 subscriptions and their login
    handler provider list | templates | add | test | rm
                                                 API keys and local model servers
    handler secret list | set | rm               the secret store
    handler tool list | add | rm                 tools an agent can get
    handler source list | add | refresh | rm     where apps, agents and tools come from
    handler connection list                      tools with their settings and secrets
    handler notes list                           notes folders an agent can get
    handler image list | rebuild                 the images agents run in
    handler toolbox [packages | add | rm | lines]
                                                 the system every agent works in
    handler app …                                apps: install, deploy, open
    handler automation …                         when a session stops or at a time, run a script,
                                                 an agent or an app's route
    handler plan check | run | list | show | cancel | delete
                                                 plans: steps an agent wrote in its folder,
                                                 approved by you, run one after another
    handler inbox                                what handler told you: apps' notifications,
                                                 agents' results, failed runs
    handler ask "…"                              say what you want: Handler picks which of
                                                 your apps does it, and runs it

Handler itself:
    handler setup [--no-build] [--yes] [--program NAME] [--runtime NAME] [--engine PACKAGE]
                  [--verbose]                    after installing: start handlerd as a service,
                                                 check this machine, build the images
    handler daemon status | install | uninstall | log
                                                 handlerd as a user service (systemd, launchd)
    handler runtime list | use NAME              the sandbox runtime agents run in (podman…)
    handler ui [--print]                         open the web UI, signed in (a one-time link)

FOLDER defaults to the current directory, inside one of the work folders (set in the web UI,
Settings → Folders). A notes FOLDER is a path relative to the notes root (see `handler notes
list`; set in the web UI), or an absolute path inside it; the agent sees it read-only at
/notes/<folder name>. Outside projects the sandbox starts with only these sites on its network,
enforced (--log-only lets every host through and logs it, to learn which it needs), strict
confinement, permissions bypass. A flag that widens it (--network open, --log-only, --containers)
is your confirmation: handler says on stderr what it gives the agent.
--allow adds hosts to a filtered agent's (on top of those its account or provider and its
tools require); --keep-blocked adds hosts it keeps blocked, which it is told not to ask for (a
host is allowed or kept blocked, never both: either flag takes it off the other list).
--permissions sets the agent's starting mode: ask (you answer each request),
accept-edits (file edits allowed) or bypass (unsupervised); the session can change it.
--containers lets the agent run containers itself (nested confinement). --display gives the agent's
sandbox your Wayland display, e.g. to watch the browser of the playwright tool, and its
clipboard (the agent can then read what you copy); nothing else of your desktop. Pasting an image
in `handler terminal` (Ctrl+V) does not need it.

An ACCOUNT runs its own harness; a PROVIDER runs the harness --harness names (or the only one
that speaks its protocol). --model picks the model (default: the harness's or the provider's).
The account or provider and the model are for this time only: never saved to the agent.

Outside projects, the agent is the one of the folder and its --name (none: the unnamed one):
the same command in the same folder always gives the same agent, made with the flags typed
the first time. In a project's folder (or below), `run`, `acp` and `terminal` use the project's
agent named AGENT, or the one using that ACCOUNT or PROVIDER (default agent first); an account
or provider none of its agents uses runs the default agent, unless it is not made for the
project's area (refused; --anyway runs it there outside the project). A flag that differs
from the agent's settings is never ignored: handler says what differs and asks "Save this to the
agent?" (yes saves it, no starts nothing); without a terminal, --save saves it, else it is
refused. Something to try once is another agent: --name NAME (outside projects).
Elsewhere, `handler run` without a name takes the only account or provider ready.
The terminal client is built in; HANDLER_ACP_CLIENT names another one (see `handler run -h`).
"""

import argparse
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from urllib.parse import urlencode

from . import (
    account_commands,
    agent_commands,
    app_commands,
    ask_commands,
    automation_commands,
    bridge,
    browser,
    daemon_commands,
    image_commands,
    inbox_commands,
    plan_commands,
    project_commands,
    provider_commands,
    runtime_commands,
    secret_commands,
    session_commands,
    setup,
    source_commands,
    terminal_client,
    tool_commands,
    toolbox_commands,
)
from .client import ClientError, Daemon
from .output import table
from .session_bridge import run_session_bridge


def add_agent_options(s: argparse.ArgumentParser) -> None:
    s.add_argument(
        "--harness",
        help="the harness, for a provider (an account has its own); in a project's folder: "
        "which agent, the one running it",
    )
    s.add_argument(
        "--model",
        help="the model (default: the harness's or the provider's); in a project's folder: "
        "which agent, the one running it",
    )
    s.add_argument("--name", help="a name, e.g. the use case (several per folder are fine)")
    s.add_argument("--network", choices=["none", "filtered", "open"], help="default: filtered")
    s.add_argument(
        "--log-only",
        action="store_true",
        help="filtered: let every host through and log it, to learn which it needs "
        "(default: deny what is not allowed)",
    )
    s.add_argument(
        "--allow",
        action="append",
        metavar="HOST:PORT",
        help="a host to allow (filtered network), on top of the required ones; repeatable",
    )
    s.add_argument(
        "--keep-blocked",
        action="append",
        metavar="HOST:PORT",
        help="a host to keep blocked (filtered network): the agent is told not to ask for it; "
        "repeatable",
    )
    s.add_argument(
        "--tool",
        action="append",
        metavar="NAME[=CONNECTION]",
        help="a tool to give the agent, with the connection filling its settings when it has "
        "some (handler connection list); repeatable",
    )
    s.add_argument(
        "--notes",
        action="append",
        metavar="FOLDER",
        help="a folder of the notes root, mounted read-only at /notes/<name>; repeatable",
    )
    s.add_argument(
        "--permissions",
        choices=["ask", "accept-edits", "bypass"],
        help="the agent's starting permission mode (default: bypass)",
    )
    s.add_argument(
        "--containers",
        action="store_true",
        help="let the agent run containers itself (nested confinement)",
    )
    s.add_argument(
        "--display",
        action="store_true",
        help="give the sandbox your Wayland display and its clipboard (watch a browser)",
    )
    s.add_argument(
        "--save",
        action="store_true",
        help="save the flags that differ from the agent's settings to it, without being asked "
        "(needed without a terminal)",
    )


def acp(d: Daemon, args: argparse.Namespace) -> int:
    """An agent of the folder's project: a daemon session (shown in the web UI) as a stdio agent.
    Otherwise (or --anyway) an account or provider: one sandbox for this connection only."""
    found = session_commands.project_agent(d, args.access, os.path.abspath(args.scope), args)
    if found is not None:
        agent, model = found
        body: dict[str, Any] = {"agentId": agent["id"]}
        if model is not None:
            body["model"] = session_commands.access_of(model)
        return run_session_bridge(d, d.call("POST", "/v1/sessions", body))
    agent, model = session_commands.open_ad_hoc(d, args)
    return bridge.run_bridge(f"{agent['acpUrl']}?{urlencode(model)}", d.token)


def terminal(d: Daemon, args: argparse.Namespace) -> int:
    """D.16: an agent of the folder's project, else (or --anyway) an account or provider; one
    sandbox for this terminal, mounting only the folder (in a project's sub-folder: that one)."""
    folder = os.path.abspath(args.scope)
    found = session_commands.project_agent(d, args.access, folder, args)
    agent, model = found if found is not None else session_commands.open_ad_hoc(d, args)
    model = model or agent["model"]
    print(terminal_identity(d, model), file=sys.stderr)
    return terminal_client.run(d, agent["id"], args.args, folder, session_commands.access_of(model))


def terminal_identity(d: Daemon, model: dict[str, Any]) -> str:
    """Who the harness runs as (the model of this terminal), from handler's own files: the harness's
    terminal cannot tell (a token login says neither the email nor the plan)."""
    if provider := model.get("provider"):
        harness = model["harness"]
        return f"handler: {harness} · provider {provider} (its endpoint and key, no subscription)"
    name = model.get("account")
    account = next((a for a in d.call("GET", "/v1/accounts") if a["name"] == name), {})
    harness = model.get("harness") or account.get("harness")  # a model it does not list: none
    described = f" ({account['description']})" if account.get("description") else ""
    plan = account.get("plan")
    subscription = f"{plan} subscription" if plan else "subscription, plan not set in the account"
    return f"handler: {harness} · account {name}{described} · {subscription}"


def print_notes(d: Daemon) -> None:
    listing = d.call("GET", "/v1/knowledge")
    if not listing["exists"]:
        print(f"no notes root: {listing['root']} does not exist (set it in the web UI)")
        return
    print(f"notes root: {listing['root']} ({listing['source']})")
    for folder in listing["folders"]:
        print(f"  {folder}")


def print_connections(d: Daemon) -> None:
    rows = [["NAME", "TOOL", "SETTINGS", "SECRETS", "ERROR"]]
    for b in d.call("GET", "/v1/bindings"):
        settings = ", ".join(f"{k}={v}" for k, v in b.get("settings", {}).items())
        rows.append(
            [
                b["name"],
                b.get("addon", "?"),
                settings or "-",
                ", ".join(b.get("secrets", [])) or "-",
                b.get("error", "")[:80],
            ]
        )
    table(rows)


def open_ui(*, print_only: bool) -> int:
    """A one-time link: the browser opening it is signed in, and keeps it (a bookmark opens the
    UI from then on); the token itself never reaches the browser."""
    url = Daemon().call("POST", "/v1/ui/open", {})["url"]
    print(url)
    if not print_only:
        browser.open_url(url)
    return 0


def installed_version() -> str:
    """This client's version, read without handlerd (a bug report needs it when handlerd is
    down): the `handler-ai` wheel users install, else this package in a checkout."""
    for distribution in ("handler-ai", "handler-cli"):
        try:
            return version(distribution)
        except PackageNotFoundError:
            pass
    return "unknown"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="handler", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--version", action="version", version=f"handler {installed_version()}")
    sub = p.add_subparsers(dest="cmd", required=True)
    session_commands.add_parsers(sub, add_agent_options)
    for name in ("terminal", "acp"):
        s = sub.add_parser(name)
        s.add_argument("access", metavar="AGENT|ACCOUNT|PROVIDER")
        s.add_argument("scope", nargs="?", default=".", metavar="FOLDER")
        add_agent_options(s)
        session_commands.add_anyway_option(s)
    for module in NOUNS.values():
        module.add_parser(sub)
    for name, help_text in (("connection", "tools with their settings and secrets"),
                            ("notes", "notes folders")):  # fmt: skip
        noun = sub.add_parser(name, help=help_text)
        noun.add_subparsers(dest=f"{name}_cmd", required=True).add_parser("list")
    ui = sub.add_parser("ui", help="open the web UI, signed in")
    ui.add_argument("--print", action="store_true", help="only print the URL")
    return p


# nouns whose module parses and runs its own subcommands
NOUNS: dict[str, Any] = {
    "agent": agent_commands,
    "project": project_commands,
    "account": account_commands,
    "provider": provider_commands,
    "secret": secret_commands,
    "tool": tool_commands,
    "source": source_commands,
    "image": image_commands,
    "toolbox": toolbox_commands,
    "runtime": runtime_commands,
    "app": app_commands,
    "automation": automation_commands,
    "plan": plan_commands,
    "inbox": inbox_commands,
    "ask": ask_commands,
    "daemon": daemon_commands,
    "setup": setup,
}


def dispatch(args: argparse.Namespace) -> int:
    if args.cmd in NOUNS:
        return NOUNS[args.cmd].dispatch(args)
    if args.cmd == "ui":
        return open_ui(print_only=args.print)
    d = Daemon()
    if args.cmd == "connection":
        print_connections(d)
    elif args.cmd == "notes":
        print_notes(d)
    elif args.cmd in ("acp", "terminal"):
        return (acp if args.cmd == "acp" else terminal)(d, args)
    else:
        return session_commands.dispatch(d, args)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    rest: list[str] = []
    if argv[:1] == ["terminal"] and "--" in argv:  # what follows `--` is the harness's
        at = argv.index("--")
        argv, rest = argv[:at], argv[at + 1 :]
    args = parser().parse_args(argv)
    args.args = rest
    try:
        return dispatch(args)
    except ClientError as e:
        print(f"handler: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
