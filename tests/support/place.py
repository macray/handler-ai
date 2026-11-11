"""Where the tests run, and what the sandbox tests can prove there.

Each runtime's `check` says what it gives on this machine (A.8); a test of a confinement it does
not give skips. What a runtime gives but these tests cannot run here is named below, with why:
those skips are the place, not a fault.

- macOS, on the Mac: the macOS runtimes (Apple container, Docker Desktop or OrbStack), as their
  `check` says.
- Linux, on the host: Podman, and Docker when installed: strict, nested and privileged.
- Linux, in a container (a dev container, a Handler agent's sandbox): Podman or Docker, strict and
  nested; not privileged, which needs the tests' own container started privileged.

HANDLER_TEST_STRICT=1 (CI) makes a skip of what this place should test a failure: a runtime named
in HANDLER_TEST_RUNTIMES that is not usable, a confinement a runtime gives that fails here.
"""

import os
import sys
from pathlib import Path

STRICT = os.environ.get("HANDLER_TEST_STRICT") == "1"


def system() -> str:
    return {"darwin": "macOS", "linux": "Linux"}.get(sys.platform, sys.platform)


def in_container() -> bool:
    """Podman writes /run/.containerenv in its containers, Docker /.dockerenv."""
    return Path("/run/.containerenv").exists() or Path("/.dockerenv").exists()


def describe() -> str:
    return f"{system()}, {'in a container' if in_container() else 'on the host'}"


def not_here(confinement: str) -> str | None:
    """Why a confinement a runtime gives cannot be tested here, None when it must be."""
    if confinement == "privileged" and in_container():
        return "privileged is not tested in a container (the tests' own is not privileged)"
    return None
