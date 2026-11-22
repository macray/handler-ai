"""Structured markdown for an app's code (H.9, D.29): what `handler.sock` answers on `/smd/*`
to an app whose manifest declares `schemas`, with `handler_smd`, the format's one
implementation (an app's backend is Bun: no second one to drift from the spec).

    POST /smd/parse {path}            → 200 {document?, diagnostics} · 400 · 403 · 404
    POST /smd/check {path}            → 200 {diagnostics} · 400 · 403 · 404
    POST /smd/write {path, document}  → 200 {diagnostics} · 400 · 403 · 404 · 409

`path` is absolute, inside a folder (or the file) given to one of the backend's files needs,
`write` only in one given read-write; nothing is read or written outside them nor through a link
(rule `app-sock.smd-only-in-its-folders`: `handler_smd.scanner` confined `within` the folder).
Its documents are read with the app's own schemas, `schemas/` of the version running.
"""

import asyncio
import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from handler_contracts import is_within
from handler_smd.models import Document
from handler_smd.scanner import check, check_file, load_schemas, write

SCHEMAS_DIR = "schemas"  # in an app's folder: `<$id>.schema.json` for each of its `schemas`
SUFFIX = ".schema.json"
CALLS = ("parse", "check", "write")
# what the confined reading refuses: a link (ELOOP, ENOTDIR on a part), not a regular file
REFUSED = (errno.ELOOP, errno.ENOTDIR, errno.EISDIR, None)


def shipped_problem(folder: Path, ids: list[str]) -> str | None:
    """Why the app's `schemas/` does not hold exactly the schemas it declares, each usable (its
    `extends` among them); None when it does."""
    shipped = folder / SCHEMAS_DIR
    files = sorted(p.name for p in shipped.glob(f"*{SUFFIX}")) if shipped.is_dir() else []
    declared = sorted(f"{i}{SUFFIX}" for i in ids)
    if missing := sorted(set(declared) - set(files)):
        return f"schemas: {SCHEMAS_DIR}/{missing[0]} does not exist"
    if extra := sorted(set(files) - set(declared)):
        return f"{SCHEMAS_DIR}/{extra[0]} is not declared in schemas"
    if not files:
        return None
    index, problems = load_schemas(shipped)
    for problem in problems:
        return f"{os.path.relpath(problem.file, folder)}: {problem.message}"
    if wrong := next((i for i in ids if i not in index.schemas), None):
        return f"{SCHEMAS_DIR}/{wrong}{SUFFIX}: its `$id` is not {wrong}"
    return None


@dataclass(frozen=True)
class AppSmd:
    """One running backend's `/smd/*`: its version's schemas, the folders it was given (need,
    path, writable), as its sandbox mounts them."""

    schemas: Path
    folders: list[tuple[str, str, bool]]

    async def answer(
        self, method: str, path: str, payload: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        call = path.removeprefix("/smd/")
        if method != "POST" or call not in CALLS:
            return 404, {"error": "POST /smd/parse, POST /smd/check, POST /smd/write"}
        body = payload or {}
        given = body.get("path")
        if not isinstance(given, str) or not os.path.isabs(given):
            return 400, {"error": "path: an absolute path"}
        where = self.locate(given, write=call == "write")
        if isinstance(where, str):
            return 403, {"error": where}
        folder, file = where
        do = {"parse": self.parse, "check": self.check, "write": self.write}[call]
        try:
            return await asyncio.to_thread(do, folder, file, body)
        except FileNotFoundError:
            return 404, {"error": f"{file}: no such file or folder"}
        except OSError as e:
            if e.errno not in REFUSED:
                raise
            return 403, {"error": f"{file}: a link or not a file: never followed"}

    def locate(self, given: str, *, write: bool) -> tuple[Path, Path] | str:
        """The folder given that holds `given` and the path normalized (`..` taken away), or
        why it is refused: outside them, through a link, read-only for a write."""
        path = os.path.normpath(given)
        for need, root, writable in self.folders:
            if not is_within(path, root):
                continue
            if write and not writable:
                return f"{path}: the folder given for {need} is read-only"
            parts = Path(path).relative_to(root).parts
            for n in range(1, len(parts) + 1):
                part = Path(root, *parts[:n])
                try:
                    if stat.S_ISLNK(os.lstat(part).st_mode):
                        return f"{part} is a link: never followed"
                except FileNotFoundError:
                    break
            return Path(root), Path(path)
        return f"{path} is not in a folder given to the app"

    def parse(self, folder: Path, file: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if file.is_dir():
            return 400, {"error": f"{file}: parse reads one file"}
        index, _ = load_schemas(self.schemas)
        result = check_file(file, index, within=folder)
        answer: dict[str, Any] = {"diagnostics": _dump(result.diagnostics)}
        if result.document is not None:
            answer["document"] = result.document.model_dump(mode="json")
        return 200, answer

    def check(self, folder: Path, file: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if not file.exists():
            raise FileNotFoundError(file)
        return 200, {"diagnostics": _dump(check(file, self.schemas, within=folder))}

    def write(self, folder: Path, file: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            document = Document.model_validate(body.get("document"))
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(x) for x in first["loc"]) or "(the JSON)"
            return 400, {"error": f"document: {where}: {first['msg']}"}
        if file.is_dir():
            return 400, {"error": f"{file}: write writes one file"}
        try:
            diagnostics = write(file, document, self.schemas, within=folder)
        except ValueError as e:  # its frontmatter would lose what it holds, not UTF-8
            return 409, {"error": str(e)}
        return 200, {"diagnostics": _dump(diagnostics)}


def _dump(diagnostics: list) -> list[dict[str, Any]]:
    return [d.model_dump(mode="json") for d in diagnostics]
