"""Sessions from the command line — the agent runs in the daemon (contract F), the terminal is one
more attachment, so the web UI and a paired phone see the same session.

    handler run [AGENT|ACCOUNT|PROVIDER] [-p REQUEST] [agent options] [--remote] [--detach]
                [--anyway]
            a session in the current directory. In a project's folder (or below): the project's
            agent of that name, or the one whose model is that account or provider (the
            default agent first; --harness, --model: which one), else its default agent with
            that account or provider this time; one not made for the
            project's area is refused unless --anyway. No name: the default agent.
            Elsewhere, or with --anyway: the ad-hoc agent of the folder and --name, with that
            account or provider this time (default: the only one ready; a provider's harness:
            --harness, or the only one speaking its protocol). Agent options that differ from
            the agent's settings are saved to it once you say yes (--save without a terminal),
            never ignored
    handler attach [SESSION] [--stdio]
            back to a session in the terminal: a running one is joined, a stopped one restarted
            with its conversation (when its harness can reload it). Default: the last active
            session of the current directory, running ones first. --stdio: as a plain stdio ACP
            agent, for other ACP clients
    handler session list [--all]      running sessions (--all: stopped ones too), most recently
                                      active first
    handler session show SESSION      its agent, model, folder, state, sharing
    handler session stop SESSION      stop its sandbox (the conversation is kept: attach resumes it)
    handler session share SESSION [--off]
                                      share a running session with your paired devices, or stop

The terminal client is built in. To use another ACP client instead, set HANDLER_ACP_CLIENT to its
command, `{bridge}` standing for the command of the stdio bridge, e.g.
    HANDLER_ACP_CLIENT='toad acp "{bridge}"'
"""

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any

from . import terminal
from .agent_commands import program
from .client import ClientError, Daemon
from .output import table
from .session_bridge import run_session_bridge

START_TIMEOUT = 300.0


