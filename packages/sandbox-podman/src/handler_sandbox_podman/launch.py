"""`launch`: run a SandboxSpec in a rootless podman container (contract A).

The launch is the kit's (handler_sandbox_kit.launch): this module gives each need its podman way.
The env goes to `podman create` through a 0600 env-file deleted right after, so secrets never
appear in argv (B3); the process is started with `podman start --attach --interactive`. With
`tty` (D.16), podman holds the process's terminal, so whoever started us can go away meanwhile.
"""

import ipaddress
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from handler_contracts import (
    CA_BUNDLE,
    Ability,
    CacheFolder,
    File,
    FilteredNetwork,
    HandlerTool,
    HostFolder,
    KeptFile,
    NoNetwork,
    Resources,
    SandboxSpec,
    WorkFolder,
)
from handler_sandbox_kit import display, egress
from handler_sandbox_kit.launch import (
    Args,
    InHome,
    Instance,
    Runtime,
    Status,
    attached_exit,
    labels,
)
from handler_sandbox_kit.launcher import (
    LAUNCHER_LABEL,
    MANAGED_LABEL,
    SANDBOX_LABEL,
    launcher_alive,
    launcher_label,
)

from .check import abilities, limit_controllers, podman_info
from .podman import (
    PROXY_IMAGE,
    PodmanError,
    agent_ids,
    image_config,
    image_exists,
    podman,
    quiet,
    subid_file,
    userns_args,
)

PROG = "handler-sandbox-podman"

# A.6: where the display's Wayland socket appears in the container, and its private runtime dir.
DISPLAY_SOCKET = "/run/handler/wayland-0"
DISPLAY_RUNTIME_DIR = "/run/handler/runtime"


def proxy_name(name: str) -> str:
    return f"{name}-proxy"


def network_name(name: str) -> str:
    return f"{name}-net"


# A sandbox that runs containers (nested, privileged): podman's default process limit (2048, its
# containers.conf `pids_limit`) counts every thread of the engine and containers inside, and a
# test suite running sandboxes inside fills it (fork fails with EAGAIN). Its own limit, higher.
CONTAINERS_PIDS_LIMIT = 16384


def resource_args(resources: Resources | None, given: frozenset[str]) -> list[str]:
    """A spec's limits, those podman can apply here (`given`: check.limit_controllers); one it
    cannot is dropped and said on stderr: the sandbox runs without it (A.8 `limits`)."""
    args: list[str] = []
    if resources is None:
        return args
    for flag, value, controller in (
        ("--memory", resources.memory, "memory"),
        ("--cpus", resources.cpus, "cpu"),
    ):
        if not value:
            continue
        if controller in given:
            args += [flag, value]
        else:
            print(
                f"handler-sandbox-podman: {flag} {value} not applied: this host does not let it be",
                file=sys.stderr,
            )
    return args


def confinement_args(spec: SandboxSpec) -> list[str]:
    """A.5: how locked down the agent container is. The proxy is always strict."""
    if spec.isolation == "privileged":
        return ["--privileged", "--read-only"]
    if spec.isolation == "nested":
        # Verified: rootless podman inside needs newuidmap, so podman's default capabilities and
        # no `no-new-privileges`; /dev/fuse for fuse-overlayfs; /dev/net/tun for pasta; an
        # unmasked /proc (the kernel refuses a new proc mount while parts of it are hidden);
        # SELinux labels off (Fedora hosts). /etc/subuid and /etc/subgid come from _files.
        return [
            "--security-opt=label=disable", "--security-opt=unmask=/proc/*",
            "--device=/dev/fuse", "--device=/dev/net/tun", "--read-only",
        ]  # fmt: skip
    return ["--cap-drop=all", "--security-opt=no-new-privileges", "--read-only"]


def _tmpfs(dest: str, mode: str) -> list[str]:
    # notmpcopyup: podman would otherwise copy what the image has at `dest` (e.g. a build-time
    # ~/.cache owned by root) into the tmpfs, which must start empty.
    return ["--mount", f"type=tmpfs,destination={dest},tmpfs-mode={mode},chown=true,notmpcopyup"]


def _give_agent(*paths: Path) -> None:
    """What the agent writes on the host is the agent's: already so where it runs as the user
    (A3), made so in a dev container (HANDLER_SANDBOX_DEV_UID, root's files otherwise)."""
    uid, gid = agent_ids()
    if (uid, gid) != (os.getuid(), os.getgid()):
        for path in paths:
            os.chown(path, uid, gid)


def _bind(source: str, target: str, writable: bool) -> Args:
    ro = "" if writable else ",ro=true"
    return ["--mount", f"type=bind,source={source},destination={target}{ro}"]


def _bind_file(path: Path, target: str) -> Args:
    return _bind(str(path), target, writable=False)


