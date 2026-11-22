"""The scanner (SMD spec 5.3, 6): with the CLI, the only module that reads or writes files.

It reads one schemas folder (its `*.schema.json`) and the markdown files of a folder or a file,
then runs the pure core on them: parse, resolve, validate; then follows references between
documents (`broken-ref`), `fmt` writes back what changes and `write` a document given as data.

Confined to a folder (`within`, what handlerd gives an app's code): nothing is read or written
outside it, nor through a link (each part of a path opened without following one), nor what is
not a regular file; a reference leading out of it is `broken-ref`.
"""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from handler_smd.models import Diagnostic, Document, Severity
from handler_smd.parser import frontmatter_block, parse
from handler_smd.renderer import render
from handler_smd.resolver import SchemaFile, SchemaIndex, index_schemas, resolve_schema
from handler_smd.schema import TypeDefinition, parse_typedef
from handler_smd.validator import REF, validate

SCHEMA_FILES = "*.schema.json"


@dataclass(frozen=True)
class Checked:
    file: Path
    document: Document | None  # None: the file could not be read; typed when its schema resolved
    typedef: TypeDefinition | None
    diagnostics: list[Diagnostic]


def documents(root: Path, within: Path | None = None) -> list[Path]:
    """`root` itself, or its markdown files, in its folders but hidden ones (`.git`…); confined
    `within` a folder, no link is followed nor listed."""
    if within is not None:
        if not root.is_dir() or root.is_symlink():
            return [root]
        found = []
        for folder, dirs, names in os.walk(root):  # never into a link to a folder
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            found += [
                Path(folder, n)
                for n in names
                if n.endswith(".md") and not n.startswith(".") and not Path(folder, n).is_symlink()
            ]
        return sorted(found)
    if root.is_file():
        return [root]
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.is_file() and not any(p.startswith(".") for p in path.relative_to(root).parts)
    )


def load_schemas(
    folder: Path | None, draft: Path | None = None
) -> tuple[SchemaIndex, list[Diagnostic]]:
    """The folder's schemas indexed; a draft schema file, if given, replaces its `$id` there for
    this run only (to test it, spec 5.3)."""
    found: list[Diagnostic] = []
    files: list[SchemaFile] = []
    paths = sorted(folder.glob(SCHEMA_FILES)) if folder is not None else []
    for path in [*paths, *([draft] if draft else [])]:
        text = _read(path)
        if isinstance(text, Diagnostic):
            found.append(text)
            continue
        typedef, problems = parse_typedef(text, str(path))
        found += problems
        if typedef is not None:
            if path == draft:
                files = [f for f in files if f.typedef.id != typedef.id]
            files.append(SchemaFile(file=str(path), typedef=typedef))
    index, problems = index_schemas(files)
    return index, found + problems


def check_file(path: Path, index: SchemaIndex, within: Path | None = None) -> Checked:
    text = _read(path, within)
    if isinstance(text, Diagnostic):
        return Checked(path, None, None, [text])
    parsed = parse(text, str(path))
    typedef, found = resolve_schema(parsed.document, index, str(path))
    if typedef is None:
        return Checked(path, parsed.document, None, parsed.diagnostics + found)
    typed, problems = validate(parsed.document, typedef, str(path))
    return Checked(path, typed, typedef, parsed.diagnostics + found + problems)


def check(
    root: Path, schemas: Path | None, draft: Path | None = None, within: Path | None = None
) -> list[Diagnostic]:
    """Every diagnostic of the schemas and of the documents under `root`, sorted (spec 6)."""
    index, found = load_schemas(schemas, draft)
    checked = [check_file(path, index, within) for path in documents(root, within)]
    for result in checked:
        found += result.diagnostics
    found += _broken_refs(checked, within)
    return sorted(found, key=lambda d: (d.file, d.line, d.path))


def write(
    path: Path,
    document: Document,
    schemas: Path | None,
    draft: Path | None = None,
    within: Path | None = None,
) -> list[Diagnostic]:
    """A document given as data (an agent's JSON, spec 8) written to `path` in its canonical
    form, typed by its schema when it resolves, then checked: its diagnostics (written with its
    problems: it stays to be completed). The file's frontmatter is kept as written while its
    fields are the same (7.1). ValueError, the file untouched, when it cannot be rendered (its
    fields changed and the frontmatter holds more than they say, or the file is not UTF-8);
    OSError when, confined, it cannot be opened (a link on the way, not a regular file)."""
    index, _ = load_schemas(schemas, draft)
    typedef, _ = resolve_schema(document, index, str(path))
    if typedef is not None:
        document, _ = validate(document, typedef, str(path))
    if within is None:
        written = path.read_text(encoding="utf-8") if path.is_file() else None
    else:
        written = _confined_text(path, within, create=True)
    text = render(document, typedef, frontmatter_block(written) if written else None)
    if within is None:
        path.write_text(text, encoding="utf-8")
    else:
        _confined_write(path, within, text)
    return check(path, schemas, draft, within)


