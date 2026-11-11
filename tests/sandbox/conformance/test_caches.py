"""Contract A.9 conformance, every runtime: the `cache` verbs, on throwaway folders only."""

import json
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from ...support import dev_env
from ...support.runtimes import Runtime
from ..conftest import popen, spec

Cache = Callable[..., subprocess.CompletedProcess[str]]


@pytest.fixture
def cache(runtime: Runtime) -> Cache:
    """`<runtime> cache ARGS…`."""

    def call(*args: str) -> subprocess.CompletedProcess[str]:
        argv = [runtime.binary, "cache", *args]
        return subprocess.run(argv, capture_output=True, text=True, check=False)

    return call


@pytest.fixture
def folder(cache: Cache) -> Iterator[Path]:
    """A cache folder outside /tmp (the sandbox mounts its own /tmp)."""
    path = dev_env.make_scope()
    yield path
    cache("clear", str(path))
    dev_env.remove_scope(path)


def inner_owned(runtime: Runtime, path: Path) -> None:
    """A file and folder of an inner user id, as a nested sandbox's image store holds."""
    (path / "layer").mkdir()
    (path / "layer" / "f").write_bytes(b"x" * 100_000)
    runtime.make_inner_owned(path / "layer")


@pytest.mark.rule("cache.measured-and-emptied-whoever-wrote-it")
def test_size_counts_inner_ids_files_and_a_missing_folder_as_zero(
    runtime: Runtime, cache: Cache, folder: Path
) -> None:
    inner_owned(runtime, folder)
    missing = folder.parent / f"{folder.name}-missing"
    r = cache("size", str(folder), str(missing))
    assert r.returncode == 0, r.stderr
    sizes = json.loads(r.stdout)
    assert sizes[str(folder)] >= 100_000 and sizes[str(missing)] == 0


@pytest.mark.rule("cache.measured-and-emptied-whoever-wrote-it")
def test_clear_empties_the_folder_inner_ids_files_too(
    runtime: Runtime, cache: Cache, folder: Path
) -> None:
    inner_owned(runtime, folder)
    (folder / "mine").write_text("x")
    r = cache("clear", str(folder))
    assert r.returncode == 0, r.stderr
    assert folder.is_dir() and list(folder.iterdir()) == []


@pytest.mark.rule("cache.never-emptied-under-a-sandbox")
def test_clear_is_refused_while_a_sandbox_mounts_the_folder(
    runtime: Runtime, cache: Cache, folder: Path
) -> None:
    """The folder itself, and one holding it (a project's own caches)."""
    cargo = folder / "cargo"
    cargo.mkdir()
    (cargo / "kept").write_text("x")
    scope = dev_env.make_scope()
    caches = [{"source": str(cargo), "target": "/home/agent/.cargo"}]
    doc = spec(scope, ["sleep", "60"], caches=caches)
    launcher = popen(runtime.binary, doc, stdin=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while not runtime.running(doc["name"]) and time.monotonic() < deadline:
            time.sleep(0.2)
        for path in (cargo, folder):
            r = cache("clear", str(path))
            assert r.returncode == 1 and "in use" in r.stderr
        assert (cargo / "kept").exists()
    finally:
        launcher.terminate()
        launcher.wait(timeout=60)
        dev_env.remove_scope(scope)