class Podman(Runtime):
    prog = PROG
    errors = (PodmanError,)

    def abilities(self) -> frozenset[Ability]:
        return abilities()

    def refuse(self, spec: SandboxSpec) -> None:
        """Nothing beyond the kit's: what this host lacks is an ability (`abilities`)."""

    def image_path(self, image: str) -> str:
        return image_config(image)[1].get("PATH", "/usr/local/bin:/usr/bin:/bin")

    # ── the needs ───────────────────────────────────────────────────────

    def host_user(self, instance: Instance) -> Args:
        return userns_args()  # keep-id

    def isolation(self, instance: Instance) -> Args:
        """confinement_args; nested and privileged: what is the host's of what an engine inside
        needs (A.5): the subordinate ids, read-only. The engine's own configuration is the
        toolbox's (its system package's), whichever engine it is."""
        args = confinement_args(instance.spec)
        if instance.spec.isolation == "strict":
            return args
        # where podman can set it (rootless: the pids controller delegated); else it applies no
        # limit at all, its default neither
        if limit_controllers(podman_info(), ("pids",)):
            args += ["--pids-limit", str(CONTAINERS_PIDS_LIMIT)]
        folder = instance.dir / "nested"
        folder.mkdir()
        nested = {f"/etc/sub{kind}": subid_file(kind) for kind in ("uid", "gid")}
        for target, content in nested.items():
            path = folder / target.replace("/", "_")
            path.write_text(content)
            path.chmod(0o444)
            args += _bind_file(path, target)
        return args

    def network(self, instance: Instance) -> Args:
        """A filtered sandbox reaches out only through its proxy, on an internal network of its
        own; an open one directly (pasta), and through its proxy when it has injections (A.3)."""
        spec = instance.spec
        if isinstance(spec.network, NoNetwork):
            return ["--network", "none"]
        if not instance.filtered:
            return []  # open: podman default (pasta when rootless)
        if not image_exists(PROXY_IMAGE):  # built by `image build-proxy` (A.7), never here
            raise PodmanError(f"{PROXY_IMAGE} is not built: `{PROG} image build-proxy`")
        name = network_name(spec.name)
        podman(
            "network", "create", "--internal", "--disable-dns",
            "--label", f"{MANAGED_LABEL}=1", "--label", f"{SANDBOX_LABEL}={spec.name}",
            "--label", f"{LAUNCHER_LABEL}={launcher_label()}",
            name,
        )  # fmt: skip
        subnet = ipaddress.ip_network(
            podman("network", "inspect", name, "--format", "{{range .Subnets}}{{.Subnet}}{{end}}")
        )
        proxy_ip = str(next(h for i, h in enumerate(subnet.hosts()) if i == 1))
        secret_hosts = instance.filter_settings()
        podman(
            "run", "-d", "--rm", "--name", proxy_name(spec.name),
            *labels(spec), *userns_args(agent=False),
            "--cap-drop=all", "--security-opt=no-new-privileges", "--read-only",
            "--network", "podman", "--network", f"{name}:ip={proxy_ip}",
            "--mount", f"type=bind,source={instance.filter_dir},destination=/cfg",
            "--mount",
            f"type=bind,source={egress.ADDON_SOURCE},destination={egress.ADDON_TARGET},ro=true",
            PROXY_IMAGE, *egress.proxy_args(proxy_ip, secret_hosts),
        )  # fmt: skip
        if not instance.filter_started():
            raise PodmanError("egress proxy did not become ready")
        instance.env |= instance.proxy_env(f"http://{proxy_ip}:{egress.PROXY_PORT}")
        args = ["--network", name]
        if not isinstance(spec.network, FilteredNetwork):
            args = ["--network", "podman", *args]  # open: its direct route too
        if spec.injections:  # the roots it trusts: the system's and its proxy's CA
            bundle = instance.dir / "ca-bundle.pem"
            shutil.copyfile(instance.filter_dir / egress.CA_BUNDLE_FILE, bundle)
            bundle.chmod(0o444)
            args += _bind_file(bundle, CA_BUNDLE)
        return args

    def work_folder(self, need: WorkFolder, instance: Instance) -> Args:
        instance.put_in_home(InHome(need.path, "folder"))
        return _bind(need.path, need.path, writable=True)

    def folder(self, need: HostFolder, instance: Instance) -> Args:
        """A folder, or a file (an app's file need, H.9): its mount point in the home is one too."""
        point = "file" if Path(need.source).is_file() else "folder"
        instance.put_in_home(InHome(need.target, point))
        return _bind(need.source, need.target, need.writable)

    def cache(self, need: CacheFolder, instance: Instance) -> Args:
        """Its folder made when missing, the agent's."""
        made = [p for p in (Path(need.source), *Path(need.source).parents) if not p.exists()]
        Path(need.source).mkdir(parents=True, exist_ok=True)
        _give_agent(*made)
        instance.put_in_home(InHome(need.target, "folder"))
        return _bind(need.source, need.target, writable=True)

    def kept_file(self, need: KeptFile, instance: Instance) -> Args:
        """The agent's, which reads and rewrites it (a login's credentials)."""
        _give_agent(Path(need.source))
        instance.put_in_home(InHome(need.target, "file"))
        return _bind(need.source, need.target, writable=True)

    def file(self, need: File, instance: Instance) -> Args:
        """Writable: written in the home's folder; read-only: mounted from the instance's."""
        if need.writable:
            instance.put_in_home(InHome(need.target, "written", need.content, int(need.mode, 8)))
            return []
        path = instance.new_file("files", need.content, int(need.mode, 8))
        _give_agent(path)  # its mode may let only its owner read it (a login's 0400)
        instance.put_in_home(InHome(need.target, "file"))
        return _bind_file(path, need.target)

    def tool(self, need: HandlerTool, instance: Instance) -> Args:
        return _bind_file(instance.new_file("tools", need.content, 0o555), need.target)

    def home(self, instance: Instance) -> Args:
        """A private tmpfs, or — when needs put something in it — a folder of the instance
        (removed with it) holding their mount points and written files. Made here, as the user:
        podman would create missing mount points as root, leaving e.g. ~/.vibe/logs unwritable
        around ~/.vibe/logs/session, or ~/.config around ~/.config/mcp/mcp.json (then Chromium,
        which writes ~/.config/chromium, cannot start)."""
        args = ["--mount", "type=tmpfs,destination=/tmp,tmpfs-mode=1777,notmpcopyup"]
        home = instance.spec.home
        if not instance.in_home:
            return [*args, *_tmpfs(home, "0700")]
        host = instance.home_folder()
        # U: owned by the sandbox user (a no-op with keep-id, where it is already the owner)
        return [*args, "--mount", f"type=bind,source={host},destination={home},U=true"]

    def display(self, instance: Instance) -> Args:
        """A.6: only the Wayland socket found here, at a fixed path, and a private runtime dir."""
        try:
            socket = display.wayland_socket()
        except display.DisplayError as e:  # gone since `abilities` found it
            raise PodmanError(str(e)) from None
        args = [
            "--mount", f"type=bind,source={socket},destination={DISPLAY_SOCKET}",
            *_tmpfs(DISPLAY_RUNTIME_DIR, "0700"),
        ]  # fmt: skip
        instance.env |= {"WAYLAND_DISPLAY": DISPLAY_SOCKET, "XDG_RUNTIME_DIR": DISPLAY_RUNTIME_DIR}
        return args

    def resources(self, instance: Instance) -> Args:
        # `podman info` only for a spec with limits (an app's): an agent's has none
        if not instance.spec.resources:
            return []
        return resource_args(instance.spec.resources, limit_controllers(podman_info()))

    # ── podman ──────────────────────────────────────────────────────────

    def create(self, instance: Instance, args: Args) -> None:
        spec = instance.spec
        podman(
            "create", "--rm", "--interactive", *(["--tty"] if spec.tty else []),
            "--init", "--name", spec.name, *labels(spec), *args,
            spec.image, *spec.argv,
        )  # fmt: skip

    def start(self, name: str) -> subprocess.Popen[bytes]:
        return subprocess.Popen(["podman", "start", "--attach", "--interactive", name])

    def status(self, name: str) -> Status:
        try:
            state = podman("container", "inspect", "--format", "{{.State.Status}}", name)
        except PodmanError:
            return "gone"  # `--rm`
        return "waiting" if state == "created" else "running"

    def filter_running(self, instance: Instance) -> bool:
        try:
            running = podman(
                "container", "inspect", "--format", "{{.State.Running}}",
                proxy_name(instance.spec.name),
            )  # fmt: skip
        except PodmanError:
            return False  # `--rm`: removed once it ended
        return running == "true"

    def wait(self, instance: Instance) -> int:
        """Until it ends; its code, the one its `attach` got: `--rm` removes it as it ends, and
        `podman wait` then has none (it says 0, or no such container)."""
        subprocess.run(["podman", "wait", instance.spec.name], capture_output=True, check=False)
        return attached_exit(instance)

    def stop(self, name: str) -> None:
        quiet("stop", "--time", "5", name)

    def remove(self, instance: Instance) -> None:
        quiet("rm", "--force", "--time", "0", instance.spec.name)
        if instance.filtered:  # its proxy
            quiet("rm", "--force", "--time", "0", proxy_name(instance.spec.name))
            quiet("network", "rm", "--force", network_name(instance.spec.name))

    def sweep(self) -> list[str]:
        """Containers, then networks (another launcher may be setting its sandbox up meanwhile:
        its network exists, no container)."""
        # json, not a `{{index .Labels …}}` template: that one fails on a container being removed
        rows = podman("ps", "-a", "--filter", f"label={MANAGED_LABEL}=1", "--format", "json")
        swept: set[str] = set()
        for row in json.loads(rows or "[]"):
            name = row["Names"][0]
            if not launcher_alive((row.get("Labels") or {}).get(LAUNCHER_LABEL, "")):
                quiet("rm", "--force", "--time", "0", name)
                swept.add(name.removesuffix("-proxy"))
        nets = podman("network", "ls", "--filter", f"label={MANAGED_LABEL}=1", "--format", "json")
        for net in json.loads(nets or "[]"):
            if not launcher_alive(net.get("labels", {}).get(LAUNCHER_LABEL, "")):
                quiet("network", "rm", "--force", net["name"])
        return sorted(swept)