def add_parsers(sub: Any, add_agent_options: Any) -> None:
    run = sub.add_parser(
        "run",
        help="a session in the current directory",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run.add_argument("access", nargs="?", metavar="AGENT|ACCOUNT|PROVIDER")
    run.add_argument("-p", "--prompt", metavar="REQUEST", help="the first request")
    run.add_argument("--remote", action="store_true", help="share it with your paired devices")
    run.add_argument("--detach", action="store_true", help="start it, do not attach")
    add_agent_options(run)
    add_anyway_option(run)
    attach = sub.add_parser("attach", help="back to a session (a stopped one is resumed)")
    attach.add_argument("session", nargs="?")
    attach.add_argument("--stdio", action="store_true", help="as a stdio ACP agent (for clients)")
    session = sub.add_parser("session", help="sessions", description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    s = session.add_subparsers(dest="session_cmd", required=True)
    s.add_parser("list").add_argument("--all", action="store_true", help="stopped ones too")
    for name in ("show", "stop"):
        s.add_parser(name).add_argument("session")
    share = s.add_parser("share")
    share.add_argument("session")
    share.add_argument("--off", action="store_true", help="stop sharing it")


def project_of(d: Daemon, folder: str) -> dict[str, Any] | None:
    """The project whose folder is `folder` or contains it (the innermost one)."""
    found = [
        p
        for p in d.call("GET", "/v1/projects")
        if folder == p["folder"] or folder.startswith(p["folder"].rstrip("/") + "/")
    ]
    found.sort(key=lambda p: len(p["folder"]))
    return found[-1] if found else None


def add_anyway_option(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--anyway",
        action="store_true",
        help="in a project's folder: run that account or provider ad hoc, outside the project",
    )


def project_agent(
    d: Daemon, name: str | None, folder: str, args: Any
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    """In a project's folder (or below), the agent of that project to use and the model it runs
    with (None: the agent's): the agent named `name`, else the one whose model is account or
    provider `name` (the default agent first; narrowed by --harness and --model), else the
    default agent on `name`, for this session only (D.19). None outside
    projects and with --anyway. ClientError when `name` is not made for the project's area:
    the folder decides which account works in it; --anyway, acknowledged, runs it outside."""
    project = project_of(d, folder)
    if project is None:
        return None
    if args.anyway:
        acknowledge_outside(d, project, name, args)
        return None
    agents = sorted(project["agents"], key=lambda a: a["id"] != project.get("defaultAgent"))
    if args.name:
        raise ClientError(
            f"--name: in a project's folder, name one of its agents: handler {args.cmd} AGENT"
        )
    if (agent := agent_named(project, name)) is not None:
        return settle_flags(d, agent, args, project), None
    harness, model = getattr(args, "harness", None), getattr(args, "model", None)
    for agent in agents:
        m = agent["model"]
        chosen = harness in (None, m.get("harness")) and model in (None, m.get("model"))
        if uses(m) == name and chosen:
            return settle_flags(d, agent, args, project), m
    assert name is not None  # else the default agent, above
    access = [*d.call("GET", "/v1/accounts"), *d.call("GET", "/v1/providers")]
    if name not in {x["name"] for x in access}:
        names = ", ".join(agent_label(a) for a in agents)
        raise ClientError(f"no agent, account or provider '{name}' in {project['name']} "
                          f"(its agents: {names})")  # fmt: skip
    if (refused := not_for(d, project, name)) is not None:
        raise ClientError(
            f"{refused}: not started. To run it here outside the project: "
            f"handler {args.cmd} {described(name, harness, model)} --anyway"
        )
    agent = settle_flags(d, agents[0], args, project)
    access = model_access(d, name, harness) | ({"model": model} if model else {})
    return agent, access


def not_for(d: Daemon, project: dict[str, Any], name: str) -> str | None:
    """Why that account or provider may not run in the project (its area, D.19), or None."""
    area = project.get("area")
    if area is None:
        return None
    found = [*d.call("GET", "/v1/accounts"), *d.call("GET", "/v1/providers")]
    made = next((x.get("areas", []) for x in found if x["name"] == name), [])
    if area in made or "any" in made:
        return None
    return f"{name} is for {', '.join(made) or 'no area'}; {project['name']} is a {area} project"


def acknowledge_outside(d: Daemon, project: dict[str, Any], name: str | None, args: Any) -> None:
    """--anyway in a project's folder with an account or provider not made for its area: the
    person confirms it in a terminal, typing yes (D.19); without a terminal, refused."""
    name = name or default_access(d)
    if (refused := not_for(d, project, name)) is None:
        return
    warning = f"{refused}. It will work in {project['folder']}, outside the project."
    if not sys.stdin.isatty():
        raise ClientError(f"{warning} Not started: confirm it in a terminal (handler {args.cmd})")
    print(f"handler: ⚠ {warning}", file=sys.stderr)
    if input("Type yes to start: ").strip().lower() != "yes":
        raise ClientError("not started")


def described(name: str | None, harness: str | None, model: str | None) -> str:
    return " ".join([str(name), *([f"--harness {harness}"] if harness else [])]) + (
        f" --model {model}" if model else ""
    )


def flag_changes(agent: dict[str, Any], args: Any) -> tuple[dict[str, Any], list[str]]:
    """What the agent flags typed (cli.add_agent_options) change in the agent's settings: those
    settings, and each change in words. A flag not typed changes nothing; --allow, --binding and
    --knowledge add to its lists. (--name says which agent; the account or provider, --harness
    and --model, the model this time only, D.19.)"""
    changed: dict[str, Any] = {}
    said: list[str] = []
    wanted = {
        "network": args.network,
        "egress": "log-only" if args.log_only else None,
        "confinement": "nested" if args.containers else None,
        "permissions": args.permissions,
        "display": True if args.display else None,
    }
    for key, value in wanted.items():
        now = agent.get(key, False if key == "display" else None)
        if value is not None and now != value:
            changed[key] = value
            said.append(f"{key} {shown(now)} → {shown(value)}")
    lists = {"allow": args.allow, "bindings": args.binding, "knowledge": args.knowledge}
    for key, given in lists.items():
        if added := sorted(set(given or []) - set(agent.get(key, []))):
            changed[key] = sorted({*agent.get(key, []), *added})
            said.append(f"{key} + {', '.join(added)}")
    return changed, said


def shown(value: Any) -> str:
    return {True: "on", False: "off", None: "none"}.get(value, str(value))


def settle_flags(
    d: Daemon, agent: dict[str, Any], args: Any, project: dict[str, Any] | None
) -> dict[str, Any]:
    """The agent once the flags that differ from its settings are saved to it: never ignored.
    In a terminal, the person says yes (the confirmation of what they widen, D.8); without one,
    --save; else refused, saying what differs. Returns the agent as it is now."""
    changed, said = flag_changes(agent, args)
    if not changed:
        return agent
    differs = f"agent {agent_label(agent)}: {'; '.join(said)} (its settings: not this)"
    if not args.save:
        if not sys.stdin.isatty():
            raise ClientError(
                f"{differs}. Not started: --save saves it to the agent, "
                "--name NAME makes another agent"
            )
        print(f"handler: {differs}", file=sys.stderr)
        if input("Save this to the agent? [y/N] ").strip().lower() not in ("y", "yes"):
            raise ClientError("not started (--name NAME makes another agent)")
    body = request_of(agent, project) | changed
    path = f"/v1/agents/{agent['id']}"
    try:
        return d.call("PUT", path, body)
    except ClientError as e:
        if (e.status, e.title) != (409, "risks not confirmed"):
            raise
        print(f"handler: this agent gets {e.detail}", file=sys.stderr)  # saying yes confirmed it
        return d.call("PUT", path, body | {"confirmRisks": True})


SETTINGS = ("network", "egress", "allow", "confinement", "permissions", "bindings", "knowledge")
SETTINGS += ("display", "interface")


def request_of(agent: dict[str, Any], project: dict[str, Any] | None) -> dict[str, Any]:
    """The request that saves the agent as it is (D.2 `AgentRequest`), its home unchanged."""
    own = ("projectId", "app", "chat", "name", "description", "instructions", "skills", "origin")
    own += ("remoteStart",) if project is not None else ("scope",)
    body = {k: agent[k] for k in (*SETTINGS, *own) if agent.get(k) is not None}
    body["model"] = access_of(agent["model"])
    if project is not None:
        body["default"] = agent["id"] == project.get("defaultAgent")
    return body


def open_ad_hoc(d: Daemon, args: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Outside projects (or --anyway): the ad-hoc agent of the folder and --name, made with the
    flags typed when it is new (D.1: the same command in the same folder gives the same agent),
    and the model it runs with this time: the account or provider named."""
    access = model_access(d, args.access, args.harness) | (
        {"model": args.model} if args.model else {}
    )
    scope = os.path.abspath(args.scope)
    name = (args.name or "").strip().lower()
    agent = next(
        (
            a
            for a in d.call("GET", "/v1/agents")
            if a.get("projectId") is None
            and a.get("app") is None
            and not a.get("chat")
            and a.get("scope") == scope
            and (a.get("name") or "").lower() == name
        ),
        None,
    )
    if agent is not None:
        return settle_flags(d, agent, args, None), access
    body: dict[str, Any] = {"model": access, "scope": scope}
    if args.name:
        body["name"] = args.name
    changed, _ = flag_changes({}, args)  # every flag typed
    try:
        agent = d.call("POST", "/v1/agents", body | changed)
    except ClientError as e:
        if (e.status, e.title) != (409, "risks not confirmed"):
            raise
        # the flags that widen it were typed: they are the confirmation (D.8), said on stderr
        print(f"handler: this agent gets {e.detail}", file=sys.stderr)
        agent = d.call("POST", "/v1/agents", body | changed | {"confirmRisks": True})
    return agent, access


def agent_named(project: dict[str, Any], name: str | None) -> dict[str, Any] | None:
    agents = project["agents"]
    if name is None:
        return next((a for a in agents if a["id"] == project.get("defaultAgent")), agents[0])
    return next((a for a in agents if agent_label(a).lower() == name.lower()), None)


def agent_label(agent: dict[str, Any]) -> str:
    return agent.get("name") or program(agent["model"])


def uses(model: dict[str, Any]) -> str:
    """The account or provider a model's calls use."""
    return model.get("account") or model.get("provider") or ""


def default_access(d: Daemon) -> str:
    """The only account or provider ready."""
    ready = [a["name"] for a in d.call("GET", "/v1/accounts") if a["status"] == "ready"]
    ready += [p["name"] for p in d.call("GET", "/v1/providers") if p["status"] == "ready"]
    if len(ready) == 1:
        return ready[0]
    raise ClientError(f"which account or provider? {', '.join(ready) or 'none ready'}")


def model_access(d: Daemon, name: str, harness: str | None) -> dict[str, Any]:
    """What an ad-hoc agent runs as, for an account or provider name: the account (its harness), or
    the provider with `harness`, else the only harness speaking its protocol."""
    if any(a["name"] == name for a in d.call("GET", "/v1/accounts")):
        return {"account": name} | ({"harness": harness} if harness else {})
    provider = next((p for p in d.call("GET", "/v1/providers") if p["name"] == name), None)
    if provider is None:
        raise ClientError(
            f"no account or provider '{name}' (handler account list; Settings → Model access)"
        )
    if harness is None:
        speaking = provider.get("harnesses", [])
        if len(speaking) != 1:
            raise ClientError(
                f"which harness for provider '{name}'? --harness {' | '.join(speaking)}"
            )
        harness = speaking[0]
    return {"provider": name, "harness": harness}


def access_of(model: dict[str, Any]) -> dict[str, Any]:
    """A model as a request names it (without what handlerd adds: its problem, the
    hosts it requires)."""
    return {k: model[k] for k in ("harness", "account", "provider", "model") if k in model}


def labels(d: Daemon) -> dict[str, str]:
    """agent id → "project · agent", for the agents of projects."""
    return {
        a["id"]: f"{p['name']} · {agent_label(a)}"
        for p in d.call("GET", "/v1/projects")
        for a in p["agents"]
    }


def wait_running(d: Daemon, session: dict[str, Any]) -> dict[str, Any]:
    deadline = time.monotonic() + START_TIMEOUT
    while session["state"] == "starting" and time.monotonic() < deadline:
        time.sleep(0.2)
        session = d.call("GET", f"/v1/sessions/{session['id']}")
    if session["state"] != "running":
        raise ClientError(f"the session did not start: {session.get('error') or session['state']}")
    return session


def open_session(
    d: Daemon,
    agent_id: str,
    args: argparse.Namespace,
    prompt: str | None,
    model: dict[str, Any] | None = None,
) -> int:
    body: dict[str, Any] = {"agentId": agent_id}
    if prompt:
        body["prompt"] = prompt
    if model is not None:
        body["model"] = access_of(model)
    session = d.call("POST", "/v1/sessions", body)
    print(f"session {session['id']} — in the web UI: {d.url}/#/sessions/{session['id']}")
    if args.remote:
        session = wait_running(d, session)
        d.call("PUT", f"/v1/sessions/{session['id']}/remote", {"enabled": True})
        print("shared with your paired devices")
    if args.detach:
        return 0
    return use(d, session)


def use(d: Daemon, session: dict[str, Any]) -> int:
    """The terminal client, or the one HANDLER_ACP_CLIENT names."""
    if command := os.environ.get("HANDLER_ACP_CLIENT"):
        handler = shutil.which("handler") or sys.argv[0]
        bridge = f"{shlex.quote(handler)} attach --stdio {session['id']}"
        return subprocess.call(
            command.replace("{bridge}", bridge), shell=True
        )  # the user's own command
    return terminal.attach(d, session)


def dispatch(d: Daemon, args: argparse.Namespace) -> int:
    here = os.path.abspath(".")
    if args.cmd == "run":
        if (found := project_agent(d, args.access, here, args)) is not None:
            agent, model = found
            return open_session(d, agent["id"], args, args.prompt, model)
        args.access = args.access or default_access(d)
        args.scope = here
        agent, model = open_ad_hoc(d, args)
        return open_session(d, agent["id"], args, args.prompt, model)
    if args.cmd == "attach":
        session = find_session(d, args.session, here)
        if args.stdio:
            return run_session_bridge(d, session)
        return use(d, session)
    if args.session_cmd == "list":
        print_sessions(d, args.all)
    elif args.session_cmd == "show":
        show_session(d, d.call("GET", f"/v1/sessions/{args.session}"))
    elif args.session_cmd == "stop":
        d.call("POST", f"/v1/sessions/{args.session}/stop")
        print(f"session {args.session}: stopped (handler attach {args.session} resumes it)")
    else:
        body = {"enabled": not args.off}
        d.call("PUT", f"/v1/sessions/{args.session}/remote", body)
        shared = "not shared" if args.off else "shared with your paired devices"
        print(f"session {args.session}: {shared}")
    return 0


def find_session(d: Daemon, session_id: str | None, here: str) -> dict[str, Any]:
    """The session named, else this directory's last active one, running ones first; a stopped
    one only when it can resume (its harness reloads a conversation)."""
    if session_id:
        session = d.call("GET", f"/v1/sessions/{session_id}")
    else:
        mine = [s for s in d.call("GET", "/v1/sessions") if s["scope"] == here]  # most recent first
        live = [s for s in mine if s["state"] in ("running", "starting")]
        resumable = [s for s in mine if s.get("canResume")]
        if not (live or resumable):
            raise ClientError(f"no session to come back to in {here} (handler session list --all)")
        session = (live or resumable)[0]
    if session["state"] in ("running", "starting"):
        return session
    if not session.get("canResume"):
        raise ClientError(
            f"session {session['id']} is {session['state']} and cannot be resumed: its harness "
            "cannot reload a conversation"
        )
    print(f"resuming session {session['id']}…", file=sys.stderr)
    return session


def show_session(d: Daemon, s: dict[str, Any]) -> None:
    access = f"account {s['account']}" if s.get("account") else f"provider {s.get('provider')}"
    model = f" · {s['model']}" if s.get("model") else ""
    state = s["state"]
    if s.get("pendingPermissions"):
        state = "needs you"
    elif s.get("busy"):
        state = "working"
    elif s.get("waitingFor"):
        state = f"waiting for its agent's run {s['waitingFor']}"
    print(f"{s['id']} · {labels(d).get(s['agentId'], s['harness'])} · {state}")
    if s.get("title"):
        print(f"  {s['title']}")
    print(f"  runs      {s['harness']} · {access}{model}")
    print(f"  folder    {s['scope']}")
    origin = f"app {s['app']}" if s.get("app") else s.get("origin", "ui")
    print(f"  started   {s['createdAt'][:16].replace('T', ' ')} ({origin})")
    print(f"  active    {s['lastActivityAt'][:16].replace('T', ' ')}")
    shared = ", shared with your paired devices" if s.get("remote") else ""
    print(f"  attached  {s.get('attached', 0)} client(s){shared}")
    if s["state"] not in ("running", "starting"):
        resume = f"handler attach {s['id']}" if s.get("canResume") else "not possible"
        print(f"  resume    {resume}")
    if s.get("error"):
        print(f"  error     {s['error']}")
    print(f"  web UI    {d.url}/#/sessions/{s['id']}")


def print_sessions(d: Daemon, everything: bool) -> None:
    names = labels(d)
    rows = [["SESSION", "STATE", "AGENT", "TITLE", "FOLDER"]]
    for s in d.call("GET", "/v1/sessions"):
        if not everything and s["state"] not in ("running", "starting"):
            continue
        state = s["state"]
        if s.get("pendingPermissions"):
            state = "needs you"
        elif s.get("busy"):
            state = "working"
        elif s.get("waitingFor"):
            state = "waiting"
        agent = names.get(s["agentId"], s.get("harness") or "the model alone")
        rows.append([s["id"], state, agent, (s.get("title") or "-")[:50], s["scope"]])
    table(rows)
