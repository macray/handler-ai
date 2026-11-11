"""The toolbox's parts and its generated recipe (contract B.7).

The toolbox image is generated from three owners' parts:
  Handler's base     `data/toolbox/distros/<distro>/`: base.containerfile, distro.toml
  system packages    the user's choice in `toolbox.toml`, each a folder `<name>/`:
                       package.toml          the manifest (`handler.system-package/v1`)
                       install-<distro>.sh   run as root at the build, one per distro it supports
                       check.sh              run in the built toolbox, as agents get it
                       files/                optional: what its install script copies
                     loaded like addons: the built-in ones (this package's data, read-only),
                     the user's (`$HANDLER_SYSTEM_PACKAGES_DIR`, else
                     `~/.config/handler-ai/system-packages/`), one named as a built-in one
                     replacing it
  the user's lines   `custom.containerfile` in the toolbox folder, appended last

`write_context` fills a build context (the generated Containerfile and the system packages'
folders, bind-mounted by their step: nothing of them stays in the image). Pure: files in, files
out; handlerd builds it (D.4).
"""

import os
import re
import shutil
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from handler_contracts import (
    CacheDeclaration,
    DistroManifest,
    SystemPackageManifest,
    ToolboxManifest,
)

from .catalog import DEFAULT_TOOLBOX, config_dir, toolbox_dir

DISTROS_DIR = DEFAULT_TOOLBOX / "distros"
BUILTIN_DIR = DEFAULT_TOOLBOX / "system-packages"
LINES_FILE = "custom.containerfile"
PACKAGE_MOUNT = "/run/handler-package"  # where a system package's folder is during its step
IMAGE_TITLE = "handler-ai-toolbox"

_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


class ToolboxError(ValueError):
    """The toolbox cannot be generated as its files are (the message says why)."""


class InvalidSystemPackageError(ToolboxError):
    pass


class UnknownSystemPackageError(LookupError):
    pass


def user_dir() -> Path:
    """`$HANDLER_SYSTEM_PACKAGES_DIR`, else `<config>/system-packages`."""
    return Path(os.environ.get("HANDLER_SYSTEM_PACKAGES_DIR", config_dir() / "system-packages"))


# ── distros ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Distro:
    manifest: DistroManifest
    directory: Path

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def base(self) -> str:
        return (self.directory / "base.containerfile").read_text()


def distros() -> list[str]:
    return sorted(d.name for d in DISTROS_DIR.iterdir() if (d / "distro.toml").is_file())


def distro(name: str) -> Distro:
    if name not in distros():
        raise ToolboxError(f"unknown distro '{name}' (Handler's: {', '.join(distros())})")
    directory = DISTROS_DIR / name
    with (directory / "distro.toml").open("rb") as f:
        return Distro(DistroManifest.model_validate(tomllib.load(f)), directory)


# ── system packages ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class SystemPackage:
    manifest: SystemPackageManifest
    directory: Path

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def builtin(self) -> bool:
        return self.directory.parent == BUILTIN_DIR

    @property
    def overrides_builtin(self) -> bool:
        """The user's, named as a built-in one, which it replaces."""
        return not self.builtin and (BUILTIN_DIR / self.name / "package.toml").is_file()

    @property
    def distros(self) -> list[str]:
        """Those it has an install script for."""
        return sorted(
            p.name[len("install-") : -len(".sh")] for p in self.directory.glob("install-*.sh")
        )

    @property
    def check(self) -> str:
        return (self.directory / "check.sh").read_text()


def load(directory: Path) -> SystemPackage:
    """Raises InvalidSystemPackageError when its files are wrong."""
    try:
        with (directory / "package.toml").open("rb") as f:
            manifest = SystemPackageManifest.model_validate(tomllib.load(f))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise InvalidSystemPackageError(f"system package '{directory.name}': {e}") from None
    except ValidationError as e:
        errors = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'package'}: {err['msg']}"
            for err in e.errors()
        )
        raise InvalidSystemPackageError(f"system package '{directory.name}': {errors}") from None
    package = SystemPackage(manifest, directory)
    if manifest.name != directory.name:
        raise InvalidSystemPackageError(
            f"{directory}: manifest name '{manifest.name}' ≠ directory name"
        )
    if not package.distros:
        raise InvalidSystemPackageError(f"system package '{package.name}': no install-<distro>.sh")
    if not (directory / "check.sh").is_file():
        raise InvalidSystemPackageError(f"system package '{package.name}': no check.sh")
    return package


