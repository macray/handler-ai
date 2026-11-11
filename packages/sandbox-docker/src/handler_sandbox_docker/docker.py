"""Thin helpers around the docker CLI, and what kind of engine answers.

Docker runs a sandbox's process as the host user (A3) in two kinds of engine: rootful on Linux,
where a container's uid is the host's own (`--user uid:gid`), and in a VM (Docker Desktop,
OrbStack, Colima), whose file sharing gives the files written to the host user whatever the uid.
A rootless engine on Linux cannot: there the container's uid 0 is the host user and every other
uid a subordinate one, and Docker has no keep-id nor id-mapped bind mounts. It is refused (`check`,
`launch`), but in development (HANDLER_SANDBOX_DEV_ROOTLESS_DOCKER, below).
"""

import contextlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

PROXY_IMAGE = "localhost/handler-ai-proxy:2"
NESTED_DEVICES = ("/dev/fuse", "/dev/net/tun")  # an inner engine's storage and network (A.5)
VM_SYSTEMS = ("Docker Desktop", "OrbStack")  # `docker info`'s OperatingSystem, on Linux too

Kind = Literal["rootful", "vm", "rootless"]


class DockerError(RuntimeError):
    pass


def docker(*args: str, check: bool = True, timeout: float = 120) -> str:
    proc = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise DockerError(f"docker {args[0]} failed: {detail[-1] if detail else proc.returncode}")
    return proc.stdout.strip()


def quiet(*args: str) -> None:
    """Best-effort command (cleanup): never raises."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["docker", *args], capture_output=True, timeout=60, check=False)


def docker_info() -> dict[str, Any] | None:
    """`docker info`, or None when no engine answers."""
    try:
        return json.loads(docker("info", "--format", "{{json .}}", timeout=60))
    except (DockerError, OSError, subprocess.SubprocessError, ValueError):
        return None


@dataclass(frozen=True)
class Engine:
    kind: Kind
    version: str


def engine_of(info: dict[str, Any]) -> Engine:
    options = " ".join(info.get("SecurityOptions") or [])
    if "name=rootless" in options:
        kind: Kind = "rootless"
    elif sys.platform == "darwin" or info.get("OperatingSystem") in VM_SYSTEMS:
        kind = "vm"
    else:
        kind = "rootful"
    return Engine(kind=kind, version=str(info.get("ServerVersion") or "?"))


@cache
def engine() -> Engine:
    """The engine that answers here (a launch asks once). Raises DockerError."""
    info = docker_info()
    if info is None or not info.get("ServerVersion"):
        raise DockerError("no Docker engine answers: `docker info` failed")
    return engine_of(info)


def dev_rootless() -> bool:
    """HANDLER_SANDBOX_DEV_ROOTLESS_DOCKER=1: a rootless engine is used anyway, the agent as the
    container's uid 0 (the host user outside), for development environments with only a rootless
    engine (an agent's own sandbox). Never set it on a real host: the agent then runs as root."""
    return bool(os.environ.get("HANDLER_SANDBOX_DEV_ROOTLESS_DOCKER"))


def user_args(kind: Kind) -> list[str]:
    """Contract A3: the host user's uid/gid (rootful, VM); in development on a rootless engine,
    the container's root, which is the host user outside."""
    if kind == "rootless":
        return ["--user", "0:0"]
    return ["--user", f"{os.getuid()}:{os.getgid()}"]


def agent_ids(kind: Kind) -> tuple[int, int]:
    return (0, 0) if kind == "rootless" else (os.getuid(), os.getgid())


def image_config(image: str) -> tuple[str, dict[str, str]]:
    """The image's id and its configured env (`docker image inspect`)."""
    out = docker(
        "image",
        "inspect",
        "--format",
        "{{.Id}}\n{{range .Config.Env}}{{println .}}{{end}}",
        reference(image),
    )
    image_id, *env = out.splitlines()
    return image_id, dict(e.split("=", 1) for e in env if "=" in e)


HEX_ID = re.compile(r"^[0-9a-f]{64}$")


def reference(ref: str) -> str:
    """An image id as Handler gives it (hex, A.7) made one Docker takes everywhere (`image save`
    refuses 64 hex digits alone); any other reference as it is."""
    return f"sha256:{ref}" if HEX_ID.match(ref) else ref


def image_exists(image: str) -> bool:
    return (
        subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=False)
        .returncode == 0
    )  # fmt: skip


def host_subids(kind: str) -> tuple[int, int] | None:
    """The host user's first range in /etc/subuid ("uid") or /etc/subgid ("gid"): (start, count)."""
    user = os.environ.get("USER") or str(os.getuid())
    with contextlib.suppress(OSError, ValueError):
        for line in Path(f"/etc/sub{kind}").read_text().splitlines():
            name, _, rest = line.partition(":")
            if name in (user, str(os.getuid())) and rest.count(":") == 1:
                start, count = rest.split(":")
                return int(start), int(count)
    return None


def subid_file(kind: str, engine_kind: Kind) -> str:
    """/etc/subuid or /etc/subgid for the agent (confinement "nested"), for an engine inside to map
    its containers' ids. Rootful: the container's ids are the host's, so the host user's own
    subordinate range (other ids are other users'). In a VM, or rootless: the sandbox's own ids,
    every one but the agent's, as Podman's runtime gives. Both files are keyed by the user (its
    uid), /etc/subgid too: the Mac's user is 501 in group 20."""
    uid, gid = agent_ids(engine_kind)
    if engine_kind == "rootful":
        found = host_subids(kind)
        return f"{uid}:{found[0]}:{found[1]}\n" if found else ""
    own = uid if kind == "uid" else gid
    ranges = [(1, own - 1), (own + 1, 65536 - own - 1)]
    return "".join(f"{uid}:{start}:{count}\n" for start, count in ranges if count > 0)
