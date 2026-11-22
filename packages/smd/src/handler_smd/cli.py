"""`handler-smd`: check, format, read and write structured markdown (SMD spec 6, 7, 8, 10.3).

The schemas folder is `--schemas`, else `$SMD_SCHEMAS` (what Handler sets in a sandbox).
Exit codes: 0; 1 when a diagnostic is an error (`check`, `write`), or for what cannot be done
(JSON that is not a document, an unknown schema); 2 for a wrong command line.
"""

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from handler_smd.agent import prompt, template, to_json_schema
from handler_smd.models import Diagnostic, Document, Severity
from handler_smd.scanner import check, check_file, documents, fmt, load_schemas, write

SCHEMAS_ENV = "SMD_SCHEMAS"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    schemas = args.schemas or (
        Path(os.environ[SCHEMAS_ENV]) if os.environ.get(SCHEMAS_ENV) else None
    )
    if wrong := _missing(args, schemas):
        print(f"handler-smd: {wrong}", file=sys.stderr)
        return 2
    if args.command == "schema":
        return _schema(args.view, args.id, schemas, args.schema)
    path: Path = args.path
    match args.command:
        case "check":
            return _check(path, schemas, args.schema, as_json=args.json)
        case "fmt":
            for changed in fmt(path, schemas, args.schema):
                print(changed)
            return 0
        case "parse":
            return _parse(path, schemas, args.schema)
        case _:  # write
            return _write(path, schemas, args.schema, sys.stdin.read())


def _missing(args: argparse.Namespace, schemas: Path | None) -> str | None:
    """What the command line names but does not exist."""
    given = [(schemas, "schemas folder"), (args.schema, "schema file")]
    if args.command != "schema":
        given.append((args.path.parent if args.command == "write" else args.path, "file or folder"))
    for path, what in given:
        if path is not None and not path.exists():
            return f"{path}: no such {what}"
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handler-smd",
        description="Structured markdown: check documents against their schemas, format them, "
        "read them as JSON, write them from JSON.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, about, path_help in [
        ("check", "report every problem of the documents and of the schemas", None),
        ("fmt", "rewrite the documents in their canonical form; prints those it changed", None),
        ("parse", "print one document as JSON, its sections keyed by its schema", "a file"),
        ("write", "write a document from its JSON on standard input, then check it", "a file"),
        ("schema", "a schema as an agent or a person reads it", None),
    ]:
        command = commands.add_parser(name, help=about, description=about)
        if name == "schema":
            command.add_argument(
                "view",
                choices=["export", "template", "prompt"],
                help="its JSON Schema, a blank document, an agent's instructions",
            )
            command.add_argument("id", help="its $id, such as decision-log@1")
        else:
            command.add_argument(
                "path", type=Path, help=path_help or "a markdown file, or a folder of them"
            )
        command.add_argument(
            "--schemas", type=Path, help=f"the schemas folder (default: ${SCHEMAS_ENV})"
        )
        command.add_argument(
            "--schema", type=Path, help="a schema file being written: replaces its $id this time"
        )
        if name == "check":
            command.add_argument("--json", action="store_true", help="the diagnostics as JSON")
    return parser


def _parse(path: Path, schemas: Path | None, draft: Path | None) -> int:
    if not path.is_file():
        print(f"handler-smd: {path}: parse reads one file", file=sys.stderr)
        return 2
    index, _ = load_schemas(schemas, draft)
    result = check_file(path, index)
    if result.document is None:
        print(f"handler-smd: {result.diagnostics[0].message}", file=sys.stderr)
        return 1
    print(result.document.model_dump_json(indent=2))
    return 0


def _write(path: Path, schemas: Path | None, draft: Path | None, given: str) -> int:
    """An agent's JSON to the file's canonical markdown (spec 8): refused, the file untouched,
    when it is not a document, or when its fields changed and the file's frontmatter holds more
    than they say (7.1); written, then checked, when it is (with its problems: it stays to be
    completed). The file's frontmatter is kept as written when its fields are the same."""
    try:
        document = Document.model_validate_json(given)
    except ValidationError as error:
        print("handler-smd: the JSON is not a document:", file=sys.stderr)
        for e in error.errors():
            where = ".".join(str(part) for part in e["loc"]) or "(the JSON)"
            print(f"  {where}: {e['msg']}", file=sys.stderr)
        return 1
    try:
        diagnostics = write(path, document, schemas, draft)
    except ValueError as error:
        print(f"handler-smd: {error}", file=sys.stderr)
        return 1
    _print_grouped(diagnostics, 1)
    return 1 if any(d.severity == Severity.ERROR for d in diagnostics) else 0


def _schema(view: str, schema_id: str, schemas: Path | None, draft: Path | None) -> int:
    index, _ = load_schemas(schemas, draft)
    typedef = index.schemas.get(schema_id)
    if typedef is None:
        where = index.broken.get(schema_id)
        reason = f"{where} cannot be used (handler-smd check says why)" if where else "not found"
        print(f"handler-smd: {schema_id}: {reason}", file=sys.stderr)
        return 1
    match view:
        case "export":
            print(json.dumps(to_json_schema(typedef), indent=2, ensure_ascii=False))
        case "template":
            print(template(typedef), end="")
        case _:
            print(prompt(typedef), end="")
    return 0


def _check(path: Path, schemas: Path | None, draft: Path | None, *, as_json: bool) -> int:
    diagnostics = check(path, schemas, draft)
    if as_json:
        print(json.dumps([d.model_dump(mode="json") for d in diagnostics], indent=2))
    else:
        _print_grouped(diagnostics, len(documents(path)))
    return 1 if any(d.severity == Severity.ERROR for d in diagnostics) else 0


def _print_grouped(diagnostics: list[Diagnostic], files: int) -> None:
    current = None
    for d in diagnostics:
        if d.file != current:
            if current is not None:
                print()
            print(d.file)
            current = d.file
        print(f"  {d.line}  {d.severity:<7}  {d.path}  {d.code}  {d.message}")
    counts = Counter(d.severity for d in diagnostics)
    if diagnostics:
        print()
    print(
        f"{_count(counts[Severity.ERROR], 'error')}, {_count(counts[Severity.WARNING], 'warning')}, "
        f"{counts[Severity.INFO]} info in {_count(files, 'file')}"
    )


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
