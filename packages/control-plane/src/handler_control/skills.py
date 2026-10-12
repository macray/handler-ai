"""Skills — the skill library (D.17): `~/.config/handler-ai/skills/<name>/`, a folder with a
SKILL.md (agentskills.io: a YAML frontmatter with `name`, the folder's name, and `description`, then
the instructions) and any other files (scripts, references, assets). Written through the Control API
(file by file, or a whole skill from an archive) or by hand.

Which projects give a skill to all their agents is theirs (projects.py, `skills`); which
skills an agent uses, the agent's. An agent's skills are mounted read-only where its harness
looks for skills, like addons' (launcher.py, render).

    parse / load / get / load_all   read the library
    digest                          what a skill's files are now, as one hash (D.17)
    copy                            a skill's files into a session's folder (D.18)
    save                            a skill's SKILL.md (a new name renames the skill)
    read_file / write_file / ...    its other files, never outside its folder
    pack / unpack / install         a skill as a zip archive (`.skill` / `.zip`), out and in
    from_folder                     a skill out of a folder (a session's, D.18), as an archive
"""

import hashlib
import io
import re
import secrets
import shutil
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from handler_contracts import MAX_SKILL_ARCHIVE_BYTES, MAX_SKILL_FILE_BYTES

SKILL_FILE = "SKILL.md"
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")  # SkillName
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(\r?\n|\Z)", re.S)
MAX_FILES = 500  # in a skill (listed, imported)
JUNK = ("__MACOSX", ".DS_Store")  # left by archivers, not imported


class SkillError(ValueError):
    pass


@dataclass(frozen=True)
class SkillFile:
    path: str  # relative to the skill's folder
    size: int
    executable: bool


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    path: Path
    description: str | None = None
    files: list[SkillFile] = field(default_factory=list)  # besides its SKILL.md
    error: str | None = None  # set when the skill is invalid (no agent can use it)


def parse(content: str) -> tuple[str, str]:
    """(name, description) of a SKILL.md; SkillError when it does not follow the format."""
    match = FRONTMATTER.match(content)
    if match is None:
        raise SkillError("a SKILL.md starts with a YAML frontmatter between '---' lines")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        raise SkillError(f"its frontmatter is not YAML: {e}") from None
    if not isinstance(meta, dict):
        raise SkillError("its frontmatter is not a mapping (name: …, description: …)")
    name, description = meta.get("name"), meta.get("description")
    if not isinstance(name, str) or len(name) > 64 or not NAME.fullmatch(name):
        raise SkillError("name: 1 to 64 lowercase letters, digits and single hyphens")
    if not isinstance(description, str) or not 0 < len(description.strip()) <= 1024:
        raise SkillError("description: 1 to 1024 characters (what it does, when to use it)")
    return name, description.strip()


def hidden(path: str) -> bool:
    return any(part.startswith(".") for part in path.split("/"))


def files_of(folder: Path) -> list[SkillFile]:
    """Its regular files but SKILL.md and hidden ones (symbolic links are not followed, nor
    listed)."""
    found = []
    for p in sorted(folder.rglob("*")):
        if p.is_symlink() or not p.is_file() or p == folder / SKILL_FILE:
            continue
        if hidden(p.relative_to(folder).as_posix()):
            continue
        info = p.stat()
        path = p.relative_to(folder).as_posix()
        found.append(SkillFile(path, info.st_size, executable(info.st_mode)))
    return found[:MAX_FILES]


def executable(mode: int) -> bool:
    return bool(mode & stat.S_IXUSR)


def load(path: Path) -> LoadedSkill:
    name = path.name
    files = files_of(path)
    try:
        declared, description = parse((path / SKILL_FILE).read_text())
    except OSError:
        return LoadedSkill(name, path, None, files, f"no {SKILL_FILE} in {path}")
    except (SkillError, UnicodeDecodeError) as e:
        return LoadedSkill(name, path, None, files, str(e))
    if declared != name:
        error = f"its {SKILL_FILE} is named '{declared}', its folder '{name}'"
        return LoadedSkill(name, path, description, files, error)
    return LoadedSkill(name, path, description, files)


def digest(folder: Path) -> str:
    """ "sha256:…" of a skill's SKILL.md and other files (paths, executable bits, contents): what
    a review saw (D.17)."""
    h = hashlib.sha256()
    entries = [SkillFile(SKILL_FILE, 0, False), *files_of(folder)]
    for f in entries:
        try:
            data = (folder / f.path).read_bytes()
        except OSError:
            data = b""
        h.update(f"{f.path}\0{int(f.executable)}\0{len(data)}\0".encode())
        h.update(data)
    return "sha256:" + h.hexdigest()


