"""`check` (contract A.8): what this host gives rootless podman, and whether sandboxes can run.

Prints a RuntimeCheck; exit 0 when every required item is ok, 1 otherwise. Nothing is started.
"""

import json
import os
from pathlib import Path
from typing import Any

from handler_contracts import Ability, RuntimeCheck, RuntimeCheckItem, RuntimeSupports
from handler_sandbox_kit import display

from .podman import NESTED_DEVICES, PodmanError, podman

LIMITS = ("memory", "cpu")  # the cgroup controllers a spec's `resources` need


def limit_controllers(
    info: dict[str, Any] | None, wanted: tuple[str, ...] = LIMITS
) -> frozenset[str]:
    """Those of `wanted` (default LIMITS) podman applies to this user's containers. Rootless, on cgroups v2 only
    (on v1 only root can set limits): those `podman info` reports (with systemd: the controllers
    it delegates to the user), and without systemd only when podman can write in the user's own
    cgroup, where it makes the containers' (else it drops the limits, silently). None: podman did
    not answer."""
    host = (info or {}).get("host", {})
    given = frozenset(host.get("cgroupControllers") or []) & set(wanted)
    if not host.get("security", {}).get("rootless"):
        return given
    if host.get("cgroupVersion") != "v2":
        return frozenset()
    if host.get("cgroupManager") == "cgroupfs" and not _own_cgroup_writable():
        return frozenset()
    return given


def _own_cgroup_writable() -> bool:
    try:
        line = next(x for x in Path("/proc/self/cgroup").read_text().splitlines() if x[:3] == "0::")
    except (OSError, StopIteration):
        return False
    return os.access(f"/sys/fs/cgroup{line[3:]}", os.W_OK)


def _limits_item(info: dict[str, Any]) -> RuntimeCheckItem:
    missing = [c for c in LIMITS if c not in limit_controllers(info)]
    if not missing:
        detail = "applied to sandboxes (an app sets them)"
    elif info.get("host", {}).get("cgroupVersion") != "v2":
        detail = (
            "not applied on this computer, apps run without them: cgroups v1 lets only root set "
            "them; switch to v2 (boot option systemd.unified_cgroup_hierarchy=1)"
        )
    elif info.get("host", {}).get("cgroupManager") == "cgroupfs":
        detail = (
            "not applied on this computer, apps run without them: podman cannot write in your "
            "cgroup (without systemd, e.g. in a container)"
        )
    else:
        detail = (
            f"{' and '.join(missing)} not applied on this computer, apps run without them: the "
            "controller is not given to your user (systemd: Delegate= in user@.service)"
        )
    return RuntimeCheckItem(name="memory and CPU limits", ok=not missing, required=False,
                            detail=detail)  # fmt: skip


def _display_item() -> RuntimeCheckItem:
    try:
        detail = f"{display.wayland_socket()}, for agents showing windows on your screen"
    except display.DisplayError as e:
        detail = f"{e} (only for agents showing windows on your screen)"
    return RuntimeCheckItem(name="display", ok=display.found(), required=False, detail=detail)


def abilities() -> frozenset[Ability]:
    """What sandboxes get here (A.8), read from the host at once: `check` prints it, and a
    launch refuses a spec needing more (A1)."""
    given: set[Ability] = {"privileged"}
    if all(Path(dev).exists() for dev in NESTED_DEVICES):
        given.add("nested")
    if display.found():  # a Wayland session, where the launcher runs (A.6)
        given.add("display")
    return frozenset(given)


def podman_info() -> dict[str, Any] | None:
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


def wsl_version(osrelease: str) -> int | None:
    """1 or 2 when this kernel is Windows' WSL (its release names Microsoft), else None."""
    release = osrelease.lower()
    if "microsoft" not in release:
        return None
    return 2 if "wsl2" in release or "microsoft-standard" in release else 1


def _wsl() -> int | None:
    try:
        return wsl_version(Path("/proc/sys/kernel/osrelease").read_text())
    except OSError:
        return None


def items(info: dict[str, Any]) -> list[RuntimeCheckItem]:
    host = info.get("host", {})
    dev = bool(os.environ.get("HANDLER_SANDBOX_DEV_NO_KEEPID"))  # podman.userns_args
    rootless = bool(host.get("security", {}).get("rootless"))
    # with the user's own id, 65535 map every id a container uses (0 to 65535): what a `nested`
    # sandbox gives inner podman, whose own id is not in its range (podman.subid_file)
    ids = min(_id_range("uid"), _id_range("gid"))
    backend = host.get("networkBackend", "")
    pasta = (host.get("pasta") or {}).get("executable", "")
    wsl = (
        [
            RuntimeCheckItem(
                name="WSL 2",
                ok=True,
                required=False,
                detail="project folders on Windows drives (/mnt/c…) are slow: keep them in "
                "Linux (~/…)",
            )
        ]
        if _wsl() == 2
        else []
    )
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
            required=False,  # plain sessions run with fewer
            detail=f"{ids} in /etc/subuid and /etc/subgid"
            if ids >= 65535
            else f"{ids or 'none'} for your user in /etc/subuid and /etc/subgid, 65535 needed "
            "only for agents that run containers and for apps: sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER, then "
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
        _limits_item(info),
        _display_item(),
        RuntimeCheckItem(
            name="/dev/fuse, /dev/net/tun",
            ok=all(Path(dev).exists() for dev in NESTED_DEVICES),
            required=False,
            detail="for agents running containers themselves (sandbox: Runs containers)",
        ),
        *wsl,
    ]


def supports(info: dict[str, Any]) -> RuntimeSupports:
    return RuntimeSupports(
        isolation="a container sharing your computer's kernel, running as your user",
        abilities=sorted(abilities()),
        limits=limit_controllers(info) == frozenset(LIMITS),
    )


def check() -> int:
    info = podman_info()
    if info is None:
        result = RuntimeCheck(
            runtime="podman",
            ok=False,
            items=[
                RuntimeCheckItem(
                    name="podman",
                    ok=False,
                    required=True,
                    detail="WSL 1 cannot run containers: in Windows, "
                    "`wsl --set-version <distribution> 2`"
                    if _wsl() == 1
                    else "`podman info` failed: install podman (rootless), e.g. "
                    "`sudo pacman -S podman passt`, `sudo apt install podman passt`, "
                    "`sudo dnf install podman passt`",
                )
            ],
        )
    else:
        found = items(info)
        version = info.get("version", {}).get("Version", "?")
        ok = all(i.ok for i in found if i.required)
        result = RuntimeCheck(
            runtime=f"podman {version}", ok=ok, items=found, supports=supports(info) if ok else None
        )
    print(result.model_dump_json(by_alias=True))
    return 0 if result.ok else 1
