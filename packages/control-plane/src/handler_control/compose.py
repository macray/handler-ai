"""Composition — the only place combining contracts:
HarnessLaunch (B) + the agent's sandbox settings (D.8) + what the selected addons add (G.3)
→ SandboxSpec (A), an app (H) → SandboxSpec (A), an addon image's check (G.4) →
SandboxSpec (A), and an automation's run (I.3) → SandboxSpec (A).

Pure: validates and assembles, never touches the filesystem or starts anything.
"""

import json
import os
from pathlib import Path

from handler_contracts import (
    APP_API_SOCKET,
    APP_CODE_DIR,
    APP_HOME,
    APP_RUN_DIR,
    APP_SOCKET,
    HANDLER_BIN,
    RUNTIME_IMAGE,
    SANDBOX_API_VERSION,
    Addon,
    AppManifest,
    Confinement,
    Enforcement,
    FilteredNetwork,
    HandlerTool,
    HarnessLaunch,
    HostFolder,
    Injection,
    MountKind,
    NetworkMode,
    NetworkPolicy,
    NoNetwork,
    OpenNetwork,
    Paste,
    Resources,
    SandboxSpec,
    SessionMount,
    SocketFolder,
    SystemPackageDaemon,
    TerminalStart,
    WorkFolder,
    is_within,
)

from .addons import AddonLaunch


class ScopeError(ValueError):
    """The requested scope is outside the work folders (D.13), or not a folder."""


class AddonConflictError(ValueError):
    """An addon sets an env var the harness sets too (no silent override)."""


class DaemonConflictError(ValueError):
    """A toolbox daemon's env var is set by the harness or an addon too (no silent override)."""


# B.7: the toolbox's daemons a sandbox has, started by this command before the agent's program.
DAEMONS_TOOL = f"{HANDLER_BIN}/handler-daemons"
DAEMONS_SCRIPT = """#!/bin/sh
# handler: the toolbox's daemons (B.7), each in the background, then the agent's program; what
# each says goes to /tmp/handler-daemons/<command>.log
mkdir -p /tmp/handler-daemons
while [ "$1" != "--" ]; do
  "$1" < /dev/null > "/tmp/handler-daemons/$1.log" 2>&1 &
  shift
done
shift
exec "$@"
"""


def started_daemons(
    daemons: list[SystemPackageDaemon], confinement: Confinement, display: bool
) -> list[SystemPackageDaemon]:
    """Those of the toolbox's daemons a sandbox with these abilities starts (B.7)."""
    has = {confinement, *(["display"] if display else [])}
    return [d for d in daemons if has & set(d.abilities)]


def canonical_scope(scope: str) -> str:
    """Absolute, symlinks resolved (contracts §0)."""
    return os.path.realpath(scope)


def check_scope(work_folders: list[str], scope: str, handler_roots: tuple[str, ...] = ()) -> str:
    """`work_folders`: the machine's (folders.roots); `handler_roots`: folders handler itself keeps
    (the folders of a folderless agent's sessions, D.18), allowed whatever the work folders."""
    resolved = canonical_scope(scope)
    roots = [canonical_scope(r) for r in [*work_folders, *handler_roots]]
    if not any(is_within(resolved, root) for root in roots):
        raise ScopeError(f"{resolved} is outside the work folders ({', '.join(roots)})")
    if not Path(resolved).is_dir():
        raise ScopeError(f"scope {resolved} is not a directory")
    return resolved


def narrowed_scope(scope: str, folder: str) -> str:
    """`folder`, a directory inside the checked `scope`, mounted instead of it (D.16)."""
    resolved = canonical_scope(folder)
    if not is_within(resolved, scope):
        raise ScopeError(f"{resolved} is outside the agent's folder {scope}")
    if not Path(resolved).is_dir():
        raise ScopeError(f"{resolved} is not a directory")
    return resolved


def required_egress(launch: HarnessLaunch, addon_egress: list[str] | None = None) -> list[str]:
    """What a filtered agent reaches whatever its own entries say (A.3): the hosts its
    harness's launch needs and those of its addons. Clients are shown the same hosts with their
    reasons (launcher.required_hosts)."""
    return sorted(set(launch.egress) | set(addon_egress or []))


