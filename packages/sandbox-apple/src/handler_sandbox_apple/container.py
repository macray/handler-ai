"""Thin helpers around Apple's `container` CLI, and what this runtime names.

Checked on a Mac (Apple container 1.6.1). `container`'s JSON documents have no documented
layout: fields are looked for by name.
"""

import contextlib
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

FILTER_IMAGE = "localhost/handler-ai-proxy:2"  # the network filter (A.3), as podman's


class ContainerError(RuntimeError):
    pass


def container(*args: str, check: bool = True, timeout: float = 120) -> str:
    proc = subprocess.run(
        ["container", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        what = detail[-1] if detail else str(proc.returncode)
        raise ContainerError(f"container {args[0]} failed: {what}")
    return proc.stdout.strip()


START_SERVICE = "`container system start`"


def service_running() -> bool:
    """Whether Apple's container service runs (`container system status`)."""
    try:
        return (
            subprocess.run(
                ["container", "system", "status"], capture_output=True, timeout=30, check=False
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def quiet(*args: str) -> None:
    """Best-effort command (cleanup): never raises."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["container", *args], capture_output=True, timeout=60, check=False)


def find(value: Any, key: str) -> Iterator[Any]:
    """Every value under `key` in a JSON document, at any depth: `inspect`'s layout is not
    documented, so fields are looked for by name."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k.lower() == key.lower():
                yield v
            yield from find(v, key)
    elif isinstance(value, list):
        for v in value:
            yield from find(v, key)


def labels_of(entry: Any) -> dict[str, str]:
    for found in find(entry, "labels"):
        if isinstance(found, dict):
            return {str(k): str(v) for k, v in found.items()}
    return {}


def containers() -> list[dict[str, Any]]:
    """Every container, stopped ones too (`list --all --format json`)."""
    out = container("list", "--all", "--format", "json", check=False)
    try:
        listed = json.loads(out or "[]")
    except ValueError:
        return []
    return [c for c in listed if isinstance(c, dict)]


def running_from(image_id: str) -> bool:
    """Whether a running container runs from the image with this id (its digest's hex)."""
    digest = f"sha256:{image_id}"
    return any(digest in find(c, "digest") and "running" in find(c, "state") for c in containers())


IMAGE_ID = re.compile(r"[0-9a-f]{64}")


def names(image: str) -> list[str]:
    """The names an image goes by: `container` refers to images by name, and refuses an id
    ("cannot specify 64 byte hex string as reference"). A name: itself; an id: every name of the
    image with that id (`image list`'s `id`, one entry per name, its `configuration.name`: not
    looked for at any depth, an image's labels may hold a `name`), none when there is no such
    image."""
    if not IMAGE_ID.fullmatch(image):
        return [image]
    try:
        listed = json.loads(container("image", "list", "--format", "json", check=False) or "[]")
    except ValueError:
        return []
    return [
        entry["configuration"]["name"]
        for entry in listed
        if isinstance(entry, dict)
        and entry.get("id") == image
        and isinstance(entry.get("configuration"), dict)
        and isinstance(entry["configuration"].get("name"), str)
    ]


def reference(image: str) -> str:
    """A name `container` takes for an image or an id (the id itself when it has none)."""
    return next(iter(names(image)), image)


def image_info(ref: str) -> dict[str, Any] | None:
    """`image inspect REF`'s document, None when there is no such image."""
    out = container("image", "inspect", reference(ref), check=False)
    try:
        doc = json.loads(out) if out else None
    except ValueError:
        return None
    if isinstance(doc, list):
        doc = doc[0] if doc else None
    return doc if isinstance(doc, dict) else None


def image_id(doc: dict[str, Any]) -> str:
    """The image's id, hex without its algorithm (the digest of its index or manifest)."""
    for key in ("digest", "id"):
        for found in find(doc, key):
            if isinstance(found, str) and found:
                return found.removeprefix("sha256:")
    raise ContainerError("image inspect: no id")


def variant(doc: dict[str, Any]) -> Any:
    """The image's own part for this Mac (linux/arm64): a pulled image lists every platform's
    (`variants`, linux/386 first on 1.7.1), a local build its one."""
    for v in doc.get("variants") or []:
        platform = v.get("platform") if isinstance(v, dict) else None
        if isinstance(platform, dict) and (platform.get("os"), platform.get("architecture")) == (
            "linux",
            "arm64",
        ):
            return v
    return doc


def image_env(doc: dict[str, Any]) -> dict[str, str]:
    for found in find(variant(doc), "env"):
        if isinstance(found, list):
            return dict(str(e).partition("=")[::2] for e in found)
    return {}


def short_dir() -> Path:
    """A folder for Unix sockets with short paths (macOS: at most 104 bytes; the state folder
    under the home is too deep for a socket in it)."""
    path = Path(tempfile.gettempdir()) / f"handler-ai-{os.getuid()}"
    path.mkdir(mode=0o700, exist_ok=True)
    return path


SOCKET_PATH_MAX = 103  # macOS: 104 bytes with the final NUL


def socket_path(name: str, what: str) -> Path:
    """A socket of the launcher's. Apple's relay to a socket mounted in a VM connects to its
    absolute path, and fails to only in its log when that is too long (the VM's connections
    then close at once): said here instead (a `TMPDIR` too deep)."""
    digest = hashlib.sha256(name.encode()).hexdigest()[:12]
    path = short_dir() / f"{digest}-{what}.sock"
    if len(str(path).encode()) > SOCKET_PATH_MAX:
        raise ContainerError(
            f"{path} is too long for a socket (over {SOCKET_PATH_MAX} bytes): set TMPDIR to a "
            "shorter folder"
        )
    return path
