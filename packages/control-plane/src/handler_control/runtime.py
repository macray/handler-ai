"""Images, through the sandbox's executable (contract A.7): the only way handlerd touches them; the
host check (A.8); the caches' sizes and emptying them (A.9: their files may be inner podman's,
of ids only the sandbox's user namespace has).

Which runtime: `<config>/runtime.toml` (`name = "podman"`; absent: the system's, podman on Linux,
apple on macOS), read at start and written when the person chooses another (choose): one per
handlerd, every sandbox and image its.

The harness adapters say what to build (`images.Recipe`) and where an image records its version;
this module asks the runtime. The egress proxy's image (the network filter, D.4) is the
runtime's own: its recipe and name stay there. Builds and pulls are long and their output goes
to a log, so the caller runs their command line (`build_argv`, `build_proxy_argv`, `pull_argv`);
the rest is synchronous and short.
"""

import json
import re
import subprocess
import time
import tomllib
from pathlib import Path

from handler_contracts import (
    FilteredNetwork,
    ImageInfo,
    ProxyImage,
    RuntimeCheck,
    RuntimeSupports,
    SandboxSpec,
)
from handler_harness.images import Recipe

from . import sandbox_process
from .settings import Settings

EXTRACT_TIMEOUT = 1800  # a JDK's folder, copied out of its image
TIMEOUT = 120


def _image(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sandbox_process.binary(), "image", *args],
        capture_output=True, text=True, check=False, timeout=TIMEOUT,
    )  # fmt: skip


def _reason(result: subprocess.CompletedProcess[str]) -> str:
    lines = result.stderr.strip().splitlines()
    return (
        lines[-1].removeprefix(sandbox_process.launcher_prefix())
        if lines
        else f"exit {result.returncode}"
    )


CHOICE_FILE = "runtime.toml"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class RuntimeChoiceError(Exception):
    """The runtime asked for is not installed here."""


class ForAnotherSystemError(RuntimeChoiceError):
    """The runtime asked for is for another system (apple: macOS)."""


def load(settings: Settings) -> str:
    """Use the runtime the person chose (runtime.toml), else the default; its name."""
    path = settings.config_dir / CHOICE_FILE
    try:
        name = tomllib.loads(path.read_text()).get("name")
    except FileNotFoundError:
        name = None
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise RuntimeChoiceError(f"{path}: {e}") from None
    if name is not None and not (isinstance(name, str) and NAME.match(name)):
        raise RuntimeChoiceError(f'{path}: name must be a runtime\'s name, e.g. "podman"')
    sandbox_process.use(name or sandbox_process.DEFAULT_RUNTIME)
    _last_check.clear()
    return sandbox_process.current()


def choose(settings: Settings, name: str) -> None:
    """Use runtime `name` from now on, and after restarts. RuntimeChoiceError when it is not
    installed, or is for another system. The caller makes sure no sandbox runs (they are the
    previous runtime's)."""
    if other := sandbox_process.for_another_system(name):
        raise ForAnotherSystemError(other)
    if name not in sandbox_process.installed():
        raise RuntimeChoiceError(f"no runtime {name} here: no handler-sandbox-{name} executable")
    path = settings.config_dir / CHOICE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(f"name = {json.dumps(name)}\n")  # a JSON string is a TOML one
    tmp.replace(path)
    sandbox_process.use(name)
    _last_check.clear()


CHECK_TTL = 300.0  # seconds a check answers supports(): a check runs `podman info`
_last_check: list[tuple[float, RuntimeCheck]] = []  # the latest, with when it ran


def check() -> RuntimeCheck:
    """Can this host run sandboxes (`check`, A.8). Remembered for supports()."""
    result = subprocess.run(
        [sandbox_process.binary(), "check"],
        capture_output=True, text=True, check=False, timeout=TIMEOUT,
    )  # fmt: skip
    found = RuntimeCheck.model_validate_json(result.stdout)
    _last_check[:] = [(time.monotonic(), found)]
    return found


