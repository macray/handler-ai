"""A sandbox's launch, the same on every runtime (contract A): refuse what cannot be given (A1) →
its instance folder → each need of the spec, by the runtime's method for it → create → run (with
`tty`: until a client's `attach`) → clean up everything (A4). Also what comes after a launch, the
same on every runtime too: a `tty` sandbox's `attach`, and the `sweep` of what dead launchers left.

A runtime is the `Runtime` below: one method per need, each giving that need its own way (the
arguments it adds to its engine's `create`, after preparing what it needs in the instance
folder), and its engine's verbs. Its workarounds live in those methods, each one named. The
instance folder's layout is the kit's alone: a runtime has `Instance.dir` for what its needs
prepare, `Instance.filter_dir` for its filter, `runtimes_dir()` for its own folders."""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Literal

from handler_contracts import (
    CA_BUNDLE,
    CA_ENV,
    HANDLER_BIN,
    PASTE_DIR,
    PASTE_IMAGE,
    Ability,
    Addon,
    CacheFolder,
    File,
    FilteredNetwork,
    HandlerTool,
    HostFolder,
    KeptFile,
    Paste,
    SandboxExit,
    SandboxSpec,
    SocketFolder,
    WorkFolder,
    is_within,
)

from . import egress
from .launcher import (
    LAUNCHER_LABEL,
    MANAGED_LABEL,
    SANDBOX_LABEL,
    launcher_alive,
    launcher_label,
)

Args = list[str]
Status = Literal["waiting", "running", "gone"]  # a created sandbox: not started yet, or ended

READY_LINE = "handler-ready"  # on stderr, with `tty`: the sandbox waits for its `attach`
ATTACH_TIMEOUT = 60.0  # seconds a `tty` sandbox waits for its `attach`
FILTER_START_TIMEOUT = 60  # seconds a starting sandbox's filter is waited for (running_filter)
FILTER_CHECK_INTERVAL = 2.0  # seconds between two checks that a running sandbox's filter runs
FILTER_STOPPED = "its network filter stopped, so the sandbox was ended"

# the instance folder's layout, the kit's alone
_LAUNCHER_FILE = "launcher"  # its launcher (sweep)
_FILTER_DIR = "proxy"  # the filter's settings, events and CA, from its start
_FILTER_READY = "ready"  # in the filter's folder once its filter answers (running_filter)
# a `tty` sandbox whose start, by `attach`, failed before it ran: attach writes _START_ENDED (the
# start's exit code), its launcher answers _START_FAILED (why), which attach says and removes
_START_ENDED = "start-ended"
_START_FAILED = "start-failed"
START_REASON_TIMEOUT = 5.0  # seconds `attach` waits for its launcher's reason, and it for attach
_ATTACH_EXIT = "attach-exit"  # a `tty` process's exit code, as its `attach` got it (attached_exit)
ATTACH_EXIT_TIMEOUT = 5.0  # seconds the launcher waits for it once the sandbox has stopped

# D.16: a terminal's program reads what the client pasted as its clipboard. Harnesses read an
# image with `xclip … -o` first (Claude Code: `-t TARGETS`, then `-t image/png`; the toolbox has
# no xclip), so this one, a command (HANDLER_BIN), answers from the paste folder; nothing there,
# it fails and they try the next way (`wl-paste`: the display's clipboard, when there is one).
PASTE_XCLIP = f"""#!/bin/sh
# handler: what handler terminal pasted (D.16), read the way xclip reads the clipboard
image={PASTE_DIR}/{PASTE_IMAGE}
case " $* " in *" -o "*) ;; *) exit 1 ;; esac
[ -f "$image" ] || exit 1
case " $* " in
  *" TARGETS "*) echo image/png ;;
  *" image/png "*) exec cat "$image" ;;
  *) exit 1 ;;
esac
"""


class UnenforceableError(Exception):
    """A1: the spec cannot be fully given by this runtime, here."""


