"""A stand-in for handler-sandbox-podman in the daemon's tests (HANDLER_TEST_SANDBOX,
sandbox_process).

    fake_sandbox.py launch 3< spec.json
    fake_sandbox.py attach NAME

A spec for the fake harness (image FAKE_IMAGE, never built) runs its command directly on the
host, in its workdir, with the spec's env: image, mounts, files and network are ignored. So the
tests of the daemon, the ACP endpoint and sessions need no container; what the sandbox does is
tested against the real one (tests/sandbox, the echo-box tests). With `tty` (D.16), `launch` says
it is ready and waits; `attach` runs the command on its own stdio (a terminal only when it is
one: no terminal of the sandbox's own) and tells `launch` how it ended. An automation's run (a
spec labelled `handler.automation`, I.3) runs on the host too, its `pathAppend` on PATH, in a
process group of its own that SIGTERM kills (as the real sandbox stops its container: a cancelled
run's processes all end); with
HANDLER_TEST_FAKE_TOOLBOX=1, `image inspect` of the toolbox answers as if it were built. The network
filter (`image proxy`) is built, so handlerd never builds it (D.4); with
HANDLER_TEST_FAKE_NETWORK_FILTER=broken it is not, and `image build-proxy` fails. Any other spec,
and every other verb (set-egress, sweep), goes to the real handler-sandbox-podman (the real
sandboxes need the real network filter: dev_env.ensure_network_filter).
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

FAKE_IMAGE = "localhost/handler-ai-test-fake"
SPEC_FD = 3
INHERITED_ENV = ("PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TZ", "XDG_RUNTIME_DIR")
REAL = Path(sys.executable).parent / "handler-sandbox-podman"
LIVE_VERBS = ("set-allow", "set-egress")
TOOLBOX = "localhost/handler-ai-toolbox:latest"
PROXY = "localhost/handler-ai-proxy:test"
ATTACH_TIMEOUT = 60.0


def env_of(spec: dict) -> dict[str, str]:
    env = {k: v for k in INHERITED_ENV if (v := os.environ.get(k)) is not None}
    env |= spec.get("env", {}) | {"HOME": spec["user"]["home"]}
    if spec.get("pathAppend"):
        env["PATH"] = ":".join([env.get("PATH", ""), *spec["pathAppend"]])
    if display := spec.get("display"):
        env["WAYLAND_DISPLAY"] = display["socket"]
    return env


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


def run_automation(spec: dict) -> int:
    """An automation's run: its processes in a group of their own, all killed on SIGTERM."""
    proc = subprocess.Popen(spec["argv"], env=env_of(spec), start_new_session=True)
    signal.signal(signal.SIGTERM, lambda *_: os.killpg(proc.pid, signal.SIGKILL))
    return proc.wait()


def real_sandbox() -> None:
    """Hand over to handler-sandbox-podman (fd 3, when there is a spec, is back at its start)."""
    os.execv(REAL, [str(REAL), *sys.argv[1:]])


def main() -> int:
    ran = Path(os.environ["HANDLER_TEST_FAKE_RAN"])
    if sys.argv[1] in LIVE_VERBS and (ran / sys.argv[2]).exists():
        return 0
    if sys.argv[1] == "attach" and (ran / f"{sys.argv[2]}.tty").exists():
        return attach(ran, sys.argv[2])
    broken_filter = os.environ.get("HANDLER_TEST_FAKE_NETWORK_FILTER") == "broken"
    if sys.argv[1:] == ["image", "proxy"]:
        image = None if broken_filter else {"id": "0" * 64, "created": "2026-10-09T00:00:00Z"}
        print(json.dumps({"ref": PROXY} | ({"image": image} if image else {})))
        return 0
    if sys.argv[1:] == ["image", "build-proxy"] and broken_filter:
        print("STEP 1/2: FROM docker.io/library/python:3.13-slim", flush=True)
        print("handler-sandbox-podman: build failed (podman exit code 125)", file=sys.stderr)
        return 1
    if sys.argv[1:] == ["image", "inspect", TOOLBOX] and os.environ.get(
        "HANDLER_TEST_FAKE_TOOLBOX"
    ):
        print(json.dumps({"id": "0" * 64, "created": "2026-10-06T00:00:00Z"}))
        return 0
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
    (ran / spec["name"]).touch()
    if spec.get("tty"):
        (ran / f"{spec['name']}.tty").write_text(json.dumps(spec))
        return wait_for_attach(ran, spec["name"])
    os.chdir(spec["workdir"])
    return run_automation(spec) if automation else run_command(spec)


if __name__ == "__main__":
    sys.exit(main())
