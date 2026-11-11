"""Each need of a sandbox on Apple container; the launch is the kit's (handler_sandbox_kit.launch).

Each sandbox is a virtual machine of its own, whose command is `handler-relay` (kit): started as
root with four capabilities, it sets no_new_privs (which `container` cannot), drops them all and
becomes the user (A3) before it runs the spec's argv. Apple's networks do not isolate
(apple/container#2062), so a filtered sandbox has none, only loopback: no route out but the
relay's. The relay joins its proxy address to the host through a socket of the host mounted in
the sandbox (`--volume`, the socket alone: Apple relays each connection to it; the other way,
`--publish-socket` works only for a socket on the sandbox's root disk, apple/container#2101, and
that is read-only), and the launcher's RelayHost joins that to the filter, a sandbox of its own whose proxy the host reaches through its
`--publish-socket` (the kit's egress proxy/front.py). A socket folder (A.10) goes the same way:
its folder is the VM's own (a tmpfs), each socket the sandbox reaches a listener of the relay
joined to the host's, each socket it serves one the launcher listens on at its host path, whose
clients the relay's parked connections carry to it; whatever the network, `none` too.

`container`'s behaviours relied on were checked on a Mac (Apple container 1.6.1); the comments
say which.
"""

import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO

from handler_contracts import (
    CA_BUNDLE,
    HANDLER_FOLDERS,
    Ability,
    CacheFolder,
    File,
    FilteredNetwork,
    HandlerTool,
    HostFolder,
    KeptFile,
    NoNetwork,
    SandboxSpec,
    SocketFolder,
    WorkFolder,
    is_within,
)
from handler_sandbox_kit import egress, given_files
from handler_sandbox_kit.launch import (
    Args,
    InHome,
    Instance,
    Runtime,
    Status,
    UnenforceableError,
    attached_exit,
    labels,
    runtimes_dir,
)
from handler_sandbox_kit.launcher import (
    LAUNCHER_LABEL,
    MANAGED_LABEL,
    SANDBOX_LABEL,
    launcher_alive,
)
from handler_sandbox_kit.relay import RelayHost

from .check import abilities
from .container import (
    FILTER_IMAGE,
    SOCKET_PATH_MAX,
    START_SERVICE,
    ContainerError,
    container,
    containers,
    find,
    image_env,
    image_info,
    labels_of,
    quiet,
    reference,
    service_running,
    socket_path,
    variant,
)

PROG = "handler-sandbox-apple"

MIN_MEMORY_MIB = 200  # `container` gives a virtual machine no less
_UNITS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def memory_arg(memory: str) -> str:
    """A spec's memory limit (`Resources.memory`), raised to `container`'s minimum when below it,
    said on stderr: still a limit, a looser one, rather than a sandbox that cannot start."""
    number = memory.rstrip("kmgKMG")
    if int(number) * _UNITS[memory[len(number) :].lower()] >= MIN_MEMORY_MIB * 1024**2:
        return memory
    raised = f"{MIN_MEMORY_MIB}m"
    print(
        f"{PROG}: --memory {memory} raised to {raised}: Apple container's minimum", file=sys.stderr
    )
    return raised