def runtimes_dir() -> Path:
    """Where the runtimes keep their files on this host: the kit's instance folders in
    `sandboxes/`, a runtime's own folders beside it."""
    base = os.environ.get("XDG_RUNTIME_DIR") or str(Path.home() / ".local" / "state")
    return Path(base) / "handler-ai"


def _instances_dir() -> Path:
    return runtimes_dir() / "sandboxes"


def _instance_dir(name: str) -> Path:
    return _instances_dir() / name


def running_filter(name: str) -> Path | None:
    """The folder of sandbox `name`'s filter (its settings: egress.EgressState) once the filter
    answers, None when it has none. One still starting is waited for: its connection is already
    the agent's (A.4)."""
    folder = _instance_dir(name) / _FILTER_DIR
    deadline = time.monotonic() + FILTER_START_TIMEOUT
    while folder.is_dir() and not (folder / _FILTER_READY).exists():
        if time.monotonic() > deadline:
            return None
        time.sleep(0.05)
    return folder if (folder / _FILTER_READY).exists() else None


@dataclass(frozen=True)
class InHome:
    """What a need puts in the home: the point a folder (`folder`) or a file (`file`) is mounted
    on, a link to elsewhere in the sandbox (`link`, `value` where it leads), or a file written
    there (`written`, `value` its content). Each runtime makes them its own way."""

    target: str
    kind: Literal["folder", "file", "link", "written"]
    value: str = ""
    mode: int = 0o600


class Instance:
    """A sandbox being launched: its spec, its host folder (removed with it), and what its needs
    set up on the way."""

    def __init__(self, spec: SandboxSpec) -> None:
        self.spec = spec
        self.dir = _instance_dir(spec.name)
        self.env: dict[str, str] = {}  # the needs' (the filter's proxy, the display, PATH)
        self.in_home: list[InHome] = []  # what the needs put in the home
        self.cleanups: list[Callable[[], None]] = []  # what a need started, stopped first
        self.watcher: egress.EventWatcher | None = None
        self.stopping = False
        self.filter_stopped = False  # its filter ended while it ran: the launcher ended it

    def new_file(self, folder: str, content: str, mode: int) -> Path:
        """A new file in a folder of the instance (removed with it), for the sandbox to mount."""
        where = self.dir / folder
        where.mkdir(exist_ok=True)
        path = where / str(len(os.listdir(where)))
        path.write_text(content)
        path.chmod(mode)
        return path

    def home_folder(self) -> Path:
        """A folder of the instance (removed with it) to mount as the home: what the needs put in
        it (`in_home`), made here as the host user: an engine would make missing mount points as
        root, leaving e.g. ~/.config unwritable around ~/.config/mcp/mcp.json."""
        host = self.dir / "home"
        host.mkdir(mode=0o700)
        for entry in self.in_home:
            path = host / os.path.relpath(entry.target, self.spec.home)
            if entry.kind == "folder":
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if entry.kind == "file":
                path.touch()
            else:  # written (links are Apple's)
                path.write_text(entry.value)
                path.chmod(entry.mode)
        return host

    def put_in_home(self, entry: InHome) -> None:
        """Record `entry` when its target is in the home (a need elsewhere needs nothing of it)."""
        if is_within(entry.target, self.spec.home) and entry.target != self.spec.home:
            self.in_home.append(entry)

    @property
    def filtered(self) -> bool:
        """Its network goes through Handler's filter: an allow-list, or secrets to give (A.3)."""
        return isinstance(self.spec.network, FilteredNetwork) or bool(self.spec.injections)

    @property
    def filter_dir(self) -> Path:
        return self.dir / _FILTER_DIR

    def filter_settings(self) -> list[str]:
        """Write the filter's settings and secrets in its folder; the hosts its secrets go to."""
        state = egress.EgressState(self.filter_dir)
        net = self.spec.network
        if isinstance(net, FilteredNetwork):
            state.write(list(net.allow), list(net.blocked), net.enforcement)
        else:
            state.write([], [], "open")
        if self.spec.injections:
            egress.write_secrets(self.filter_dir, self.spec.injections)
        return [h for i in self.spec.injections for h in i.hosts]

    def filter_started(self) -> bool:
        """Once the runtime started the filter: whether it answers. Its events are then reported
        (A.3) and `set-allow`/`set-blocked`/`set-egress` no longer wait for it."""
        if not egress.wait_until_ready(self.filter_dir):
            return False
        self.watcher = egress.EventWatcher(self.filter_dir / egress.EVENTS_FILE)
        self.watcher.start()
        (self.filter_dir / _FILTER_READY).touch()
        return True

    def proxy_env(self, url: str) -> dict[str, str]:
        """What leads the sandbox's programs to its filter at `url`, and (with secrets) the roots
        they trust, at CA_BUNDLE (A.3)."""
        no_proxy = "localhost,127.0.0.1,::1"
        env = {
            "HTTPS_PROXY": url, "HTTP_PROXY": url, "https_proxy": url, "http_proxy": url,
            "NO_PROXY": no_proxy, "no_proxy": no_proxy,
        }  # fmt: skip
        if self.spec.injections:
            env |= dict.fromkeys(CA_ENV, CA_BUNDLE)
        return env

    def env_file(self) -> Path:
        """The process's environment in a 0600 file, for the engine's `--env-file`: secrets never
        in a command line (B3). Removed once the sandbox is created."""
        env = self.env | dict(self.spec.env) | {"HOME": self.spec.home}
        path = self.dir / "env"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.writelines(f"{k}={v}\n" for k, v in env.items())
        return path


