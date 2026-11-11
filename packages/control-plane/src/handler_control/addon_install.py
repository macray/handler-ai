"""Installing addons into the user's folder (contract G.5): from a source (D.26), a folder, or a
`.tar.gz` archive over HTTPS.

    preview(source)          fetch it into <state>/addon-staging/<digest>/<name>/, validate it
                             (G.1), say what it brings and what it adds to the toolbox (B.6);
                             `digest` names exactly that content, with the system packages it
                             brings from its source
    install(source, digest, toolbox_adds)
                             the staged content, only if it is still `digest` and the system
                             packages it adds are those confirmed, copied to
                             ~/.config/handler-ai/tools/<name>/ (replacing what is
                             installed under that name), recorded in
                             ~/.config/handler-ai/tools.lock.toml; the system packages from
                             its source copied to ~/.config/handler-ai/system-packages/<name>/,
                             recorded in system-packages.lock.toml
    remove(name)             an installed addon (never a folder the user wrote: not in the lock)

What the toolbox lacks of its needs is answered by a system package providing it: one Handler or
the user has, else one of the addon's own source (B.7). The lock records where each installed
addon came from and its digest: an addon installed from a source has an update when the source,
as read last, holds other content. The daemon then turns the system packages on and applies the
toolbox, or builds the addon's image (G.4), as any rebuild: checked before agents get it.
"""

import contextlib
import hashlib
import os
import shutil
import tarfile
import tempfile
import tomllib
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
import tomlkit
from pydantic import ValidationError

from handler_contracts import (
    AddonManifest,
    AddonPreview,
    AddonSlot,
    AddonSlotInfo,
    AddonToolbox,
    ToolboxAdd,
)
from handler_harness import addons, catalog
from handler_harness import toolbox as parts

from . import files, sources, toolbox
from .settings import Settings

SOURCE_PREFIX = "source:"  # source:<source>/<name>, an addon of a source (D.26)
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_FILES = 2000
DOWNLOAD_TIMEOUT = 60.0


class AddonInstallError(ValueError):
    """The source cannot be installed (the reason is shown to the user)."""


class ToolboxNotConfirmedError(AddonInstallError):
    """The system packages it adds are not those the person confirmed."""

    def __init__(self, adds: list[str]) -> None:
        super().__init__(f"installing it adds to the toolbox: {', '.join(adds) or 'nothing'}")
        self.adds = adds


@dataclass(frozen=True)
class LockEntry:
    source: str
    digest: str
    installed_at: str


def lock_path() -> Path:
    """Next to the user's tools folder: ~/.config/handler-ai/tools.lock.toml."""
    return addons.user_dir().parent / "tools.lock.toml"


def packages_lock_path() -> Path:
    """Next to the user's system packages: ~/.config/handler-ai/system-packages.lock.toml."""
    return parts.user_dir().parent / "system-packages.lock.toml"


def _read_lock(path: Path, key: str) -> dict[str, LockEntry]:
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return {}
    return {
        name: LockEntry(e["source"], e["digest"], e["installedAt"])
        for name, e in data.get(key, {}).items()
    }


def lock() -> dict[str, LockEntry]:
    return _read_lock(lock_path(), "tools")


def packages_lock() -> dict[str, LockEntry]:
    """The system packages installed with addons, from their sources (B.7)."""
    return _read_lock(packages_lock_path(), "systemPackages")


