"""The sandbox runtimes the contract A conformance suite runs against (tests/sandbox/conformance).

The suite drives a runtime through its executable only, as handlerd does. What it cannot see that
way (what an instance left behind, its labels, a server only its filter reaches, files of inner
user ids) each runtime answers here, with its own engine.

HANDLER_TEST_RUNTIMES (comma-separated names, e.g. `podman`) limits the suite to those; by default,
every runtime whose engine answers on this machine.
"""

import contextlib
import functools
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from . import dev_env, place

ECHO_SERVER = (Path(__file__).parent / "echo_server.py").read_text()  # its source: `python3 -c`


def _executable(name: str) -> str:
    """Next to the interpreter (the workspace's), as handlerd finds it, else on PATH."""
    sibling = Path(sys.executable).parent / name
    return str(sibling) if sibling.exists() else (shutil.which(name) or name)


class Runtime(Protocol):
    name: str
    binary: str
    server_image: str  # an image with Python and pip, its program mitmdump: the filter's

    def usable(self) -> bool: ...
    @property
    def abilities(self) -> frozenset[str]: ...  # what its `check` says it gives here (A.8)
    @property
    def limits(self) -> bool: ...  # its `check`: a spec's memory and CPU limits applied here
    def leftovers(self, name: str) -> list[str]: ...
    def running(self, name: str) -> bool: ...
    def kill(self, name: str) -> None: ...  # a container of its engine, killed (out of memory)
    def labels(self, name: str) -> dict[str, str] | None: ...
    def image_label(self, image_id: str, key: str) -> str: ...
    def local_server(self) -> AbstractContextManager[str]: ...
    def make_inner_owned(self, path: Path) -> None: ...
    def confinement_usable(self, confinement: str) -> bool: ...