def labels(spec: SandboxSpec) -> Args:
    """The labels of what a runtime creates for a sandbox (`sweep` finds them by the launcher's),
    then the spec's own."""
    own = {MANAGED_LABEL: "1", SANDBOX_LABEL: spec.name, LAUNCHER_LABEL: launcher_label()}
    return [a for k, v in (own | dict(spec.labels or {})).items() for a in ("--label", f"{k}={v}")]


class Runtime(ABC):
    """A sandbox runtime: what it gives here, one method per need, and its engine's verbs."""

    prog: str  # its executable's name, in what it says
    errors: tuple[type[Exception], ...]  # its engine's failures: a setup that failed

    @abstractmethod
    def abilities(self) -> frozenset[Ability]:
        """What it gives here (A.8): `check` prints it, a spec needing more is refused (A1)."""

    @abstractmethod
    def refuse(self, spec: SandboxSpec) -> None:
        """Its own refusals (A1): what only a fact of this host or engine forbids. Raises
        UnenforceableError."""

    @abstractmethod
    def image_path(self, image: str) -> str:
        """The image's own PATH, which the addons' folders and HANDLER_BIN extend."""

    # ── the needs: each returns the arguments it adds to `create` ──────

    @abstractmethod
    def host_user(self, instance: Instance) -> Args:
        """The process runs as the host user's uid/gid (A3)."""

    @abstractmethod
    def isolation(self, instance: Instance) -> Args:
        """What keeps the sandbox from the computer, at the spec's level (A.5)."""

    @abstractmethod
    def network(self, instance: Instance) -> Args:
        """None, open, or filtered through Handler's filter (started here), with the secrets it
        gives (A.3); its env in `instance.env`."""

    # the files group (A.1): each need may put what it needs in the home (Instance.put_in_home)

    @abstractmethod
    def work_folder(self, need: WorkFolder, instance: Instance) -> Args:
        """The scope, read-write, at the same path (A2)."""

    @abstractmethod
    def folder(self, need: HostFolder, instance: Instance) -> Args: ...

    def socket_folder(self, need: SocketFolder, instance: Instance) -> Args:
        """Its sockets each way, as declared (A.10). Where a socket crosses a bind mount (one
        kernel, or a VM whose engine passes sockets): the folder, writable, and nothing else."""
        return self.folder(
            HostFolder(source=need.source, target=need.target, writable=True), instance
        )

    @abstractmethod
    def cache(self, need: CacheFolder, instance: Instance) -> Args:
        """Its folder created if missing."""

    @abstractmethod
    def kept_file(self, need: KeptFile, instance: Instance) -> Args: ...

    @abstractmethod
    def file(self, need: File, instance: Instance) -> Args: ...

    @abstractmethod
    def tool(self, need: HandlerTool, instance: Instance) -> Args:
        """Executable, in one of Handler's folders, which no image has."""

    @abstractmethod
    def home(self, instance: Instance) -> Args:
        """The home, writable, empty at the start but for what the needs put in it
        (`instance.in_home`), discarded; /tmp likewise. Made after the other needs, its
        arguments before theirs."""

    def paste(self, need: Paste, instance: Instance) -> Args:
        """An image pasted in the terminal reaches `xclip -o` (D.16): its folder, read-only at
        PASTE_DIR, and PASTE_XCLIP, a command. Every runtime gives it this way."""
        folder = HostFolder(source=need.source, target=PASTE_DIR, writable=False)
        xclip = HandlerTool(target=f"{HANDLER_BIN}/xclip", content=PASTE_XCLIP)
        return [*self.folder(folder, instance), *self.tool(xclip, instance)]

    def display(self, instance: Instance) -> Args:
        """Its windows on the person's screen (A.6), the display the runtime finds: only a
        runtime giving `display`."""
        raise NotImplementedError(f"{self.prog} does not give a display")

    def addon(self, need: Addon, instance: Instance) -> Args:
        """An addon's folder, read-only at its target (A.1). Every runtime gives it this way."""
        folder = HostFolder(source=need.source, target=need.target, writable=False)
        return self.folder(folder, instance)

    @abstractmethod
    def resources(self, instance: Instance) -> Args:
        """Memory and CPU limits, those this host lets it apply (A.8 `limits`)."""

    # ── its engine ──────────────────────────────────────────────────────

    @abstractmethod
    def create(self, instance: Instance, args: Args) -> None:
        """Create the sandbox, not started: the needs' arguments, the environment's file's."""

    @abstractmethod
    def start(self, name: str) -> subprocess.Popen[bytes]:
        """Start it attached to our stdio."""

    @abstractmethod
    def status(self, name: str) -> Status: ...

    @abstractmethod
    def filter_running(self, instance: Instance) -> bool:
        """Whether a filtered sandbox's filter still runs: False once it ended (killed, out of
        memory), removed or not."""

    @abstractmethod
    def wait(self, instance: Instance) -> int:
        """Until a started `tty` sandbox ends: its exit code, when the engine tells it."""

    def start_failed(self, instance: Instance) -> str | None:
        """Once its engine's start (attached for the whole run) has ended in error: why, when it
        is the engine's and the runtime knows what the person can do (a folder refused, the
        engine stopped); the launcher says it and exits SETUP_FAILED (A.1). None (the default):
        the start's own exit code is the launcher's."""
        return None

    def attached(self, folder: Path, code: int) -> None:
        """After a `tty` sandbox's `attach`, the exit code it got (`folder`: the sandbox's
        instance folder), for `wait` to read with `attached_exit`: an engine may keep none
        (Apple's `inspect`), or none once its `--rm` removed the sandbox (podman)."""
        with contextlib.suppress(OSError):  # its launcher gone: nobody to tell
            (folder / f"{_ATTACH_EXIT}.new").write_text(str(code))
            (folder / f"{_ATTACH_EXIT}.new").replace(folder / _ATTACH_EXIT)

    @abstractmethod
    def stop(self, name: str) -> None:
        """Stop it, best effort."""

    @abstractmethod
    def remove(self, instance: Instance) -> None:
        """Remove what the engine holds of it (its filter too), best effort, never raising."""

    @abstractmethod
    def sweep(self) -> list[str]:
        """Remove what the engine holds of sandboxes whose launcher is gone (`launcher_alive` on
        the label `create` put on it), never what a live one is still setting up: their names."""