def _write_lock(
    entries: dict[str, LockEntry],
    path: Path | None = None,
    key: str = "tools",
    what: str = "Tools installed by handler (contract G.5)",
) -> None:
    path = path or lock_path()
    doc = tomlkit.document()
    doc.add(tomlkit.comment(f"{what}: written by handlerd"))
    table = tomlkit.table()
    for name, e in sorted(entries.items()):
        row = tomlkit.table()
        row.update({"source": e.source, "digest": e.digest, "installedAt": e.installed_at})
        table.add(name, row)
    doc.add(key, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(tomlkit.dumps(doc))
    tmp.replace(path)


def digest(folder: Path) -> str:
    """The content of an addon folder: every file's path, executable bit and bytes, every
    symbolic link's path and target."""
    h = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if path.is_symlink():
            h.update(f"{rel}\0link\0{os.readlink(path)}\0".encode())
        elif path.is_file():
            executable = os.access(path, os.X_OK)
            h.update(f"{rel}\0{int(executable)}\0{path.stat().st_size}\0".encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def _links_stay_inside(root: Path) -> None:
    """A folder's symbolic links may only point inside it (copied as links, never followed: a
    link to ~/.ssh would otherwise bring its files into the addon agents get)."""
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(resolved_root):
            raise AddonInstallError(f"{path.relative_to(root)} links outside the tool")


def source_digest(settings: Settings, source: str) -> str | None:
    """What a source now holds for `source:<source>/<name>` (None: no such addon there)."""
    try:
        return digest(_from_source(settings, source))
    except (AddonInstallError, sources.SourceError):
        return None


# ── fetching a source ───────────────────────────────────────────────────


def _addon_root(tree: Path) -> Path:
    """The folder holding tool.toml: the tree itself or its only folder (a forge's archive)."""
    if (tree / addons.MANIFEST).is_file():
        return tree
    children = [c for c in tree.iterdir() if c.is_dir()]
    if len(children) == 1 and (children[0] / addons.MANIFEST).is_file():
        return children[0]
    raise AddonInstallError(
        f"no {addons.MANIFEST} at the top of the source (or in its only folder)"
    )


def _download(url: str, into: Path) -> Path:
    if not url.startswith("https://"):
        raise AddonInstallError("an archive is fetched over https:// only")
    archive = into / "archive.tar.gz"
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=DOWNLOAD_TIMEOUT) as r:
            r.raise_for_status()
            size = 0
            with archive.open("wb") as f:
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > MAX_ARCHIVE_BYTES:
                        raise AddonInstallError(f"the archive is over {MAX_ARCHIVE_BYTES} bytes")
                    f.write(chunk)
    except httpx.HTTPError as e:
        raise AddonInstallError(f"cannot download {url}: {e}") from None
    tree = into / "tree"
    tree.mkdir()
    try:
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            if len(members) > MAX_FILES:
                raise AddonInstallError(f"the archive holds more than {MAX_FILES} files")
            tar.extractall(tree, filter="data")  # no links out, no devices, no absolute paths
    except (tarfile.TarError, OSError) as e:
        raise AddonInstallError(f"not a .tar.gz archive handler can unpack: {e}") from None
    return tree


def _from_source(settings: Settings, source: str) -> Path:
    source_id, _, name = source.removeprefix(SOURCE_PREFIX).partition("/")
    try:
        return sources.item(settings, source_id, "addon", name)
    except sources.SourceError as e:
        raise AddonInstallError(str(e)) from None


def _fetch(settings: Settings, source: str, into: Path) -> Path:
    """The source's addon folder, copied or unpacked under `into`."""
    if source.startswith(SOURCE_PREFIX):
        return _from_source(settings, source)
    if source.startswith(("https://", "http://")):
        return _addon_root(_download(source, into))
    path = Path(source)
    if not path.is_absolute() or not path.is_dir():
        raise AddonInstallError(
            f"{source}: not a folder (give an absolute path), a URL or source:<source>/<name>"
        )
    return _addon_root(path)


def _stage(settings: Settings, source: str) -> tuple[Path, str]:
    """Copy the source's addon into <state>/addon-staging/<digest>/<name>/, validated."""
    staging = settings.state_dir / "addon-staging"
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging) as tmp:
        root = _fetch(settings, source, Path(tmp))
        _links_stay_inside(root)
        # validated before its name makes a path: "../x" would copy it outside the staging
        try:
            text = (root / addons.MANIFEST).read_text()
            name = AddonManifest.model_validate(tomllib.loads(text)).name
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise AddonInstallError(f"{addons.MANIFEST}: {e}") from None
        except ValidationError as e:
            raise AddonInstallError(f"{addons.MANIFEST}: {files.describe(e)}") from None
        candidate = Path(tmp) / "candidate" / name
        shutil.copytree(root, candidate, symlinks=True)
        found = digest(candidate)
        target = staging / found / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(candidate, target)
    try:
        addons.load(target)
    except addons.InvalidAddonError as e:
        raise AddonInstallError(str(e)) from None
    return target, found