def fmt(root: Path, schemas: Path | None, draft: Path | None = None) -> list[Path]:
    """Each document under `root` rewritten canonically (spec 7), with its schema when it
    resolves, its frontmatter as written (7.1); only those that change are written. Returns
    them."""
    index, _ = load_schemas(schemas, draft)
    changed: list[Path] = []
    for path in documents(root):
        result = check_file(path, index)
        if result.document is None:
            continue
        written = path.read_text(encoding="utf-8")
        text = render(result.document, result.typedef, frontmatter_block(written))
        if text != written:
            path.write_text(text, encoding="utf-8")
            changed.append(path)
    return changed


def _broken_refs(checked: list[Checked], within: Path | None) -> list[Diagnostic]:
    """Each `ref` value must name a file that exists and, after `#`, one of its items (spec 4:
    a path relative to the document's own file)."""
    slugs: dict[str, set[str]] = {
        os.path.normpath(r.file): {i.slug for i in r.document.items}
        for r in checked
        if r.document is not None
    }
    found: list[Diagnostic] = []
    for result in checked:
        if result.document is None or result.typedef is None:
            continue
        for index, item in enumerate(result.document.items):
            for key, definition in result.typedef.item.fields.items():
                if "ref" not in (definition.type, definition.of):
                    continue
                value = item.fields.get(key)
                for ref in value if isinstance(value, list) else [value]:
                    if not isinstance(ref, str) or not REF.match(ref):
                        continue  # absent, or invalid: the validator said so
                    problem = _ref_problem(result.file, ref, slugs, within)
                    if problem is not None:
                        found.append(
                            Diagnostic(
                                file=str(result.file),
                                line=item.field_lines.get(key, item.line),
                                path=f"items[{index}].fields.{key}",
                                severity=Severity.ERROR,
                                code="broken-ref",
                                message=f"{key}: {problem}",
                            )
                        )
    return found


def _ref_problem(
    file: Path, ref: str, slugs: dict[str, set[str]], within: Path | None
) -> str | None:
    target, _, slug = ref.partition("#")
    # by its text: `sub/../other.md` is other.md even when sub does not exist
    path = os.path.normpath(file.parent / target) if target else os.path.normpath(file)
    if path not in slugs:
        if within is not None:
            if not _inside(Path(path), within):
                return f"{target} is outside the folder"
            try:
                text = _read(Path(path), within)
            except FileNotFoundError:
                return f"{target} does not exist"
            except OSError:
                return f"{target} is a link or not a file: never followed here"
        elif not Path(path).is_file():
            return f"{target} does not exist"
        else:
            text = _read(Path(path))
        slugs[path] = (
            set()
            if isinstance(text, Diagnostic)
            else {i.slug for i in parse(text, path).document.items}
        )
    if slug and slug not in slugs[path]:
        return f"no item #{slug} in {target or 'this document'}"
    return None


def _read(path: Path, within: Path | None = None) -> str | Diagnostic:
    try:
        if within is not None:
            text = _confined_text(path, within, create=False)
            assert text is not None
            return text
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        return Diagnostic(
            file=str(path),
            line=1,
            path="",
            severity=Severity.ERROR,
            code="invalid-encoding",
            message=f"not UTF-8 text: {error.reason} at byte {error.start}",
        )


def _inside(path: Path, within: Path) -> bool:
    return path == within or within in path.parents


def _confined_open(path: Path, within: Path, flags: int) -> int:
    """`path` (absolute, normalized) opened from `within` one part at a time, never through a
    link; what it opens must be a regular file (never a pipe that would block). OSError: it
    cannot be (outside, a link, not a file, missing without O_CREAT)."""
    if not _inside(path, within):
        raise OSError(f"{path} is outside {within}")
    parts = path.relative_to(within).parts
    flags |= os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    if not parts:  # `within` is the file itself
        fd = os.open(within, flags)
    else:
        folder = os.open(within, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in parts[:-1]:
                inner = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=folder
                )
                os.close(folder)
                folder = inner
            fd = os.open(parts[-1], flags, 0o644, dir_fd=folder)
        finally:
            os.close(folder)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError(f"{path} is not a file")
    return fd


def _confined_text(path: Path, within: Path, *, create: bool) -> str | None:
    """Its text read from `within` (UnicodeDecodeError when not UTF-8); None when it does not
    exist and `create` (to be written)."""
    try:
        fd = _confined_open(path, within, os.O_RDONLY)
    except FileNotFoundError:
        if create:
            return None
        raise
    with os.fdopen(fd, "rb") as f:
        return f.read().decode("utf-8")


def _confined_write(path: Path, within: Path, text: str) -> None:
    """Written in place (a file given alone is that very file: renaming over it would leave
    the one mounted elsewhere unchanged)."""
    fd = _confined_open(path, within, os.O_WRONLY | os.O_CREAT)
    with os.fdopen(fd, "wb") as f:
        f.truncate(0)
        f.write(text.encode("utf-8"))
