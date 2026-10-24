"""Installing addons into the user's folder (contract G.5): from a source (D.26), a folder, or a
`.tar.gz` archive over HTTPS.

    preview(source)          fetch it into <state>/addon-staging/<digest>/<name>/, validate it
                             (G.1), say what it brings; `digest` names exactly that content
    install(source, digest)  the staged content, only if it is still `digest`, copied to
                             ~/.config/handler-ai/addons/<name>/ (replacing what is
                             installed under that name), recorded in
                             ~/.config/handler-ai/addons.lock.toml
    remove(name)             an installed addon (never a folder the user wrote: not in the lock)

The lock records where each installed addon came from and its digest: an addon installed from a
source has an update when the source, as read last, holds other content. The daemon builds an
installed addon's image afterwards (G.4), as any rebuild: checked before agents get it.
"""

import contextlib
import hashlib
import os
import shutil
import tarfile
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
import tomlkit
from pydantic import ValidationError

from handler_contracts import AddonManifest, AddonPreview, AddonSlot, AddonSlotInfo
from handler_harness import addons

from . import files, sources
from .settings import Settings

SOURCE_PREFIX = "source:"  # source:<source>/<name>, an addon of a source (D.26)
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_FILES = 2000
DOWNLOAD_TIMEOUT = 60.0


class AddonInstallError(ValueError):
    """The source cannot be installed (the reason is shown to the user)."""


@dataclass(frozen=True)
class LockEntry:
    source: str
    digest: str
    installed_at: str


def lock_path() -> Path:
    """Next to the user's addons folder: ~/.config/handler-ai/addons.lock.toml."""
    return addons.user_dir().parent / "addons.lock.toml"


def lock() -> dict[str, LockEntry]:
    try:
        data = tomllib.loads(lock_path().read_text())
    except FileNotFoundError:
        return {}
    return {
        name: LockEntry(e["source"], e["digest"], e["installedAt"])
        for name, e in data.get("addons", {}).items()
    }


def _write_lock(entries: dict[str, LockEntry]) -> None:
    doc = tomlkit.document()
    doc.add(tomlkit.comment("Addons installed by handler (contract G.5): written by handlerd"))
    table = tomlkit.table()
    for name, e in sorted(entries.items()):
        row = tomlkit.table()
        row.update({"source": e.source, "digest": e.digest, "installedAt": e.installed_at})
        table.add(name, row)
    doc.add("addons", table)
    path = lock_path()
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
            raise AddonInstallError(f"{path.relative_to(root)} links outside the addon")


def source_digest(settings: Settings, source: str) -> str | None:
    """What a source now holds for `source:<source>/<name>` (None: no such addon there)."""
    try:
        return digest(_from_source(settings, source))
    except (AddonInstallError, sources.SourceError):
        return None


# ── fetching a source ───────────────────────────────────────────────────


def _addon_root(tree: Path) -> Path:
    """The folder holding addon.toml: the tree itself or its only folder (a forge's archive)."""
    if (tree / "addon.toml").is_file():
        return tree
    children = [c for c in tree.iterdir() if c.is_dir()]
    if len(children) == 1 and (children[0] / "addon.toml").is_file():
        return children[0]
    raise AddonInstallError("no addon.toml at the top of the source (or in its only folder)")


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
            text = (root / "addon.toml").read_text()
            name = AddonManifest.model_validate(tomllib.loads(text)).name
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise AddonInstallError(f"addon.toml: {e}") from None
        except ValidationError as e:
            raise AddonInstallError(f"addon.toml: {files.describe(e)}") from None
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
    if (addons.user_dir() / name / "addon.toml").is_file():
        return "own"
    return "builtin" if (addons.BUILTIN_DIR / name / "addon.toml").is_file() else None


def preview(settings: Settings, source: str) -> AddonPreview:
    folder, found = _stage(settings, source)
    addon = addons.load(folder)
    m = addon.manifest
    return AddonPreview(
        source=source,
        digest=found,
        name=m.name,
        description=m.description,
        image=m.image,
        commands=m.commands,
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


def install(settings: Settings, source: str, expected: str) -> str:
    """Install what the preview showed; returns the addon's name."""
    folder, found = _stage(settings, source)
    if found != expected:
        raise AddonInstallError("the source changed since its preview: look at it again")
    name = folder.name
    if _replaces(name) == "own":
        raise AddonInstallError(
            f"{addons.user_dir() / name} is your own addon: move it away to install this one"
        )
    target = addons.user_dir() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=f".{name}-") as tmp:
        shutil.copytree(folder, Path(tmp) / name, symlinks=True)
        if target.exists():
            shutil.rmtree(target)
        (Path(tmp) / name).rename(target)
    entries = lock()
    entries[name] = LockEntry(source, found, datetime.now(UTC).isoformat(timespec="seconds"))
    _write_lock(entries)
    with contextlib.suppress(OSError):
        shutil.rmtree(folder.parent)  # its staging
    return name


def remove(name: str) -> None:
    entries = lock()
    if name not in entries:
        raise AddonInstallError(f"'{name}' was not installed by handler: only installed addons go")
    shutil.rmtree(addons.user_dir() / name, ignore_errors=True)
    del entries[name]
    _write_lock(entries)
