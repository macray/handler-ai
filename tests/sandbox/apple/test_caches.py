"""Caches on Apple container: a sandbox only adds files to them. Each cache is an overlay (the
Mac folder read-only under the sandbox's own disk), served by a program with no capability; its
new files are merged into the cache once it ends, by a VM of their own, crashed or not."""

import fcntl
import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ...support import dev_env
from ...support.runtimes import RUNTIMES
from ..conftest import HOME_IN, run, spec

APPLE = RUNTIMES["apple"]
pytestmark = pytest.mark.skipif(not APPLE.usable(), reason="Apple container not usable")

TARGET = f"{HOME_IN}/.cache"


def sh(script: str) -> list[str]:
    return ["sh", "-c", script]


@pytest.fixture
def cache() -> Iterator[Path]:
    """A cache folder holding what earlier sandboxes added."""
    path = dev_env.make_scope()
    (path / "kept").write_text("shared\n")
    (path / "other").write_text("other\n")
    yield path
    dev_env.remove_scope(path)


def with_cache(scope: Path, cache: Path, script: str, **overrides: Any) -> dict[str, Any]:
    caches = [{"source": str(cache), "target": TARGET}]
    return spec(scope, sh(script), caches=caches, **overrides)


def volume(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["container", "volume", *args], capture_output=True, text=True, check=False
    )


@pytest.mark.rule("cache.on-apple-a-sandbox-only-adds")
def test_a_sandbox_s_new_files_are_kept_its_changes_and_deletions_are_not(
    scope: Path, cache: Path
) -> None:
    """If this fails: an agent rewrites a package the next agent runs, or what it downloaded is
    lost."""
    script = (
        f"cd {TARGET} && echo changed > kept && rm other && echo new > new && mkdir -p d/e "
        "&& echo deep > d/e/f && ln -s new link && cat kept && ls"
    )
    r = run(APPLE.binary, with_cache(scope, cache, script))
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == [b"changed", b"d", b"kept", b"link", b"new"]  # its own view
    assert (cache / "kept").read_text() == "shared\n"  # changed in the sandbox only
    assert (cache / "other").read_text() == "other\n"  # deleted in the sandbox only
    assert (cache / "new").read_text() == "new\n"
    assert (cache / "d" / "e" / "f").read_text() == "deep\n"
    assert os.readlink(cache / "link") == "new"


@pytest.mark.rule("cache.on-apple-a-sandbox-only-adds")
def test_two_sandboxes_at_once_both_add_to_a_cache(scope: Path, cache: Path) -> None:
    """If this fails: two agents of a project running together lose or break what they share."""
    results: dict[str, subprocess.CompletedProcess[bytes]] = {}

    def one(name: str) -> None:
        script = f"echo {name} > {TARGET}/{name} && echo {name} > {TARGET}/both && sleep 3"
        results[name] = run(APPLE.binary, with_cache(scope, cache, script))

    threads = [threading.Thread(target=one, args=(n,)) for n in ("first", "second")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(r.returncode == 0 for r in results.values()), [r.stderr for r in results.values()]
    assert (cache / "first").read_text() == "first\n"
    assert (cache / "second").read_text() == "second\n"
    assert (cache / "both").read_text() in ("first\n", "second\n")  # one of them, whole
    assert not [p for p in cache.iterdir() if p.name.startswith(".handler-merge")]


@pytest.mark.rule("sandbox.hardened-by-default")
def test_the_program_serving_a_cache_has_no_capability(scope: Path, cache: Path) -> None:
    """If this fails: a `strict` sandbox with caches holds a root process the agent talks to."""
    script = (
        "for p in /proc/[0-9]*; do grep -q '^Name:.fuse-overlayfs' $p/status 2>/dev/null && "
        "grep -E '^(Uid|CapEff|CapBnd|NoNewPrivs):' $p/status; done; "
        f"grep -E '^(CapEff|NoNewPrivs):' /proc/self/status; grep ' {TARGET} ' /proc/mounts"
    )
    r = run(APPLE.binary, with_cache(scope, cache, script))
    assert r.returncode == 0, r.stderr
    status = r.stdout.decode()
    uid = str(os.getuid())
    assert f"Uid:\t{uid}\t{uid}\t{uid}\t{uid}" in status
    assert status.count("CapEff:\t0000000000000000") == 2  # the program and the agent
    assert "CapBnd:\t0000000000000000" in status
    assert status.count("NoNewPrivs:\t1") == 2
    assert "nosuid,nodev" in status


@pytest.mark.rule("sandbox.on-apple-its-cache-disk-at-most-20-gb")
def test_a_sandbox_s_disk_holds_20_gb_at_most_and_goes_with_it(scope: Path, cache: Path) -> None:
    """If this fails: a sandbox fills the Mac's disk, or its disks stay after it."""
    doc = with_cache(scope, cache, "df -k /run/handler/disk | tail -1")
    r = run(APPLE.binary, doc)
    assert r.returncode == 0, r.stderr
    size_kib = int(r.stdout.split()[1])
    assert 19 * 1024**2 < size_kib <= 20 * 1024**2
    assert not APPLE.leftovers(doc["name"])


@pytest.mark.rule("cache.on-apple-additions-merged-even-after-a-crash")
def test_sweep_merges_what_a_dead_launcher_s_sandbox_added(cache: Path) -> None:
    """If this fails: a sandbox that crashed loses what it downloaded, or its disk stays."""
    from handler_sandbox_apple.launch import (  # noqa: PLC0415 — on a Mac only
        CACHES_LABEL,
        Apple,
    )
    from handler_sandbox_kit.launch import runtimes_dir  # noqa: PLC0415

    sandbox = unique("handler-test-swept")
    disk = f"{sandbox}-disk"
    labels = {
        "handler.managed": "1", "handler.sandbox": sandbox,
        "handler.launcher": "1:1", CACHES_LABEL: json.dumps([str(cache)]),
    }  # fmt: skip
    # its merge lock held until its files are written: a dead launcher's from its creation, the
    # disk would be merged by another test's sweep while `write_on` writes on it
    locks = runtimes_dir() / "disks"
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / f"{disk}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        created = volume(
            "create", "-s", "1G",
            *(a for k, v in labels.items() for a in ("--label", f"{k}={v}")), disk,
        )  # fmt: skip
        assert created.returncode == 0, created.stderr
        write_on(disk, "mkdir -p /d/0/u && echo crashed > /d/0/u/added")
    assert sandbox in Apple().sweep()
    # merged by this sweep, or by another launcher's at the same time (another test's)
    deadline = time.monotonic() + 120
    while disk in volume("list", "--format", "json").stdout:
        assert time.monotonic() < deadline, "the dead launcher's disk was not merged"
        time.sleep(1)
    assert (cache / "added").read_text() == "crashed\n"