class Podman:
    name = "podman"
    binary = _executable("handler-sandbox-podman")
    # an image with Python (a local server) every machine running the suite has: the filter's
    server_image = "localhost/handler-ai-proxy:2"

    def usable(self) -> bool:
        return _podman_usable()

    @property
    def abilities(self) -> frozenset[str]:
        return _abilities(self.binary)

    @property
    def limits(self) -> bool:
        return bool(_supports(self.binary).get("limits"))

    def _out(self, *args: str) -> str:
        r = subprocess.run(["podman", *args], capture_output=True, text=True, check=False)
        return r.stdout

    def leftovers(self, name: str) -> list[str]:
        """Anything an instance named `name` could have left behind (A4)."""
        found = self._out("ps", "-a", "--format", "{{.Names}}").split()
        found += self._out("network", "ls", "--format", "{{.Name}}").split()
        found = [n for n in found if n.startswith(name)]
        base = os.environ.get("XDG_RUNTIME_DIR") or str(Path.home() / ".local" / "state")
        if (Path(base) / "handler-ai" / "sandboxes" / name).exists():
            found.append("instance dir")
        return found

    def running(self, name: str) -> bool:
        return bool(self._out("ps", "-q", "--filter", f"name=^{name}$").strip())

    def kill(self, name: str) -> None:
        subprocess.run(["podman", "kill", name], capture_output=True, check=True)

    def labels(self, name: str) -> dict[str, str] | None:
        """The instance's labels, None while it does not exist."""
        r = subprocess.run(
            ["podman", "inspect", "-f", "{{json .Config.Labels}}", name],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        return json.loads(r.stdout) if r.returncode == 0 else None

    def image_label(self, image_id: str, key: str) -> str:
        return self._out("image", "inspect", "--format", f"{{{{.Labels.{key}}}}}", image_id).strip()

    @contextlib.contextmanager
    def local_server(self) -> Iterator[str]:
        """The tests' echo server (echo_server.py) on port 8000, that a sandbox's filter reaches
        but not the sandbox itself, as a model server on the LAN: its address."""
        name = f"handler-test-http-{os.urandom(3).hex()}"
        argv = ["podman", "run", "-d", "--rm", "--name", name, "--network", "podman"]
        serve = ["--entrypoint", "python3", self.server_image, "-c", ECHO_SERVER]
        subprocess.run([*argv, *serve], check=True, capture_output=True)
        try:
            yield self._out(
                "inspect",
                name,
                "--format",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            ).strip()
        finally:
            subprocess.run(
                ["podman", "rm", "-f", "-t", "0", name], capture_output=True, check=False
            )

    def make_inner_owned(self, path: Path) -> None:
        """Give `path` to an inner user id (100), as a nested sandbox's image store holds."""
        prefix = ["podman", "unshare"] if os.getuid() != 0 else []
        subprocess.run([*prefix, "chown", "-R", "100:100", str(path)], check=True)
        subprocess.run([*prefix, "chmod", "700", str(path)], check=True)

    def confinement_usable(self, confinement: str) -> bool:
        if confinement != "strict" and confinement not in self.abilities:
            return False
        return confinement != "privileged" or _podman_privileged_usable()


@functools.cache
def _supports(binary: str) -> dict:
    out = subprocess.run([binary, "check"], capture_output=True, text=True, check=False).stdout
    return json.loads(out).get("supports") or {}


def _abilities(binary: str) -> frozenset[str]:
    return frozenset(_supports(binary).get("abilities", []))


@functools.cache
def _podman_usable() -> bool:
    if not shutil.which("podman"):
        return False
    return subprocess.run(["podman", "info"], capture_output=True, check=False).returncode == 0


@functools.cache
def _podman_privileged_usable() -> bool:
    """`--privileged` needs a fresh sysfs mount, refused when podman itself runs in a container
    (e.g. a handler agent running these tests)."""
    argv = ["podman", "run", "--rm", "--privileged", dev_env.CURL_IMAGE, "true"]
    return subprocess.run(argv, capture_output=True, check=False).returncode == 0


class Apple:
    """Apple container (macOS 26): a VM per sandbox. `inspect`'s layout is not documented: its
    observations look fields up by name."""

    name = "apple"
    binary = _executable("handler-sandbox-apple")
    server_image = "localhost/handler-ai-proxy:2"

    def usable(self) -> bool:
        return _apple_usable()

    @property
    def abilities(self) -> frozenset[str]:
        return _abilities(self.binary)

    @property
    def limits(self) -> bool:
        return bool(_supports(self.binary).get("limits"))

    def _containers(self) -> list[dict]:
        out = subprocess.run(
            ["container", "list", "--all", "--format", "json"],
            capture_output=True, text=True, check=False,
        ).stdout  # fmt: skip
        try:
            return [c for c in json.loads(out or "[]") if isinstance(c, dict)]
        except ValueError:
            return []

    def leftovers(self, name: str) -> list[str]:
        found = [n for n in json.dumps(self._containers()).split('"') if n.startswith(name)]
        base = os.environ.get("XDG_RUNTIME_DIR") or str(Path.home() / ".local" / "state")
        if (Path(base) / "handler-ai" / "sandboxes" / name).exists():
            found.append("instance dir")
        return sorted(set(found))

    def running(self, name: str) -> bool:
        out = subprocess.run(
            ["container", "inspect", name], capture_output=True, text=True, check=False
        ).stdout
        return '"running"' in out.lower()

    def kill(self, name: str) -> None:
        subprocess.run(["container", "kill", name], capture_output=True, check=True)

    def labels(self, name: str) -> dict[str, str] | None:
        from handler_sandbox_apple.container import labels_of  # noqa: PLC0415 — on a Mac only

        r = subprocess.run(
            ["container", "inspect", name], capture_output=True, text=True, check=False
        )
        return labels_of(json.loads(r.stdout)) if r.returncode == 0 and r.stdout else None

    def image_label(self, image_id: str, key: str) -> str:
        from handler_sandbox_apple.container import image_info, labels_of  # noqa: PLC0415

        return labels_of(image_info(image_id) or {}).get(key, "")

    @contextlib.contextmanager
    def local_server(self) -> Iterator[str]:
        name = f"handler-test-http-{os.urandom(3).hex()}"
        argv = ["container", "run", "--detach", "--rm", "--name", name, "--entrypoint", "python3"]
        subprocess.run([*argv, self.server_image, "-c", ECHO_SERVER], check=True)
        try:
            from handler_sandbox_apple.container import find  # noqa: PLC0415 — on a Mac only

            out = subprocess.run(
                ["container", "inspect", name], capture_output=True, text=True, check=False
            ).stdout
            addresses = [
                a for key in ("ipv4Address", "address") for a in find(json.loads(out), key)
                if isinstance(a, str) and a.count(".") == 3
            ]  # fmt: skip
            yield addresses[0].split("/")[0]  # the field's name is a guess
        finally:
            subprocess.run(
                ["container", "delete", "--force", name], capture_output=True, check=False
            )

    def make_inner_owned(self, path: Path) -> None:
        """No inner user ids on this runtime yet (no `nested`): the user's own files."""

    def confinement_usable(self, confinement: str) -> bool:
        return confinement == "strict" or confinement in self.abilities


@functools.cache
def _apple_usable() -> bool:
    if sys.platform != "darwin" or not shutil.which("container"):
        return False
    status = subprocess.run(["container", "system", "status"], capture_output=True, check=False)
    return status.returncode == 0


class Docker:
    """Docker: rootful on Linux, or in a VM (Docker Desktop, OrbStack); a rootless engine only
    with HANDLER_SANDBOX_DEV_ROOTLESS_DOCKER (its `check` fails otherwise: not usable)."""

    name = "docker"
    binary = _executable("handler-sandbox-docker")
    server_image = "localhost/handler-ai-proxy:2"

    def usable(self) -> bool:
        return _docker_usable(self.binary)

    @property
    def abilities(self) -> frozenset[str]:
        return _abilities(self.binary)

    @property
    def limits(self) -> bool:
        return bool(_supports(self.binary).get("limits"))

    def _out(self, *args: str) -> str:
        r = subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
        return r.stdout

    def leftovers(self, name: str) -> list[str]:
        """Anything an instance named `name` could have left behind (A4)."""
        found = self._out("ps", "-a", "--format", "{{.Names}}").split()
        found += self._out("network", "ls", "--format", "{{.Name}}").split()
        found = [n for n in found if n.startswith(name)]
        base = os.environ.get("XDG_RUNTIME_DIR") or str(Path.home() / ".local" / "state")
        if (Path(base) / "handler-ai" / "sandboxes" / name).exists():
            found.append("instance dir")
        return found

    def running(self, name: str) -> bool:
        return bool(self._out("ps", "-q", "--filter", f"name=^{name}$").strip())

    def kill(self, name: str) -> None:
        subprocess.run(["docker", "kill", name], capture_output=True, check=True)

    def labels(self, name: str) -> dict[str, str] | None:
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{json .Config.Labels}}", name],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        return json.loads(r.stdout) if r.returncode == 0 else None

    def image_label(self, image_id: str, key: str) -> str:
        return self._out("image", "inspect", "--format", f"{{{{index .Config.Labels \"{key}\"}}}}",
                         image_id).strip()  # fmt: skip

    @contextlib.contextmanager
    def local_server(self) -> Iterator[str]:
        """The tests' echo server (echo_server.py) on port 8000, that a sandbox's filter reaches
        but not the sandbox itself, as a model server on the LAN: its address."""
        name = f"handler-test-http-{os.urandom(3).hex()}"
        argv = ["docker", "run", "-d", "--rm", "--name", name, "--network", "bridge"]
        serve = ["--entrypoint", "python3", self.server_image, "-c", ECHO_SERVER]
        subprocess.run([*argv, *serve], check=True, capture_output=True)
        try:
            yield self._out(
                "inspect", name, "--format",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            ).strip()  # fmt: skip
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)

    def make_inner_owned(self, path: Path) -> None:
        """Give `path` to an inner user id (100), as a nested sandbox's image store holds: as
        root in a container."""
        mount = ["--mount", f"type=bind,source={path},destination=/p"]
        run = ["docker", "run", "--rm", "--user", "0:0", *mount, "--entrypoint", "sh"]
        script = "chown -R 100:100 /p && chmod 700 /p"
        subprocess.run([*run, self.server_image, "-c", script], check=True, capture_output=True)

    def confinement_usable(self, confinement: str) -> bool:
        return confinement == "strict" or confinement in self.abilities