def network_policy(
    launch: HarnessLaunch,
    mode: NetworkMode,
    enforcement: Enforcement,
    addon_egress: list[str] | None = None,
    *,
    agent_allow: list[str] | None = None,
    blocked: list[str] | None = None,
    injections: list[Injection] | None = None,
) -> NetworkPolicy:
    """The agent's network: in filtered mode, the required hosts and its own, and those the
    person keeps blocked; enforcement live-switchable (A.4). `injections`: the secrets its filter gives in place of the phantoms the
    launch holds (A.3); none without a network (secrets.Delivery)."""
    if mode == "none":
        return NoNetwork(mode="none")
    if mode == "open":
        return OpenNetwork(mode="open", injections=list(injections or []))
    allow = sorted(set(required_egress(launch, addon_egress)) | set(agent_allow or []))
    return FilteredNetwork(
        mode="filtered",
        allow=allow,
        blocked=list(blocked or []),
        enforcement=enforcement,
        injections=list(injections or []),
    )


def sandbox_spec(
    *,
    name: str,
    launch: HarnessLaunch,
    scope: str,
    network: NetworkMode,
    enforcement: Enforcement,
    confinement: Confinement,
    allow: list[str] | None = None,
    blocked: list[str] | None = None,
    labels: dict[str, str] | None = None,
    addons: AddonLaunch | None = None,
    knowledge: list[HostFolder] | None = None,
    subject: HostFolder | None = None,
    display: bool = False,
    terminal: TerminalStart | None = None,
    paste: str | None = None,
    injections: list[Injection] | None = None,
    daemons: list[SystemPackageDaemon] | None = None,
) -> SandboxSpec:
    """`scope` must already be checked (check_scope), `addons` resolved from checked bindings
    (addons.check, addons.resolve), `knowledge` built from checked folders (knowledge.folders),
    `subject` from a run's checked input (D.18).
    `network`, `enforcement`, `confinement`, `allow` (its own allowed hosts) and `blocked` (those
    the person keeps blocked): the agent's.

    `display`: its windows on the person's screen (A.6), the display its runtime finds.
    `terminal`: the process runs on the client's terminal (D.16), whose type it is told;
    `paste`: the host folder the client puts a pasted image into, read as its clipboard.
    `injections`: the secrets its proxy gives in place of the phantoms `launch` holds (A.3).
    `daemons`: the toolbox's (B.7); those of the sandbox's abilities start before its program.
    """
    addons = addons or AddonLaunch()
    if clash := sorted(addons.env.keys() & launch.env.keys()):
        raise AddonConflictError(f"tool env vars also set by the harness: {', '.join(clash)}")
    started = started_daemons(daemons or [], confinement, display)
    daemon_env = {k: v for d in started for k, v in d.env.items()}
    if clash := sorted(daemon_env.keys() & (launch.env.keys() | addons.env.keys())):
        raise DaemonConflictError(
            f"toolbox daemon env vars also set by the harness or a tool: {', '.join(clash)}"
        )
    argv = list(launch.argv)
    tools = list(launch.tools)
    if started:
        argv = [DAEMONS_TOOL, *(d.command for d in started), "--", *argv]
        tools.append(HandlerTool(target=DAEMONS_TOOL, content=DAEMONS_SCRIPT))
    term_env = {}
    if terminal is not None:
        term_env = {"TERM": terminal.term} | (
            {"COLORTERM": terminal.colorterm} if terminal.colorterm else {}
        )
    return SandboxSpec(
        api_version=SANDBOX_API_VERSION,
        name=name,
        isolation=confinement,
        image=launch.image,
        argv=argv,
        env=dict(launch.env) | addons.env | daemon_env | term_env,
        workdir=scope,
        home=launch.home,
        work_folder=WorkFolder(path=scope),
        folders=[
            *launch.folders,
            *launch.skills,
            *(knowledge or []),
            *([subject] if subject else []),
        ],
        caches=list(launch.caches),
        kept_files=list(launch.kept_files),
        files=list(launch.files),
        tools=tools,
        addons=list(addons.images),
        network=network_policy(
            launch,
            network,
            enforcement,
            addons.egress,
            agent_allow=allow,
            blocked=blocked,
            injections=injections,
        ),
        display=display,
        paste=Paste(source=paste) if paste is not None else None,
        labels=labels,
        tty=terminal is not None,
    )


