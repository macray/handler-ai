"""The daemon's own files: writing them whole, atomically, readable by the user only (0600), and
saying in one line why one is invalid."""

import os
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