@pytest.mark.rule("cache.merge-stays-in-its-cache")
def test_the_merge_writes_through_no_link(cache: Path) -> None:
    """If this fails: an agent writes files of your Mac outside its cache, through a link it
    left in the cache."""
    from handler_sandbox_apple.launch import DISK, merge_and_remove  # noqa: PLC0415

    outside = dev_env.make_scope()
    try:
        (cache / "escape").symlink_to(f"{DISK}")  # a link an earlier sandbox added
        (cache / "out").symlink_to(str(outside))
        sandbox = unique("handler-test-merge")
        disk = f"{sandbox}-disk"
        from handler_sandbox_kit.launcher import launcher_label  # noqa: PLC0415

        # a sandbox's disk, its launcher this test (alive: another test's sweep leaves it)
        labels = {"handler.managed": "1", "handler.sandbox": sandbox,
                  "handler.launcher": launcher_label()}  # fmt: skip
        created = volume(
            "create", "-s", "1G", *(a for k, v in labels.items() for a in ("--label", f"{k}={v}")),
            disk,
        )  # fmt: skip
        assert created.returncode == 0, created.stderr
        write_on(
            disk,
            "mkdir -p /d/0/u/escape /d/0/u/out && echo x > /d/0/u/escape/planted "
            "&& echo x > /d/0/u/out/planted && ln -s /etc/passwd /d/0/u/link "
            "&& mknod /d/0/u/other c 0 0",
        )
        merge_and_remove(disk, [str(cache)])
        assert not list(outside.iterdir())
        assert os.readlink(cache / "link") == "/etc/passwd"  # a link, never followed
        assert (cache / "other").exists()  # a deletion: dropped
        assert disk not in volume("list", "--format", "json").stdout
    finally:
        dev_env.remove_scope(outside)


@pytest.mark.rule("cache.never-emptied-under-a-sandbox")
def test_a_cache_is_not_emptied_while_additions_to_it_are_to_merge(cache: Path) -> None:
    """If this fails: emptying a cache races a merge, which puts back half of what was there."""
    from handler_sandbox_apple.launch import CACHES_LABEL  # noqa: PLC0415

    sandbox = unique("handler-test-pending")
    disk = f"{sandbox}-disk"
    from handler_sandbox_kit.launcher import launcher_label  # noqa: PLC0415

    # a live launcher's (this test's): another test's sweep leaves it
    labels = {"handler.managed": "1", "handler.sandbox": sandbox,
              "handler.launcher": launcher_label(),
              CACHES_LABEL: json.dumps([str(cache / "inner")])}  # fmt: skip
    created = volume(
        "create", "-s", "1G", *(a for k, v in labels.items() for a in ("--label", f"{k}={v}")),
        disk,
    )  # fmt: skip
    assert created.returncode == 0, created.stderr
    try:
        r = subprocess.run(
            [APPLE.binary, "cache", "clear", str(cache)],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        assert r.returncode == 1 and sandbox in r.stderr
        assert (cache / "kept").exists()
    finally:
        volume("delete", disk)


def unique(name: str) -> str:
    """A sandbox's name no other run uses: ci.sh runs each test on two Pythons at once."""
    return f"{name}-{uuid.uuid4().hex[:8]}"


def write_on(disk: str, script: str) -> None:
    """Files on a disk as a sandbox would leave them (as root: whiteouts), at /d."""
    r = subprocess.run(
        ["container", "run", "--rm", "--volume", f"{disk}:/d", "docker.io/library/alpine:3.20",
         "sh", "-c", f"{script} && chown -R {os.getuid()}:{os.getgid()} /d/0"],
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