@functools.cache
def _docker_usable(binary: str) -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run([binary, "check"], capture_output=True, check=False).returncode == 0


RUNTIMES: dict[str, Runtime] = {"podman": Podman(), "apple": Apple(), "docker": Docker()}


@functools.cache
def available() -> list[Runtime]:
    """With HANDLER_TEST_STRICT, every runtime named in HANDLER_TEST_RUNTIMES must be usable."""
    wanted = os.environ.get("HANDLER_TEST_RUNTIMES")
    names = [n.strip() for n in wanted.split(",")] if wanted else list(RUNTIMES)
    if unknown := [n for n in names if n not in RUNTIMES]:
        raise ValueError(f"HANDLER_TEST_RUNTIMES: no runtime {', '.join(unknown)}")
    missing = [n for n in names if not RUNTIMES[n].usable()]
    if wanted and place.STRICT and missing:
        raise RuntimeError(f"HANDLER_TEST_STRICT: {', '.join(missing)} not usable here")
    return [RUNTIMES[n] for n in names if n not in missing]


def default_runtime() -> Runtime | None:
    """The runtime the suites starting real agents and apps run on (tests/harness, tests/apps):
    the one handlerd uses with no runtime.toml (Apple container on a Mac, Podman elsewhere), when
    it is tested here."""
    default = RUNTIMES["apple" if sys.platform == "darwin" else "podman"]
    return default if default in available() else None


def real_sandbox_env() -> dict[str, str]:
    """For a test handlerd (start_daemon): the fake hands real specs to the default runtime,
    whose network filter (on Apple, its relay too) is built as handlerd would."""
    runtime = default_runtime()
    if runtime is None:
        return {}
    dev_env.ensure_network_filter(runtime.binary)
    return {"HANDLER_TEST_REAL_SANDBOX": runtime.binary}


def summary() -> list[str]:
    """Where the sandbox tests ran and what each runtime was tested for: a skip of what is not
    listed is this place, not a fault."""
    lines = [f"{place.describe()}; HANDLER_TEST_STRICT {'on' if place.STRICT else 'off'}"]
    for name, runtime in RUNTIMES.items():
        if runtime not in available():
            lines.append(f"{name}: not tested (not usable here, or not in HANDLER_TEST_RUNTIMES)")
            continue
        tested = [c for c in ("strict", *sorted(runtime.abilities - {"display"}))
                  if not place.not_here(c) and runtime.confinement_usable(c)]  # fmt: skip
        lines.append(f"{name}: {', '.join(tested)} confinement; abilities "
                     f"{', '.join(sorted(runtime.abilities)) or 'none'}")  # fmt: skip
    return lines
