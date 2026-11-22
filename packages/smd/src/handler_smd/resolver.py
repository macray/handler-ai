"""Resolution (SMD spec 5.3): the schemas of one folder, indexed by `$id` with `extends` applied
once, then a document's schema found by its `$id` alone. Never a path, never nearest-wins: one
`$id`, one schema. Pure: the scanner reads the folder."""

from handler_smd.models import Diagnostic, Document, Model, Severity
from handler_smd.parser import section_key
from handler_smd.schema import SCHEMA_ID, ItemDef, TypeDefinition


class SchemaFile(Model):
    file: str
    typedef: TypeDefinition


class SchemaIndex(Model):
    schemas: dict[str, TypeDefinition]  # by `$id`, `extends` applied
    # `$id`s found but unusable (a broken `extends`, sections at odds…), and their file, whose
    # diagnostics say why
    broken: dict[str, str]


def index_schemas(files: list[SchemaFile]) -> tuple[SchemaIndex, list[Diagnostic]]:
    found: list[Diagnostic] = []
    by_id: dict[str, SchemaFile] = {}
    for schema in files:
        first = by_id.setdefault(schema.typedef.id, schema)
        if first is not schema:
            found.append(
                _error(
                    schema.file,
                    "$id",
                    "duplicate-schema-id",
                    f"{schema.typedef.id} is already {first.file}: this one is ignored",
                )
            )

    schemas: dict[str, TypeDefinition] = {}
    broken: dict[str, str] = {}
    for schema_id, schema in by_id.items():
        typedef, problems = _resolved(schema, by_id)
        found += problems
        if typedef is None:
            broken[schema_id] = schema.file
        else:
            schemas[schema_id] = typedef
    found.sort(key=lambda d: (d.file, d.line, d.path))
    return SchemaIndex(schemas=schemas, broken=broken), found


def resolve_schema(
    document: Document, index: SchemaIndex, file: str
) -> tuple[TypeDefinition | None, list[Diagnostic]]:
    """The schema a document names in its frontmatter; none named: none, silently (the parser
    said `missing-schema-field`)."""
    schema_id = document.meta.get("schema")
    if schema_id is None:
        return None, []
    if not isinstance(schema_id, str) or not SCHEMA_ID.match(schema_id):
        return None, [
            _error(
                file,
                "meta.schema",
                "invalid-frontmatter",
                f"`schema` is `<name>@<version>`, such as notes@1 (got {schema_id!r})",
            )
        ]
    if schema_id in index.schemas:
        return index.schemas[schema_id], []
    if schema_id in index.broken:
        return None, [
            _error(
                file,
                "meta.schema",
                "schema-not-found",
                f"{schema_id} is {index.broken[schema_id]}, which cannot be used: "
                "see its diagnostics",
            )
        ]
    name = schema_id.split("@")[0]
    versions = sorted(
        (i for i in [*index.schemas, *index.broken] if i.split("@")[0] == name),
        key=lambda i: int(i.split("@")[1]),
    )
    if versions:
        return None, [
            _error(
                file,
                "meta.schema",
                "schema-version-mismatch",
                f"no {schema_id}; there is {', '.join(versions)}",
            )
        ]
    return None, [_error(file, "meta.schema", "schema-not-found", f"no schema {schema_id}")]


def _resolved(
    schema: SchemaFile, by_id: dict[str, SchemaFile]
) -> tuple[TypeDefinition | None, list[Diagnostic]]:
    typedef = schema.typedef
    if typedef.extends is not None:
        parent = by_id.get(typedef.extends)
        if parent is None:
            return None, [
                _error(
                    schema.file,
                    "extends",
                    "schema-not-found",
                    f"extends {typedef.extends}, which is not in the schemas",
                )
            ]
        if parent.typedef.extends is not None:
            return None, [
                _error(
                    schema.file,
                    "extends",
                    "invalid-schema",
                    f"extends {parent.typedef.id}, which itself extends "
                    f"{parent.typedef.extends}: one level only",
                )
            ]
        typedef = typedef.model_copy(update={"item": _overlay(parent.typedef.item, typedef.item)})
    problems = [
        _error(schema.file, path, "invalid-schema", message)
        for path, message in _problems(typedef.item)
    ]
    return (None if problems else typedef), problems


def _overlay(parent: ItemDef, child: ItemDef) -> ItemDef:
    """The parent's item, then the child's: the child wins per field, per section, and for each
    setting it gives (spec 5.3)."""
    given = {name: getattr(child, name) for name in child.model_fields_set}
    given["fields"] = {**parent.fields, **child.fields}
    given["sections"] = {**parent.sections, **child.sections}
    return parent.model_copy(update=given)


def _problems(item: ItemDef) -> list[tuple[str, str]]:
    """What a schema cannot say once merged: one heading read as two sections, a leniency on a
    field it does not have."""
    problems: list[tuple[str, str]] = []
    owner: dict[str, str] = {}  # a heading's key → the section reading it
    for key, section in item.sections.items():
        for heading in [section.heading, *section.aliases]:
            other = owner.setdefault(section_key(heading), key)
            if other != key:
                problems.append(
                    ("item.sections", f"the heading '{heading}' would be both {other} and {key}")
                )
    if item.lenient_when is not None and item.lenient_when.field not in item.all_fields():
        problems.append(
            (
                "item.lenient_when.field",
                f"lenient_when names {item.lenient_when.field}, not a field of the item",
            )
        )
    return problems


def _error(file: str, path: str, code: str, message: str) -> Diagnostic:
    return Diagnostic(
        file=file, line=1, path=path, severity=Severity.ERROR, code=code, message=message
    )