# in the sandbox: `container` mounts folders only. Handler's own folders (HANDLER_FOLDERS),
# which no image has, are folders of the instance, read-only: a tool is there at its path, and the
# CA bundle; a read-only file (in the home) is in a folder of its own in FILES, and a link at its
# target leads to it. A kept file is alone in its folder (contract A.1): that folder is mounted in
# STATE, writable, and linked to likewise. In HANDLER_RUN, the host's relay folder, read-only.
HANDLER_RUN = "/run/handler"  # CA_BUNDLE is in it
RELAY_BIN = f"{HANDLER_RUN}/relay-bin"
FILES = f"{HANDLER_RUN}/files"
STATE = f"{HANDLER_RUN}/state"
# where the host's socket is mounted: outside every mounted folder (in one, the mount fails)
HOST_SOCKET = "/run/handler-host.sock"
RELAY_CAPS = ("CAP_SETUID", "CAP_SETGID", "CAP_SETPCAP", "CAP_CHOWN")  # the relay drops them
EGRESS_ADDRESS = "127.42.0.1:3128"  # the proxy, on the sandbox's loopback
# in the filter's sandbox: its socket, published to the host from its root disk (the only place
# `--publish-socket` works), writable
FILTER_SOCKET = "/tmp/filter.sock"
DEFAULT_GATEWAY = "192.168.64.1"  # the host: Apple's default network's gateway
# The VM's kernel settings (sysctl on its command line), no seccomp in Apple's VMs: no user
# namespace (in one, every capability back); neither unprivileged BPF nor io_uring, the kernel
# features most privilege escalations went through; its log and its addresses hidden. Its kernel
# has no modules, no kexec, no userfaultfd already (C7).
KERNEL_SETTINGS = (
    "user.max_user_namespaces=0",
    "kernel.unprivileged_bpf_disabled=1",
    "kernel.io_uring_disabled=2",
    "kernel.dmesg_restrict=1",
    "kernel.kptr_restrict=2",
)


# the places of the home macOS asks about before an app reads them (its privacy settings), by
# their names there: Apple container's helper, `container-runtime-linux`, waits for the person's
# answer to its dialog the first time, with no time limit, and fails once refused
PROTECTED = (
    ("Library/Mobile Documents", "iCloud Drive"),
    ("Desktop", "Desktop"),
    ("Documents", "Documents"),
    ("Downloads", "Downloads"),
)
ALLOW = "System Settings → Privacy & Security → Files & Folders (or Full Disk Access)"


def _copy_out(stream: IO[bytes]) -> None:
    """What comes on `stream`, onto our stderr as it comes, until its end."""
    with contextlib.suppress(OSError), stream:
        while data := os.read(stream.fileno(), 4096):
            os.write(sys.stderr.fileno(), data)


def protected(spec: SandboxSpec) -> list[tuple[str, str]]:
    """The spec's folders of the Mac in a place macOS protects, with that place's name."""
    home = Path.home().resolve()
    sources = [
        spec.work_folder.path,
        *(f.source for f in spec.folders if not Path(f.source).is_file()),  # a file: linked
        *(c.source for c in spec.caches),
        *(str(Path(k.source).parent) for k in spec.kept_files),
    ]
    found = []
    for source in sources:
        real = Path(os.path.realpath(source))  # a link to it too
        place = next((n for p, n in PROTECTED if real.is_relative_to(home / p)), None)
        if place:
            found.append((source, place))
    return found


def relay_dir() -> Path:
    """Where `image build-proxy` exports handler-relay for the VMs' Linux."""
    return runtimes_dir() / "relay"


def filter_name(name: str) -> str:
    return f"{name}-proxy"


def handler_folder(target: str) -> str | None:
    """The folder of Handler's own `target` is in, if any."""
    return next((f for f in HANDLER_FOLDERS if is_within(target, f) and target != f), None)


def check_kept_files(spec: SandboxSpec) -> None:
    """A1: a kept file's folder is mounted (U2b), so it must hold nothing else (A.1)."""
    for f in spec.kept_files:
        if os.listdir(Path(f.source).parent) != [Path(f.source).name]:
            raise UnenforceableError(f"{f.source} is not alone in its folder (A.1)")


def bind(source: Path | str, target: str, read_only: bool) -> list[str]:
    return [
        "--mount",
        f"type=bind,source={source},target={target}{',readonly' if read_only else ''}",
    ]