def check_enforceable(runtime: Runtime, spec: SandboxSpec) -> None:
    """A1: the abilities it needs, then what every runtime's engine refuses, then the runtime's
    own refusals."""
    if missing := spec.abilities() - runtime.abilities():
        raise UnenforceableError(f"not given here: {', '.join(sorted(missing))} (A.8)")
    for source in [spec.work_folder.path, *(n.source for n in [*spec.folders, *spec.kept_files])]:
        if not Path(source).exists():
            raise UnenforceableError(f"{source} does not exist")
    paths = [spec.home, *spec.targets()]
    paths += [
        n.source for n in [*spec.folders, *spec.socket_folders, *spec.caches, *spec.kept_files]
    ]
    for p in paths:
        if "," in p:
            raise UnenforceableError(f"path with ',' cannot be expressed as a --mount: {p}")
    for key, value in spec.env.items():
        if "\n" in value:
            raise UnenforceableError(f"env value for {key} contains a newline (env-file)")
    runtime.refuse(spec)


def create(runtime: Runtime, instance: Instance) -> None:
    """Each need of the spec by the runtime's method, then the sandbox, created."""
    spec = instance.spec
    instance.dir.mkdir(parents=True, exist_ok=False)
    (instance.dir / _LAUNCHER_FILE).write_text(launcher_label())
    if instance.filtered:
        instance.filter_dir.mkdir()  # set-allow/set-blocked/set-egress now wait for its filter
    args = [
        *runtime.host_user(instance),
        *runtime.isolation(instance),
        *(runtime.display(instance) if spec.display else []),
        *runtime.network(instance),  # its filter started: what the files may need of it
    ]
    files = [
        *runtime.work_folder(spec.work_folder, instance),
        *(a for n in spec.folders for a in runtime.folder(n, instance)),
        *(a for n in spec.socket_folders for a in runtime.socket_folder(n, instance)),
        *(a for n in spec.addons for a in runtime.addon(n, instance)),
        *(a for n in spec.caches for a in runtime.cache(n, instance)),
        *(a for n in spec.kept_files for a in runtime.kept_file(n, instance)),
        *(a for n in spec.files for a in runtime.file(n, instance)),
        *(a for n in spec.tools for a in runtime.tool(n, instance)),
        *(runtime.paste(spec.paste, instance) if spec.paste else []),
    ]
    args += [*runtime.home(instance), *files, *runtime.resources(instance)]
    commands = [c.path for c in spec.caches if c.path] + [a.path for a in spec.addons if a.path]
    if spec.paste or any(is_within(t.target, HANDLER_BIN) for t in spec.tools):
        commands.append(HANDLER_BIN)
    if commands:  # the image's PATH, then the caches', the addons' (A.1)
        instance.env["PATH"] = ":".join([runtime.image_path(spec.image), *commands])
    env_file = instance.env_file()
    try:
        runtime.create(instance, [*args, "--env-file", str(env_file), "--workdir", spec.workdir])
    finally:
        env_file.unlink(missing_ok=True)  # secrets live only in the engine's configuration


