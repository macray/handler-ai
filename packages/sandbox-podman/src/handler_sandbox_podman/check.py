"""`check` (contract A.8): what this host gives rootless podman, and whether sandboxes can run.

Prints a RuntimeCheck; exit 0 when every required item is ok, 1 otherwise. Nothing is started.
"""

import json
import os
from pathlib import Path
from typing import Any

from handler_contracts import RuntimeCheck, RuntimeCheckItem

from .podman import PodmanError, podman


def _info() -> dict[str, Any] | None:
    try:
        return json.loads(podman("info", "--format", "json", timeout=60))
    except (PodmanError, OSError, ValueError):
        return None


def _id_range(kind: str) -> int:
    """How many subordinate ids (/etc/subuid or /etc/subgid) the user has."""
    user = os.environ.get("USER") or str(os.getuid())
    total = 0
    try:
        for line in Path(f"/etc/sub{kind}").read_text().splitlines():
            name, _, rest = line.partition(":")
            if name in (user, str(os.getuid())) and rest.count(":") == 1:
                total += int(rest.split(":")[1])
    except (OSError, ValueError):
        return 0
    return total


def items(info: dict[str, Any]) -> list[RuntimeCheckItem]:
    host = info.get("host", {})
    dev = bool(os.environ.get("HANDLER_SANDBOX_DEV_NO_KEEPID"))  # podman.userns_args
    rootless = bool(host.get("security", {}).get("rootless"))
    # with the user's own id, 65535 map every id a container uses (0 to 65535): what a `nested`
    # sandbox gives inner podman, whose own id is not in its range (podman.subid_file)
    ids = min(_id_range("uid"), _id_range("gid"))
    backend = host.get("networkBackend", "")
    pasta = (host.get("pasta") or {}).get("executable", "")
    cgroup = host.get("cgroupVersion", "")
    return [
        RuntimeCheckItem(
            name="rootless",
            ok=rootless or dev,
            required=True,
            detail="podman runs as your user"
            if rootless
            else "podman runs as root: development mode (HANDLER_SANDBOX_DEV_NO_KEEPID)"
            if dev
            else "podman runs as root: agents must run as your user (A3); run handler as yourself",
        ),
        RuntimeCheckItem(
            name="subordinate ids",
            ok=ids >= 65535 or dev or not rootless,
            required=True,
            detail=f"{ids} in /etc/subuid and /etc/subgid"
            if ids >= 65535
            else f"{ids or 'none'} for your user in /etc/subuid and /etc/subgid, 65535 needed: "
            "sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER, then "
            "podman system migrate",
        ),
        RuntimeCheckItem(
            name="network",
            ok=backend == "netavark" and bool(pasta),
            required=True,
            detail=f"{backend or 'no backend'}, {'pasta' if pasta else 'no pasta'}"
            + (
                ""
                if backend == "netavark" and pasta
                else ": allow-listed sandboxes need both; install passt (and netavark, podman"
                " 5's default backend)"
            ),
        ),
        RuntimeCheckItem(
            name="cgroups v2",
            ok=cgroup == "v2",
            required=False,
            detail="memory and CPU limits work"
            if cgroup == "v2"
            else f"{cgroup or 'unknown'}: memory and CPU limits need v2",
        ),
        RuntimeCheckItem(
            name="/dev/fuse",
            ok=Path("/dev/fuse").exists(),
            required=False,
            detail="for agents running containers themselves (sandbox: Runs containers)",
        ),
    ]


def check() -> int:
    info = _info()
    if info is None:
        result = RuntimeCheck(
            runtime="podman",
            ok=False,
            items=[
                RuntimeCheckItem(
                    name="podman",
                    ok=False,
                    required=True,
                    detail="`podman info` failed: install podman (rootless), e.g. "
                    "`sudo pacman -S podman passt`, `sudo apt install podman passt`, "
                    "`sudo dnf install podman passt`",
                )
            ],
        )
    else:
        found = items(info)
        version = info.get("version", {}).get("Version", "?")
        result = RuntimeCheck(
            runtime=f"podman {version}",
            ok=all(i.ok for i in found if i.required),
            items=found,
        )
    print(result.model_dump_json(by_alias=True))
    return 0 if result.ok else 1
