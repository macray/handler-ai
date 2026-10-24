"""Images, through the sandbox's executable (contract A.7): the only way handlerd touches them; the
host check (A.8); the caches' sizes and emptying them (A.9: their files may be inner podman's,
of ids only the sandbox's user namespace has).

The harness adapters say what to build (`images.Recipe`) and where an image records its version;
this module asks the runtime. The egress proxy's image (the network filter, D.4) is the
runtime's own: its recipe and name stay there. Builds and pulls are long and their output goes
to a log, so the caller runs their command line (`build_argv`, `build_proxy_argv`, `pull_argv`);
the rest is synchronous and short.
"""

import json
import subprocess
from pathlib import Path

from handler_contracts import FilteredNetwork, ImageInfo, ProxyImage, RuntimeCheck, SandboxSpec
from handler_harness.images import Recipe

from . import sandbox_process

TIMEOUT = 120


def _image(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sandbox_process.binary(), "image", *args],
        capture_output=True, text=True, check=False, timeout=TIMEOUT,
    )  # fmt: skip


def _reason(result: subprocess.CompletedProcess[str]) -> str:
    lines = result.stderr.strip().splitlines()
    return (
        lines[-1].removeprefix(f"{sandbox_process.IMPLEMENTATION}: ")
        if lines
        else f"exit {result.returncode}"
    )


def check() -> RuntimeCheck:
    """Can this host run sandboxes (`check`, A.8)."""
    result = subprocess.run(
        [sandbox_process.binary(), "check"],
        capture_output=True, text=True, check=False, timeout=TIMEOUT,
    )  # fmt: skip
    return RuntimeCheck.model_validate_json(result.stdout)


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


_versions: dict[str, str | None] = {}  # image id → recorded version (an id's content never changes)


def version(ref: str, path: str) -> str | None:
    """The first line of the version file `path` the image recorded (B.6, G.1), or None if it
    has none or there is no such image."""
    info = inspect(ref)
    if info is None:
        return None
    if info.id not in _versions:
        result = _image("read", info.id, path)
        text = result.stdout.strip()
        _versions[info.id] = text.splitlines()[0] if result.returncode == 0 and text else None
    return _versions[info.id]


def tag(source: str, target: str) -> None:
    """Point `target` at `source` (a reference or an image id)."""
    result = _image("tag", source, target)
    if result.returncode != 0:
        raise RuntimeError(f"cannot tag {target}: {_reason(result)}")


def remove(image_id: str) -> str | None:
    """Remove the image if nothing uses it (no container runs from it or mounts it, nor another
    image is built on it). None when removed, else why not."""
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