def _names(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    return {d.name for d in root.iterdir() if (d / "package.toml").is_file()}


def names() -> list[str]:
    """Every system package, built-in or the user's, by name."""
    return sorted(_names(BUILTIN_DIR) | _names(user_dir()))


def get(name: str) -> SystemPackage:
    """The user's, else the built-in one. Raises UnknownSystemPackageError, or
    InvalidSystemPackageError when its files are wrong."""
    if _NAME.fullmatch(name):
        for root in (user_dir(), BUILTIN_DIR):
            if (root / name / "package.toml").is_file():
                return load(root / name)
    raise UnknownSystemPackageError(f"unknown system package '{name}'")


def with_dependencies(chosen: Iterable[str]) -> list[str]:
    """`chosen`, in its order, each followed by what it depends on that is not there yet (turned on
    with it). Raises UnknownSystemPackageError, InvalidSystemPackageError."""
    found: list[str] = []

    def add(name: str) -> None:
        if name in found:
            return
        found.append(name)
        for dependency in get(name).manifest.depends_on:
            add(dependency)

    for name in chosen:
        add(name)
    return found


def ordered(manifest: ToolboxManifest) -> list[SystemPackage]:
    """The system packages on, in the order of their layers: `toolbox.toml`'s (the order they were
    added: a new one goes last, the layers before it stay cached), each moved after what it
    depends on and what it installs after. Raises ToolboxError."""
    on = list(manifest.system_packages)
    try:
        packages = {name: get(name) for name in on}
    except UnknownSystemPackageError as e:
        raise ToolboxError(str(e)) from None
    for package in packages.values():
        if manifest.distro not in package.distros:
            raise ToolboxError(
                f"system package '{package.name}' has no install script for {manifest.distro}"
            )
        if missing := [d for d in package.manifest.depends_on if d not in packages]:
            raise ToolboxError(
                f"system package '{package.name}' needs {', '.join(missing)}: turn it on too"
            )
    after = {
        name: [
            d
            for d in (*package.manifest.depends_on, *package.manifest.installs_after)
            if d in packages
        ]
        for name, package in packages.items()
    }
    result: list[str] = []
    while len(result) < len(on):
        ready = next(
            (n for n in on if n not in result and all(d in result for d in after[n])), None
        )
        if ready is None:
            cycle = ", ".join(n for n in on if n not in result)
            raise ToolboxError(f"system packages {cycle} each come after another")
        result.append(ready)
    return [packages[n] for n in result]


# ── the toolbox ─────────────────────────────────────────────────────────


def lines() -> str:
    """The user's own lines (`custom.containerfile`); none when the file is missing."""
    try:
        return (toolbox_dir() / LINES_FILE).read_text()
    except FileNotFoundError:
        return ""


def save_lines(content: str) -> None:
    path = toolbox_dir() / LINES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(content)
    tmp.replace(path)


def caches(manifest: ToolboxManifest) -> list[tuple[CacheDeclaration, str]]:
    """Every cache of the toolbox with who declares it ("base", "system-package:<name>", "user"),
    in that order. A system package that cannot be loaded declares none (the toolbox cannot be
    built with it: its build says why). Raises ToolboxError for an unknown distro."""
    found = [(c, "base") for c in distro(manifest.distro).manifest.caches]
    for name in manifest.system_packages:
        try:
            package = get(name)
        except (ToolboxError, UnknownSystemPackageError):
            continue
        found += [(c, f"system-package:{name}") for c in package.manifest.caches]
    return found + [(c, "user") for c in manifest.caches]


HEADER = """\
# Generated by Handler from your toolbox folder (toolbox.toml, custom.containerfile), contract B.7.
# Do not edit: change the system packages in Settings → Sandboxes, your lines in custom.containerfile.
"""


def containerfile(manifest: ToolboxManifest, user_lines: str) -> str:
    """The toolbox's recipe: Handler's base, the system packages on, the user's lines last.
    Raises ToolboxError."""
    base = distro(manifest.distro)
    text = HEADER + "\n" + base.base.rstrip("\n") + "\n"
    for package in ordered(manifest):
        script = f"install-{base.name}.sh"
        text += (
            f"\n# system package {package.name} {package.manifest.version}\n"
            f"RUN --mount=type=bind,source=system-packages/{package.name},"
            f"target={PACKAGE_MOUNT} \\\n"
            f'    . /etc/os-release && test "$ID" = {base.name} \\\n'
            f"    && cd {PACKAGE_MOUNT} && sh -eu {script}\n"
        )
    if user_lines.strip():
        text += f"\n# your lines ({LINES_FILE})\n" + user_lines.rstrip("\n") + "\n"
    return text + f'\nLABEL org.opencontainers.image.title="{IMAGE_TITLE}"\n'


def write_context(folder: Path, manifest: ToolboxManifest, user_lines: str) -> None:
    """Fill `folder` (emptied first) with the toolbox's build context: its Containerfile and the
    folders of the system packages on. Raises ToolboxError."""
    text = containerfile(manifest, user_lines)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    (folder / "Containerfile").write_text(text)
    for package in ordered(manifest):
        shutil.copytree(package.directory, folder / "system-packages" / package.name)
