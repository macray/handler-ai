"""What handler-sandbox-apple's guarantees rest on in Apple container's virtual machines, run on
each `container` release: what a VM sees of the Mac, who answers on Apple's default network, the
guest kernel, a filter that dies. What every runtime must do is in ../conformance."""

import json
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ...support import dev_env
from ...support.runtimes import RUNTIMES
from ..conftest import popen, run, spec

APPLE = RUNTIMES["apple"]
pytestmark = pytest.mark.skipif(not APPLE.usable(), reason="Apple container not usable")


def container(*args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["container", *args], capture_output=True, text=True, check=False, **kwargs
    )


def address(name: str) -> str:
    """A container's address on Apple's default network."""
    status = json.loads(container("inspect", name).stdout)[0]["status"]
    return status["networks"][0]["ipv4Address"].split("/")[0]


def wait_running(name: str) -> None:
    deadline = time.monotonic() + 60
    while not APPLE.running(name):
        assert time.monotonic() < deadline, f"{name} did not start"
        time.sleep(0.5)


@pytest.fixture
def held(scope: Path) -> Iterator[dict[str, Any]]:
    """A filtered sandbox kept running, with a read-only folder: its spec."""
    given = dev_env.make_scope()
    doc = spec(
        scope, ["sleep", "300"],
        folders=[{"source": str(given), "target": str(given), "writable": False}],
        network={"mode": "filtered", "allow": ["www.example.org:443"], "enforcement": "enforce"},
    )  # fmt: skip
    proc = popen(APPLE.binary, doc, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
    try:
        wait_running(doc["name"])
        yield doc
    finally:
        proc.terminate()
        proc.wait(60)
        dev_env.remove_scope(given)


# a TCP connect to every port of an address, from Apple's default network: the open ones
SCAN = """
import asyncio, sys
async def main(ip):
    sem = asyncio.Semaphore(500)
    async def probe(port):
        async with sem:
            try:
                _, w = await asyncio.wait_for(asyncio.open_connection(ip, port), 1)
                w.close()
                return port
            except (OSError, asyncio.TimeoutError):
                return None
    found = await asyncio.gather(*(probe(p) for p in range(1, 65536)))
    print(sorted(p for p in found if p))
asyncio.run(main(sys.argv[1]))
"""


def test_a_filter_answers_on_no_port_of_apple_s_network(held: dict[str, Any]) -> None:
    """Apple's networks do not isolate (apple/container#2062): a filter's VM is on the default
    network, as every open sandbox, so its proxy listens on its loopback and its socket only."""
    filter_ip = address(f"{held['name']}-proxy")
    r = container(
        "run", "--rm", "--entrypoint", "python3", APPLE.server_image, "-c", SCAN, filter_ip,
        timeout=600,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert r.stdout.split("\n")[-2] == "[]"


@pytest.mark.rule("sandbox.sees-only-what-it-is-given")
def test_a_sandbox_s_vm_is_given_only_the_spec_s_folders(held: dict[str, Any], scope: Path) -> None:
    """Of the Mac, a sandbox's VM gets the folders `container` is told to share, nothing else:
    the work folder, the spec's folders, and Handler's own for it (its instance's, the relay);
    and one socket, its relay's, which `inspect` lists as a share but Apple relays alone (in
    the VM a node on a tmpfs, its folder not shared: test_host_socket.py)."""
    from handler_sandbox_apple.launch import relay_dir, socket_path  # noqa: PLC0415 — on a Mac only

    mounts = json.loads(container("inspect", held["name"]).stdout)[0]["configuration"]["mounts"]
    sources = {m["source"] for m in mounts if "virtiofs" in m["type"]}
    sockets = {s for s in sources if Path(s).is_socket()}
    assert sockets == {str(socket_path(held["name"], "relay"))}
    shared = sources - sockets
    handler_s = {s for s in shared if f"/sandboxes/{held['name']}/" in s}
    assert shared - handler_s == {str(scope), held["folders"][0]["source"], str(relay_dir())}
    assert all("/own/" in s for s in handler_s), handler_s


@pytest.mark.rule("sandbox.sees-only-what-it-is-given", "sandbox.read-only-stays-read-only")
def test_a_vm_s_share_holds_only_its_folders_read_only_kept_by_the_mac(tmp_path: Path) -> None:
    """A VM's folders are one virtiofs share whose root holds them and nothing more (not the
    Mac's root, as in SharedRoot), and the Mac refuses a write to a read-only one even to the
    VM's root with every capability, its mount made writable: what an escape to it reaches."""
    for folder in ("rw", "ro"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / f"{folder}.txt").write_text(folder)
    dev_env.ensure_image(dev_env.ALPINE_IMAGE, APPLE.binary)
    script = (
        "mkdir /x && mount -t virtiofs virtiofs /x &&"
        "echo $(ls /x | wc -l) $(for d in /x/*; do ls $d; done | sort);"
        "mount -o remount,rw /mnt/ro; touch /mnt/ro/new /mnt/rw/new 2>/dev/null;"
        "for d in /x/*; do touch $d/new2 2>/dev/null; done; ls /sys/fs/virtiofs | wc -l"
    )
    r = container(
        "run", "--rm", "--cap-add", "ALL",
        "-v", f"{tmp_path / 'rw'}:/mnt/rw", "-v", f"{tmp_path / 'ro'}:/mnt/ro:ro",
        dev_env.ALPINE_IMAGE, "sh", "-c", script, timeout=120,
    )  # fmt: skip
    listing, devices = r.stdout.strip().split("\n")[-2:]
    assert listing.split() == ["2", "ro.txt", "rw.txt"], r.stdout + r.stderr
    assert devices == "1"
    assert sorted(os.listdir(tmp_path / "rw")) == ["new", "new2", "rw.txt"]
    assert os.listdir(tmp_path / "ro") == ["ro.txt"]


# what the agent's process can reach of the guest kernel (Linux files: their absence is the
# feature built out of the kernel), and the settings the launcher gives it
KERNEL = (
    "unshare -U true 2>/dev/null && echo userns; "
    "test -e /proc/modules && echo modules; "
    "test -e /proc/sys/kernel/kexec_load_disabled && echo kexec; "
    "for s in unprivileged_bpf_disabled io_uring_disabled dmesg_restrict kptr_restrict; do "
    "echo $s=$(cat /proc/sys/kernel/$s); done"
)


@pytest.mark.rule("sandbox.hardened-by-default")
def test_the_guest_kernel_gives_no_namespace_module_kexec_bpf_nor_io_uring(scope: Path) -> None:
    """Without seccomp in Apple's VMs, the kernel itself: user namespaces off (in one, every
    capability back), no modules to load, no kexec; unprivileged BPF and io_uring off, the
    features most privilege escalations went through; its log and its addresses hidden."""
    out = run(APPLE.binary, spec(scope, ["sh", "-c", KERNEL])).stdout.decode().split()
    assert out == [
        "unprivileged_bpf_disabled=1", "io_uring_disabled=2", "dmesg_restrict=1", "kptr_restrict=2"
    ]  # fmt: skip


@pytest.mark.rule("network.filtered-fails-closed", "network.a-stopped-filter-ends-its-sandbox")
def test_a_filter_dying_cuts_the_network(scope: Path) -> None:
    """Its filter's VM gone (killed, out of memory), a filtered sandbox reaches nothing, neither
    through the relay, which no longer finds it, nor directly, until its launcher ends it."""
    with APPLE.local_server() as server:
        fetch = "curl -s -m 10 -o /dev/null -w '%{http_code}' --retry 5 --retry-connrefused"
        quick = "curl -s -m 1 -o /dev/null -w '%{http_code}'"
        url = f"http://{server}:8000/"
        script = (
            f"{fetch} {url}; echo; read x; while true; do "
            f"echo $({quick} {url}) $({quick} -p {url}) $({quick} --noproxy '*' {url}); done"
        )
        allow = {"mode": "filtered", "allow": [f"{server}:8000"], "enforcement": "enforce"}
        doc = spec(scope, ["sh", "-c", script], network=allow)
        proc = popen(APPLE.binary, doc, unchained=True, stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE)  # fmt: skip
        assert proc.stdin is not None and proc.stdout is not None
        try:
            assert proc.stdout.readline().decode().strip() == "200"
            assert container("kill", f"{doc['name']}-proxy").returncode == 0
            proc.stdin.write(b"go\n")
            proc.stdin.flush()
            tries = [line.split() for line in proc.stdout.read().decode().splitlines()]
            assert proc.wait(timeout=60) == 67
        finally:
            proc.kill()
    assert all(codes == ["000", "000", "000"] for codes in tries), tries


# in the VM: every read of `f` for 8 s, how many found it and how many did not
READS = (
    "ok=0; missing=0; end=$(( $(date +%s) + 8 )); while [ $(date +%s) -lt $end ]; do "
    "if cat f >/dev/null 2>&1; then ok=$((ok+1)); else missing=$((missing+1)); fi; done; "
    "echo $ok $missing"
)


@pytest.mark.xfail(
    strict=True,
    reason="Apple's virtiofs (1.7.1): a file the Mac replaces by rename is missing in the VM "
    "for ~650 ms; fixed when this passes",
)
def test_a_file_the_mac_replaces_by_rename_is_never_missing_in_the_vm(scope: Path) -> None:
    """Editors' safe save and git (`index`, refs, `HEAD`) replace a file by a rename: on Linux the
    sandbox sees the old file or the new one, never none."""
    (scope / "f").write_text("0")
    dev_env.ensure_image(dev_env.ALPINE_IMAGE, APPLE.binary)
    doc = spec(scope, ["sh", "-c", READS], image=dev_env.ALPINE_IMAGE)
    proc = popen(APPLE.binary, doc, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    try:
        time.sleep(2)
        for i in range(1, 6):
            (scope / "f.new").write_text(str(i))
            (scope / "f.new").replace(scope / "f")
            time.sleep(1)
        out, _ = proc.communicate(timeout=60)
    finally:
        proc.kill()
    ok, missing = out.decode().split()
    assert int(ok) > 0 and int(missing) == 0
