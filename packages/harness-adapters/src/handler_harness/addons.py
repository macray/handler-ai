"""Where tools live and how they are loaded (contract G.1, tools design; `Addon` in the code).

Two folders: the built-in tools (this package's data, read-only) and the user's
(`$HANDLER_TOOLS_DIR`, else `~/.config/handler-ai/tools/`: their own, or installed: from a
source, a folder or an archive, G.5). A user tool named as a built-in one overrides it. A tool
is a directory `<name>/` containing:
  tool.toml         the manifest (`handler.tool/v1`)
  Containerfile     the tool's image, FROM the toolbox image; present iff the manifest has an `image`
  skills/<skill>/   zero or more skills, each with a SKILL.md
  PROVISIONING.md   how to create the account a connection needs (for people, not read here)
"""

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from handler_contracts import AddonManifest

from .catalog import DATA, config_dir

BUILTIN_DIR = DATA / "tools"
MANIFEST = "tool.toml"


def user_dir() -> Path:
    """`$HANDLER_TOOLS_DIR`, else `<config>/tools`."""
    return Path(os.environ.get("HANDLER_TOOLS_DIR", config_dir() / "tools"))


@dataclass(frozen=True)
class Addon:
    manifest: AddonManifest
    directory: Path

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def builtin(self) -> bool:
        """Shipped with handler; else the user's (G.1)."""
        return self.directory.parent == BUILTIN_DIR

    @property
    def overrides_builtin(self) -> bool:
        """A user tool named as a built-in one, which it replaces."""
        return not self.builtin and (BUILTIN_DIR / self.name / MANIFEST).is_file()

    @property
    def containerfile(self) -> Path:
        return self.directory / "Containerfile"

    @property
    def skills(self) -> list[Path]:
        """Skill folders, sorted; each is mounted under its own name (B.2)."""
        root = self.directory / "skills"
        return sorted(d for d in root.iterdir() if d.is_dir()) if root.is_dir() else []


_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


class UnknownAddonError(LookupError):
    pass


class InvalidAddonError(ValueError):
    pass


def load(directory: Path) -> Addon:
    """Raises InvalidAddonError with a readable message when the tool's files are wrong."""
    try:
        with (directory / MANIFEST).open("rb") as f:
            manifest = AddonManifest.model_validate(tomllib.load(f))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise InvalidAddonError(f"tool '{directory.name}': {e}") from None
    except ValidationError as e:
        errors = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'tool'}: {err['msg']}" for err in e.errors()
        )
        raise InvalidAddonError(f"tool '{directory.name}': {errors}") from None
    addon = Addon(manifest, directory)
    if manifest.name != directory.name:
        raise InvalidAddonError(f"{directory}: manifest name '{manifest.name}' ≠ directory name")
    if (manifest.image is not None) != addon.containerfile.is_file():
        raise InvalidAddonError(
            f"tool '{addon.name}': a Containerfile is needed iff the manifest has an 'image'"
        )
    for skill in addon.skills:
        if not (skill / "SKILL.md").is_file():
            raise InvalidAddonError(f"tool '{addon.name}': skill {skill.name} has no SKILL.md")
    return addon


def _names(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    return {d.name for d in root.iterdir() if (d / MANIFEST).is_file()}


def names() -> list[str]:
    """Every tool, built-in or the user's, by name."""
    return sorted(_names(BUILTIN_DIR) | _names(user_dir()))


def locate(name: str) -> Path | None:
    """The folder tool `name` is loaded from: the user's, else the built-in one."""
    if _NAME.fullmatch(name):
        for root in (user_dir(), BUILTIN_DIR):
            if (root / name / MANIFEST).is_file():
                return root / name
    return None


def get(name: str) -> Addon:
    """Raises UnknownAddonError, or InvalidAddonError when its files are wrong."""
    if (directory := locate(name)) is None:
        raise UnknownAddonError(f"unknown tool '{name}' (no {name}/{MANIFEST} in {user_dir()})")
    return load(directory)
