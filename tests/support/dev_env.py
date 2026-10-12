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


def make_scope() -> Path:
    path = Path(tempfile.mkdtemp(prefix="scope-", dir=scope_root()))
    if DEV_MODE:
        path.chmod(0o777)  # the dev uid must be able to write into it
    return path


def remove_scope(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


@functools.cache
def ensure_network_filter() -> None:
    """The egress proxy's image (A.7), built once if missing, as handlerd does on its start: a
    launch never builds it. Under a lock, for the parallel workers. Best effort: without it, the
    filtered sandboxes' tests fail with the launch's reason."""
    binary = Path(sys.executable).parent / "handler-sandbox-podman"
    if not shutil.which("podman") or os.environ.get("HANDLER_TEST_OFFLINE"):
        return
    with open(Path(tempfile.gettempdir()) / "handler-test-network-filter.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        found = subprocess.run(
            [binary, "image", "proxy"], capture_output=True, text=True, check=False
        )
        if found.returncode == 0 and "image" not in json.loads(found.stdout):
            subprocess.run(
                [binary, "image", "build-proxy"],
                capture_output=True, check=False, timeout=IMAGE_TIMEOUT,
            )  # fmt: skip