def check_of(name: str) -> RuntimeCheck | None:
    """Runtime `name`'s host check (A.8), the one in use or another installed one; None when it
    cannot say (its `check` failed, or printed no check)."""
    if name == sandbox_process.current():
        argv = [sandbox_process.binary(), "check"]
    elif found := sandbox_process.executable(name):
        argv = [found, "check"]
    else:
        return None
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=TIMEOUT)
        return RuntimeCheck.model_validate_json(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def not_ready() -> str | None:
    """Why the runtime in use cannot run sandboxes now (its host check, A.8: the first required
    item failing, e.g. Apple's service stopped, Docker Desktop not running), None when it can or
    cannot say. Asked when an image seems missing: a stopped engine knows of no image either."""
    found = check_of(sandbox_process.current())
    item = next((i for i in found.items if i.required and not i.ok), None) if found else None
    return f"{found.runtime}: {item.name}: {item.detail}" if found and item else None


def supports() -> RuntimeSupports | None:
    """What sandboxes get on this host (A.8), from a check at most CHECK_TTL old; None when the
    runtime cannot run sandboxes here, or cannot say."""
    if not _last_check or time.monotonic() - _last_check[0][0] > CHECK_TTL:
        try:
            check()
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
    return _last_check[0][1].supports


def build_argv(recipe: Recipe, id_file: str) -> list[str]:
    """Builds the recipe, untagged; the image's id is written to `id_file`."""
    argv = [sandbox_process.binary(), "image", "build", str(recipe.context), "--id-file", id_file]
    for name, value in recipe.build_args.items():
        argv += ["--build-arg", f"{name}={value}"]
    argv += ["--pull"] if recipe.pull else []
    argv += ["--no-cache"] if recipe.no_cache else []
    argv += ["--no-intermediate"] if recipe.no_intermediate else []
    return argv


def build_proxy_argv() -> list[str]:
    """Builds the egress proxy's image (the network filter, D.4), checks it and switches to it."""
    return [sandbox_process.binary(), "image", "build-proxy"]


def proxy() -> ProxyImage:
    """The egress proxy's image (A.3, A.7): its reference, and whether it is built."""
    return ProxyImage.model_validate_json(_image("proxy").stdout)


def missing_proxy(spec: SandboxSpec) -> bool:
    """The sandbox needs the egress proxy (a filtered network, or secrets to add, A.3) and its
    image is not built: its launch would fail (A.7: launches never build it)."""
    needs = isinstance(spec.network, FilteredNetwork) or bool(spec.injections)
    return needs and proxy().image is None


def pull_argv(ref: str) -> list[str]:
    """Pulls a published image (the apps' runtime, H.3)."""
    return [sandbox_process.binary(), "image", "pull", ref]


def inspect(ref: str) -> ImageInfo | None:
    """The image's id and build time, or None if there is no such image."""
    result = _image("inspect", ref)
    return ImageInfo.model_validate_json(result.stdout) if result.returncode == 0 else None


def exists(ref: str) -> bool:
    return inspect(ref) is not None


_versions: dict[str, str] = {}  # image id → recorded version (an id's content never changes)


def version(ref: str, path: str) -> str | None:
    """The first line of the version file `path` the image recorded (B.6, G.1), or None if it
    has none or there is no such image."""
    info = inspect(ref)
    if info is None:
        return None
    if info.id not in _versions:
        result = _image("read", info.id, path)
        text = result.stdout.strip()
        if result.returncode != 0 or not text:
            return None  # not kept: a read that failed is tried again next time
        _versions[info.id] = text.splitlines()[0]
    return _versions[info.id]


def extract(ref: str, path: str, folder: Path) -> str | None:
    """Copy the image's folder `path` to `folder`, which it makes (A.7). None when done, else
    why not."""
    result = subprocess.run(
        [sandbox_process.binary(), "image", "extract", ref, path, str(folder)],
        capture_output=True, text=True, check=False, timeout=EXTRACT_TIMEOUT,
    )  # fmt: skip
    return None if result.returncode == 0 else _reason(result)


def tag(source: str, target: str) -> None:
    """Point `target` at `source` (a reference or an image id)."""
    result = _image("tag", source, target)
    if result.returncode != 0:
        raise RuntimeError(f"cannot tag {target}: {_reason(result)}")


def remove(image_id: str) -> str | None:
    """Remove the image if no container runs from it or mounts it; an image built on it outlives
    it (the engine may keep it meanwhile). None when removed, else why not."""
    result = _image("remove", image_id)
    return None if result.returncode == 0 else _reason(result)


def cache_sizes(folders: list[str]) -> dict[str, int]:
    """Bytes on disk of each folder (0: not made yet)."""
    result = subprocess.run(
        [sandbox_process.binary(), "cache", "size", *folders],
        capture_output=True, text=True, check=False, timeout=TIMEOUT,
    )  # fmt: skip
    if result.returncode != 0:
        raise RuntimeError(f"cannot measure the caches: {_reason(result)}")
    return json.loads(result.stdout)


def clear_cache(folder: Path) -> str | None:
    """Empty the folder unless a sandbox mounts it or a folder inside it. None when done, else
    why not."""
    result = subprocess.run(
        [sandbox_process.binary(), "cache", "clear", str(folder)],
        capture_output=True, text=True, check=False, timeout=TIMEOUT,
    )  # fmt: skip
    return None if result.returncode == 0 else _reason(result)