# ── preview, install, remove ────────────────────────────────────────────


def _replaces(name: str) -> Literal["builtin", "installed", "own"] | None:
    if name in lock():
        return "installed"
    if (addons.user_dir() / name / addons.MANIFEST).is_file():
        return "own"
    return "builtin" if (addons.BUILTIN_DIR / name / addons.MANIFEST).is_file() else None


# ── what it adds to the toolbox ─────────────────────────────────────────


@dataclass(frozen=True)
class Toolbox:
    """An addon's needs against the toolbox: the view (`part`), the system packages it brings
    from its source (name → their folder and digest)."""

    part: AddonToolbox
    from_source: dict[str, tuple[Path, str]]

    def digest(self, addon: str) -> str:
        """The addon's digest, with those of the system packages it brings (if any)."""
        if not self.from_source:
            return addon
        h = hashlib.sha256(addon.encode())
        for name, (_, found) in sorted(self.from_source.items()):
            h.update(f"\0{name}\0{found}".encode())
        return h.hexdigest()


def _source_packages(settings: Settings, source: str) -> list[tuple[str, Path]]:
    """The system packages the source of `source:<source>/<name>` offers (none otherwise)."""
    if not source.startswith(SOURCE_PREFIX):
        return []
    source_id = source.removeprefix(SOURCE_PREFIX).partition("/")[0]
    try:
        found = sources.items(settings, source_id)
    except sources.SourceError:
        return []
    return [(n, f) for kind, n, f, _ in found if kind == "system-package" and f is not None]


def _add(
    package: parts.SystemPackage, provides: list[str], distro: str, source: str | None
) -> ToolboxAdd:
    script = package.directory / f"install-{distro}.sh"
    return ToolboxAdd(
        name=package.name,
        description=package.manifest.description,
        provides=provides,
        source=source,
        script=script.read_text(errors="replace") if script.is_file() else None,
    )


def toolbox_part(settings: Settings, manifest: AddonManifest, source: str) -> Toolbox:
    """What the toolbox lacks of the addon's needs, and the system packages answering it: one
    Handler or the user has, else one of the addon's source (B.7), whose folder must be valid
    and depend only on installed ones."""
    needs = [toolbox.Need((c,), f"addon:{manifest.name}") for c in manifest.needs]
    lacking = toolbox.to_add(settings, needs)
    try:
        distro = catalog.toolbox().distro
    except (OSError, ValueError):
        return Toolbox(AddonToolbox(has=manifest.needs), {})
    adds = [_add(parts.get(n), c, distro, None) for n, c in lacking.adds.items()]
    from_source: dict[str, tuple[Path, str]] = {}
    unprovided = []
    offered = _source_packages(settings, source) if lacking.unprovided else []
    for command in lacking.unprovided:
        for name, folder in offered:
            with contextlib.suppress(parts.ToolboxError):
                package = parts.load(folder)
                if command not in package.manifest.provides or distro not in package.distros:
                    continue
                if name in from_source:
                    next(a for a in adds if a.name == name).provides.append(command)
                    break
                if unknown := [d for d in package.manifest.depends_on if d not in parts.names()]:
                    raise AddonInstallError(
                        f"system package '{name}' depends on {', '.join(unknown)}, not installed"
                    )
                if name in parts.names():
                    raise AddonInstallError(
                        f"system package '{name}' of the source has the name of one you have"
                    )
                ref = f"{source.removeprefix(SOURCE_PREFIX).partition('/')[0]}/{name}"
                adds.append(_add(package, [command], distro, f"{SOURCE_PREFIX}{ref}"))
                from_source[name] = (folder, digest(folder))
                break
        else:
            unprovided.append(command)
    lost = {*lacking.unprovided, *(c for answered in lacking.adds.values() for c in answered)}
    part = AddonToolbox(
        has=[c for c in manifest.needs if c not in lost], adds=adds, lacking=unprovided
    )
    return Toolbox(part, from_source)


