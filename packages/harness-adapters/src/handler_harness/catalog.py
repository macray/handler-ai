"""Where harness adapters and the toolbox live and how they are loaded.

A harness adapter is a directory `<data>/harnesses/<name>/` containing:
  harness.toml    the descriptor (contract B, `handler.harness/v1`)
  Containerfile   the image recipe, built FROM the toolbox image

Platform data ships in this package (`data/`, read-only): the harnesses, the built-in addons, the
default toolbox and `handler-sandbox-env`. The toolbox is the user's:
`~/.config/handler-ai/toolbox/` (Containerfile + toolbox.toml, whose caches the projects use),
seeded from the default.
"""

import json
import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from handler_contracts import HarnessDescriptor, ToolboxManifest

DATA = Path(__file__).resolve().parent / "data"
DEFAULT_TOOLBOX = DATA / "toolbox"


def config_dir() -> Path:
    """The user's handler configuration (as handlerd's settings: `$HANDLER_CONFIG_DIR`, else
    XDG)."""
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return Path(os.environ.get("HANDLER_CONFIG_DIR", xdg / "handler-ai"))


def harnesses_dir() -> Path:
    """`$HANDLER_HARNESSES_DIR` (tests), else the package's harnesses."""
    return Path(os.environ.get("HANDLER_HARNESSES_DIR", DATA / "harnesses"))


def toolbox_dir() -> Path:
    """`$HANDLER_TOOLBOX_DIR`, else `<config>/toolbox`: the user's (see `seed_toolbox`)."""
    return Path(os.environ.get("HANDLER_TOOLBOX_DIR", config_dir() / "toolbox"))


def seed_toolbox() -> bool:
    """Copy the default toolbox to the user's toolbox folder if there is none (handlerd's start).
    True when it did. Afterwards the folder is the user's: never overwritten."""
    if toolbox_dir().exists():
        return False
    shutil.copytree(DEFAULT_TOOLBOX, toolbox_dir())
    return True


def toolbox() -> ToolboxManifest:
    """`toolbox.toml` of the toolbox directory (B.6): its caches."""
    return ToolboxManifest.model_validate(
        tomllib.loads((toolbox_dir() / "toolbox.toml").read_text())
    )


TOOLBOX_TOML_HEADER = """\
# What the toolbox declares besides its image (contract B.6).
#
# caches: the toolchains' state kept between sessions, one table per cache: target, the home
# path it is mounted at; about, what it holds; general = true for a folder any tool writes to
# (~/.cache), not one tool's. Each project chooses whether its agents keep their own, use the
# global ones with other projects (a write channel between projects), or get none (D.8).
"""


def save_toolbox(manifest: ToolboxManifest) -> None:
    """Write `toolbox.toml` (the caches, from Settings → Caches); its comments are handler's."""
    text = TOOLBOX_TOML_HEADER
    for name, cache in manifest.caches.items():
        text += f"\n[caches.{name}]\ntarget = {json.dumps(cache.target)}\n"
        if cache.about:
            text += f"about = {json.dumps(cache.about, ensure_ascii=False)}\n"
        if cache.general:
            text += "general = true\n"
    (toolbox_dir() / "toolbox.toml").write_text(text)


@dataclass(frozen=True)
class Harness:
    descriptor: HarnessDescriptor
    directory: Path

    @property
    def name(self) -> str:
        return self.descriptor.name

    @property
    def containerfile(self) -> Path:
        return self.directory / "Containerfile"


class UnknownHarnessError(LookupError):
    pass


def load(directory: Path) -> Harness:
    with (directory / "harness.toml").open("rb") as f:
        descriptor = HarnessDescriptor.model_validate(tomllib.load(f))
    if descriptor.name != directory.name:
        raise ValueError(f"{directory}: descriptor name '{descriptor.name}' ≠ directory name")
    return Harness(descriptor, directory)


def all_harnesses(root: Path | None = None) -> list[Harness]:
    root = root or harnesses_dir()
    return [load(d) for d in sorted(root.iterdir()) if (d / "harness.toml").is_file()]


def get(name: str, root: Path | None = None) -> Harness:
    directory = (root or harnesses_dir()) / name
    if not (directory / "harness.toml").is_file():
        raise UnknownHarnessError(f"unknown harness '{name}' (no {directory}/harness.toml)")
    return load(directory)