class FilterWatch(threading.Thread):
    """While a filtered sandbox runs, whether its filter still does, every FILTER_CHECK_INTERVAL.
    Its filter gone, the sandbox's requests all fail (it fails closed), its secrets are given no
    more: the launcher says so and ends it (rule `network.a-stopped-filter-ends-its-sandbox`), its exit FILTER_STOPPED."""

    def __init__(self, runtime: Runtime, instance: Instance) -> None:
        super().__init__(daemon=True, name="handler-filter-watch")
        self.runtime = runtime
        self.instance = instance
        self._done = threading.Event()

    def stop(self) -> None:
        self._done.set()

    def run(self) -> None:
        instance = self.instance
        while not self._done.wait(FILTER_CHECK_INTERVAL):
            if instance.stopping or self.runtime.filter_running(instance):
                continue
            if instance.stopping or self._done.is_set():  # ended meanwhile, its filter with it
                return
            instance.filter_stopped = instance.stopping = True
            print(f"{self.runtime.prog}: {FILTER_STOPPED}", file=sys.stderr, flush=True)
            self.runtime.stop(instance.spec.name)
            return


def run(runtime: Runtime, instance: Instance) -> int:
    """Until the sandbox ends; a signal stops it, and so does its filter's end (FilterWatch).
    With `tty`, its process is not on our stdio: we say READY_LINE and wait for a client to start
    it on its own terminal (`attach`), then for it to end, its exit code that client's."""

    def on_signal(_signum: int, _frame: FrameType | None) -> None:
        if not instance.stopping:
            instance.stopping = True
            runtime.stop(instance.spec.name)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, on_signal)
    watch = FilterWatch(runtime, instance) if instance.filtered else None
    if watch is not None:
        watch.start()
    try:
        code = _run(runtime, instance)
    finally:
        if watch is not None:
            watch.stop()
    if instance.filter_stopped and code != SandboxExit.SETUP_FAILED:  # the engine's reason first
        return SandboxExit.FILTER_STOPPED
    return code


