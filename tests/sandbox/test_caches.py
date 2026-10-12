"""Contract A.9: the `cache` verbs, on throwaway folders only."""

import json
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from ..support import dev_env
from .conftest import popen, requires_podman, spec

BIN = "handler-sandbox-podman"

pytestmark = requires_podman


@pytest.fixture
def folder() -> Iterator[Path]:
    """A cache folder outside /tmp (the sandbox mounts its own /tmp)."""
    path = dev_env.make_scope()
    yield path
    subprocess.run([BIN, "cache", "clear", str(path)], check=False)
    dev_env.remove_scope(path)


def inner_owned(path: Path) -> None:
    """A file and folder of an inner user id, as inner podman's image store holds."""
    (path / "layer").mkdir()
    (path / "layer" / "f").write_bytes(b"x" * 100_000)
    prefix = ["podman", "unshare"] if os.getuid() != 0 else []
    subprocess.run([*prefix, "chown", "-R", "100:100", str(path / "layer")], check=True)
    subprocess.run([*prefix, "chmod", "700", str(path / "layer")], check=True)


def cache(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([BIN, "cache", *args], capture_output=True, text=True, check=False)


def test_size_counts_inner_ids_files_and_a_missing_folder_as_zero(folder: Path) -> None:
    inner_owned(folder)
    missing = folder.parent / f"{folder.name}-missing"
    r = cache("size", str(folder), str(missing))
    assert r.returncode == 0, r.stderr
    sizes = json.loads(r.stdout)
    assert sizes[str(folder)] >= 100_000 and sizes[str(missing)] == 0


def test_clear_empties_the_folder_inner_ids_files_too(folder: Path) -> None:
    inner_owned(folder)
    (folder / "mine").write_text("x")
    r = cache("clear", str(folder))
    assert r.returncode == 0, r.stderr
    assert folder.is_dir() and list(folder.iterdir()) == []


def test_clear_is_refused_while_a_sandbox_mounts_the_folder(folder: Path) -> None:
    """The folder itself, and one holding it (a project's own caches)."""
    cargo = folder / "cargo"
    cargo.mkdir()
    (cargo / "kept").write_text("x")
    scope = dev_env.make_scope()
    mount = {"source": str(cargo), "target": "/home/agent/.cargo", "readOnly": False}
    doc = spec(scope, ["sleep", "60"])
    doc["mounts"] += [mount | {"kind": "cache"}]
    launcher = popen(BIN, doc, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            ps = ["podman", "ps", "-q", "--filter", f"name={doc['name']}"]
            if subprocess.run(ps, capture_output=True, text=True, check=False).stdout.strip():
                break
            time.sleep(0.2)
        for path in (cargo, folder):
            r = cache("clear", str(path))
            assert r.returncode == 1 and "in use" in r.stderr
        assert (cargo / "kept").exists()
    finally:
        launcher.terminate()
        launcher.wait(timeout=60)
        dev_env.remove_scope(scope)
