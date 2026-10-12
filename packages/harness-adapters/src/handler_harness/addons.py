"""Where addons live and how they are loaded (contract G.1, docs/dev/design/addons.md).

Two folders: the built-in addons (this package's data, read-only) and the user's
(`$HANDLER_ADDONS_DIR`, else `~/.config/handler-ai/addons/`: their own, or installed: from the
catalog, also shipped here but not loaded, a folder or an archive). A user addon named as a built-in
one overrides it. An addon is a directory `<name>/` containing:
  addon.toml        the manifest (`handler.addon/v1`)
  Containerfile     the tool image, FROM the toolbox image; present iff the manifest has an `image`
  skills/<skill>/   zero or more skills, each with a SKILL.md
  PROVISIONING.md   how to create the account a binding needs (for people, not read here)
"""

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from handler_contracts import AddonManifest

from .catalog import DATA, config_dir

BUILTIN_DIR = DATA / "addons"
CATALOG_DIR = DATA / "catalog"  # addons shipped with handler, installed only when the user asks


def user_dir() -> Path:
    """`$HANDLER_ADDONS_DIR`, else `<config>/addons`."""
    return Path(os.environ.get("HANDLER_ADDONS_DIR", config_dir() / "addons"))


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
        """A user addon named as a built-in one, which it replaces."""
        return not self.builtin and (BUILTIN_DIR / self.name / "addon.toml").is_file()

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
    """Raises InvalidAddonError with a readable message when the addon's files are wrong."""
    try:
        with (directory / "addon.toml").open("rb") as f:
            manifest = AddonManifest.model_validate(tomllib.load(f))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise InvalidAddonError(f"addon '{directory.name}': {e}") from None
    except ValidationError as e:
        errors = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'addon'}: {err['msg']}" for err in e.errors()
        )
        raise InvalidAddonError(f"addon '{directory.name}': {errors}") from None
    addon = Addon(manifest, directory)
    if manifest.name != directory.name:
        raise InvalidAddonError(f"{directory}: manifest name '{manifest.name}' ≠ directory name")
    if (manifest.image is not None) != addon.containerfile.is_file():
        raise InvalidAddonError(
            f"addon '{addon.name}': a Containerfile is needed iff the manifest has an 'image'"
        )
    for skill in addon.skills:
        if not (skill / "SKILL.md").is_file():
            raise InvalidAddonError(f"addon '{addon.name}': skill {skill.name} has no SKILL.md")
    return addon


def _names(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    return {d.name for d in root.iterdir() if (d / "addon.toml").is_file()}


def names() -> list[str]:
    """Every addon, built-in or the user's, by name."""
    return sorted(_names(BUILTIN_DIR) | _names(user_dir()))


def locate(name: str) -> Path | None:
    """The folder addon `name` is loaded from: the user's, else the built-in one."""
    if _NAME.fullmatch(name):
        for root in (user_dir(), BUILTIN_DIR):
            if (root / name / "addon.toml").is_file():
                return root / name
    return None


def get(name: str) -> Addon:
    """Raises UnknownAddonError, or InvalidAddonError when its files are wrong."""
    if (directory := locate(name)) is None:
        raise UnknownAddonError(f"unknown addon '{name}' (no {name}/addon.toml in {user_dir()})")
    return load(directory)


def catalog_names() -> list[str]:
    """The addons of the catalog (installable, G.5)."""
    return sorted(_names(CATALOG_DIR))
