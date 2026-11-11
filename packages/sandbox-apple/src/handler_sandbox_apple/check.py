"""`check` (contract A.8): can this Mac run sandboxes on Apple container, and what they get.

Prints a RuntimeCheck; exit 0 when every required item is ok, 1 otherwise. Nothing is started.
"""

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
    "Handler's first runtime on Apple container. Not available yet: agents running containers "
    "and privileged agents (these virtual machines give no user namespaces nor subordinate ids "
    "yet); windows on your screen (the one Wayland display for macOS, cocoa-way, gives every "
    "window your Mac's clipboard)"
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


def items() -> list[RuntimeCheckItem]:
    running = service_running()
    return [
        macos_item(platform.mac_ver()[0], platform.machine()),
        RuntimeCheckItem(
            name="container service",
            ok=running,
            required=True,
            detail="running" if running else f"not running: {START_SERVICE}",
        ),
        RuntimeCheckItem(
            name="experimental",
            ok=True,
            required=False,
            detail=EXPERIMENTAL,
        ),
    ]


def abilities() -> frozenset[Ability]:
    """What sandboxes get on Apple container (A.8): not yet `nested` nor `privileged` (an engine
    inside needs user namespaces, off in every VM, and subordinate ids, a file Apple cannot
    mount; as the user, `privileged` would give nothing the toolbox uses), nor a display
    (cocoa-way gives every client the Mac's clipboard). EXPERIMENTAL says it; a launch refuses a
    spec needing more (A1). Limits: each VM's own."""
    return frozenset()


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
