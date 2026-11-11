"""Test environment settings, in one place.

On a real host (rootless podman, normal user) nothing here changes behaviour.

In a dev container running nested *rootful* podman as root, keep-id cannot work. There we
drop keep-id and run sandboxes as a fixed non-root uid instead, so tests still exercise a
non-root agent (e.g. Claude refuses bypass mode as root). Scopes then live under /var/tmp,
which that uid can traverse.
"""

import fcntl
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEV_UID = 1000
DEV_MODE = os.getuid() == 0
# how long a test may take that builds or pulls images, runs a real harness or a browser (the
# others: pyproject's `timeout`); a first run on a new machine fetches a lot
IMAGE_TIMEOUT = 900

# The images the tests run, from registries without Docker Hub's anonymous pull limit (agents run
# the suite often, from one address): the curl project's own (quay.io), Google's mirror of the
# official images. Pulled once, when missing (`ensure_image`), never again at each run.
CURL_IMAGE = "quay.io/curl/curl:8.11.1"
ALPINE_IMAGE = "mirror.gcr.io/library/alpine:3.22"

if DEV_MODE:
    os.environ.setdefault("HANDLER_SANDBOX_DEV_NO_KEEPID", "1")
    os.environ.setdefault("HANDLER_SANDBOX_DEV_UID", str(DEV_UID))


def sandbox_uid() -> int:
    """uid/gid the sandboxed process runs as (and owns the files it writes)."""
    return int(os.environ["HANDLER_SANDBOX_DEV_UID"]) if DEV_MODE else os.getuid()


def sandbox_gid() -> int:
    return int(os.environ["HANDLER_SANDBOX_DEV_UID"]) if DEV_MODE else os.getgid()


def scope_root() -> Path:
    default = (
        Path("/var/tmp/handler-tests") if DEV_MODE else Path.home() / ".cache" / "handler-tests"
    )
    root = Path(os.environ.get("HANDLER_TEST_SCOPE_ROOT", default))
    root.mkdir(parents=True, exist_ok=True)
    return root


def home_env() -> dict[str, str]:
    """Every test daemon's HOME (start_daemon): apps are given host files only inside the home
    (H.9). In DEV_MODE, the scope root, where those files are: root's own home is out of the dev
    uid's reach."""
    return {"HOME": str(scope_root())} if DEV_MODE else {}


def make_scope() -> Path:
    path = Path(tempfile.mkdtemp(prefix="scope-", dir=scope_root()))
    if DEV_MODE:
        path.chmod(0o777)  # the dev uid must be able to write into it
    return path


def remove_scope(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def ensure_image(ref: str, binary: str = "podman") -> None:
    """Pull `ref` only when it is missing (best effort: a test needing it fails or skips with its
    reason). `binary`: podman, or a runtime's executable (its `image` verbs, A.7)."""
    found = [binary, "image", "exists" if binary == "podman" else "inspect", ref]
    if subprocess.run(found, capture_output=True, check=False).returncode != 0:
        pull = [binary, "pull", "-q", ref] if binary == "podman" else [binary, "image", "pull", ref]
        subprocess.run(pull, capture_output=True, check=False, timeout=IMAGE_TIMEOUT)


@functools.cache
def ensure_network_filter(binary: str | None = None) -> None:
    """The egress proxy's image (A.7), built once if missing, as handlerd does on its start: a
    launch never builds it. Under a lock, for the parallel workers. Best effort: without it, the
    filtered sandboxes' tests fail with the launch's reason. `binary`: the runtime's executable
    (default: podman's)."""
    if binary is None:
        if not shutil.which("podman"):
            return
        binary = str(Path(sys.executable).parent / "handler-sandbox-podman")
    if os.environ.get("HANDLER_TEST_OFFLINE"):
        return
    lock_name = f"handler-test-network-filter-{Path(binary).name}.lock"
    with open(Path(tempfile.gettempdir()) / lock_name, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        found = subprocess.run(
            [binary, "image", "proxy"], capture_output=True, text=True, check=False
        )
        if found.returncode == 0 and json.loads(found.stdout).get("image") is None:
            if Path(binary).name == "handler-sandbox-apple" and _apple_filter_built():
                _build_apple_relay()  # its relay alone: the image store's filter kept as it is
                return
            subprocess.run(
                [binary, "image", "build-proxy"],
                capture_output=True, check=False, timeout=IMAGE_TIMEOUT,
            )  # fmt: skip


def _apple_filter_built() -> bool:
    from handler_sandbox_apple.container import FILTER_IMAGE  # noqa: PLC0415 — on a Mac only
    from handler_sandbox_apple.images import info_of  # noqa: PLC0415

    return info_of(FILTER_IMAGE) is not None


def _build_apple_relay() -> None:
    """Apple's filter counts as built only with its relay, current, in this HOME's state: an
    older one lacks what the launcher gives it (`--serve`)."""
    from handler_sandbox_apple.images import build_relay  # noqa: PLC0415 — on a Mac only

    build_relay()