def seen(
    *,
    launch: HarnessLaunch,
    scope: str,
    addons: AddonLaunch | None = None,
    knowledge: list[HostFolder] | None = None,
    subject: HostFolder | None = None,
) -> list[SessionMount]:
    """What a session's sandbox (sandbox_spec, from the same parts) sees of the host, each by
    what it is (F.8); browsable: its folder, knowledge, a subject, skills."""

    def folder(f: HostFolder, kind: MountKind) -> SessionMount:
        browsable = kind in ("knowledge", "subject", "config")
        return SessionMount(target=f.target, kind=kind, read_only=not f.writable,
                            source=f.source, browsable=browsable)  # fmt: skip

    found = [SessionMount(target=scope, kind="scope", read_only=False, source=scope,
                          browsable=True)]  # fmt: skip
    found += [folder(f, "state") for f in launch.folders]
    found += [
        SessionMount(target=f.target, kind="state", read_only=False, source=f.source,
                     browsable=False)
        for f in launch.kept_files
    ]  # fmt: skip
    found += [
        SessionMount(target=c.target, kind="cache", read_only=False, source=c.source,
                     browsable=False)
        for c in launch.caches
    ]  # fmt: skip
    found += [folder(f, "config") for f in launch.skills]
    found += [folder(f, "knowledge") for f in knowledge or []]
    found += [folder(subject, "subject")] if subject else []
    found += [
        SessionMount(target=i.target, kind="tools", read_only=True, source=i.source,
                     browsable=False)
        for i in (addons or AddonLaunch()).images
    ]  # fmt: skip
    return found


CHECK_HOME = "/home/agent"  # the harnesses' home (harness.toml), where agents use addons


def addon_check_spec(
    *,
    name: str,
    toolbox: str,
    source: str,
    target: str,
    scope: str,
    argv: list[str],
    path: str | None = None,
) -> SandboxSpec:
    """G.4: an addon's folder checked as agents get it: mounted read-only at `target` in the
    toolbox, confined like an agent (`strict`, the host user), no network. `path`: the addon's
    bin directory as agents get it on PATH, or nothing to see what the toolbox alone provides.
    `scope`: an empty folder, checked (the workdir)."""
    addon = Addon(source=source, target=target, path=path)
    return _check_spec(name=name, toolbox=toolbox, scope=scope, argv=argv, addons=[addon])


def toolbox_check_spec(*, name: str, toolbox: str, scope: str, argv: list[str]) -> SandboxSpec:
    """B.6: a command run in the toolbox alone, as agents get it, confined like an agent
    (`strict`, the host user), no network. `scope`: an empty folder, checked (the workdir)."""
    return _check_spec(name=name, toolbox=toolbox, scope=scope, argv=argv, addons=[])


def _check_spec(
    *,
    name: str,
    toolbox: str,
    scope: str,
    argv: list[str],
    addons: list[Addon],
) -> SandboxSpec:
    return SandboxSpec(
        api_version=SANDBOX_API_VERSION,
        name=name,
        image=toolbox,
        argv=argv,
        env={},
        workdir=scope,
        home=CHECK_HOME,
        work_folder=WorkFolder(path=scope),
        addons=addons,
        network=NoNetwork(mode="none"),
        labels={"handler.check": name},
    )


AUTOMATION_HOME = "/home/agent"


def automation_run_spec(
    *,
    name: str,
    run_id: str,
    toolbox: str,
    run: str,
    definition: str,
    input_dir: str,
    output: str,
    commands: dict[str, str],
    services: str | None,
    trial: bool,
) -> SandboxSpec:
    """I.3: an automation's run. Its command line (`sh -c`) in the toolbox, confined like an
    agent (`strict`, the host user), no network; every folder at its host path: its output
    read-write (its work folder), its definition read-only (the workdir), its input read-only,
    and its services socket when it has one, at SERVICES_DIR (A.10). `commands`: handler's (`handler-llm`),
    name → content, given as commands (tools in HANDLER_BIN)."""
    folders = [
        HostFolder(source=definition, target=definition, writable=False),
        HostFolder(source=input_dir, target=input_dir, writable=False),
    ]
    env = {
        "HANDLER_INPUT": input_dir,
        "HANDLER_OUTPUT": output,
        "HANDLER_RUN": run_id,
        "HANDLER_TRY": "1" if trial else "0",
    }
    sockets = []
    if services is not None:
        name = os.path.basename(services)
        folder = os.path.dirname(services)
        sockets.append(SocketFolder(source=folder, target=SERVICES_DIR, reaches=[name]))
        env["HANDLER_SERVICES"] = f"{SERVICES_DIR}/{name}"
    return SandboxSpec(
        api_version=SANDBOX_API_VERSION,
        name=name,
        image=toolbox,
        argv=["sh", "-c", run],
        env=env,
        workdir=definition,
        home=AUTOMATION_HOME,
        work_folder=WorkFolder(path=output),
        folders=folders,
        socket_folders=sockets,
        tools=[HandlerTool(target=f"{HANDLER_BIN}/{n}", content=c) for n, c in commands.items()],
        network=NoNetwork(mode="none"),
        labels={"handler.automation": name},
    )


