"""The daemon's own files: writing them whole, atomically, readable by the user only (0600), and
saying in one line why one is invalid."""

import io
import os
import shutil
import zipfile
from pathlib import Path

from pydantic import ValidationError


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    tmp.replace(path)


def describe(error: ValidationError) -> str:
    """One readable line: `field.path: message; …`."""
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'file'}: {e['msg']}" for e in error.errors()
    )


def unzip(data: bytes, target: Path, max_files: int, max_bytes: int) -> None:
    """A zip unpacked into `target` (made). ValueError, in the person's words: not a zip, a path
    leaving the folder, a link (an export holds none), more than `max_files` files or
    `max_bytes` bytes once unpacked."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("not a zip file") from None
    with zf:
        infos = zf.infolist()
        if len(infos) > max_files:
            raise ValueError(f"more than {max_files} files")
        if sum(i.file_size for i in infos) > max_bytes:
            raise ValueError(f"more than {max_bytes // 2**20} MiB once unpacked")
        target.mkdir(parents=True)
        for info in infos:
            parts = info.filename.replace("\\", "/").split("/")
            if info.filename.startswith("/") or ".." in parts:
                raise ValueError(f"{info.filename}: a path leaving its folder")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"{info.filename} is a link: an export holds none")
            path = target.joinpath(*[p for p in parts if p])
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, path.open("wb") as out:
                shutil.copyfileobj(src, out)
            if (info.external_attr >> 16) & 0o111:
                path.chmod(0o755)


def zipped(folder: Path) -> bytes:
    """`folder`'s files as a zip, their paths relative to it."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(folder).as_posix())
    return buffer.getvalue()
