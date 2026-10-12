"""`launch`: run a SandboxSpec in a rootless podman container (contract A).

Lifecycle: validate → refuse what cannot be enforced (A1) → network (+ proxy) → `podman create`
(env via a 0600 env-file deleted right after, so secrets never appear in argv, B3) →
`podman start --attach --interactive` with our stdio → cleanup of everything on exit (A4).

With `tty` (D.16), our stdio is not the process's: once created, we say READY_LINE on stderr and
wait for a client to start it on its own terminal (`attach`, cli.py), then for it to end. podman
holds the process's terminal, so whoever started us can go away meanwhile.
"""

import ipaddress
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType

from handler_contracts import (
    CA_BUNDLE,
    CA_ENV,
    FilteredNetwork,
    GeneratedFile,
    NoNetwork,
    SandboxExit,
    SandboxSpec,
    is_within,
)

from . import egress
from .podman import (
    IMAGE_MOUNT_LABEL_PREFIX,
    LAUNCHER_LABEL,
    MANAGED_LABEL,
    PROXY_IMAGE,
    SANDBOX_LABEL,
    PodmanError,
    image_config,
    image_exists,
    launcher_label,
    podman,
    quiet,
    subid_file,
    userns_args,
)

# A.6: where the display's Wayland socket appears in the container, and its private runtime dir.
DISPLAY_SOCKET = "/run/handler/wayland-0"
DISPLAY_RUNTIME_DIR = "/run/handler/runtime"


# Inner rootless podman's configuration (nested and privileged, A.5): storage on fuse-overlayfs
# (the kernel overlay cannot stack on the container's own overlay); no systemd nor journald
# (cgroupfs, events and `podman logs` in files); no sysctls and the sandbox's UTS namespace (the
# sandbox's seccomp profile refuses sethostname), none of which the sandbox can delegate. Its
# container database and volumes are the sandbox's own, in /tmp: the image store
# (~/.local/share/containers/storage) may be a cache shared with other sandboxes, and a database
# there would be another sandbox's (podman refuses one made with another runroot) and, after a
# restart, would hold containers whose runtime state is gone. Given by the sandbox, so any toolbox
# with podman works nested.
NESTED_PODMAN_CONFIG = {
    "/etc/containers/storage.conf": (
        '[storage]\ndriver = "overlay"\n'
        '[storage.options.overlay]\nmount_program = "/usr/bin/fuse-overlayfs"\n'
    ),
    "/etc/containers/containers.conf": (
        '[engine]\ncgroup_manager = "cgroupfs"\nevents_logger = "file"\n'
        'static_dir = "/tmp/podman/libpod"\nvolume_path = "/tmp/podman/volumes"\n'
        '[containers]\ndefault_sysctls = []\nutsns = "host"\nlog_driver = "k8s-file"\n'
    ),
}


class UnenforceableError(Exception):
    """A1: the spec cannot be fully enforced by this implementation."""


def is_socket(path: str) -> bool:
    try:
        return stat.S_ISSOCK(os.stat(path).st_mode)
    except OSError:
        return False


def state_root() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or str(Path.home() / ".local" / "state")
    return Path(base) / "handler-ai" / "sandboxes"


def instance_dir(name: str) -> Path:
    return state_root() / name


READY_LINE = "handler-ready"  # on stderr, with `tty`: the sandbox waits for its `attach`
ATTACH_TIMEOUT = 60.0  # seconds a `tty` sandbox waits for its `attach`
LAUNCHER_FILE = "launcher"  # in the instance dir: its launcher, as LAUNCHER_LABEL (sweep)
PROXY_ADDON = Path(__file__).parent / "proxy" / "addon.py"
PROXY_DIR = "proxy"  # in the instance dir of a filtered sandbox, from its start
PROXY_READY = "ready"  # in PROXY_DIR once its proxy answers: set-allow/set-egress wait for it


def proxy_name(name: str) -> str:
    return f"{name}-proxy"