APP_MEMORY = "512m"
SERVICES_DIR = "/run/handler-services"  # an automation's services socket (I.5) is in it


def app_sandbox_spec(
    *,
    name: str,
    manifest: AppManifest,
    code: str,
    data: str,
    run: str,
    test: bool = False,
    secrets: dict[str, str] | None = None,
    files: list[tuple[str, str, bool]] | None = None,
) -> SandboxSpec:
    """H.3: an app's backend. Its code read-only at APP_CODE_DIR, its data read-write at the
    same path (its scope, so the paths it stores stay valid across versions), the directory of
    its socket; no network unless the manifest lists hosts, then the allow-list, enforced.
    `test`: `bun test` on the backend's directory instead of serving it (H.6). All host paths
    absolute and existing. `secrets`: the values of the manifest's secrets (H.2), given as env
    vars (never to tests). `files`: the folders given for its files needs, checked and resolved
    (need, path, writable), mounted at the same path, `HANDLER_APP_FILES` naming them by need
    (not for tests either). With `needs.notify` or `needs.agents`, the backend reaches handler at
    APP_API_SOCKET (H.9, H.11).
    """
    files = [] if test else list(files or [])
    egress = list(manifest.needs.egress)
    # Its dependencies are in its code: nothing is installed, no .env of its data folder is read.
    flags = ["--no-install", "--no-env-file"]
    if test:
        argv = ["test", *flags, "--pass-with-no-tests", f"{APP_CODE_DIR}/{manifest.server.dir}"]
    else:
        argv = ["run", *flags, f"{APP_CODE_DIR}/{manifest.server.entry}"]
    network: NetworkPolicy = (
        FilteredNetwork(mode="filtered", allow=sorted(set(egress)), enforcement="enforce")
        if egress
        else NoNetwork(mode="none")
    )
    return SandboxSpec(
        api_version=SANDBOX_API_VERSION,
        name=name,
        image=RUNTIME_IMAGE,
        argv=argv,  # the image's entrypoint is bun
        env={
            "HANDLER_APP_NAME": manifest.name,
            "HANDLER_APP_VERSION": manifest.version,
            "HANDLER_APP_DATA": data,
            "HANDLER_APP_SOCKET": APP_SOCKET,
            "NO_COLOR": "1",
        }
        | ({} if test else dict(secrets or {}))
        | ({"HANDLER_APP_FILES": json.dumps({n: p for n, p, _ in files})} if files else {})
        | ({"HANDLER_APP_API": APP_API_SOCKET} if manifest.needs.handler_api and not test else {}),
        workdir=data,
        home=APP_HOME,
        work_folder=WorkFolder(path=data),
        folders=[
            HostFolder(source=code, target=APP_CODE_DIR, writable=False),
            # its files needs, each a folder or a file (H.9): their shape waits for the App work
            *(HostFolder(source=p, target=p, writable=rw) for _, p, rw in files),
        ],
        # its socket, and handlerd's for its needs (H.3, H.9, H.11)
        socket_folders=[
            SocketFolder(
                source=run,
                target=APP_RUN_DIR,
                serves=[os.path.basename(APP_SOCKET)],
                reaches=[os.path.basename(APP_API_SOCKET)]
                if manifest.needs.handler_api and not test
                else [],
            )
        ],
        network=network,
        resources=manifest.resources or Resources(memory=APP_MEMORY),
        labels={"handler.app": manifest.name},
    )
