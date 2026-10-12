"""Knowledge folders (D.5): folders of the knowledge root given to an agent, per agent,
read-only at /knowledge/<folder name>; and the root itself, set and browsed from the web UI.

handler knows nothing of what the folders hold (a skill may teach the agent to read them): to
handler they are mounts, and files it shows as they are.
"""

import json
import os
import tomllib
from pathlib import Path, PurePosixPath
from typing import Literal

from handler_contracts import (
    KnowledgeFolderView,
    KnowledgeListing,
    KnowledgeNote,
    Mount,
    is_within,
)

from .settings import Settings

MOUNT_ROOT = "/knowledge"
LISTING_DEPTH = 3
CONFIG_FILE = "knowledge.toml"  # in the config dir: `root = "…"`, written by set_root
INDEX = "_index.md"
MAX_NOTE_BYTES = 1024 * 1024

Source = Literal["env", "config", "default"]


class KnowledgeError(ValueError):
    """A knowledge folder or note cannot be used (outside the root, missing, hidden, …)."""


class KnowledgeConflictError(KnowledgeError):
    """The request conflicts with the current state (the root is forced, the folder exists)."""


# ── the root ────────────────────────────────────────────────────────────


def root(settings: Settings) -> tuple[Path, Source]:
    """HANDLER_KNOWLEDGE_DIR, else the root set through the API, else ~/knowledge. Read on every
    call: a change applies to the next check or agent start, no restart needed."""
    if settings.knowledge_dir is not None:
        return settings.knowledge_dir, "env"
    config = settings.config_dir / CONFIG_FILE
    try:
        configured = tomllib.loads(config.read_text()).get("root")
    except (OSError, tomllib.TOMLDecodeError):
        configured = None
    if isinstance(configured, str) and os.path.isabs(configured):
        return Path(configured), "config"
    return Path.home() / "knowledge", "default"


def set_root(settings: Settings, path: str | None, create: bool = False) -> None:
    """Save the root in the config dir (None: back to the default). Existing agents keep
    their folders as paths relative to the root, so they follow it."""
    if settings.knowledge_dir is not None:
        raise KnowledgeConflictError("the knowledge root is set by HANDLER_KNOWLEDGE_DIR")
    config = settings.config_dir / CONFIG_FILE
    if path is None:
        config.unlink(missing_ok=True)
        return
    target = Path(os.path.expanduser(path))
    if not target.is_absolute():
        raise KnowledgeError(f"the knowledge root must be an absolute path: {path}")
    if create:
        target.mkdir(parents=True, exist_ok=True)
    if not target.is_dir():
        raise KnowledgeError(f"{target} is not a folder")
    config.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.with_suffix(".tmp")
    tmp.write_text(f"root = {json.dumps(os.path.realpath(target))}\n")  # JSON string = TOML one
    tmp.replace(config)


# ── folders given to agents ─────────────────────────────────────────────


def check(root: Path, folders: list[str]) -> list[str]:
    """The folders as sorted paths relative to `root` ("." for the root itself), all usable;
    raises KnowledgeError otherwise. Absolute paths inside the root are accepted too."""
    if not folders:
        return []
    base = os.path.realpath(root)
    selected = sorted({_folder(base, folder)[1] for folder in folders})
    names: dict[str, str] = {}
    for folder in selected:
        for other in selected:
            if other != folder and (folder == "." or other.startswith(folder + "/")):
                raise KnowledgeError(f"knowledge folder {other} is inside {folder}: select one")
        name = mount_name(base, folder)
        if name in names:
            raise KnowledgeError(
                f"knowledge folders {names[name]} and {folder} would both be {MOUNT_ROOT}/{name}"
            )
        names[name] = folder
    return selected


def mount_name(root: str | Path, folder: str) -> str:
    return Path(root).name if folder == "." else PurePosixPath(folder).name


def mounts(root: Path, folders: list[str]) -> list[Mount]:
    """`folders` must already be checked."""
    base = os.path.realpath(root)
    return [
        Mount(
            source=os.path.join(base, folder) if folder != "." else base,
            target=f"{MOUNT_ROOT}/{mount_name(base, folder)}",
            read_only=True,
            kind="knowledge",
        )
        for folder in folders
    ]


