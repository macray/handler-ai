"""The Library's schemas (D.29, structured knowledge): `~/.config/handler-ai/schemas/
<$id>.schema.json`, one file per `$id`, in the SMD format's schema vocabulary (`handler_smd`).
One place only, found by `$id` alone: nothing shadows anything. Added by the person (Library →
Schemas, `handler schema add`) or with an agent that ships one (`schemas/` next to its `skills/`,
definitions.py); never by an agent from its sandbox.

    load_all / get          the Library, each schema with its problem if no agent can use it
    add                     a schema's text into the Library: one of that `$id` already there and
                            different is refused unless replaced; the same is kept
    remove                  a schema's file
    files                   what an agent gets: its schemas and those they extend, as text
"""

import os
from dataclasses import dataclass
from pathlib import Path

from handler_smd.resolver import SchemaFile, index_schemas
from handler_smd.schema import SCHEMA_ID, TypeDefinition, parse_typedef

SUFFIX = ".schema.json"


class SchemaError(ValueError):
    """A schema cannot be added or used: not a schema, unknown, unusable."""


class SchemaClashError(SchemaError):
    """Another schema with that `$id` is in the Library: the person decides (replace or keep)."""


@dataclass(frozen=True)
class LoadedSchema:
    id: str  # its `$id`, or the file's name when it cannot be read
    path: Path
    typedef: TypeDefinition | None
    error: str | None  # why no agent can use it


def path_of(folder: Path, schema_id: str) -> Path:
    if not SCHEMA_ID.match(schema_id):
        raise SchemaError(f"{schema_id!r} is not a schema's `<name>@<version>`")
    return folder / f"{schema_id}{SUFFIX}"


def parse(text: str, file: str) -> TypeDefinition:
    """A schema file's text, checked by the format; SchemaError saying why not."""
    typedef, problems = parse_typedef(text, file)
    if typedef is None:
        raise SchemaError("; ".join(f"{p.path or 'schema'}: {p.message}" for p in problems))
    return typedef


def load_all(folder: Path) -> list[LoadedSchema]:
    """Every schema of the Library, sorted by `$id`. A file that is not a schema, named after
    another `$id`, or whose `extends` is not there or unusable, says why (its error)."""
    read: list[LoadedSchema] = []
    for path in sorted(folder.glob(f"*{SUFFIX}")) if folder.is_dir() else []:
        name = path.name.removesuffix(SUFFIX)
        try:
            typedef = parse(_read(path), path.name)
        except SchemaError as e:
            read.append(LoadedSchema(name, path, None, str(e)))
            continue
        if typedef.id != name:
            error = f"its `$id` is {typedef.id}, its file says {name}"
            read.append(LoadedSchema(name, path, None, error))
            continue
        read.append(LoadedSchema(name, path, typedef, None))
    usable = [SchemaFile(file=s.path.name, typedef=s.typedef) for s in read if s.typedef]
    index, problems = index_schemas(usable)
    said = {}
    for problem in problems:
        said.setdefault(problem.file, problem.message)
    return [
        LoadedSchema(s.id, s.path, s.typedef, said.get(s.path.name, "unusable"))
        if s.typedef is not None and s.id in index.broken
        else s
        for s in read
    ]


def get(folder: Path, schema_id: str) -> LoadedSchema:
    """One schema of the Library; SchemaError when it is not there."""
    for schema in load_all(folder):
        if schema.id == schema_id:
            return schema
    raise SchemaError(f"no schema {schema_id} in the Library")


def text(schema: LoadedSchema) -> str:
    return _read(schema.path)


def add(folder: Path, content: str, *, replace: bool = False) -> tuple[str, bool]:
    """`content` (a schema file's text) into the Library under its `$id`: its `$id` and whether
    it changed the Library. SchemaClashError when a different one has that `$id` and not
    `replace`."""
    typedef = parse(content, "schema")
    path = path_of(folder, typedef.id)
    if path.exists():
        if _read(path) == content:
            return typedef.id, False
        if not replace:
            raise SchemaClashError(
                f"{typedef.id} is already in the Library and differs from this one: keep yours, "
                "or replace it (its documents are read with the new one)"
            )
    folder.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    return typedef.id, True


def remove(folder: Path, schema_id: str) -> None:
    path = path_of(folder, schema_id)
    if not path.exists():
        raise SchemaError(f"no schema {schema_id} in the Library")
    path.unlink()


def files(folder: Path, ids: list[str]) -> dict[str, str]:
    """What an agent using `ids` gets: each one's file and those it extends, `<$id>.schema.json`
    → its text. SchemaError when one is not there or no agent can use it."""
    by_id = {s.id: s for s in load_all(folder)}
    given: dict[str, str] = {}
    wanted = list(ids)
    while wanted:
        schema_id = wanted.pop()
        if f"{schema_id}{SUFFIX}" in given:
            continue
        schema = by_id.get(schema_id)
        if schema is None:
            raise SchemaError(f"no schema {schema_id} in the Library")
        if schema.typedef is None or schema.error is not None:
            raise SchemaError(f"schema {schema_id} cannot be used: {schema.error}")
        given[schema.path.name] = text(schema)
        if schema.typedef.extends:
            wanted.append(schema.typedef.extends)
    return dict(sorted(given.items()))


def _read(path: Path) -> str:
    if os.path.islink(path):  # one place, the Library's own files: a link is not one
        raise SchemaError(f"{path.name} is a link")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise SchemaError(f"{path.name} cannot be read: {e}") from None