def network_name(name: str) -> str:
    return f"{name}-net"


def check_enforceable(spec: SandboxSpec) -> None:
    if spec.confinement == "nested":
        for dev in ("/dev/fuse", "/dev/net/tun"):
            if not Path(dev).exists():
                raise UnenforceableError(f"confinement 'nested' needs {dev} on the host")
    paths = [m.source for m in spec.mounts] + [m.target for m in spec.mounts]
    paths += [m.target for m in spec.image_mounts]
    paths += [f.target for f in spec.files] + list(spec.writable_paths) + [spec.user.home]
    paths += [spec.display.socket] if spec.display else []
    for p in paths:
        if "," in p:
            raise UnenforceableError(f"path with ',' cannot be expressed as a podman --mount: {p}")
    for key, value in spec.env.items():
        if "\n" in value:
            raise UnenforceableError(
                f"env value for {key} contains a newline (env-file limitation)"
            )
    for m in spec.mounts:
        if not Path(m.source).exists():
            raise UnenforceableError(f"mount source does not exist: {m.source}")
    if spec.display and not is_socket(spec.display.socket):
        raise UnenforceableError(f"no display socket at {spec.display.socket}")


def _labels(spec: SandboxSpec, image_mounts: dict[str, str] | None = None) -> list[str]:
    labels = {
        MANAGED_LABEL: "1",
        SANDBOX_LABEL: spec.name,
        LAUNCHER_LABEL: launcher_label(),
    } | dict(spec.labels or {})
    # A6: podman does not protect an image a container only mounts; the label lets `image remove`
    # (images.py) see that this instance still uses it.
    labels |= {
        f"{IMAGE_MOUNT_LABEL_PREFIX}{image_id}": t for t, image_id in (image_mounts or {}).items()
    }
    return [arg for k, v in labels.items() for arg in ("--label", f"{k}={v}")]


def confinement_args(spec: SandboxSpec) -> list[str]:
    """A.5: how locked down the agent container is. The proxy is always strict."""
    if spec.confinement == "privileged":
        return ["--privileged", "--read-only"]
    if spec.confinement == "nested":
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


