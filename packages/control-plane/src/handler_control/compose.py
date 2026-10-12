"""Composition — the only place combining contracts:
HarnessLaunch (B) + the agent's sandbox settings (D.8) + what the selected addons add (G.3)
→ SandboxSpec (A), a mini app (H) → SandboxSpec (A), an addon image's check (G.4) →
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
    RUNTIME_IMAGE,
    SANDBOX_API_VERSION,
    Confinement,
    Enforcement,
    FilteredNetwork,
    HarnessLaunch,
    ImageMount,
    Injection,
    MiniAppManifest,
    Mount,
    NetworkMode,
    NetworkPolicy,
    NoNetwork,
    OpenNetwork,
    Resources,
    SandboxSpec,
    SandboxUser,
    TerminalStart,
    WaylandDisplay,
    is_within,
)

from .addons import AddonLaunch


class ScopeError(ValueError):
    """The requested scope is outside the work folders (D.13), or not a folder."""


class AddonConflictError(ValueError):
    """An addon sets an env var the harness sets too (no silent override)."""


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
) -> NetworkPolicy:
    """The agent's network: in filtered mode, the required hosts and its own; enforcement
    live-switchable (A.4)."""
    if mode == "none":
        return NoNetwork(mode="none")
    if mode == "open":
        return OpenNetwork(mode="open")
    allow = sorted(set(required_egress(launch, addon_egress)) | set(agent_allow or []))
    return FilteredNetwork(mode="filtered", allow=allow, enforcement=enforcement)


def sandbox_spec(
    *,
    name: str,
    launch: HarnessLaunch,
    scope: str,
    network: NetworkMode,
    enforcement: Enforcement,
    confinement: Confinement,
    allow: list[str] | None = None,
    labels: dict[str, str] | None = None,
    addons: AddonLaunch | None = None,
    knowledge: list[Mount] | None = None,
    subject: Mount | None = None,
    display: WaylandDisplay | None = None,
    terminal: TerminalStart | None = None,
    injections: list[Injection] | None = None,
) -> SandboxSpec:
    """`scope` must already be checked (check_scope), `addons` resolved from checked bindings
    (addons.check, addons.resolve), `knowledge` built from checked folders (knowledge.mounts),
    `subject` from a run's checked input (D.18).
    `network`, `enforcement`, `confinement` and `allow` (its own allowed hosts): the agent's.

    `terminal`: the process runs on the client's terminal (D.16), whose type it is told.
    `injections`: the secrets its proxy gives in place of the phantoms `launch` holds (A.3).
    """
    addons = addons or AddonLaunch()
    if clash := sorted(addons.env.keys() & launch.env.keys()):
        raise AddonConflictError(f"addon env vars also set by the harness: {', '.join(clash)}")
    term_env = {}
    if terminal is not None:
        term_env = {"TERM": terminal.term} | (
            {"COLORTERM": terminal.colorterm} if terminal.colorterm else {}
        )
    scope_mount = Mount(source=scope, target=scope, read_only=False, kind="scope")
    return SandboxSpec(
        api_version=SANDBOX_API_VERSION,
        name=name,
        confinement=confinement,
        image=launch.image,
        argv=list(launch.argv),
        env=dict(launch.env) | addons.env | term_env,
        workdir=scope,
        user=SandboxUser(mode="host-user", home=launch.home),
        mounts=[scope_mount, *launch.mounts, *(knowledge or []), *([subject] if subject else [])],
        image_mounts=list(addons.image_mounts),
        path_append=list(addons.path_append),
        files=list(launch.files),
        writable_paths=list(launch.writable_paths),
        network=network_policy(launch, network, enforcement, addons.egress, agent_allow=allow),
        display=display,
        labels=labels,
        tty=terminal is not None,
        injections=list(injections or []),
    )


CHECK_HOME = "/home/agent"  # the harnesses' home (harness.toml), where agents use addons


def addon_check_spec(
    *,
    name: str,
    toolbox: str,
    image: str,
    target: str,
    scope: str,
    argv: list[str],
    path_append: list[str] | None = None,
) -> SandboxSpec:
    """G.4: an addon image checked as agents get it: mounted read-only at `target` in the
    toolbox, confined like an agent (`strict`, the host user), no network. `path_append`: the
    addon's bin directory as agents get it on PATH, or nothing to see what the toolbox alone
    provides. `scope`: an empty folder, checked (the workdir)."""
    return SandboxSpec(
        api_version=SANDBOX_API_VERSION,
        name=name,
        image=toolbox,
        argv=argv,
        env={},
        workdir=scope,
        user=SandboxUser(mode="host-user", home=CHECK_HOME),
        mounts=[Mount(source=scope, target=scope, read_only=False, kind="scope")],
        image_mounts=[ImageMount(image=image, target=target)],
        path_append=list(path_append or []),
        files=[],
        writable_paths=[],
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
    bin_dir: str,
    services: str | None,
    trial: bool,
) -> SandboxSpec:
    """I.3: an automation's run. Its command line (`sh -c`) in the toolbox, confined like an
    agent (`strict`, the host user), no network; every mount at its host path: its definition
    read-only (the workdir), its input read-only, its output read-write, handler's commands
    (`handler-llm`) read-only on PATH, and the folder of its services socket when it has one."""
    mounts = [
        Mount(source=definition, target=definition, read_only=True, kind="scope"),
        Mount(source=input_dir, target=input_dir, read_only=True, kind="subject"),
        Mount(source=output, target=output, read_only=False, kind="state"),
        Mount(source=bin_dir, target=bin_dir, read_only=True, kind="config"),
    ]
    env = {
        "HANDLER_INPUT": input_dir,
        "HANDLER_OUTPUT": output,
        "HANDLER_RUN": run_id,
        "HANDLER_TRY": "1" if trial else "0",
    }
    if services is not None:
        folder = os.path.dirname(services)
        mounts.append(Mount(source=folder, target=folder, read_only=True, kind="state"))
        env["HANDLER_SERVICES"] = services
    return SandboxSpec(
        api_version=SANDBOX_API_VERSION,
        name=name,
        image=toolbox,
        argv=["sh", "-c", run],
        env=env,
        workdir=definition,
        user=SandboxUser(mode="host-user", home=AUTOMATION_HOME),
        mounts=mounts,
        path_append=[bin_dir],
        files=[],
        writable_paths=[],
        network=NoNetwork(mode="none"),
        labels={"handler.automation": name},
    )


APP_MEMORY = "512m"


def app_sandbox_spec(
    *,
    name: str,
    manifest: MiniAppManifest,
    code: str,
    data: str,
    run: str,
    test: bool = False,
    secrets: dict[str, str] | None = None,
    files: list[tuple[str, bool]] | None = None,
) -> SandboxSpec:
    """H.3: a mini app's backend. Its code read-only at APP_CODE_DIR, its data read-write at the
    same path (its scope, so the paths it stores stay valid across versions), the directory of
    its socket; no network unless the manifest lists hosts, then the allow-list, enforced. Deno's
    own permissions repeat these limits inside the container. `test`: `deno test` on the backend's
    directory instead of serving it (H.6). All host paths absolute and existing. `secrets`: the
    values of the manifest's secrets (H.2), given as env vars (never to tests). `files`: the
    manifest's host files, checked and resolved (path, writable), mounted at the same path (not
    for tests either). With `needs.notify`, the backend reaches handler at APP_API_SOCKET (H.9).
    """
    files = [] if test else list(files or [])
    net = [f"unix:{APP_SOCKET}"]
    if manifest.needs.notify and not test:
        net.append(f"unix:{APP_API_SOCKET}")
    egress = list(manifest.needs.egress)
    wildcard = any(e.startswith("*.") for e in egress)
    allow_net = "--allow-net" if wildcard else f"--allow-net={','.join(net + egress)}"
    permissions = [
        "--cached-only",  # dependencies are vendored with the code: nothing is fetched
        "--frozen",
        "--no-prompt",
        f"--allow-read={','.join([APP_CODE_DIR, data, APP_RUN_DIR, *(p for p, _ in files)])}",
        f"--allow-write={','.join([data, APP_RUN_DIR, *(p for p, rw in files if rw)])}",
        allow_net,  # a wildcard host cannot be said to Deno: the proxy filters alone
        "--allow-env",
    ]
    if test:
        argv = ["test", *permissions, "--permit-no-files", f"{APP_CODE_DIR}/{manifest.server.dir}"]
    else:
        argv = ["run", *permissions, f"{APP_CODE_DIR}/{manifest.server.entry}"]
    network: NetworkPolicy = (
        FilteredNetwork(mode="filtered", allow=sorted(set(egress)), enforcement="enforce")
        if egress
        else NoNetwork(mode="none")
    )
    return SandboxSpec(
        api_version=SANDBOX_API_VERSION,
        name=name,
        image=RUNTIME_IMAGE,
        argv=argv,  # the image's entrypoint is deno
        env={
            "HANDLER_APP_NAME": manifest.name,
            "HANDLER_APP_VERSION": manifest.version,
            "HANDLER_APP_DATA": data,
            "HANDLER_APP_SOCKET": APP_SOCKET,
            "DENO_DIR": f"{APP_HOME}/.cache/deno",  # the image's /deno-dir is read-only
            "DENO_NO_UPDATE_CHECK": "1",
            "NO_COLOR": "1",
            "TINI_SUBREAPER": "1",  # the image's tini runs under podman's init
        }
        | ({} if test else dict(secrets or {}))
        | ({"HANDLER_APP_FILES": json.dumps([p for p, _ in files])} if files else {})
        | ({"HANDLER_APP_API": APP_API_SOCKET} if manifest.needs.notify and not test else {}),
        workdir=data,
        user=SandboxUser(mode="host-user", home=APP_HOME),
        mounts=[
            Mount(source=data, target=data, read_only=False, kind="scope"),
            Mount(source=code, target=APP_CODE_DIR, read_only=True, kind="app"),
            Mount(source=run, target=APP_RUN_DIR, read_only=False, kind="app"),
            *(Mount(source=p, target=p, read_only=not rw, kind="app") for p, rw in files),
        ],
        files=[],
        writable_paths=[],
        network=network,
        resources=manifest.resources or Resources(memory=APP_MEMORY),
        labels={"handler.app": manifest.name},
    )
