"""The `cache` verbs (A.9) without a sandbox: what `clear` refuses before touching anything."""

import sys
from pathlib import Path
from typing import Any

import pytest

from handler_sandbox_podman import caches


@pytest.mark.rule("cache.never-emptied-under-a-sandbox")
@pytest.mark.skipif(sys.platform != "linux", reason="/dev holds mount points on Linux")
def test_a_folder_holding_a_mount_point_is_not_cleared(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mounted from elsewhere (the verb run in a container), its sandboxes may be invisible here:
    /dev holds mount points (/dev/shm, /dev/pts) on every Linux. Nothing is run, not even the engine's `ps`."""

    def never(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"ran {args}")

    monkeypatch.setattr(caches, "_in_userns", never)
    monkeypatch.setattr(caches, "podman", never)
    assert caches.clear(Path("/dev")) == 1
    assert "holds a mount point here" in capsys.readouterr().err