def copy(folder: Path, target: Path) -> None:
    """A skill's SKILL.md and other files into `target` (an existing folder), with their
    executable bits: no hidden files, no symbolic links."""
    for f in [SkillFile(SKILL_FILE, 0, False), *files_of(folder)]:
        source, dest = folder / f.path, target / f.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write(dest, source.read_bytes(), executable(source.stat().st_mode))


def get(directory: Path, name: str) -> LoadedSkill:
    """A skill by name; unknown → LoadedSkill with an error (the caller decides)."""
    path = directory / name
    if not NAME.fullmatch(name) or not path.is_dir():
        return LoadedSkill(name, path, error=f"unknown skill '{name}' (no {path})")
    return load(path)


def exists(directory: Path, name: str) -> bool:
    return bool(NAME.fullmatch(name)) and (directory / name).is_dir()


def load_all(directory: Path) -> list[LoadedSkill]:
    if not directory.is_dir():
        return []
    return [load(p) for p in sorted(directory.iterdir()) if p.is_dir() and NAME.fullmatch(p.name)]


def content(directory: Path, name: str) -> str | None:
    try:
        return (directory / name / SKILL_FILE).read_text()
    except (OSError, UnicodeDecodeError):
        return None


def save(directory: Path, text: str, old: str | None = None) -> str:
    """Write a skill's SKILL.md (its name is the SKILL.md's); `old`: the skill it replaces,
    renamed with its other files when the name changes (the caller checked the new name is
    free). Returns the name."""
    name, _ = parse(text)
    folder = directory / name
    if old is not None and old != name:
        (directory / old).rename(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _write(folder / SKILL_FILE, text.encode(), False)
    return name


def delete(directory: Path, name: str) -> None:
    shutil.rmtree(directory / name)


def paths(directory: Path, names: list[str]) -> list[str]:
    """The folders of an agent's skills, to mount (each must be valid)."""
    found = []
    for name in names:
        skill = get(directory, name)
        if skill.error:
            raise SkillError(f"skill '{name}': {skill.error}")
        found.append(str(skill.path))
    return found


# ── its files ───────────────────────────────────────────────────────────


def relative(path: str) -> str:
    """A file's path in a skill: relative, no '..', no empty or hidden part; SkillError else."""
    parts = path.split("/")
    if (
        not path
        or len(path) > 512
        or "\x00" in path
        or "\\" in path
        or any(p in ("", ".", "..") or p.startswith(".") for p in parts)
    ):
        raise SkillError(f"'{path}': a path relative to the skill's folder, without hidden parts")
    return path


def _inside(folder: Path, path: str) -> Path:
    """The file `path` of the skill in `folder`, through no symbolic link."""
    target = folder / relative(path)
    current = folder
    for part in PurePosixPath(path).parts:
        current = current / part
        if current.is_symlink():
            raise SkillError(f"'{path}': a symbolic link, changed by hand only")
    return target


def read_file(directory: Path, name: str, path: str) -> tuple[bytes, bool]:
    """A file's content and whether it is executable; FileNotFoundError when missing."""
    target = _inside(directory / name, path)
    if not target.is_file():
        raise FileNotFoundError(path)
    return target.read_bytes(), executable(target.stat().st_mode)


def write_file(directory: Path, name: str, path: str, data: bytes, is_executable: bool) -> None:
    """Create or replace a file of the skill (not its SKILL.md: `save`)."""
    if path == SKILL_FILE:
        raise SkillError(f"its {SKILL_FILE} is saved with the skill")
    if len(data) > MAX_SKILL_FILE_BYTES:
        raise SkillError(f"'{path}': larger than {MAX_SKILL_FILE_BYTES} bytes")
    target = _inside(directory / name, path)
    if target.is_dir():
        raise SkillError(f"'{path}' is a folder")
    if not target.exists() and len(files_of(directory / name)) >= MAX_FILES:
        raise SkillError(f"a skill has at most {MAX_FILES} files")
    target.parent.mkdir(parents=True, exist_ok=True)
    _write(target, data, is_executable)


def delete_file(directory: Path, name: str, path: str) -> None:
    """Remove a file (not its SKILL.md), and the folders it leaves empty."""
    if path == SKILL_FILE:
        raise SkillError(f"a skill keeps its {SKILL_FILE}")
    folder = directory / name
    target = _inside(folder, path)
    if not target.is_file():
        raise FileNotFoundError(path)
    target.unlink()
    parent = target.parent
    while parent != folder and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def _write(target: Path, data: bytes, is_executable: bool) -> None:
    tmp = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_bytes(data)
    tmp.chmod(0o755 if is_executable else 0o644)
    tmp.replace(target)


# ── as an archive ───────────────────────────────────────────────────────


def pack(directory: Path, name: str) -> bytes:
    """The skill as a zip archive: its folder, `<name>/…`, with the executable bits."""
    folder = directory / name
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for f in [SkillFile(SKILL_FILE, 0, False), *files_of(folder)]:
            source = folder / f.path
            if not source.is_file():
                continue
            info = zipfile.ZipInfo(f"{name}/{f.path}")
            info.external_attr = (stat.S_IFREG | (source.stat().st_mode & 0o777)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, source.read_bytes())
    return buffer.getvalue()


def unpack(data: bytes, folder: str | None = None) -> tuple[str, dict[str, tuple[bytes, bool]]]:
    """A skill from a zip archive (`.skill`, `.zip`): its SKILL.md at the root or in a folder
    (the shallowest one, which must be unique), and the files next to it → (its name, its
    files). `folder`: the archive is a repository's (one top folder, as GitHub makes them) and
    the skill is taken from that folder of it ("": the repository's root). Symbolic links,
    hidden files and archiver junk are left out; SkillError when it is not a skill."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SkillError("not a zip archive") from None
    with archive:
        entries = [
            i
            for i in archive.infolist()
            if not i.is_dir()
            and not stat.S_ISLNK(i.external_attr >> 16)
            and not any(part in JUNK for part in i.filename.split("/"))
        ]
        if folder is not None:
            inside = f"{folder.strip('/')}/" if folder.strip("/") else ""
            entries = [i for i in entries if i.filename.partition("/")[2].startswith(inside)]
            if not entries:
                raise SkillError(f"no folder '{folder}' in the repository")
        found = [i.filename for i in entries if PurePosixPath(i.filename).name == SKILL_FILE]
        if not found:
            raise SkillError(f"no {SKILL_FILE} in the archive")
        depth = min(f.count("/") for f in found)
        shallowest = [f for f in found if f.count("/") == depth]
        if len(shallowest) > 1:
            listed = ", ".join(sorted(shallowest))
            raise SkillError(
                f"several skills in the archive ({listed}): import one at a time (from a"
                " repository, the URL of one skill's folder)"
            )
        base = shallowest[0][: -len(SKILL_FILE)]
        chosen = [
            i
            for i in entries
            if i.filename.startswith(base) and not hidden(i.filename[len(base) :])
        ]
        if len(chosen) > MAX_FILES:
            raise SkillError(f"a skill has at most {MAX_FILES} files")
        if sum(i.file_size for i in chosen) > MAX_SKILL_ARCHIVE_BYTES:
            raise SkillError(f"it unpacks to more than {MAX_SKILL_ARCHIVE_BYTES} bytes")
        files: dict[str, tuple[bytes, bool]] = {}
        for info in chosen:
            path = relative(info.filename[len(base) :])
            if info.file_size > MAX_SKILL_FILE_BYTES:
                raise SkillError(f"'{path}': larger than {MAX_SKILL_FILE_BYTES} bytes")
            files[path] = (archive.read(info), executable(info.external_attr >> 16))
    try:
        name, _ = parse(files[SKILL_FILE][0].decode())
    except UnicodeDecodeError:
        raise SkillError(f"its {SKILL_FILE} is not UTF-8 text") from None
    return name, files


def from_folder(folder: Path) -> tuple[str, dict[str, tuple[bytes, bool]]]:
    """A skill from a folder (a session's, D.18): as from an archive of it, with the same rules
    (the shallowest SKILL.md, no hidden files nor symbolic links, the same limits)."""
    buffer, total, count = io.BytesIO(), 0, 0
    with zipfile.ZipFile(buffer, "w") as archive:
        for p in sorted(folder.rglob("*")):
            path = p.relative_to(folder).as_posix()
            if p.is_symlink() or not p.is_file() or hidden(path):
                continue
            total, count = total + p.stat().st_size, count + 1
            if total > MAX_SKILL_ARCHIVE_BYTES or count > MAX_FILES * 4:
                raise SkillError(f"more than {MAX_SKILL_ARCHIVE_BYTES} bytes in the folder")
            info = zipfile.ZipInfo(path)
            info.external_attr = (stat.S_IFREG | p.stat().st_mode & 0o777) << 16
            archive.writestr(info, p.read_bytes())
    return unpack(buffer.getvalue())


def install(directory: Path, name: str, files: dict[str, tuple[bytes, bool]]) -> None:
    """Put an unpacked skill in the library, replacing the folder of the same name (if any)
    at once."""
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / f".import-{secrets.token_hex(4)}"
    try:
        for path, (data, is_executable) in files.items():
            target = staging / path
            target.parent.mkdir(parents=True, exist_ok=True)
            _write(target, data, is_executable)
        folder = directory / name
        old = directory / f".replaced-{secrets.token_hex(4)}"
        if folder.exists():
            folder.rename(old)
        staging.rename(folder)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
