"""`launch`: run a SandboxSpec in a Docker container (contract A).

The launch is the kit's (handler_sandbox_kit.launch): this module gives each need its Docker way.
The env goes to `docker create` through a 0600 env-file deleted right after, so secrets never
appear in argv (B3); the process is started with `docker start --attach --interactive`. With
`tty` (D.16), Docker holds the process's terminal, so whoever started us can go away meanwhile.

Where Docker differs from Podman, each in its method: no keep-id (`host_user`: the uid, and a
passwd entry for it), a tmpfs is `noexec` unless told (`_tmpfs`), a container is created on one
kind of network and connected to the other before it starts (`network`), the filter reaches the
host as `host-gateway` (`network`), Docker's seccomp profile refuses the user namespaces an engine
inside makes (`isolation`).
"""

import ipaddress
import shutil
import subprocess
import sys
from pathlib import Path

from handler_contracts import (
    CA_BUNDLE,
    CONTAINER_HOST,
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
from handler_sandbox_kit import display, egress, given_files
from handler_sandbox_kit.launch import (
    Args,
    InHome,
    Instance,
    Runtime,
    Status,
    UnenforceableError,
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

from . import check
from .docker import (
    PROXY_IMAGE,
    DockerError,
    agent_ids,
    dev_rootless,
    docker,
    docker_info,
    engine,
    image_config,
    image_exists,
    quiet,
    reference,
    subid_file,
    user_args,
)
from .images import read_bytes

PROG = "handler-sandbox-docker"

# A.6: where the display's Wayland socket appears in the container, and its private runtime dir.
DISPLAY_SOCKET = "/run/handler/wayland-0"
DISPLAY_RUNTIME_DIR = "/run/handler/runtime"
# D.16: Docker's client gives a terminal its size once the process has started (`docker start
# --attach` resizes it then; Podman before): the process waits for it, 2 s at most, so that what
# it reads first (a TUI's layout, `stty size`) is the client's terminal and not none.
TTY_WAIT_TARGET = "/run/handler/tty-size"
TTY_WAIT = """#!/bin/sh
# handler-sandbox-docker: the terminal's size, which Docker gives once this runs, then the program
i=0
while [ "$i" -lt 40 ]; do
  case "$(stty size 2>/dev/null)" in "" | "0 0") ;; *) break ;; esac
  sleep 0.05
  i=$((i + 1))
done
exec "$@"
"""
PROXY_ENV = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "NO_PROXY", "no_proxy")


def proxy_name(name: str) -> str:
    return f"{name}-proxy"


def network_name(name: str) -> str:
    return f"{name}-net"


def resource_args(resources: Resources | None, applied: bool) -> list[str]:
    """A spec's limits, when the engine applies them (`check.limits`); else dropped and said on
    stderr: the sandbox runs without them (A.8 `limits`)."""
    args: list[str] = []
    if resources is None:
        return args
    for flag, value in (("--memory", resources.memory), ("--cpus", resources.cpus)):
        if not value:
            continue
        if applied:
            args += [flag, value]
        else:
            print(f"{PROG}: {flag} {value} not applied: this engine does not", file=sys.stderr)
    return args


def confinement_args(spec: SandboxSpec) -> list[str]:
    """A.5: how locked down the agent container is. The proxy is always strict."""
    if spec.isolation == "privileged":
        return ["--privileged", "--read-only"]
    if spec.isolation == "nested":
        # An engine inside (rootless podman or dockerd) makes user namespaces and mounts, which
        # Docker's seccomp profile refuses without CAP_SYS_ADMIN (Podman's allows them): no
        # seccomp profile, no AppArmor one (Ubuntu); newuidmap needs Docker's default
        # capabilities and no `no-new-privileges`; /dev/fuse for fuse-overlayfs; /dev/net/tun for
        # pasta; unmasked /proc and /sys (the kernel refuses a new proc mount while parts of it
        # are hidden); SELinux labels off. /etc/subuid and /etc/subgid come from `isolation`.
        return [
            "--security-opt=seccomp=unconfined", "--security-opt=apparmor=unconfined",
            "--security-opt=label=disable", "--security-opt=systempaths=unconfined",
            "--device=/dev/fuse", "--device=/dev/net/tun", "--read-only",
        ]  # fmt: skip
    return ["--cap-drop=all", "--security-opt=no-new-privileges", "--read-only"]


def _tmpfs(dest: str, mode: str, owner: tuple[int, int] | None = None) -> Args:
    # exec: Docker's tmpfs is noexec unless told (Podman's is not); empty at the start: Docker
    # copies nothing of the image into it
    owned = f",uid={owner[0]},gid={owner[1]}" if owner else ""
    return ["--tmpfs", f"{dest}:exec,mode={mode}{owned}"]


def _bind(source: str, target: str, writable: bool) -> Args:
    ro = "" if writable else ",readonly"
    return ["--mount", f"type=bind,source={source},destination={target}{ro}"]


def _bind_file(path: Path, target: str) -> Args:
    return _bind(str(path), target, writable=False)


def with_user(table: str, entry: str, numeric_id: int) -> str:
    """The image's /etc/passwd or /etc/group, with `entry` added when no line has that id."""
    lines = [line for line in table.splitlines() if line.strip()]
    if any(line.split(":")[2:3] == [str(numeric_id)] for line in lines):
        return "\n".join(lines) + "\n"
    return "\n".join([*lines, entry]) + "\n"


def _internal_network(name: str, sandbox: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """A filtered sandbox's internal network, its subnet the one Docker picks as free, stated:
    the proxy's address is set on it (it listens on that network only), which Docker (28 at least)
    allows on a network whose subnet was given only ("user specified IP address is supported
    only when connecting to networks with user configured subnets"). Picked, then the network
    made again with it; taken meanwhile by another network, picked again."""
    labels = [
        "--label", f"{MANAGED_LABEL}=1", "--label", f"{SANDBOX_LABEL}={sandbox}",
        "--label", f"{LAUNCHER_LABEL}={launcher_label()}",
    ]  # fmt: skip
    error = DockerError("no free subnet")
    for _ in range(5):
        docker("network", "create", "--internal", *labels, name)
        subnet = docker(
            "network", "inspect", name, "--format", "{{range .IPAM.Config}}{{.Subnet}}{{end}}"
        )
        docker("network", "rm", name)
        try:
            docker("network", "create", "--internal", "--subnet", subnet, *labels, name)
        except DockerError as e:
            error = e
            continue
        return ipaddress.ip_network(subnet)
    raise error


class Docker(Runtime):
    prog = PROG
    errors = (DockerError,)

    def __init__(self) -> None:
        self.connect_bridge = False  # an open network with a proxy: Docker's bridge too
        # in a VM, a file is given by a link (its sharing loses a file the host replaces)
        self.linked_files = given_files.LinkedFiles(lambda s, t, ro: _bind(str(s), t, not ro))

    def abilities(self) -> frozenset[Ability]:
        return check.abilities(engine().kind)

    def refuse(self, spec: SandboxSpec) -> None:
        """A rootless engine on Linux cannot run the process as the host user (A3): refused, but
        in development. A socket folder in a VM: its sockets reach neither side (A.10). A file
        given in a VM: through a link (given_files), which has its conditions."""
        if spec.socket_folders and engine().kind == "vm":  # checked on Docker Desktop 2026-11-10
            raise UnenforceableError(
                "a socket cannot cross the virtual machine Docker runs (A.10): an app's backend "
                "or a script calling models does not run with Docker here"
            )
        if engine().kind == "vm":
            given_files.check(spec, "Docker in a virtual machine")
        if engine().kind == "rootless" and not dev_rootless():
            raise UnenforceableError(
                "rootless Docker maps your user to the containers' root: agents would run as "
                "root (A3). Use Podman, or a rootful Docker"
            )

    def image_path(self, image: str) -> str:
        return image_config(image)[1].get("PATH", "/usr/local/bin:/usr/bin:/bin")

    # ── the needs ───────────────────────────────────────────────────────

    def host_user(self, instance: Instance) -> Args:
        """The uid/gid (no keep-id), and an entry of the image's /etc/passwd and /etc/group for
        them, which keep-id adds and programs look up (Node's os.userInfo, ssh)."""
        kind = engine().kind
        args = user_args(kind)
        uid, gid = agent_ids(kind)
        if uid == 0:
            return args  # the image's root
        home = instance.spec.home
        for path, entry, numeric_id in (
            ("/etc/passwd", f"agent:x:{uid}:{gid}::{home}:/bin/sh", uid),
            ("/etc/group", f"agent:x:{gid}:", gid),
        ):
            table = read_bytes(instance.spec.image, path).decode(errors="replace")
            content = with_user(table, entry, numeric_id)
            args += _bind_file(instance.new_file("users", content, 0o444), path)
        return args

    def isolation(self, instance: Instance) -> Args:
        """confinement_args; nested and privileged: the subordinate ids an engine inside maps
        (A.5), read-only. The engine's own configuration is the toolbox's (its system package's),
        whichever engine it is."""
        args = confinement_args(instance.spec)
        if instance.spec.isolation == "strict":
            return args
        kind = engine().kind
        folder = instance.dir / "nested"
        folder.mkdir()
        for name in ("uid", "gid"):
            path = folder / f"sub{name}"
            path.write_text(subid_file(name, kind))
            path.chmod(0o444)
            args += _bind_file(path, f"/etc/sub{name}")
        return args

    def network(self, instance: Instance) -> Args:
        """A filtered sandbox reaches out only through its proxy, on an internal network of its
        own (B1); an open one through Docker's bridge, and through its proxy when it has
        injections (A.3). A container is created on one network and connected to the other
        before it starts: `docker create` takes Docker's bridge or user-defined networks, not
        both."""
        spec = instance.spec
        if isinstance(spec.network, NoNetwork):
            return ["--network", "none"]
        if not instance.filtered:
            return ["--network", "bridge"]
        if not image_exists(PROXY_IMAGE):  # built by `image build-proxy` (A.7), never here
            raise DockerError(f"{PROXY_IMAGE} is not built: `{PROG} image build-proxy`")
        name = network_name(spec.name)
        subnet = _internal_network(name, spec.name)
        proxy_ip = str(next(h for i, h in enumerate(subnet.hosts()) if i == 1))
        secret_hosts = instance.filter_settings()
        proxy = proxy_name(spec.name)
        docker(
            "create", "--rm", "--name", proxy,
            *labels(spec), *user_args(engine().kind),
            "--cap-drop=all", "--security-opt=no-new-privileges", "--read-only",
            "--network", "bridge", "--add-host", f"{CONTAINER_HOST}:host-gateway",
            "--mount", f"type=bind,source={instance.filter_dir},destination=/cfg",
            "--mount",
            f"type=bind,source={egress.ADDON_SOURCE},destination={egress.ADDON_TARGET},readonly",
            PROXY_IMAGE, *egress.proxy_args(proxy_ip, secret_hosts),
        )  # fmt: skip
        docker("network", "connect", "--ip", proxy_ip, name, proxy)
        docker("start", proxy)
        if not instance.filter_started():
            raise DockerError("egress proxy did not become ready")
        instance.env |= instance.proxy_env(f"http://{proxy_ip}:{egress.PROXY_PORT}")
        args = ["--network", name]
        if not isinstance(spec.network, FilteredNetwork):
            self.connect_bridge = True  # open: its direct route too (`create`)
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
        if engine().kind == "vm" and Path(need.source).is_file():
            return self.linked_files.link(need, instance)
        point = "file" if Path(need.source).is_file() else "folder"  # its mount point in the home
        instance.put_in_home(InHome(need.target, point))
        return _bind(need.source, need.target, need.writable)

    def cache(self, need: CacheFolder, instance: Instance) -> Args:
        Path(need.source).mkdir(parents=True, exist_ok=True)
        instance.put_in_home(InHome(need.target, "folder"))
        return _bind(need.source, need.target, writable=True)

    def kept_file(self, need: KeptFile, instance: Instance) -> Args:
        instance.put_in_home(InHome(need.target, "file"))
        return _bind(need.source, need.target, writable=True)

    def file(self, need: File, instance: Instance) -> Args:
        """Writable: written in the home's folder; read-only: mounted from the instance's."""
        if need.writable:
            instance.put_in_home(InHome(need.target, "written", need.content, int(need.mode, 8)))
            return []
        path = instance.new_file("files", need.content, int(need.mode, 8))
        instance.put_in_home(InHome(need.target, "file"))
        return _bind_file(path, need.target)

    def tool(self, need: HandlerTool, instance: Instance) -> Args:
        return _bind_file(instance.new_file("tools", need.content, 0o555), need.target)

    def home(self, instance: Instance) -> Args:
        """A private tmpfs owned by the agent, or — when needs put something in it — a folder of
        the instance (removed with it, made here as the host user: the agent's own) holding their
        mount points and written files. Made here: Docker would create missing mount points as
        root, leaving e.g. ~/.config unwritable around ~/.config/mcp/mcp.json."""
        args = _tmpfs("/tmp", "1777")
        home = instance.spec.home
        if not instance.in_home:
            return [*args, *_tmpfs(home, "0700", agent_ids(engine().kind))]
        host = instance.home_folder()
        return [*args, *_bind(str(host), home, writable=True)]

    def display(self, instance: Instance) -> Args:
        """A.6: only the Wayland socket found here, at a fixed path, and a private runtime dir.
        The agent runs with the host user's uid: the socket's owner."""
        try:
            socket = display.wayland_socket()
        except display.DisplayError as e:  # gone since `abilities` found it
            raise DockerError(str(e)) from None
        args = [
            "--mount", f"type=bind,source={socket},destination={DISPLAY_SOCKET}",
            *_tmpfs(DISPLAY_RUNTIME_DIR, "0700", agent_ids(engine().kind)),
        ]  # fmt: skip
        instance.env |= {"WAYLAND_DISPLAY": DISPLAY_SOCKET, "XDG_RUNTIME_DIR": DISPLAY_RUNTIME_DIR}
        return args

    def resources(self, instance: Instance) -> Args:
        # `docker info` only for a spec with limits (an app's): an agent's has none
        if not instance.spec.resources:
            return []
        return resource_args(instance.spec.resources, check.limits(docker_info() or {}))

    # ── docker ──────────────────────────────────────────────────────────

    def create(self, instance: Instance, args: Args) -> None:
        """The filter's proxy also as `--env`: Docker's client puts the proxies of its own
        configuration (~/.docker/config.json) over the env-file's, not over these. An address,
        not a secret. With `tty`, the process is started by TTY_WAIT (`_tty_wait`)."""
        spec = instance.spec
        args = self.linked_files.finish(args)
        proxies = [
            a for k in PROXY_ENV if k in instance.env for a in ("--env", f"{k}={instance.env[k]}")
        ]
        argv = list(spec.argv)
        if spec.tty:
            args = [*args, *_bind_file(instance.new_file("tools", TTY_WAIT, 0o555),
                                       TTY_WAIT_TARGET)]  # fmt: skip
            argv = [TTY_WAIT_TARGET, *argv]
        docker(
            "create", "--rm", "--interactive", *(["--tty"] if spec.tty else []),
            "--init", "--name", spec.name, *labels(spec), *args, *proxies,
            reference(spec.image), *argv,
        )  # fmt: skip
        if self.connect_bridge:
            docker("network", "connect", "bridge", spec.name)

    def start(self, name: str) -> subprocess.Popen[bytes]:
        return subprocess.Popen(["docker", "start", "--attach", "--interactive", name])

    def status(self, name: str) -> Status:
        try:
            state = docker("container", "inspect", "--format", "{{.State.Status}}", name)
        except DockerError:
            return "gone"  # `--rm`
        return "waiting" if state == "created" else "running"

    def filter_running(self, instance: Instance) -> bool:
        try:
            running = docker(
                "container", "inspect", "--format", "{{.State.Running}}",
                proxy_name(instance.spec.name),
            )  # fmt: skip
        except DockerError:
            return False  # `--rm`: removed once it ended
        return running == "true"

    def wait(self, instance: Instance) -> int:
        waited = subprocess.run(
            ["docker", "wait", instance.spec.name], capture_output=True, text=True, check=False
        )
        if waited.stdout.strip().isdigit():
            return int(waited.stdout.strip())
        return attached_exit(instance)  # removed (`--rm`) before `docker wait` looked

    def stop(self, name: str) -> None:
        quiet("stop", "--time", "5", name)

    def remove(self, instance: Instance) -> None:
        quiet("rm", "--force", instance.spec.name)
        if instance.filtered:  # its proxy
            quiet("rm", "--force", proxy_name(instance.spec.name))
            quiet("network", "rm", network_name(instance.spec.name))

    def sweep(self) -> list[str]:
        """Containers, then networks (another launcher may be setting its sandbox up meanwhile:
        its network exists, no container)."""
        label = f'{{{{.Label "{LAUNCHER_LABEL}"}}}}'
        rows = docker("ps", "-a", "--filter", f"label={MANAGED_LABEL}=1",
                      "--format", f"{{{{.Names}}}}\t{label}")  # fmt: skip
        swept: set[str] = set()
        for row in rows.splitlines():
            name, _, launcher = row.partition("\t")
            if not launcher_alive(launcher):
                quiet("rm", "--force", name)
                swept.add(name.removesuffix("-proxy"))
        nets = docker("network", "ls", "--filter", f"label={MANAGED_LABEL}=1",
                      "--format", f"{{{{.Name}}}}\t{label}")  # fmt: skip
        for row in nets.splitlines():
            name, _, launcher = row.partition("\t")
            if not launcher_alive(launcher):
                quiet("network", "rm", name)
        return sorted(swept)
