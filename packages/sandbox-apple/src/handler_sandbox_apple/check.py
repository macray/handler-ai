"""`check` (contract A.8): can this Mac run sandboxes on Apple container, and what they get.

Prints a RuntimeCheck; exit 0 when every required item is ok, 1 otherwise. Nothing is started.
"""

import json
import os
import platform
import shutil
import subprocess
import sys

from handler_contracts import Ability, RuntimeCheck, RuntimeCheckItem, RuntimeSupports

from .container import START_SERVICE, service_running

MIN_MACOS = 26  # what `container` needs for its networks and more


def _version() -> str:
    try:
        out = subprocess.run(
            ["container", "--version"], capture_output=True, text=True, timeout=30, check=False
        ).stdout.strip()
    except OSError:
        return ""
    # "container CLI version 1.6.1 (build: release, commit: aa8d76b)"
    _, found, rest = out.partition(" version ")
    return rest.split()[0] if found and rest else ""


OTHER_WAY = "use Docker Desktop or OrbStack instead (`handler runtime use docker`)"

# what sandboxes do not get here, and why (abilities())
EXPERIMENTAL = (
    "Handler's first runtime on Apple container. Not available yet: privileged agents (as your "
    "user in its virtual machine, privileged gives nothing more); windows on your screen (the one "
    "Wayland display for macOS, cocoa-way, gives every window your Mac's clipboard)"
)


def macos_item(macos: str, machine: str) -> RuntimeCheckItem:
    """macOS 26 on Apple silicon; else what to do: update macOS, or the other way."""
    major = int(macos.split(".", maxsplit=1)[0]) if macos else 0
    detail = f"macOS {macos} on {machine}"
    if machine != "arm64":
        detail += f": Apple container needs a Mac with Apple silicon; {OTHER_WAY}"
    elif major < MIN_MACOS:
        detail += f": Apple container needs macOS {MIN_MACOS}: update macOS, or {OTHER_WAY}"
    return RuntimeCheckItem(
        name="macOS", ok=major >= MIN_MACOS and machine == "arm64", required=True, detail=detail
    )


def virtualization_item(hv_support: str) -> RuntimeCheckItem:
    """Every sandbox and every build is a virtual machine: a Mac that cannot make one (macOS in a
    virtual machine itself: Apple gives nested virtualization to Linux guests only) fails every
    build with Apple's "Virtualization is not available on this hardware"."""
    ok = hv_support.strip() != "0"
    detail = (
        "this Mac can run virtual machines"
        if ok
        else "this Mac cannot run virtual machines (is it a virtual machine itself?): Apple "
        "container runs each sandbox and each build in one, and so do Docker Desktop and "
        "OrbStack"
    )
    return RuntimeCheckItem(name="virtualization", ok=ok, required=True, detail=detail)


# what handlerd does at its start (`start-engine`): said, so it is not a hidden capability
SERVICE_RUNNING = "running; after a restart of the Mac, Handler starts it when it starts itself"
TRIED = "Handler tries at its own start: `handler daemon log` says how it went"


# started over SSH, Apple's service lands in launchd's `user/<uid>` session, which `container`
# from the desktop's session (handlerd's, a launch agent) does not reach
IN_ANOTHER_SESSION = (
    "running in another session, which Handler does not reach (started over SSH?): run "
    "`container system stop` there, then `handler setup` (Handler starts it again where it runs)"
)


def service_item(running: bool, elsewhere: bool) -> RuntimeCheckItem:
    """Apple's service, reached from here (handlerd's launchd session); one running where this
    session does not reach it is said, with how to bring it here, not "start it"."""
    if running:
        detail = SERVICE_RUNNING
    elif elsewhere:
        detail = IN_ANOTHER_SESSION
    else:
        detail = f"not running: {START_SERVICE} ({TRIED})"
    return RuntimeCheckItem(name="container service", ok=running, required=True, detail=detail)


def _running_in_another_session() -> bool:
    done = _quiet_run("launchctl", "print", f"user/{os.getuid()}/com.apple.container.apiserver")
    return done is not None and done.returncode == 0 and "state = running" in done.stdout


INSTALL_ROSETTA = "`softwareupdate --install-rosetta --agree-to-license`"


def rosetta_item(builder_wants_it: bool, installed: bool) -> RuntimeCheckItem:
    """Apple container's builder VM is made with Rosetta (its `build.rosetta`, true by default,
    to build Intel images too), and Apple refuses to make it without: "Rosetta is not
    installed". Handler's images are arm64 only and never use it; a fresh Mac lacks it."""
    ok = installed or not builder_wants_it
    if installed:
        detail = "installed"
    elif ok:
        detail = "not installed, not needed (Apple container's builder does not use it)"
    else:
        detail = (
            "not installed: Apple container's builder needs it to build Handler's images "
            f"(a minute, once): {INSTALL_ROSETTA}"
        )
    return RuntimeCheckItem(name="Rosetta", ok=ok, required=True, detail=detail)


def _quiet_run(*argv: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def _hv_support() -> str:
    done = _quiet_run("sysctl", "-n", "kern.hv_support")
    return done.stdout if done and done.returncode == 0 else ""  # unknown: not said to fail


def _builder_wants_rosetta() -> bool:
    """Apple container's `build.rosetta`; true, its default, when it cannot be read."""
    done = _quiet_run("container", "system", "property", "list", "--format", "json")
    try:
        return json.loads(done.stdout)["build"]["rosetta"] is not False if done else True
    except (ValueError, KeyError, TypeError):
        return True


def _rosetta_installed() -> bool:
    done = _quiet_run("arch", "-x86_64", "/usr/bin/true")  # "Bad CPU type" without Rosetta
    return done is not None and done.returncode == 0


def items() -> list[RuntimeCheckItem]:
    running = service_running()
    return [
        macos_item(platform.mac_ver()[0], platform.machine()),
        virtualization_item(_hv_support()),
        rosetta_item(_builder_wants_rosetta(), _rosetta_installed()),
        service_item(running, not running and _running_in_another_session()),
        RuntimeCheckItem(
            name="experimental",
            ok=True,
            required=False,
            detail=EXPERIMENTAL,
        ),
    ]


def abilities() -> frozenset[Ability]:
    """What sandboxes get on Apple container (A.8): `nested` (an engine inside, in a VM of its
    own: user namespaces in that VM only, the relay's --nested); not `privileged` (as the user,
    it would give nothing the toolbox uses), nor a display (cocoa-way gives every client the
    Mac's clipboard). EXPERIMENTAL says it; a launch refuses a spec needing more (A1). Limits:
    each VM's own."""
    return frozenset({"nested"})


def supports() -> RuntimeSupports:
    return RuntimeSupports(
        isolation="a virtual machine of its own (Apple container)",
        abilities=sorted(abilities()),
        limits=True,
    )


def check() -> int:
    if sys.platform != "darwin" or not shutil.which("container"):
        result = RuntimeCheck(
            runtime="Apple container",
            ok=False,
            items=[
                RuntimeCheckItem(
                    name="container",
                    ok=False,
                    required=True,
                    detail="Apple's `container` on macOS 26 (Apple silicon): "
                    "https://github.com/apple/container/releases",
                )
            ],
        )
    else:
        found = items()
        ok = all(i.ok for i in found if i.required)
        result = RuntimeCheck(
            runtime=f"Apple container {_version()}".strip(),
            ok=ok,
            items=found,
            supports=supports() if ok else None,
        )
    print(result.model_dump_json(by_alias=True))
    return 0 if result.ok else 1