def _run(runtime: Runtime, instance: Instance) -> int:
    if not instance.spec.tty:
        proc = runtime.start(instance.spec.name)
        while True:
            try:
                code = proc.wait()
                break
            except InterruptedError:
                continue
        if code != 0 and (why := runtime.start_failed(instance)):
            print(f"{runtime.prog}: {why}", file=sys.stderr)
            return SandboxExit.SETUP_FAILED
        return code
    print(READY_LINE, file=sys.stderr, flush=True)
    deadline = time.monotonic() + ATTACH_TIMEOUT
    while runtime.status(instance.spec.name) == "waiting" and not instance.stopping:
        if (instance.dir / _START_ENDED).exists():  # attach's start failed: it never ran
            return _start_failed(runtime, instance)
        if time.monotonic() > deadline:
            print(f"{runtime.prog}: nobody attached, stopping", file=sys.stderr)
            return SandboxExit.SETUP_FAILED
        time.sleep(0.2)
    if instance.stopping:
        return 0
    return runtime.wait(instance)  # gone already: ended between two looks, its code still told


def attached_exit(instance: Instance) -> int:
    """A `tty` sandbox that ended: the code its `attach` got (`Runtime.attached`), written right
    after the end, hence the wait; 0 when it never comes (an `attach` killed)."""
    path = instance.dir / _ATTACH_EXIT
    deadline = time.monotonic() + ATTACH_EXIT_TIMEOUT
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return 0


def _start_failed(runtime: Runtime, instance: Instance) -> int:
    """A `tty` sandbox's start by `attach` failed before it ran: why, said here (handlerd's log)
    and to `attach`, which says it on the person's terminal; waited for it to read it (its
    folder goes with the cleanup)."""
    code = (instance.dir / _START_ENDED).read_text().strip()
    why = runtime.start_failed(instance) or f"the sandbox did not start (exit {code})"
    print(f"{runtime.prog}: {why}", file=sys.stderr, flush=True)
    answer = instance.dir / _START_FAILED
    (instance.dir / f"{_START_FAILED}.new").write_text(why)
    (instance.dir / f"{_START_FAILED}.new").replace(answer)
    deadline = time.monotonic() + START_REASON_TIMEOUT
    while answer.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return SandboxExit.SETUP_FAILED


def cleanup(runtime: Runtime, instance: Instance) -> None:
    """A4: every step runs even if an earlier one fails — never leave resources behind."""
    for stop in [*instance.cleanups, *([instance.watcher.stop] if instance.watcher else [])]:
        try:
            stop()
        except Exception as e:  # report and keep cleaning up
            print(f"{runtime.prog}: cleanup: {e}", file=sys.stderr)
    if instance.watcher:
        instance.watcher.join(timeout=1)
    runtime.remove(instance)
    if error := _remove_instance_dir(instance.dir):
        print(f"{runtime.prog}: cleanup: {error}", file=sys.stderr)


