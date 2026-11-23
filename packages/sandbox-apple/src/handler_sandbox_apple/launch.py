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
import fcntl
import json
import os
import shlex
import shutil
import signal
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
from .mirror import REGISTRIES, Mirror, Upstream

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
# The caches: a sandbox only adds files to them. Each cache's folder is mounted read-only in
# CACHES (its index); what the sandbox writes over it goes to its disk, an Apple volume of its
# own mounted at DISK (`<index>/u`, `<index>/w`), the relay's overlay joining both at the cache's
# target. Once the sandbox has ended, a merge VM adds its new files to the caches (`merge`),
# then the disk is removed. A sparse file on the Mac: it holds what was written, DISK_SIZE at
# most; it does not shrink when files are deleted in it.
CACHES = f"{HANDLER_RUN}/caches"
DISK = f"{HANDLER_RUN}/disk"
DISK_SIZE = "20G"
CACHES_LABEL = "handler.caches"  # on the disk: its caches' folders, by index (JSON), for sweep
# An engine's store: the sandbox's own, on its disk (it holds files of other owners and locks no
# VM shares), whatever the caches; an `images` cache is not mounted (its downloads: the mirror).
# Podman's configuration from the runtime: files of Handler's folder (read-only), named by
# CONTAINERS_STORAGE_CONF and CONTAINERS_CONF_OVERRIDE (which the toolbox's podman wrapper adds
# to its own); nothing written in the home.
PODMAN_STORE = f"{DISK}/engine/podman"  # the relay's --nested makes `engine` the user's
PODMAN_STORAGE = f"{HANDLER_RUN}/podman/storage.conf"
PODMAN_CONF = f"{HANDLER_RUN}/podman/containers.conf"
PODMAN_REGISTRIES = f"{HANDLER_RUN}/podman/registries.conf"  # added to the image's (relay)
# the images mirror on the sandbox's loopback (mirror.py): Podman's, and Docker's (Docker Hub's)
MIRROR = "127.0.0.1:5000"
DOCKER_MIRROR = "127.0.0.1:5001"
# A `nested` sandbox: an engine inside (relay --nested), the disk always (its /tmp, /var/tmp),
# and the capabilities an engine's newuidmap gains from its file kept in the bounding set.
ENGINE_CAPS = (
    "CAP_CHOWN", "CAP_DAC_OVERRIDE", "CAP_FOWNER", "CAP_FSETID", "CAP_KILL", "CAP_SETGID",
    "CAP_SETUID", "CAP_SETPCAP", "CAP_NET_BIND_SERVICE", "CAP_SYS_CHROOT", "CAP_SETFCAP",
)  # fmt: skip
# Where inner containers reach the filter's proxy: the relay also listens on 127.0.0.1 (pasta and
# rootlesskit forward the sandbox's loopback only there), seen as Podman's
# host.containers.internal (pasta's --map-host-loopback) and Docker's 10.0.2.2 (rootlesskit).
INNER_EGRESS = "127.0.0.1:3128"
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
# has no modules, no kexec, no userfaultfd already (C7). A `nested` sandbox's VM gives user
# namespaces (an engine inside makes its containers with them): NESTED_KERNEL_SETTINGS.
KERNEL_SETTINGS = (
    "user.max_user_namespaces=0",
    "kernel.unprivileged_bpf_disabled=1",
    "kernel.io_uring_disabled=2",
    "kernel.dmesg_restrict=1",
    "kernel.kptr_restrict=2",
)
NESTED_KERNEL_SETTINGS = tuple(s for s in KERNEL_SETTINGS if not s.startswith("user."))


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


def disk_name(name: str) -> str:
    """A sandbox's disk (an Apple volume): its caches' writes."""
    return f"{name}-disk"


def disks() -> list[tuple[str, dict[str, str]]]:
    """Every sandbox's disk, with its labels."""
    listed = _json(container("volume", "list", "--format", "json", check=False) or "[]")
    found = []
    for v in listed if isinstance(listed, list) else []:
        conf = v.get("configuration", {}) if isinstance(v, dict) else {}
        labels = conf.get("labels") or {}
        if isinstance(labels, dict) and labels.get(MANAGED_LABEL) == "1" and conf.get("name"):
            found.append((str(conf["name"]), {str(k): str(x) for k, x in labels.items()}))
    return found


MERGE_TIMEOUT = 1800  # a merge VM's run, at most: a large cache's additions copied to the Mac
# A disk is held a while after the VM using it was deleted, longer under load: a VM started on
# it fails ("The storage device attachment is invalid"), and `volume delete` refuses it ("is
# currently in use"). Tried again for HELD_TIMEOUT seconds, the merge then the delete.
HELD = ("The storage device attachment is invalid", "is currently in use")
HELD_TIMEOUT = 30.0


