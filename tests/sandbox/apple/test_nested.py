"""`nested` on Apple container: an engine inside the sandbox's own VM (Podman's here; Docker's
when the image has it). What every runtime must give is in ../conformance; this is Apple's way:
no network device in a filtered or no-network VM, the filter on the sandbox's loopback, the
engine's store and temporary files on the sandbox's disk, user namespaces in that VM only."""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ...support import dev_env
from ...support.runtimes import RUNTIMES
from ..conftest import HOME_IN, run, spec

APPLE = RUNTIMES["apple"]
TOOLBOX = os.environ.get("HANDLER_TEST_TOOLBOX_IMAGE", "localhost/handler-ai-toolbox:latest")
pytestmark = [
    pytest.mark.skipif(not APPLE.usable(), reason="Apple container not usable"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]
INNER = "docker.io/library/alpine:3.20"
STORE = f"{HOME_IN}/.local/share/containers/storage"


def sh(script: str) -> list[str]:
    return ["sh", "-c", script]


@pytest.fixture(scope="module")
def images() -> Iterator[Path]:
    """A folder holding an image to load inside (a VM with no network cannot pull)."""
    if subprocess.run(["container", "image", "inspect", TOOLBOX], capture_output=True,
                      check=False).returncode != 0:  # fmt: skip
        pytest.skip(f"{TOOLBOX} not built")
    folder = dev_env.make_scope()
    for args in (["image", "pull", INNER], ["image", "save", INNER, "-o", str(folder / "a.tar")]):
        r = subprocess.run(["container", *args], capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stderr
    folder.chmod(0o755)
    yield folder
    dev_env.remove_scope(folder)


def nested(scope: Path, images: Path, script: str, **overrides: Any) -> dict[str, Any]:
    folders = [{"source": str(images), "target": "/images", "writable": False}]
    return spec(scope, sh(script), isolation="nested", image=TOOLBOX, folders=folders, **overrides)


LOAD = "podman load -q -i /images/a.tar >/dev/null && "


@pytest.mark.rule("confinement.nested-gets-only-host-devices-and-ids")
def test_containers_inside_a_vm_with_no_network(scope: Path, images: Path) -> None:
    """If this fails: an agent of a no-network sandbox cannot run its containers, nor a Compose
    file (named networks, their names)."""
    script = LOAD + (
        f"podman run --rm {INNER} sh -c 'echo inner-ok; cat /proc/self/uid_map | tail -1' && "
        "podman network create n1 >/dev/null && "
        f"podman run -d --name web --network n1 {INNER} sh -c "
        "'while true; do printf \"HTTP/1.0 200 OK\\r\\n\\r\\nnamed-ok\" | nc -l -p 80; done' "
        f">/dev/null && sleep 1 && podman run --rm --network n1 {INNER} wget -qO- http://web/"
    )
    r = run(APPLE.binary, nested(scope, images, script), timeout=300)
    out = r.stdout.decode()
    assert r.returncode == 0 and "inner-ok" in out and "named-ok" in out, r.stderr.decode()
    assert " 1 " in out.splitlines()[1] or "100000" in out  # inner ids mapped past the user's


@pytest.mark.rule("confinement.only-the-container-loosens")
def test_containers_inside_a_filtered_sandbox_reach_only_what_it_allows(
    scope: Path, images: Path
) -> None:
    """If this fails: containers an agent runs get past its network filter, or reach nothing."""
    fetch = "wget -qO- -T 10 https://{} >/dev/null 2>&1 && echo {}=yes || echo {}=no"
    inner = "; ".join(fetch.format(h, h, h) for h in ("www.example.org", "www.example.com"))
    script = LOAD + f"podman run --rm {INNER} sh -c '{inner}'"
    network = {"mode": "filtered", "allow": ["www.example.org:443"], "enforcement": "enforce"}
    r = run(APPLE.binary, nested(scope, images, script, network=network), timeout=300)
    out = r.stdout.decode()
    assert "www.example.org=yes" in out and "www.example.com=no" in out, r.stderr.decode()


@pytest.mark.rule("confinement.nested-gets-only-host-devices-and-ids")
def test_an_images_cache_is_the_sandbox_s_own_store_on_its_disk(scope: Path, images: Path) -> None:
    """If this fails: an engine's store is shared between VMs that share no lock (a broken
    store), or held in memory."""
    cache = dev_env.make_scope()
    try:
        caches = [{"source": str(cache), "target": STORE, "kind": "images"}]
        script = LOAD + (
            "root=$(podman info --format '{{.Store.GraphRoot}}'); "
            'echo store=$(stat -f -c %T "$root"); echo tmp=$(stat -f -c %T /tmp); '
            f"grep -c ' {STORE} ' /proc/mounts || true"
        )
        r = run(APPLE.binary, nested(scope, images, script, caches=caches), timeout=300)
        out = r.stdout.decode()
        assert r.returncode == 0, r.stderr.decode()
        assert "store=ext2/ext3" in out  # the disk (ext4), not the Mac folder nor memory
        assert "tmp=ext2/ext3" in out  # its temporary files too
        assert out.split()[-1] == "0"  # the cache is not mounted
        assert not list(cache.iterdir())  # nothing of the store merged into the cache
    finally:
        dev_env.remove_scope(cache)


@pytest.mark.rule("confinement.nested-gets-only-host-devices-and-ids")
def test_a_nested_sandbox_s_user_holds_no_capability(scope: Path, images: Path) -> None:
    """If this fails: an agent allowed to run containers is root in its VM, or its engine
    cannot map its containers' ids."""
    script = (
        "grep -E '^(Uid|CapEff|CapBnd):' /proc/self/status; cat /proc/sys/user/max_user_namespaces"
    )
    r = run(APPLE.binary, nested(scope, images, script), timeout=120)
    out = r.stdout.decode()
    assert "CapEff:\t0000000000000000" in out
    assert "CapBnd:\t0000000000000000" not in out  # an engine's, for newuidmap's file caps
    assert int(out.split()[-1]) > 0  # user namespaces in that VM


@pytest.mark.rule("sandbox.hardened-by-default")
def test_a_strict_sandbox_still_has_no_user_namespace(scope: Path) -> None:
    """If this fails: giving `nested` to some sandboxes loosened every sandbox."""
    r = run(APPLE.binary, spec(scope, ["cat", "/proc/sys/user/max_user_namespaces"]))
    assert r.stdout.strip() == b"0", r.stderr


HUB_API = ["registry-1.docker.io:443", "auth.docker.io:443"]
HUB_CDN = [  # where Docker Hub's layers are
    "production.cloudflare.docker.com:443",
    "production.cloudfront.docker.com:443",
]


def pull(
    scope: Path, images: Path, cache: Path, allow: list[str]
) -> subprocess.CompletedProcess[bytes]:
    caches = [{"source": str(cache), "target": STORE, "kind": "images"}]
    network = {"mode": "filtered", "allow": allow, "enforcement": "enforce"}
    script = f"podman pull -q {INNER} >/dev/null && podman run --rm {INNER} echo pulled-ok"
    doc = nested(scope, images, script, caches=caches, network=network)
    return run(APPLE.binary, doc, timeout=300)


@pytest.mark.rule("cache.the-mirror-reaches-only-what-the-sandbox-may")
def test_an_images_cache_shares_what_was_downloaded(scope: Path, images: Path) -> None:
    """If this fails: every sandbox downloads its images again, or the mirror serves what the
    registry did not send."""
    cache = dev_env.make_scope()
    try:
        first = pull(scope, images, cache, [*HUB_API, *HUB_CDN])
        assert b"pulled-ok" in first.stdout, first.stderr.decode()
        blobs = list((cache / "blobs" / "sha256").iterdir())
        assert blobs and not [b for b in blobs if b.name.startswith(".")]
        # its layers from the cache: the CDN they come from is not allowed this time
        second = pull(scope, images, cache, HUB_API)
        assert b"pulled-ok" in second.stdout, second.stderr.decode()
    finally:
        dev_env.remove_scope(cache)


@pytest.mark.rule("cache.the-mirror-reaches-only-what-the-sandbox-may")
def test_the_mirror_reaches_no_registry_the_sandbox_may_not(scope: Path, images: Path) -> None:
    """If this fails: an agent with no access to a registry pulls from it through the mirror."""
    cache = dev_env.make_scope()
    try:
        r = pull(scope, images, cache, ["www.example.org:443"])
        assert b"pulled-ok" not in r.stdout
        assert not (cache / "blobs").exists()
    finally:
        dev_env.remove_scope(cache)