class Apple(Runtime):
    prog = PROG
    errors = (ContainerError,)

    def __init__(self) -> None:
        # handler-relay's command line before the spec's argv: the user it becomes (A3) and, when
        # the sandbox is filtered, the host's socket and the proxy address
        self.relay_prefix: list[str] = []
        # the launcher's RelayHost, when the relay has a way to the host: its targets by name
        # (the filter's proxy, the sockets the sandbox reaches), the sockets it serves
        self.relay_targets: dict[str, str] = {}
        self.relay_serves: dict[str, Path] = {}
        self.sockets = 0  # socket folders, by the names of their sockets on the relay
        self.linked_files = given_files.LinkedFiles(lambda s, t, ro: bind(s, t, read_only=ro))
        self.kept = 0  # kept files, by the folder each has in STATE
        self.given = 0  # read-only files, by the folder each has in FILES

    def abilities(self) -> frozenset[Ability]:
        return abilities()

    def refuse(self, spec: SandboxSpec) -> None:
        check_kept_files(spec)
        for f in spec.socket_folders:  # the launcher listens or connects at each one's path
            for name in [*f.serves, *f.reaches]:
                if len(str(Path(f.source) / name).encode()) > SOCKET_PATH_MAX:
                    raise UnenforceableError(
                        f"{Path(f.source) / name} is too long for a socket on macOS"
                    )
        given_files.check(spec, "Apple container")

    def image_path(self, image: str) -> str:
        info = image_info(image) or {}
        return image_env(info).get("PATH", "/usr/local/bin:/usr/bin:/bin")

    # ── the needs ───────────────────────────────────────────────────────

    def host_user(self, instance: Instance) -> Args:
        """handler-relay starts as root and becomes the user (A3)."""
        relay = relay_dir() / "handler-relay"
        if not relay.exists():
            raise ContainerError(f"{relay} is missing: `{PROG} image build-proxy`")
        self.relay_prefix = [f"{RELAY_BIN}/handler-relay", "--user", f"{os.getuid()}:{os.getgid()}"]
        self.own(instance, RELAY_BIN).mkdir()  # its mount point
        return ["--uid", "0", "--gid", "0"]

    def isolation(self, instance: Instance) -> Args:
        """A3: a VM of its own, its root read-only, the four capabilities the relay drops, its
        kernel's settings (KERNEL_SETTINGS)."""
        return [
            "--read-only", "--cap-drop", "ALL",
            *(a for cap in RELAY_CAPS for a in ("--cap-add", cap)),
            *(a for s in KERNEL_SETTINGS for a in ("--kernel-arg", f"sysctl.{s}")),
        ]  # fmt: skip

    def network(self, instance: Instance) -> Args:
        """Filtered (or with secrets): no network, the relay joins the proxy address to the host
        through the host's socket, the launcher's RelayHost to the filter."""
        if instance.filtered:
            instance.env |= self._start_filter(instance)
        if instance.spec.injections:  # the roots it trusts, in Handler's folder
            bundle = self.own(instance, CA_BUNDLE)
            shutil.copyfile(instance.filter_dir / egress.CA_BUNDLE_FILE, bundle)
            bundle.chmod(0o444)
        return self.network_args(instance)

    def network_args(self, instance: Instance) -> Args:
        args: Args = []
        if isinstance(instance.spec.network, NoNetwork | FilteredNetwork):
            args += ["--network", "none", "--no-dns"]  # loopback only
        # open: Apple's default network (and its relay to the filter, with secrets)
        if instance.filtered:
            args += self._host_socket(instance)
            self.relay_prefix += ["--listen", f"tcp:{EGRESS_ADDRESS}=egress"]
        return args

    def _host_socket(self, instance: Instance) -> Args:
        """The launcher's RelayHost's socket, mounted alone (once: the filter's way out and the
        socket folders share it)."""
        if "--host" in self.relay_prefix:
            return []
        self.relay_prefix += ["--host", HOST_SOCKET]
        host = socket_path(instance.spec.name, "relay")
        return ["--volume", f"{host}:{HOST_SOCKET}"]  # `--mount` takes folders only

    def _start_filter(self, instance: Instance) -> dict[str, str]:
        """The filter's sandbox, its socket published to the host; returns the agent's env."""
        if image_info(FILTER_IMAGE) is None:  # built by `image build-proxy` (A.7), never here
            raise ContainerError(f"{FILTER_IMAGE} is not built: `{PROG} image build-proxy`")
        spec = instance.spec
        secret_hosts = instance.filter_settings()
        front = egress.proxy_dir()
        published = socket_path(spec.name, "filter")
        published.unlink(missing_ok=True)
        mitmdump = shlex.join(egress.proxy_args("127.0.0.1", secret_hosts))  # `.*`: no glob
        container(
            "run", "--detach", "--rm", "--name", filter_name(spec.name),
            *labels(spec), "--cap-drop", "ALL",
            "--uid", str(os.getuid()), "--gid", str(os.getgid()),
            *bind(instance.filter_dir, "/cfg", read_only=False),
            *bind(str(front), "/handler", read_only=True),
            "--publish-socket", f"{published}:{FILTER_SOCKET}",
            "--env", f"HANDLER_HOST_ADDRESS={host_address()}",
            "--entrypoint", "sh", FILTER_IMAGE, "-c",
            f"python3 /handler/front.py {FILTER_SOCKET} {egress.PROXY_PORT} & "
            f"exec mitmdump {mitmdump}",
        )  # fmt: skip
        if not instance.filter_started():
            raise ContainerError("the network filter did not become ready")
        self.relay_targets["egress"] = str(published)
        return instance.proxy_env(f"http://{EGRESS_ADDRESS}")

    # the files group: `container` mounts folders only

    def own(self, instance: Instance, target: str) -> Path:
        """Where `target`, in one of Handler's folders, is on the host: in a folder of the
        instance, mounted read-only (`home`); its parent made."""
        folder = handler_folder(target) or target
        path = instance.dir / "own" / str(HANDLER_FOLDERS.index(folder))
        path /= os.path.relpath(target, folder)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def work_folder(self, need: WorkFolder, instance: Instance) -> Args:
        instance.put_in_home(InHome(need.path, "folder"))
        return bind(need.path, need.path, read_only=False)  # the same path

    def folder(self, need: HostFolder, instance: Instance) -> Args:
        if Path(need.source).is_file():  # `container` mounts folders only
            return self.linked_files.link(need, instance)
        if handler_folder(need.target):  # its mount point (the paste folder)
            self.own(instance, need.target).mkdir(exist_ok=True)
        instance.put_in_home(InHome(need.target, "folder"))
        return bind(need.source, need.target, read_only=not need.writable)

    def socket_folder(self, need: SocketFolder, instance: Instance) -> Args:
        """The VM's own folder (a socket in a shared one reaches neither side): each socket
        through the relay, named `s<n>/<name>` on it."""
        n = self.sockets
        self.sockets += 1
        for name in need.reaches:
            on_relay = f"s{n}/{name}"
            self.relay_prefix += ["--listen", f"unix:{need.target}/{name}={on_relay}"]
            self.relay_targets[on_relay] = str(Path(need.source) / name)
        for name in need.serves:
            on_relay = f"s{n}/{name}"
            self.relay_prefix += ["--serve", f"unix:{need.target}/{name}={on_relay}"]
            self.relay_serves[on_relay] = Path(need.source) / name
        return [*self._host_socket(instance), "--tmpfs", need.target]

    def cache(self, need: CacheFolder, instance: Instance) -> Args:
        Path(need.source).mkdir(parents=True, exist_ok=True)
        instance.put_in_home(InHome(need.target, "folder"))
        return bind(need.source, need.target, read_only=False)

    def kept_file(self, need: KeptFile, instance: Instance) -> Args:
        """U2b: its folder, holding only it (A.1), mounted writable in STATE, and a link."""
        folder = f"{STATE}/{self.kept}"
        self.kept += 1
        self.own(instance, folder).mkdir()  # its mount point
        instance.put_in_home(InHome(need.target, "link", f"{folder}/{Path(need.source).name}"))
        return bind(Path(need.source).parent, folder, read_only=False)

    def file(self, need: File, instance: Instance) -> Args:
        """Writable: written in the home's folder. Read-only (folders only): in a folder of its
        own in FILES, in Handler's read-only folder, and a link at its target."""
        if need.writable:
            instance.put_in_home(InHome(need.target, "written", need.content, int(need.mode, 8)))
            return []
        inside = f"{FILES}/{self.given}/{Path(need.target).name}"
        self.given += 1
        path = self.own(instance, inside)
        path.write_text(need.content)
        path.chmod(int(need.mode, 8))
        instance.put_in_home(InHome(need.target, "link", inside))
        return []

    def tool(self, need: HandlerTool, instance: Instance) -> Args:
        path = self.own(instance, need.target)  # at its path, in Handler's read-only folder
        path.write_text(need.content)
        path.chmod(0o555)
        return []

    def home(self, instance: Instance) -> Args:
        """/tmp and the home: a tmpfs each (writable by the user), or, the home holding what the
        needs put in it, a folder of the instance (removed with it); then Handler's own folders,
        read-only, before what is mounted in them: the CA bundle, the files and tools in them,
        mount points (the relay's, the kept files' folders, the paste folder)."""
        home = instance.spec.home
        args = ["--tmpfs", "/tmp"]
        if not instance.in_home:
            args += ["--tmpfs", home]
        else:
            host = instance.dir / "home"
            host.mkdir(mode=0o700)
            for entry in instance.in_home:
                path = host / os.path.relpath(entry.target, home)
                path.parent.mkdir(parents=True, exist_ok=True)  # a folder: its mount point's
                if entry.kind == "link":
                    path.symlink_to(entry.value)
                elif entry.kind == "written":
                    path.write_text(entry.value)
                    path.chmod(entry.mode)
            args += bind(host, home, read_only=False)
        own = [(f, instance.dir / "own" / str(i)) for i, f in enumerate(HANDLER_FOLDERS)]
        args += [a for f, d in own if d.exists() for a in bind(d, f, read_only=True)]
        return [*args, *bind(relay_dir(), RELAY_BIN, read_only=True)]

    def resources(self, instance: Instance) -> Args:
        res = instance.spec.resources
        return [
            *(["--memory", memory_arg(res.memory)] if res and res.memory else []),
            *(["--cpus", res.cpus] if res and res.cpus else []),
        ]

    # ── Apple container ─────────────────────────────────────────────────

    def _entrypoint(self, image: str) -> list[str]:
        """The image's entrypoint, which the relay runs before the spec's argv."""
        info = image_info(image) or {}
        for found in find(variant(info), "entrypoint"):
            if isinstance(found, list):
                return [str(a) for a in found]
        return []

    def command(self, spec: SandboxSpec) -> list[str]:
        """The image (by a name: `container` refuses an id) and what runs in it: handler-relay,
        which runs the image's own entrypoint then the spec's argv."""
        first, *rest = self.relay_prefix
        image = reference(spec.image)
        return ["--entrypoint", first, image, *rest, "--", *self._entrypoint(image),
                *spec.argv]  # fmt: skip

    def create(self, instance: Instance, args: Args) -> None:
        """First what dead launchers left: a launcher cannot delete its sandbox while Apple's
        service is stopped, so it stays, stopped, until this (or handlerd's start)."""
        self.sweep()
        spec = instance.spec
        args = self.linked_files.finish(args)
        if self.relay_targets or self.relay_serves:  # listening before the VM starts
            relay = RelayHost(
                socket_path(spec.name, "relay"), self.relay_targets, self.relay_serves
            )
            relay.start()
            instance.cleanups.append(relay.stop)
        container(
            "create", "--interactive", *(["--tty"] if spec.tty else []),
            "--name", spec.name, *labels(spec), "--init", *args, *self.command(spec),
        )  # fmt: skip
        for folder, place in protected(spec):  # the start may wait for the person's answer
            print(
                f"{PROG}: {folder} is in {place}, which macOS protects: if macOS asks whether "
                "container-runtime-linux may access it, allow it",
                file=sys.stderr, flush=True,
            )  # fmt: skip

    def start_failed(self, instance: Instance) -> str | None:
        """Apple's service stopped (`container system stop`: every VM ends, the agent's code 137);
        or the VM never ran, a folder in a place macOS protects: refused it, the start fails at
        once with Apple's words only, naming no folder."""
        if not service_running():
            return f"Apple's container service stopped: {START_SERVICE}, then start the agent again"
        found = protected(instance.spec)
        if not found or self.status(instance.spec.name) != "waiting":
            return None
        folder, place = found[0]
        return (
            f"the sandbox did not start: {folder} is in {place}, which macOS protects; if it was "
            f"refused to Apple container, allow container-runtime-linux in {ALLOW}, or move the "
            f"folder out of {place}"
        )

    def start(self, name: str) -> subprocess.Popen[bytes]:
        """stdin and stdout: the process's (with `tty`, its terminal's output comes through
        stdout alone). `container start` draws its progress ("Starting container", a spinner)
        when its own stderr is a terminal, and has no `--progress` to stop it (1.7.1): its stderr
        is a pipe, copied onto ours, so its words reach us and it draws none."""
        proc = subprocess.Popen(
            ["container", "start", "--attach", "--interactive", name], stderr=subprocess.PIPE
        )
        assert proc.stderr is not None
        threading.Thread(target=_copy_out, args=(proc.stderr,)).start()  # to its end
        return proc

    def _state(self, name: str) -> tuple[str | None, bool]:
        """`inspect`'s state, and whether it has started: `stopped` is a created container's state
        and an ended one's, `startedDate` set only in the second."""
        info = _json(container("inspect", name, check=False))
        for key in ("status", "state"):
            found = [f for f in find(info, key) if isinstance(f, str)]
            if found:
                return found[0].lower(), any(find(info, "startedDate"))
        return None, False

    def status(self, name: str) -> Status:
        state, started = self._state(name)
        if state in ("created", "stopped"):
            return "running" if started else "waiting"  # ended: as Docker's `exited`
        return "running" if state == "running" else "gone"

    def filter_running(self, instance: Instance) -> bool:
        return self._state(filter_name(instance.spec.name))[0] == "running"

    def wait(self, instance: Instance) -> int:
        """`inspect` keeps no exit code: the one its `attach` got."""
        while self._state(instance.spec.name)[0] == "running" and not instance.stopping:
            time.sleep(0.5)
        return attached_exit(instance)

    def stop(self, name: str) -> None:
        quiet("stop", "--time", "5", name)

    def remove(self, instance: Instance) -> None:
        quiet("delete", "--force", instance.spec.name)
        if instance.filtered:
            quiet("delete", "--force", filter_name(instance.spec.name))
        for what in ("filter", "relay"):
            socket_path(instance.spec.name, what).unlink(missing_ok=True)

    def sweep(self) -> list[str]:
        swept = []
        for c in containers():
            labels = labels_of(c)
            dead = not launcher_alive(labels.get(LAUNCHER_LABEL, ""))
            if labels.get(MANAGED_LABEL) == "1" and dead:
                name = labels.get(SANDBOX_LABEL, "")
                for each in (name, filter_name(name)):
                    quiet("delete", "--force", each)
                swept.append(name)
        return swept


def _json(text: str) -> object:
    try:
        return json.loads(text)
    except ValueError:
        return None


def host_address() -> str:
    """The host's address from Apple's default network, for the filter."""
    out = container("network", "inspect", "default", check=False)
    for found in find(_json(out), "ipv4Gateway"):
        if isinstance(found, str) and found:
            return found.split("/")[0]
    return DEFAULT_GATEWAY