class Launch:
    def __init__(self, spec: SandboxSpec) -> None:
        self.spec = spec
        self.dir = instance_dir(spec.name)
        self.watcher: egress.EventWatcher | None = None
        self.stopping = False
        self.image_mounts: dict[str, str] = {}  # target → image id, pinned at creation (A6)

    # ── setup ───────────────────────────────────────────────────────────

    def _network(self) -> tuple[list[str], dict[str, str]]:
        """Podman network args and extra env for the agent container. A filtered sandbox reaches
        out only through its proxy; an open one directly, and through its proxy when it has
        injections (A.3), whose secrets the proxy gives."""
        net = self.spec.network
        injections = self.spec.injections
        if isinstance(net, NoNetwork):
            return ["--network", "none"], {}
        if not isinstance(net, FilteredNetwork) and not injections:
            return [], {}  # open: podman default (pasta when rootless)

        if not image_exists(PROXY_IMAGE):  # built by `image build-proxy` (A.7), never here
            raise PodmanError(
                f"{PROXY_IMAGE} is not built: `handler-sandbox-podman image build-proxy`"
            )
        name = network_name(self.spec.name)
        podman(
            "network", "create", "--internal", "--disable-dns",
            "--label", f"{MANAGED_LABEL}=1", "--label", f"{SANDBOX_LABEL}={self.spec.name}",
            "--label", f"{LAUNCHER_LABEL}={launcher_label()}",
            name,
        )  # fmt: skip
        subnet = ipaddress.ip_network(
            podman("network", "inspect", name, "--format", "{{range .Subnets}}{{.Subnet}}{{end}}")
        )
        proxy_ip = str(next(h for i, h in enumerate(subnet.hosts()) if i == 1))

        cfg = self.dir / PROXY_DIR
        state = egress.EgressState(cfg)
        if isinstance(net, FilteredNetwork):
            state.write(list(net.allow), net.enforcement)
        else:
            state.write([], "open")
        if injections:
            egress.write_secrets(cfg, injections)
        secret_hosts = [h for i in injections for h in i.hosts]
        podman(
            "run", "-d", "--rm", "--name", proxy_name(self.spec.name),
            *_labels(self.spec), *userns_args(agent=False),
            "--cap-drop=all", "--security-opt=no-new-privileges", "--read-only",
            "--network", "podman", "--network", f"{name}:ip={proxy_ip}",
            "--mount", f"type=bind,source={cfg},destination=/cfg",
            "--mount", f"type=bind,source={PROXY_ADDON},destination={egress.ADDON_TARGET},ro=true",
            PROXY_IMAGE, *egress.proxy_args(proxy_ip, secret_hosts),
        )  # fmt: skip
        if not egress.wait_until_ready(cfg):
            raise PodmanError("egress proxy did not become ready")
        self.watcher = egress.EventWatcher(cfg / egress.EVENTS_FILE)
        self.watcher.start()
        (cfg / PROXY_READY).touch()

        url = f"http://{proxy_ip}:{egress.PROXY_PORT}"
        no_proxy = "localhost,127.0.0.1,::1"
        env = {
            "HTTPS_PROXY": url, "HTTP_PROXY": url, "https_proxy": url, "http_proxy": url,
            "NO_PROXY": no_proxy, "no_proxy": no_proxy,
        }  # fmt: skip
        args = ["--network", name]
        if not isinstance(net, FilteredNetwork):
            args = ["--network", "podman", *args]  # open: its direct route too
        if injections:  # the roots it trusts: the system's and its proxy's CA
            bundle = self.dir / "ca-bundle.pem"
            shutil.copyfile(cfg / egress.CA_BUNDLE_FILE, bundle)
            bundle.chmod(0o444)
            args += ["--mount", f"type=bind,source={bundle},destination={CA_BUNDLE},ro=true"]
            env |= dict.fromkeys(CA_ENV, CA_BUNDLE)
        return args, env

    def _files(self) -> list[str]:
        """Generated files mounted read-only (seeded ones are written by _writable_mounts)."""
        args: list[str] = []
        files_dir = self.dir / "files"
        files_dir.mkdir()
        for i, f in enumerate(self.spec.files):
            if f.seed:
                continue
            path = files_dir / str(i)
            path.write_text(f.content)
            path.chmod(int(f.mode, 8) if f.mode else 0o444)
            args += ["--mount", f"type=bind,source={path},destination={f.target},ro=true"]
        if self.spec.confinement != "strict":  # what inner podman needs from us (A.5)
            nested = {f"/etc/sub{kind}": subid_file(kind) for kind in ("uid", "gid")}
            for target, content in (nested | NESTED_PODMAN_CONFIG).items():
                path = files_dir / target.replace("/", "_")
                path.write_text(content)
                path.chmod(0o444)
                args += ["--mount", f"type=bind,source={path},destination={target},ro=true"]
        return args

    def _writable_mounts(self) -> list[str]:
        """Home and writable paths: a private tmpfs each, or — when seeded files, mounts or
        generated files go inside — a per-instance host directory (removed with the instance, A4)
        holding those files and the mount points. Created here, as the user: podman would create
        missing mount points as root, leaving e.g. ~/.vibe/logs unwritable around
        ~/.vibe/logs/session, or ~/.config around ~/.config/mcp/mcp.json (then Chromium, which
        writes ~/.config/chromium, cannot start)."""
        home = self.spec.user.home
        roots = [home] + [p for p in self.spec.writable_paths if p not in (home, "/tmp")]

        def deepest_root(target: str) -> str | None:
            inside = [r for r in roots if is_within(target, r) and target != r]
            return max(inside, key=len) if inside else None

        seeded: dict[str, list[GeneratedFile]] = {}
        for f in self.spec.files:
            if f.seed:  # always inside a writable root (A1)
                seeded.setdefault(
                    max((r for r in roots if is_within(f.target, r)), key=len), []
                ).append(f)
        nested: dict[str, list[tuple[str, bool]]] = {}  # root → (mount point, is a directory)
        for m in self.spec.mounts:
            if root := deepest_root(m.target):
                nested.setdefault(root, []).append((m.target, Path(m.source).is_dir()))
        for f in self.spec.files:
            if not f.seed and (root := deepest_root(f.target)):  # bound read-only by _files
                nested.setdefault(root, []).append((f.target, False))
        args = ["--mount", "type=tmpfs,destination=/tmp,tmpfs-mode=1777,notmpcopyup"]
        for i, root in enumerate(roots):
            if root not in seeded and root not in nested:
                args += _tmpfs(root, "0700")
                continue
            host = self.dir / "writable" / str(i)
            host.mkdir(parents=True, mode=0o700)
            for target, is_dir in nested.get(root, []):
                point = host / os.path.relpath(target, root)
                if is_dir:
                    point.mkdir(parents=True, exist_ok=True)
                else:
                    point.parent.mkdir(parents=True, exist_ok=True)
                    point.touch()
            for f in seeded.get(root, []):
                path = host / os.path.relpath(f.target, root)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f.content)
                path.chmod(int(f.mode, 8) if f.mode else 0o600)
            # U: owned by the sandbox user (a no-op with keep-id, where it is already the owner)
            args += ["--mount", f"type=bind,source={host},destination={root},U=true"]
        return args

    def _resolve_images(self) -> dict[str, str]:
        """A6: pin every image mount to an id now, and compute PATH = the image's + pathAppend.
        Returns the extra env (PATH), empty without pathAppend."""
        for m in self.spec.image_mounts:
            try:
                self.image_mounts[m.target] = image_config(m.image)[0]
            except PodmanError:
                raise PodmanError(
                    f"image {m.image} (for {m.target}) is missing: build it first"
                ) from None
        if not self.spec.path_append:
            return {}
        base = image_config(self.spec.image)[1].get("PATH", "/usr/local/bin:/usr/bin:/bin")
        return {"PATH": ":".join([base, *self.spec.path_append])}

    def _image_mounts(self) -> list[str]:
        return [
            arg
            for target, image_id in self.image_mounts.items()
            for arg in ("--mount", f"type=image,source={image_id},destination={target},rw=false")
        ]

    def _mounts(self) -> list[str]:
        args = self._writable_mounts()
        for m in self.spec.mounts:
            ro = ",ro=true" if m.read_only else ""
            args += ["--mount", f"type=bind,source={m.source},destination={m.target}{ro}"]
        return args

    def _display(self) -> tuple[list[str], dict[str, str]]:
        """A.6: only the Wayland socket, at a fixed path, and a private runtime dir."""
        if not self.spec.display:
            return [], {}
        args = [
            "--mount",
            f"type=bind,source={self.spec.display.socket},destination={DISPLAY_SOCKET}",
        ]
        args += _tmpfs(DISPLAY_RUNTIME_DIR, "0700")
        return args, {"WAYLAND_DISPLAY": DISPLAY_SOCKET, "XDG_RUNTIME_DIR": DISPLAY_RUNTIME_DIR}

    def _env_file(self, extra: dict[str, str]) -> Path:
        env = extra | dict(self.spec.env) | {"HOME": self.spec.user.home}
        path = self.dir / "env"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.writelines(f"{k}={v}\n" for k, v in env.items())
        return path

    def create(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=False)
        (self.dir / LAUNCHER_FILE).write_text(launcher_label())
        if isinstance(self.spec.network, FilteredNetwork) or self.spec.injections:
            (self.dir / PROXY_DIR).mkdir()  # set-allow/set-egress now wait for its proxy
        path_env = self._resolve_images()
        net_args, net_env = self._network()
        display_args, display_env = self._display()
        env_file = self._env_file(net_env | path_env | display_env)
        res = self.spec.resources
        try:
            podman(
                "create", "--rm", "--interactive", *(["--tty"] if self.spec.tty else []),
                "--init", "--name", self.spec.name,
                *_labels(self.spec, self.image_mounts), *userns_args(),
                *confinement_args(self.spec),
                *self._mounts(), *self._image_mounts(), *self._files(), *display_args,
                "--env-file", str(env_file), "--workdir", self.spec.workdir,
                *net_args,
                *(["--memory", res.memory] if res and res.memory else []),
                *(["--cpus", res.cpus] if res and res.cpus else []),
                self.spec.image, *self.spec.argv,
            )  # fmt: skip
        finally:
            env_file.unlink(missing_ok=True)  # secrets live only in podman's container config

    # ── run & cleanup ───────────────────────────────────────────────────

    def _on_signal(self, signum: int, _frame: FrameType | None) -> None:
        if not self.stopping:
            self.stopping = True
            quiet("stop", "--time", "5", self.spec.name)

    def run(self) -> int:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, self._on_signal)
        if self.spec.tty:
            return self._run_attached_elsewhere()
        proc = subprocess.Popen(["podman", "start", "--attach", "--interactive", self.spec.name])
        while True:
            try:
                return proc.wait()
            except InterruptedError:
                continue

    def _status(self) -> str | None:
        """The container's state; None once it is gone (`--rm`)."""
        try:
            return podman("container", "inspect", "--format", "{{.State.Status}}", self.spec.name)
        except PodmanError:
            return None

    def _run_attached_elsewhere(self) -> int:
        """`tty`: until a client has started the container (`attach`), then until it ends; its
        exit code reaches that client, ours is only logged."""
        print(READY_LINE, file=sys.stderr, flush=True)
        deadline = time.monotonic() + ATTACH_TIMEOUT
        while (status := self._status()) == "created" and not self.stopping:
            if time.monotonic() > deadline:
                print("handler-sandbox-podman: nobody attached, stopping", file=sys.stderr)
                return SandboxExit.SETUP_FAILED
            time.sleep(0.2)
        if status is None or self.stopping:
            return 0
        waited = subprocess.run(
            ["podman", "wait", self.spec.name], capture_output=True, text=True, check=False
        )
        return int(waited.stdout.strip()) if waited.stdout.strip().isdigit() else 0

    def cleanup(self) -> None:
        # A4: every step runs even if an earlier one fails — never leave resources behind.
        if self.watcher:
            try:
                self.watcher.stop()
                self.watcher.join(timeout=1)
            except Exception as e:  # report and keep cleaning up
                print(f"handler-sandbox-podman: egress event watcher: {e}", file=sys.stderr)
        quiet("rm", "--force", "--time", "0", self.spec.name)
        if isinstance(self.spec.network, FilteredNetwork) or self.spec.injections:  # its proxy
            quiet("rm", "--force", "--time", "0", proxy_name(self.spec.name))
            quiet("network", "rm", "--force", network_name(self.spec.name))
        shutil.rmtree(self.dir, ignore_errors=True)


def launch(spec: SandboxSpec) -> int:
    try:
        check_enforceable(spec)
    except UnenforceableError as e:
        print(f"handler-sandbox-podman: refused (A1): {e}", file=sys.stderr)
        return SandboxExit.UNENFORCEABLE
    if instance_dir(spec.name).exists():
        print(f"handler-sandbox-podman: sandbox name in use: {spec.name}", file=sys.stderr)
        return SandboxExit.SETUP_FAILED

    run = Launch(spec)
    try:
        try:
            run.create()
        except (PodmanError, OSError, subprocess.SubprocessError) as e:
            print(f"handler-sandbox-podman: setup failed: {e}", file=sys.stderr)
            return SandboxExit.SETUP_FAILED
        return run.run()
    finally:
        run.cleanup()
