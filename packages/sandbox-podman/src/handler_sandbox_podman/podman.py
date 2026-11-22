"""Thin helpers around the podman CLI."""

import contextlib
import os
import subprocess

PROXY_IMAGE = "localhost/handler-ai-proxy:2"
NESTED_DEVICES = ("/dev/fuse", "/dev/net/tun")  # inner podman's storage and network (A.5)


class PodmanError(RuntimeError):
    pass


# how a user gets the subordinate ids every id of an image needs (only root can: check.py's item)
ADD_IDS = (
    "sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER, then "
    "podman system migrate"
)


def podman(*args: str, check: bool = True, timeout: float = 120) -> str:
    proc = subprocess.run(
        ["podman", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if check and proc.returncode != 0:
        raise PodmanError(f"podman {args[0]} failed: {said(proc)}")
    return proc.stdout.strip()


def said(proc: subprocess.CompletedProcess[str]) -> str:
    """What a failed podman call said: its last line, and how to fix too few subordinate ids
    (podman's own words name the files, not the command)."""
    output = proc.stderr or proc.stdout or ""
    lines = output.strip().splitlines()
    last = lines[-1] if lines else f"exit code {proc.returncode}"
    if "insufficient UIDs or GIDs" in output:  # an image using ids beyond the user's
        last += f" (your user has too few subordinate ids for this image: {ADD_IDS})"
    return last


def quiet(*args: str) -> None:
    """Best-effort command (cleanup): never raises."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["podman", *args], capture_output=True, timeout=60, check=False)


def image_config(image: str) -> tuple[str, dict[str, str]]:
    """The image's id and its configured env (`podman image inspect`)."""
    out = podman(
        "image", "inspect", "--format", "{{.Id}}\n{{range .Config.Env}}{{println .}}{{end}}", image
    )
    image_id, *env = out.splitlines()
    return image_id, dict(e.split("=", 1) for e in env if "=" in e)


def image_exists(image: str) -> bool:
    return subprocess.run(["podman", "image", "exists", image], check=False).returncode == 0


def agent_ids() -> tuple[int, int]:
    """The uid/gid the agent runs as: the host user's (A3), or HANDLER_SANDBOX_DEV_UID (see
    below)."""
    dev = os.environ.get("HANDLER_SANDBOX_DEV_UID")
    if os.environ.get("HANDLER_SANDBOX_DEV_NO_KEEPID") and dev:
        return int(dev), int(dev)
    return os.getuid(), os.getgid()


def userns_args(*, agent: bool = True) -> list[str]:
    """Contract A3: run as the host user's uid/gid via keep-id.

    HANDLER_SANDBOX_DEV_NO_KEEPID=1 drops keep-id for development environments where it cannot work
    (nested rootful podman); HANDLER_SANDBOX_DEV_UID then picks a non-root uid. Never set them on a
    real host. The dev uid applies to agent containers only (the proxy writes into our state dir).
    """
    if os.environ.get("HANDLER_SANDBOX_DEV_NO_KEEPID"):
        uid = agent_ids()[0] if agent else os.getuid()
        return ["--user", f"{uid}:{uid}"]
    return ["--userns=keep-id", "--user", f"{os.getuid()}:{os.getgid()}"]


def _userns_size(kind: str) -> int:
    """How many uids ("uid") or gids ("gid") the sandbox's user namespace holds: rootless podman's
    (the host user + its /etc/subuid range), or a conventional 65536 when podman is rootful."""
    if os.getuid() != 0:
        with contextlib.suppress(PodmanError, subprocess.SubprocessError, ValueError):
            lines = podman("unshare", "cat", f"/proc/self/{kind}_map").splitlines()
            return sum(int(line.split()[2]) for line in lines)
    return 65536


def subid_file(kind: str) -> str:
    """/etc/subuid or /etc/subgid for the agent (confinement "nested"): inner rootless podman maps
    every id of the sandbox's user namespace except the agent's own, which newuidmap maps itself.
    Both files are keyed by the user (its uid), /etc/subgid too, whatever its gid."""
    uid, gid = agent_ids()
    own = uid if kind == "uid" else gid
    size = _userns_size(kind)
    ranges = [(1, own - 1), (own + 1, size - own - 1)]
    return "".join(f"{uid}:{start}:{count}\n" for start, count in ranges if count > 0)
