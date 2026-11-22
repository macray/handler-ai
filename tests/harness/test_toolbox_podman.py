"""The toolbox's podman, as an agent runs it in a sandbox (A.5, B.7): its `podman` command
(the podman system package's `files/podman`) run with this computer's podman, on a store of its
own (a HOME of its own), offline. Sandboxes are played by what makes one: its /tmp (TMPDIR), its
run root (XDG_RUNTIME_DIR, the same path in every sandbox, empty at each start), and its end
(its processes killed)."""

import contextlib
import os
import shutil
import signal
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from handler_harness import toolbox

WRAPPER = toolbox.BUILTIN_DIR / "podman" / "files" / "podman"
REAL = Path("/usr/bin/podman")  # where the toolbox's podman package installs it

pytestmark = pytest.mark.skipif(
    not REAL.is_file() or not shutil.which("flock") or not shutil.which("setsid"),
    reason="needs podman at /usr/bin/podman, flock and setsid (util-linux)",
)


@dataclass
class Place:
    root: Path

    @property
    def store(self) -> Path:
        return self.root / "home" / ".local" / "share" / "containers" / "storage"

    @property
    def states(self) -> Path:
        return self.store / "handler-sandboxes"

    def env(self, sandbox: str) -> dict[str, str]:
        tmp = self.root / sandbox / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        (self.root / "run").mkdir(mode=0o700, exist_ok=True)
        keep = {k: os.environ[k] for k in ("PATH", "LANG") if k in os.environ}
        return keep | {
            "HOME": str(self.root / "home"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_RUNTIME_DIR": str(self.root / "run"),
            "TMPDIR": str(tmp),
        }

    def podman(self, sandbox: str, *args: str) -> str:
        r = subprocess.run(
            ["sh", str(WRAPPER), *args], env=self.env(sandbox),
            capture_output=True, text=True, timeout=120, check=False,
        )  # fmt: skip
        assert r.returncode == 0, r.stderr
        return r.stdout

    def end(self, sandbox: str) -> None:
        """Its processes killed, its run root gone (the next sandbox gets an empty one)."""
        holder = self.root / sandbox / "tmp" / "handler-podman" / "holder"
        os.killpg(int(holder.read_text()), signal.SIGKILL)
        self.unshare("rm", "-rf", str(self.root / "run"))

    def unshare(self, *argv: str) -> None:
        env = self.env("teardown")
        subprocess.run([str(REAL), "unshare", *argv], env=env, check=False, timeout=60)

    def containers_files(self) -> int:
        folder = self.store / "overlay-containers"
        return len([p for p in folder.iterdir() if p.is_dir()]) if folder.is_dir() else 0


@pytest.fixture
def place(tmp_path: Path) -> Iterator[Place]:
    place = Place(tmp_path)
    yield place
    for holder in tmp_path.glob("*/tmp/handler-podman/holder"):
        with contextlib.suppress(ProcessLookupError):  # ended by the test
            os.killpg(int(holder.read_text()), signal.SIGKILL)
    place.unshare("rm", "-rf", str(tmp_path / "home"), str(tmp_path / "run"))


@pytest.mark.rule("cache.podman-frees-what-ended-sandboxes-left")
def test_a_sandbox_frees_what_ended_sandboxes_left_and_never_a_running_one_s(
    place: Place, tmp_path: Path
) -> None:
    """A sandbox's first podman call removes the containers of the sandboxes that have ended,
    freeing their files in the shared image store; a sandbox still running keeps its own; the
    images stay.

    If this fails: the podman cache grows with every sandbox that ran a container, until
    emptied by hand; or one agent's containers vanish while another starts."""
    context = tmp_path / "context"
    context.mkdir()
    (context / "x").write_text("x\n")
    (context / "Containerfile").write_text("FROM scratch\nCOPY x /x\n")
    image = "localhost/handler-test-podman-package:1"
    place.podman("ended", "build", "-q", "-t", image, str(context))
    place.podman("ended", "create", "--name", "left", image, "/x")
    place.podman("running", "create", "--name", "kept", image, "/x")
    assert place.containers_files() == 2 and len(list(place.states.iterdir())) == 2
    place.end("ended")

    assert place.podman("new", "ps", "-a", "--format", "{{.Names}}").split() == []
    assert place.containers_files() == 1  # the ended sandbox's container freed
    assert len(list(place.states.iterdir())) == 2  # the running one's and the new one's
    assert place.podman("running", "ps", "-a", "--format", "{{.Names}}").split() == ["kept"]
    assert image in place.podman("new", "images", "--format", "{{.Repository}}:{{.Tag}}")
