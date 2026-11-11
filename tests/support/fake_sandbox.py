"""A stand-in for handler-sandbox-podman in the daemon's tests (HANDLER_TEST_SANDBOX,
sandbox_process); its own messages carry the prefix of the runtime handlerd uses with no
runtime.toml (handler-sandbox-apple on macOS), which handlerd reads.

    fake_sandbox.py launch 3< spec.json
    fake_sandbox.py attach NAME

A spec for the fake harness (image FAKE_IMAGE, never built) runs its command directly on the
host, in its workdir, with the spec's env (a path in a socket folder: its host path): image,
mounts, files and network are ignored; the spec
is kept in HANDLER_TEST_FAKE_RAN/<its name> (what handlerd composed: a test may run its folders
in the real sandbox). So the
tests of the daemon, the ACP endpoint and sessions need no container; what the sandbox does is
tested against the real one (tests/sandbox, the echo-box tests). With `tty` (D.16), `launch` says
it is ready and waits; `attach` runs the command on its own stdio (a terminal only when it is
one: no terminal of the sandbox's own) and tells `launch` how it ended. An automation's run (a
spec labelled `handler.automation`, I.3) runs on the host too, its commands on PATH, in a
process group of its own that SIGTERM kills (as the real sandbox stops its container: a cancelled
run's processes all end); with
HANDLER_TEST_FAKE_TOOLBOX=1, `image inspect` of the toolbox answers as if it were built. The image
the fake ignores (the fake harness's) is built for `image inspect` (a launch's check, A.7) unless
HARNESS_MISSING is in
HANDLER_TEST_FAKE_RAN; with SETUP_FAILS there, `launch` fails as the real one does before the
sandboxed process starts (66, its reason on stderr); with FILTER_WATCHED there, it watches its
agent as the real one watches the filter, and ends it once FILTER_STOPPED is there too (67, its
reason on stderr). The network
filter (`image proxy`) is built, so handlerd never builds it (D.4); with
HANDLER_TEST_FAKE_NETWORK_FILTER=broken it is not, and `image build-proxy` fails. The toolbox is
not built (a whole system): its `image build` fails at once, unless
HANDLER_TEST_REAL_TOOLBOX_BUILD=1 (a real build on purpose). A live verb (set-allow, set-watched,
set-blocked, set-egress) on a fake sandbox succeeds, its arguments kept in
HANDLER_TEST_FAKE_RAN/<name>.<verb>. Any other spec,
and every other verb (sweep; `check` where the runtime runs, else a passing one), goes to the real
runtime: handler-sandbox-podman, or the one in HANDLER_TEST_REAL_SANDBOX (the app suites': Apple
container on a Mac, runtimes.default_runtime); the real sandboxes need the real network filter
(dev_env.ensure_network_filter).
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

FAKE_IMAGE = "localhost/handler-ai-test-fake"
IGNORED_IMAGES = (f"{FAKE_IMAGE}:",)
HARNESS_MISSING = "harness-image-missing"  # a file: the fake harness's image is not built
SETUP_FAILS = "setup-fails"  # a file: its launches fail
FILTER_WATCHED = "filter-watched"  # a file: its launches watch their filter (the one below)
FILTER_STOPPED = "filter-stopped"  # a file: the filter of a watched launch stopped
SPEC_FD = 3
INHERITED_ENV = ("PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TZ", "XDG_RUNTIME_DIR")
# handler_control's sandbox_process.DEFAULT_RUNTIME, not imported (below): the runtime handlerd
# uses with no runtime.toml, whose prefix it takes off a launcher's reason
RUNTIME = f"handler-sandbox-{'apple' if sys.platform == 'darwin' else 'podman'}"
# the real runtime it hands over to: the app suites' (HANDLER_TEST_REAL_SANDBOX), else Podman's
REAL = Path(
    os.environ.get("HANDLER_TEST_REAL_SANDBOX")
    or Path(sys.executable).parent / "handler-sandbox-podman"
)
LIVE_VERBS = ("set-allow", "set-blocked", "set-egress", "set-watched")
TOOLBOX = "localhost/handler-ai-toolbox:latest"
PROXY = "localhost/handler-ai-proxy:test"
ATTACH_TIMEOUT = 60.0
# handler_contracts.HANDLER_BIN, not imported: the fake starts as fast as a command (an automation's
# test restarts handlerd while its script runs)
HANDLER_BIN = "/run/handler/bin"


def env_of(spec: dict, commands: Path | None = None) -> dict[str, str]:
    """`commands`: where its commands (tools in HANDLER_BIN) were written, put on PATH."""
    env = {k: v for k in INHERITED_ENV if (v := os.environ.get(k)) is not None}
    env |= spec.get("env", {}) | {"HOME": spec["home"]}
    for folder in spec.get("socketFolders", []):  # on the host: its sockets at their host path
        for key, value in env.items():
            if value.startswith(folder["target"] + "/"):
                env[key] = folder["source"] + value[len(folder["target"]) :]
    if commands is not None:
        env["PATH"] = ":".join([env.get("PATH", ""), str(commands)])
    if spec.get("display"):  # as the runtime finds it
        from handler_sandbox_kit import display  # noqa: PLC0415 — only then (HANDLER_BIN)

        env["WAYLAND_DISPLAY"] = display.wayland_socket()
    return env


def display_found() -> bool:
    from handler_sandbox_kit import display  # noqa: PLC0415 — only then (HANDLER_BIN)

    return display.found()


def write_commands(ran: Path, spec: dict) -> Path:
    """Its tools in HANDLER_BIN, on the host (the automation's `handler-llm`)."""
    folder = ran / f"{spec['name']}-bin"
    folder.mkdir(exist_ok=True)  # a run started again has the same name
    for tool in spec.get("tools", []):
        if tool["target"].startswith(f"{HANDLER_BIN}/"):
            path = folder / tool["target"].rsplit("/", 1)[1]
            path.write_text(tool["content"])
            path.chmod(0o755)
    return folder


def wait_for_attach(ran: Path, name: str) -> int:
    """`launch` of a `tty` spec: ready, then until `attach` has run the command."""
    print("handler-ready", file=sys.stderr, flush=True)
    deadline = time.monotonic() + ATTACH_TIMEOUT
    while not (ran / f"{name}.attached").exists():
        if time.monotonic() > deadline:
            return 66
        time.sleep(0.1)
    while not (ran / f"{name}.exit").exists():
        time.sleep(0.1)
    return int((ran / f"{name}.exit").read_text())


def attach(ran: Path, name: str) -> int:
    spec = json.loads((ran / f"{name}.tty").read_text())
    (ran / f"{name}.attached").touch()
    code = subprocess.call(spec["argv"], env=env_of(spec), cwd=spec["workdir"])
    (ran / f"{name}.exit").write_text(str(code))
    return code


def run_command(spec: dict) -> int:
    """A session's agent: the fake sandbox becomes its command."""
    os.execvpe(spec["argv"][0], spec["argv"], env_of(spec))


def run_watched(ran: Path, spec: dict) -> int:
    """A session's agent, ended as the real launcher ends it once its filter stopped."""
    proc = subprocess.Popen(spec["argv"], env=env_of(spec))
    signal.signal(signal.SIGTERM, lambda *_: proc.terminate())
    while proc.poll() is None:
        if (ran / FILTER_STOPPED).exists():
            proc.kill()
            proc.wait()
            print(f"{RUNTIME}: its network filter stopped, so the sandbox was ended",
                  file=sys.stderr, flush=True)  # fmt: skip
            return 67
        time.sleep(0.1)
    return proc.returncode


def run_automation(ran: Path, spec: dict) -> int:
    """An automation's run: its processes in a group of their own, all killed on SIGTERM."""
    env = env_of(spec, write_commands(ran, spec))
    proc = subprocess.Popen(spec["argv"], env=env, start_new_session=True)
    signal.signal(signal.SIGTERM, lambda *_: os.killpg(proc.pid, signal.SIGKILL))
    return proc.wait()


def real_sandbox() -> None:
    """Hand over to the real runtime (fd 3, when there is a spec, is back at its start)."""
    os.execv(REAL, [str(REAL), *sys.argv[1:]])


def check() -> int:
    """The real one's host check; where it fails (no Podman here: a Mac, a host without it),
    the same check passing, still without `supports` (what it gives is not known): the fake's
    sandboxes are processes on this host, so an image it says is not built is that, not an
    engine that cannot run (handlerd asks the check then, launcher.missing)."""
    real = subprocess.run([str(REAL), "check"], capture_output=True, text=True, check=False)
    if real.returncode == 0:
        print(real.stdout, end="")
        return 0
    found = json.loads(real.stdout)
    found["ok"] = True
    for item in found["items"]:
        item["ok"] = True
    print(json.dumps(found))
    return 0


def image_verb(ran: Path, args: list[str]) -> int | None:
    """What the fake answers itself of `image …`; None: the real one's."""
    broken_filter = os.environ.get("HANDLER_TEST_FAKE_NETWORK_FILTER") == "broken"
    if args == ["proxy"]:
        image = None if broken_filter else {"id": "0" * 64, "created": "2026-10-09T00:00:00Z"}
        print(json.dumps({"ref": PROXY} | ({"image": image} if image else {})))
        return 0
    if args == ["build-proxy"] and broken_filter:
        print("STEP 1/2: FROM docker.io/library/python:3.13-slim", flush=True)
        print(f"{RUNTIME}: build failed (podman exit code 125)", file=sys.stderr)
        return 1
    real_toolbox = os.environ.get("HANDLER_TEST_REAL_TOOLBOX_BUILD") == "1"
    if args[:1] == ["build"] and Path(args[1]).name == "toolbox-build" and not real_toolbox:
        print(f"{RUNTIME}: the tests' fake does not build the toolbox", file=sys.stderr)
        return 1
    built = args == ["inspect", TOOLBOX] and os.environ.get("HANDLER_TEST_FAKE_TOOLBOX")
    if args[:1] == ["inspect"] and (built or args[1].startswith(IGNORED_IMAGES)):
        if args[1].startswith(f"{FAKE_IMAGE}:") and (ran / HARNESS_MISSING).exists():
            print(f"{RUNTIME}: no image {args[1]}", file=sys.stderr)
            return 1
        print(json.dumps({"id": ("0" if built else "1") * 64, "created": "2026-10-06T00:00:00Z"}))
        return 0
    return None


def main() -> int:
    ran = Path(os.environ["HANDLER_TEST_FAKE_RAN"])
    if sys.argv[1] in LIVE_VERBS and (ran / sys.argv[2]).exists():
        (ran / f"{sys.argv[2]}.{sys.argv[1]}").write_text(json.dumps(sys.argv[3:]))
        return 0
    if sys.argv[1:] == ["check"]:
        return check()
    if sys.argv[1] == "attach" and (ran / f"{sys.argv[2]}.tty").exists():
        return attach(ran, sys.argv[2])
    if sys.argv[1] == "image" and (code := image_verb(ran, sys.argv[2:])) is not None:
        return code
    if sys.argv[1:2] != ["launch"]:
        real_sandbox()
    with os.fdopen(SPEC_FD, "rb", closefd=False) as f:  # a file (sandbox_process): seekable
        spec = json.loads(f.read())
    automation = "handler.automation" in (spec.get("labels") or {})
    if not spec["image"].startswith(f"{FAKE_IMAGE}:") and not automation:
        os.lseek(SPEC_FD, 0, os.SEEK_SET)
        real_sandbox()
    return launch(ran, spec, automation)


def launch(ran: Path, spec: dict, automation: bool) -> int:
    if (ran / SETUP_FAILS).exists():
        print(f"{RUNTIME}: setup failed: the fake was told to", file=sys.stderr)
        return 66
    if spec.get("display") and not display_found():  # as the real one refuses it (A1)
        print(f"{RUNTIME}: refused (A1): not given here: display", file=sys.stderr)
        return 64
    (ran / spec["name"]).write_text(json.dumps(spec))  # what it was given: tests read it
    if spec.get("tty"):
        (ran / f"{spec['name']}.tty").write_text(json.dumps(spec))
        return wait_for_attach(ran, spec["name"])
    os.chdir(spec["workdir"])
    if automation:
        return run_automation(ran, spec)
    return run_watched(ran, spec) if (ran / FILTER_WATCHED).exists() else run_command(spec)


if __name__ == "__main__":
    sys.exit(main())