def _remove_instance_dir(d: Path) -> str | None:
    """Its folder, even the folders an agent made read-only (Vibe's logs: `dr-x------`); the
    launcher's file last, so that a folder left (the error said) is swept once its launcher died."""

    def writable(_func: Callable[..., object], path: str, e: BaseException) -> None:
        if not isinstance(e, PermissionError):
            raise e
        os.chmod(os.path.dirname(path), 0o700)  # the folder holding it, then once more
        if os.path.isdir(path) and not os.path.islink(path):
            os.chmod(path, 0o700)
            shutil.rmtree(path, onexc=writable)
        else:
            os.unlink(path)

    try:
        for child in d.iterdir():
            if child.name == _LAUNCHER_FILE:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, onexc=writable)
            else:
                child.unlink()
        (d / _LAUNCHER_FILE).unlink(missing_ok=True)
        d.rmdir()
    except FileNotFoundError:
        return None
    except OSError as e:
        return f"{d} not removed: {e}"
    return None


def launch(runtime: Runtime, spec: SandboxSpec) -> int:
    try:
        check_enforceable(runtime, spec)
    except UnenforceableError as e:
        print(f"{runtime.prog}: refused (A1): {e}", file=sys.stderr)
        return SandboxExit.UNENFORCEABLE
    if _instance_dir(spec.name).exists():
        print(f"{runtime.prog}: sandbox name in use: {spec.name}", file=sys.stderr)
        return SandboxExit.SETUP_FAILED
    instance = Instance(spec)
    try:
        try:
            create(runtime, instance)
        except (*runtime.errors, OSError, subprocess.SubprocessError) as e:
            print(f"{runtime.prog}: setup failed: {e}", file=sys.stderr)
            return SandboxExit.SETUP_FAILED
        return run(runtime, instance)
    finally:
        cleanup(runtime, instance)


def attach(runtime: Runtime, name: str) -> int:
    """A `tty` sandbox (D.16): start its process on this terminal (raw, resized with it, the
    engine passing our signals on), its exit code ours. When this terminal goes away first (a
    hang-up), the process gets it too; whatever still runs then is stopped. A start that failed
    before the process ran: its launcher's reason, said after the engine's own words, and
    SETUP_FAILED."""
    proc: subprocess.Popen[bytes] | None = None

    def pass_on(signum: int, _frame: FrameType | None) -> None:
        # a hang-up is the session leader's (this process), not the engine's: it passes it in
        if proc is not None:
            proc.send_signal(signum)

    for sig in (signal.SIGHUP, signal.SIGTERM):  # not to die before the stop below
        signal.signal(sig, pass_on)
    proc = runtime.start(name)
    code = proc.wait()
    runtime.attached(_instance_dir(name), code)
    if code != 0 and runtime.status(name) == "waiting":  # it never ran
        return _said_start_failed(runtime, name, code)
    runtime.stop(name)
    return code


def _said_start_failed(runtime: Runtime, name: str, code: int) -> int:
    """Tell the launcher the start failed, and say its reason here (none within
    START_REASON_TIMEOUT: the start's own code)."""
    folder = _instance_dir(name)
    try:
        (folder / _START_ENDED).write_text(str(code))
    except OSError:  # its launcher gone, its folder with it
        return code
    answer = folder / _START_FAILED
    deadline = time.monotonic() + START_REASON_TIMEOUT
    while time.monotonic() < deadline:
        try:
            why = answer.read_text()
        except FileNotFoundError:
            time.sleep(0.05)
            continue
        answer.unlink(missing_ok=True)
        print(f"{runtime.prog}: {why}", file=sys.stderr, flush=True)
        return SandboxExit.SETUP_FAILED
    return code


def sweep(runtime: Runtime) -> int:
    """Remove what dead launchers left: the engine's (`Runtime.sweep`), then the instance folders
    (one without its launcher's file is just made: its launcher writes it right after)."""
    swept = runtime.sweep()
    _sweep_instances()
    if swept:
        print(f"swept: {', '.join(sorted(swept))}", file=sys.stderr)
    return 0


def _sweep_instances() -> None:
    root = _instances_dir()
    if not root.exists():
        return
    for d in root.iterdir():
        try:
            launcher = (d / _LAUNCHER_FILE).read_text()
        except FileNotFoundError:
            continue
        if not launcher_alive(launcher):
            _remove_instance_dir(d)
