"""`check` (contract A.8): which Docker engine answers, what it gives sandboxes, whether they can
run.

Prints a RuntimeCheck; exit 0 when every required item is ok, 1 otherwise. Nothing is started.
"""

import subprocess
from pathlib import Path
from typing import Any

from handler_contracts import Ability, RuntimeCheck, RuntimeCheckItem, RuntimeSupports
from handler_sandbox_kit import display

from .docker import NESTED_DEVICES, Engine, Kind, dev_rootless, docker_info, engine_of

ISOLATION: dict[Kind, str] = {
    "rootful": "a container sharing your computer's kernel, its engine running as root",
    "vm": "a container in the virtual machine Docker runs",
    "rootless": "a container sharing your computer's kernel, its engine running as you",
}


def limits(info: dict[str, Any]) -> bool:
    """Whether a spec's memory and CPU limits are applied (`docker info`'s own answer)."""
    return bool(info.get("MemoryLimit")) and bool(info.get("CpuCfsQuota"))


def abilities(kind: Kind) -> frozenset[Ability]:
    """What sandboxes get here (A.8). `privileged` only where an escape stays in a VM or your
    account: a privileged container of a rootful engine is root on this computer. The display
    only where the engine shares this computer's kernel (a Wayland socket cannot cross a VM)."""
    given: set[Ability] = set()
    if kind == "vm" or all(Path(dev).exists() for dev in NESTED_DEVICES):
        given.add("nested")
    if kind != "rootful":
        given.add("privileged")
    if kind != "vm" and display.found():
        given.add("display")
    return frozenset(given)


def buildx() -> bool:
    """Docker's BuildKit client, which builds every image (A.7: `RUN --mount`, its progress)."""
    try:
        found = subprocess.run(
            ["docker", "buildx", "version"], capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return found.returncode == 0


def items(engine: Engine, info: dict[str, Any]) -> list[RuntimeCheckItem]:
    kind = engine.kind
    files = {
        "rootful": "the engine gives containers your uid: what agents write is yours",
        "vm": "Docker's file sharing makes what agents write yours",
        "rootless": "rootless Docker maps your user to the containers' root: agents would run as "
        "root, or write files you do not own. Use Podman (rootless), or a rootful Docker"
        + (" — development mode: agents run as root (HANDLER_SANDBOX_DEV_ROOTLESS_DOCKER)"
           if dev_rootless() else ""),
    }  # fmt: skip
    found = [
        RuntimeCheckItem(
            name="your files",
            ok=kind != "rootless" or dev_rootless(),
            required=True,
            detail=files[kind],
        ),
        RuntimeCheckItem(
            name="buildx",
            ok=buildx(),
            required=True,
            detail="builds the images"
            if buildx()
            else "`docker buildx` is missing: install Docker's buildx plugin "
            "(docker-buildx-plugin; docker-buildx on Arch)",
        ),
        RuntimeCheckItem(
            name="rootless",
            ok=kind != "rootful",
            required=False,
            detail="Docker runs as root: an agent escaping its sandbox would be root on this "
            "computer (Podman, rootless, is safer); agents cannot be privileged"
            if kind == "rootful"
            else "the engine runs in a virtual machine"
            if kind == "vm"
            else "the engine runs as you",
        ),
        RuntimeCheckItem(
            name="memory and CPU limits",
            ok=limits(info),
            required=False,
            detail="applied to sandboxes (an app sets them)"
            if limits(info)
            else "not applied by this engine, apps run without them",
        ),
    ]
    if kind != "vm":
        try:
            detail = f"{display.wayland_socket()}, for agents showing windows on your screen"
        except display.DisplayError as e:
            detail = f"{e} (only for agents showing windows on your screen)"
        found.append(
            RuntimeCheckItem(name="display", ok=display.found(), required=False, detail=detail)
        )
        found.append(
            RuntimeCheckItem(
                name="/dev/fuse, /dev/net/tun",
                ok=all(Path(dev).exists() for dev in NESTED_DEVICES),
                required=False,
                detail="for agents running containers themselves (sandbox: Runs containers)",
            )
        )
    return found


def check() -> int:
    info = docker_info()
    if info is None or not info.get("ServerVersion"):
        result = RuntimeCheck(
            runtime="docker",
            ok=False,
            items=[
                RuntimeCheckItem(
                    name="docker",
                    ok=False,
                    required=True,
                    detail="`docker info` failed: install Docker (Docker Desktop, OrbStack, or "
                    "Docker Engine) and start it; on Linux, your user in the `docker` group",
                )
            ],
        )
    else:
        engine = engine_of(info)
        found = items(engine, info)
        ok = all(i.ok for i in found if i.required)
        supports = RuntimeSupports(
            isolation=ISOLATION[engine.kind],
            abilities=sorted(abilities(engine.kind)),
            limits=limits(info),
        )
        result = RuntimeCheck(
            runtime=f"docker {engine.version}", ok=ok, items=found,
            supports=supports if ok else None,
        )  # fmt: skip
    print(result.model_dump_json(by_alias=True))
    return 0 if result.ok else 1