def _until_released(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run `argv`, again while it failed on a disk still held (HELD), for HELD_TIMEOUT."""
    deadline = time.monotonic() + HELD_TIMEOUT
    while True:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        held = proc.returncode != 0 and any(h in proc.stdout + proc.stderr for h in HELD)
        if not held or time.monotonic() > deadline:
            return proc
        time.sleep(0.5)


def merge_and_remove(disk: str, sources: list[str]) -> None:
    """An ended sandbox's additions to its caches (`handler-relay merge`), in a VM of their own:
    your user (what it adds is seen as yours by later sandboxes), no network, the relay's folder,
    the disk, the caches; then the disk removed. A merge that could not run (Apple's service
    stopped) keeps the disk for `sweep`; one that failed in a cache removes it all the same: the
    worst is a cache miss. One merge of a disk at a time (two launchers sweeping at once): a
    lock of the Mac's, then the disk looked for (`container run --volume` would make a missing
    one, empty)."""
    locks = runtimes_dir() / "disks"
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / f"{disk}.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # another launcher merges it
        if not any(name == disk for name, _ in disks()):
            return  # merged and removed meanwhile
        _merge_and_remove(disk, sources)


def _merge_and_remove(disk: str, sources: list[str]) -> None:
    pairs = [(i, s) for i, s in enumerate(sources) if s and Path(s).is_dir()]  # "": images'
    if pairs:
        argv = [
            "container", "run", "--rm", "--uid", str(os.getuid()), "--gid", str(os.getgid()),
            "--network", "none", "--cap-drop", "ALL",
            "--entrypoint", f"{RELAY_BIN}/handler-relay",
            *bind(relay_dir(), RELAY_BIN, read_only=True), "--volume", f"{disk}:{DISK}",
            *(a for i, s in pairs for a in bind(s, f"{CACHES}/{i}", read_only=False)),
            FILTER_IMAGE, "merge",
            *(a for i, _ in pairs for a in (f"{DISK}/{i}/u", f"{CACHES}/{i}")),
        ]  # fmt: skip
        try:
            proc = _until_released(argv, MERGE_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"{PROG}: {disk} kept for later: its merge did not run: {e}", file=sys.stderr)
            return
        said = (proc.stdout + proc.stderr).strip()
        if proc.returncode not in (0, 125):  # `container` itself failed: the merge never ran
            print(f"{PROG}: {disk} kept for later: its merge did not run: {said}", file=sys.stderr)
            return
        if said:
            print(f"{PROG}: {said}", file=sys.stderr)
    with contextlib.suppress(OSError, subprocess.SubprocessError):  # best effort: sweep's then
        _until_released(["container", "volume", "delete", disk], 60)


# `container start --attach` (1.7.1) passes the process's output on before it watches the terminal
# for resizes: one in between (a window resized as the session starts, longer under load) is
# lost, the process left at the old size until the next. A resize signal sent to it at these
# times since its start makes it read the terminal's size again and pass it on; before it
# watches, the signal is ignored (SIGWINCH's default).
RESYNC_AT = (0.5, 1.0, 2.0, 4.0, 8.0)


def _resync_size(proc: subprocess.Popen[bytes]) -> None:
    started = time.monotonic()
    for at in RESYNC_AT:
        time.sleep(max(0.0, started + at - time.monotonic()))
        if proc.poll() is not None:
            return
        with contextlib.suppress(OSError):
            proc.send_signal(signal.SIGWINCH)


# `container create` reads an image's name twice: a name switched to another image in between (a
# rebuild's switch, D.4, as the sandbox starts) fails it ("descriptor mismatch"). Tried again,
# its image and entrypoint read again: the name's new image, the one a launch now gets.
SWITCHED = "descriptor mismatch"
SWITCHED_TRIES = 3


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
        self.caches: list[CacheFolder] = []  # by their index in CACHES and on the disk
        self.uses_disk = False  # its caches or its engine need its disk (`disk`)
        self.disk_made = False  # its disk made: merged and removed with it

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
        kernel's settings (KERNEL_SETTINGS). `nested` (A.5): what an engine inside needs of the
        VM, the relay's --nested, the disk; user namespaces in that VM only."""
        if instance.spec.isolation != "nested":
            return [
                "--read-only", "--cap-drop", "ALL",
                *(a for cap in RELAY_CAPS for a in ("--cap-add", cap)),
                *(a for s in KERNEL_SETTINGS for a in ("--kernel-arg", f"sysctl.{s}")),
            ]  # fmt: skip
        self.relay_prefix += ["--nested", DISK]
        caps = dict.fromkeys([*RELAY_CAPS, *ENGINE_CAPS])
        # the kernel's overlay (the store is on the disk, ext4: none under it to stack on)
        self.handler_file(
            instance, PODMAN_STORAGE,
            f'[storage]\ndriver = "overlay"\ngraphroot = "{PODMAN_STORE}"\n',
        )  # fmt: skip
        instance.env["CONTAINERS_STORAGE_CONF"] = PODMAN_STORAGE
        return [
            "--read-only", "--cap-drop", "ALL", *(a for cap in caps for a in ("--cap-add", cap)),
            *(a for s in NESTED_KERNEL_SETTINGS for a in ("--kernel-arg", f"sysctl.{s}")),
            *self.disk(instance),
        ]  # fmt: skip

    def disk(self, instance: Instance) -> Args:
        """The sandbox's disk (`create` makes it), once, and the capability to mount (the relay
        drops it): what its caches write, its engine's store and temporary files."""
        if self.uses_disk:
            return []
        self.uses_disk = True
        self.own(instance, DISK).mkdir()  # its mount point
        return ["--cap-add", "CAP_SYS_ADMIN", "--volume", f"{disk_name(instance.spec.name)}:{DISK}"]

    def handler_file(self, instance: Instance, target: str, content: str) -> None:
        """A file in Handler's folder (read-only in the sandbox)."""
        path = self.own(instance, target)
        path.write_text(content)
        path.chmod(0o444)

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
        nested = instance.spec.isolation == "nested"
        if isinstance(instance.spec.network, NoNetwork | FilteredNetwork):
            # loopback only; an engine's named networks need a resolv.conf (nothing answers)
            args += ["--network", "none", *(["--dns", "127.0.0.1"] if nested else ["--no-dns"])]
        # open: Apple's default network (and its relay to the filter, with secrets)
        if instance.filtered:
            args += self._host_socket(instance)
            self.relay_prefix += ["--listen", f"tcp:{EGRESS_ADDRESS}=egress"]
            if nested:
                self.relay_prefix += ["--listen", f"tcp:{INNER_EGRESS}=egress"]
                self.inner_proxy(instance)
        return args

    def inner_proxy(self, instance: Instance) -> None:
        """Containers inside a filtered `nested` sandbox reach its filter through the sandbox's
        loopback (INNER_EGRESS): Podman's by its user configuration (pasta's options, the proxy
        its containers get instead of the sandbox's own), Docker's by its daemon's environment
        (handler-dockerd, the toolbox's docker package)."""
        port = INNER_EGRESS.rsplit(":", 1)[1]
        podman = f"http://host.containers.internal:{port}"
        env = [f"{k}={podman}" for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy")]
        # dotted keys, no table header: the toolbox's podman wrapper adds them to its own
        self.handler_file(instance, PODMAN_CONF, (
            f"containers.http_proxy = false\ncontainers.env = {json.dumps(env)}\n"
            f'network.pasta_options = ["-T", "{port}", "--map-host-loopback", "169.254.1.2"]\n'
        ))  # fmt: skip
        instance.env |= {
            "CONTAINERS_CONF_OVERRIDE": PODMAN_CONF,
            "DOCKERD_ROOTLESS_ROOTLESSKIT_DISABLE_HOST_LOOPBACK": "false",
            "HANDLER_DOCKER_CONTAINERS_PROXY": f"http://10.0.2.2:{port}",
        }

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
        """A folder cache: its folder read-only in CACHES, the relay's overlay over it
        (`command`), on the disk; its mount point the relay's (a cache inside another is made
        in that one's overlay). An `images` cache is not mounted: an engine's store is the
        sandbox's own, on its disk (`isolation`); its downloads are shared by the mirror
        (`images_mirror`)."""
        Path(need.source).mkdir(parents=True, exist_ok=True)
        index = len(self.caches)
        self.caches.append(need)
        if need.kind == "images":
            return self.images_mirror(need, instance)
        self.own(instance, f"{CACHES}/{index}").mkdir()  # its mount point
        return [*bind(need.source, f"{CACHES}/{index}", read_only=True), *self.disk(instance)]

    def images_mirror(self, need: CacheFolder, instance: Instance) -> Args:
        """A `nested` sandbox's engines pull through a mirror of the registries (mirror.py),
        served here from the images cache's folder, reached on the sandbox's loopback through
        its relay: Podman's (MIRROR, `registries.conf` naming it for REGISTRIES, composed by the
        relay with the image's own) and Docker's (DOCKER_MIRROR, Docker Hub's alone, on the
        daemon's own loopback). What it lacks it fetches through the sandbox's own network."""
        if instance.spec.isolation != "nested" or self.relay_targets.get("mirror"):
            return []
        spec = instance.spec
        upstream = Upstream(
            proxy=Path(self.relay_targets["egress"]) if instance.filtered else None,
            extra_roots=instance.filter_dir / egress.CA_BUNDLE_FILE if spec.injections else None,
            offline=isinstance(spec.network, NoNetwork),
        )
        for name, address, only in (
            ("mirror", MIRROR, ""),
            ("mirror-hub", DOCKER_MIRROR, "docker.io"),
        ):
            served = Mirror(Path(need.source), upstream, only).serve(socket_path(spec.name, name))
            instance.cleanups.append(served.stop)
            self.relay_targets[name] = str(served.path)
            self.relay_prefix += ["--listen", f"tcp:{address}={name}"]
        entries = "".join(
            f'[[registry]]\nprefix = "{r}"\nlocation = "{r}"\n'
            f'[[registry.mirror]]\nlocation = "{MIRROR}/{r}"\ninsecure = true\n'
            for r in REGISTRIES
        )
        self.handler_file(instance, PODMAN_REGISTRIES, entries)
        self.relay_prefix += ["--registries", PODMAN_REGISTRIES]
        instance.env |= {
            "CONTAINERS_REGISTRIES_CONF": f"{DISK}/etc/registries.conf",
            "HANDLER_DOCKER_REGISTRY_MIRROR": f"http://{DOCKER_MIRROR}",  # the daemon's own network
        }
        return self._host_socket(instance)

    def overlays(self) -> list[str]:
        """The relay's `--overlay` for each folder cache, a cache inside another after it."""
        ordered = sorted(enumerate(self.caches), key=lambda c: Path(c[1].target).parts)
        return [
            a
            for i, c in ordered
            if c.kind == "folder"
            for a in ("--overlay", f"{CACHES}/{i}:{DISK}/{i}/u:{DISK}/{i}/w:{c.target}")
        ]

    def merged(self) -> list[str]:
        """The folders of the caches a merge adds to, by index ("" for an images cache: its
        store is the sandbox's own)."""
        return [c.source if c.kind == "folder" else "" for c in self.caches]

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
        return ["--entrypoint", first, image, *rest, *self.overlays(), "--",
                *self._entrypoint(image), *spec.argv]  # fmt: skip

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
        if self.uses_disk:
            sources = json.dumps(self.merged())
            container(
                "volume", "create", "-s", DISK_SIZE, *labels(spec),
                "--label", f"{CACHES_LABEL}={sources}", disk_name(spec.name),
            )  # fmt: skip
            self.disk_made = True
        for attempt in range(SWITCHED_TRIES):
            try:
                container(
                    "create", "--interactive", *(["--tty"] if spec.tty else []),
                    "--name", spec.name, *labels(spec), "--init", *args, *self.command(spec),
                )  # fmt: skip
                break
            except ContainerError as e:
                if SWITCHED not in str(e) or attempt == SWITCHED_TRIES - 1:
                    raise
                quiet("delete", "--force", spec.name)
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
        threading.Thread(target=_resync_size, args=(proc,), daemon=True).start()
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
        if self.disk_made:
            merge_and_remove(disk_name(instance.spec.name), self.merged())

    def start_engine(self) -> str | None:
        """Apple's service does not outlive a restart: `container system start` registers it
        with launchd until the session ends. Started here, from handlerd's own launchd session,
        the one that must see it (started over SSH, it lands in another), without asking nor
        downloading a kernel (the first `container system start` did)."""
        if service_running():
            return None
        try:
            container("system", "start", "--disable-kernel-install", timeout=120)
        except (ContainerError, OSError, subprocess.SubprocessError) as e:
            return f"Apple's container service could not be started: {e}"
        return "Apple's container service started"

    def sweep(self) -> list[str]:
        """What dead launchers left: their sandboxes, then their disks, merged first (a sandbox
        that crashed keeps what it added to its caches)."""
        swept = []
        for c in containers():
            labels = labels_of(c)
            dead = not launcher_alive(labels.get(LAUNCHER_LABEL, ""))
            if labels.get(MANAGED_LABEL) == "1" and dead:
                name = labels.get(SANDBOX_LABEL, "")
                for each in (name, filter_name(name)):
                    quiet("delete", "--force", each)
                swept.append(name)
        for name, labels in disks():
            if launcher_alive(labels.get(LAUNCHER_LABEL, "")):
                continue
            sources = _json(labels.get(CACHES_LABEL, "[]"))
            merge_and_remove(
                name,
                [s for s in sources if isinstance(s, str)] if isinstance(sources, list) else [],
            )
            if (sandbox := labels.get(SANDBOX_LABEL, "")) not in swept:
                swept.append(sandbox)
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