def listing(root: Path, source: Source) -> KnowledgeListing:
    """The selectable folders, a few levels deep, parents before children. Folders whose name
    starts with "." or "_" are left out."""
    base = os.path.realpath(root)
    if not os.path.isdir(base):
        return KnowledgeListing(root=base, source=source, exists=False, folders=[])
    folders: list[str] = []

    def walk(path: Path, depth: int) -> None:
        for child in sorted(path.iterdir()):
            if _visible(child) and child.is_dir():
                relative = child.relative_to(base).as_posix()
                folders.append(relative)
                if depth < LISTING_DEPTH:
                    walk(child, depth + 1)

    walk(Path(base), 1)
    return KnowledgeListing(root=base, source=source, exists=True, folders=folders)


# ── browsing and creating (web UI) ──────────────────────────────────────


def create_folder(root: Path, relative: str) -> None:
    """Create one folder; its parent must exist inside the root."""
    base = os.path.realpath(root)
    parts = PurePosixPath(relative).parts
    if not parts or any(p in (".", "..") or p.startswith((".", "_")) for p in parts):
        raise KnowledgeError(f"invalid folder name {relative!r}")
    parent, _ = _folder(base, str(PurePosixPath(*parts[:-1])) if len(parts) > 1 else ".")
    try:
        (Path(parent) / parts[-1]).mkdir()
    except FileExistsError:
        raise KnowledgeConflictError(f"{relative} already exists") from None


def browse(root: Path, relative: str) -> KnowledgeFolderView:
    path, rel = _folder(os.path.realpath(root), relative)
    folders, notes = [], []
    for child in sorted(Path(path).iterdir(), key=lambda p: p.name.lower()):
        if not _visible(child):
            continue
        if child.is_dir():
            folders.append(child.name)
        elif child.suffix == ".md" and child.is_file():
            notes.append(child.name)
    index = Path(path) / INDEX
    text = _read(index) if index.is_file() else None
    return KnowledgeFolderView(path=rel, folders=folders, notes=notes, index=text)


def read_note(root: Path, relative: str) -> KnowledgeNote:
    base = os.path.realpath(root)
    path, rel = _resolve(base, relative)
    if not path.endswith(".md") or not os.path.isfile(path):
        raise KnowledgeError(f"{relative}: not a markdown file in the knowledge root")
    return KnowledgeNote(path=rel, text=_read(Path(path)))


# ── appends (automations, I.6) ──────────────────────────────────────────


def check_note(root: Path, relative: str) -> str:
    """A note an automation may append to, relative to the root: inside it (symlinks resolved),
    no hidden or `_` component, a `.md` file (that may not exist yet) in an existing folder."""
    path, rel = _resolve(os.path.realpath(root), relative)
    if any(part.startswith("_") for part in PurePosixPath(rel).parts):
        raise KnowledgeError(f"{relative}: folders and files starting with _ cannot be used")
    if not rel.endswith(".md"):
        raise KnowledgeError(f"{relative}: not a markdown note (.md)")
    if os.path.exists(path) and not os.path.isfile(path):
        raise KnowledgeError(f"{relative}: not a file")
    if not os.path.isdir(os.path.dirname(path)):
        raise KnowledgeError(f"{relative}: its folder does not exist in the knowledge root")
    return rel


def append_note(root: Path, relative: str, text: str) -> None:
    """Append `text` to a note (`check_note`), created when missing: the only write handler makes in
    the knowledge root."""
    rel = check_note(root, relative)
    with open(os.path.join(os.path.realpath(root), rel), "a", encoding="utf-8") as f:
        f.write(text)


# ── confinement ─────────────────────────────────────────────────────────


def _resolve(base: str, relative: str) -> tuple[str, str]:
    """(absolute path, path relative to `base`) of `relative`, symlinks resolved; refuses
    anything outside `base` or with a hidden component."""
    path = os.path.realpath(os.path.join(base, relative))  # symlinks resolved: no way out
    if not is_within(path, base):
        raise KnowledgeError(f"{relative}: outside the knowledge root {base}")
    rel = os.path.relpath(path, base)
    if any(part.startswith(".") and part != "." for part in PurePosixPath(rel).parts):
        raise KnowledgeError(f"{relative}: hidden folders and files cannot be used")
    return path, rel


def _folder(base: str, relative: str) -> tuple[str, str]:
    path, rel = _resolve(base, relative)
    if not os.path.isdir(path):
        raise KnowledgeError(f"knowledge folder {relative}: not a folder in {base}")
    return path, rel


def _visible(path: Path) -> bool:
    return not path.name.startswith((".", "_"))


def _read(path: Path) -> str:
    if path.stat().st_size > MAX_NOTE_BYTES:
        raise KnowledgeError(f"{path.name} is larger than {MAX_NOTE_BYTES // 1024} KiB")
    return path.read_text(encoding="utf-8", errors="replace")