def preview(settings: Settings, source: str) -> AddonPreview:
    folder, found = _stage(settings, source)
    addon = addons.load(folder)
    m = addon.manifest
    tb = toolbox_part(settings, m, source)
    return AddonPreview(
        source=source,
        digest=tb.digest(found),
        toolbox=tb.part,
        name=m.name,
        description=m.description,
        image=m.image,
        commands=m.commands,
        needs=m.needs,
        caches=m.caches,
        env=sorted((m.env or {}).keys()),
        settings=[_slot(n, s) for n, s in sorted(m.settings.items())],
        secret_slots=[_slot(n, s) for n, s in sorted(m.secret_slots.items())],
        egress=m.egress,
        mcp=m.mcp.command if m.mcp else None,
        skills=[s.name for s in addon.skills],
        replaces=_replaces(m.name),
    )


def _slot(name: str, slot: AddonSlot) -> AddonSlotInfo:
    return AddonSlotInfo(name=name, required=slot.required, description=slot.description)


@dataclass(frozen=True)
class Installed:
    name: str
    adds: list[str]  # the system packages to turn on (then apply the toolbox)
    lacking: list[str]  # its needs nothing provides: it waits for the user's lines


def install(
    settings: Settings, source: str, expected: str, toolbox_adds: Collection[str] = ()
) -> Installed:
    """Install what the preview showed, with the system packages of its source it brings.
    ToolboxNotConfirmedError: they add other system packages than `toolbox_adds`."""
    folder, found = _stage(settings, source)
    tb = toolbox_part(settings, addons.load(folder).manifest, source)
    if tb.digest(found) != expected:
        raise AddonInstallError("the source changed since its preview: look at it again")
    adds = [a.name for a in tb.part.adds]
    if sorted(adds) != sorted(set(toolbox_adds)):
        raise ToolboxNotConfirmedError(adds)
    name = folder.name
    if _replaces(name) == "own":
        raise AddonInstallError(
            f"{addons.user_dir() / name} is your own tool: move it away to install this one"
        )
    target = addons.user_dir() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=f".{name}-") as tmp:
        shutil.copytree(folder, Path(tmp) / name, symlinks=True)
        if target.exists():
            shutil.rmtree(target)
        (Path(tmp) / name).rename(target)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    _install_packages(source, tb.from_source, now)
    entries = lock()
    entries[name] = LockEntry(source, found, now)
    _write_lock(entries)
    with contextlib.suppress(OSError):
        shutil.rmtree(folder.parent)  # its staging
    return Installed(name, adds, tb.part.lacking)


def _install_packages(source: str, found: dict[str, tuple[Path, str]], now: str) -> None:
    """The system packages of the addon's source, copied to the user's folder (B.7)."""
    if not found:
        return
    source_id = source.removeprefix(SOURCE_PREFIX).partition("/")[0]
    entries = packages_lock()
    for name, (folder, found_digest) in found.items():
        target = parts.user_dir() / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target.parent, prefix=f".{name}-") as tmp:
            shutil.copytree(folder, Path(tmp) / name, symlinks=True)
            (Path(tmp) / name).rename(target)  # not there: refused by `toolbox_part`
        entries[name] = LockEntry(f"{SOURCE_PREFIX}{source_id}/{name}", found_digest, now)
    what = "System packages installed with tools by handler (contract B.7)"
    _write_lock(entries, packages_lock_path(), "systemPackages", what)


def remove(name: str) -> None:
    entries = lock()
    if name not in entries:
        raise AddonInstallError(f"'{name}' was not installed by handler: only installed tools go")
    shutil.rmtree(addons.user_dir() / name, ignore_errors=True)
    del entries[name]
    _write_lock(entries)
