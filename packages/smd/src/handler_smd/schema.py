"""Schemas (SMD spec 5.1, 5.2): one document type, its small vocabulary as models, and a schema
file's text to a TypeDefinition. Pure: the scanner reads the files."""

import json
import re
from typing import Literal, Self

from pydantic import Field, ValidationError, field_validator, model_validator

from handler_smd.models import Diagnostic, Model, Severity

# `<name>@<integer version>`: how documents and `extends` name a schema, never by path (5.2)
SCHEMA_ID = re.compile(r"^[a-z0-9][a-z0-9-]*@[1-9][0-9]*$")
KEY = re.compile(r"^[a-z][a-z0-9_]*$")  # a field's or a section's key: what a document writes

FieldType = Literal[
    "string", "enum", "date", "datetime", "time", "time-range", "duration", "list", "ref"
]
# what a list may be of
ScalarType = Literal["string", "enum", "date", "datetime", "time", "time-range", "duration", "ref"]
LeadType = Literal["date", "time", "time-range", "duration"]  # a value a line may start with
Missing = Literal["error", "warning", "info", "none"]  # the severity when absent; none: silent
Additional = Literal["allow", "warn", "forbid"]  # unknown fields or sections: info, warning, error


class FieldDef(Model):
    type: FieldType
    values: list[str] | None = None  # an enum's, or a list of enums'
    of: ScalarType | None = None  # a list's
    missing: Missing = "none"
    description: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        enum = self.type == "enum" or self.of == "enum"
        if enum and not self.values:
            raise ValueError("an enum needs `values`, at least one")
        if not enum and self.values is not None:
            raise ValueError("only an enum has `values`")
        if (self.type == "list") != (self.of is not None):
            raise ValueError("a list says what it is `of`, and only a list does")
        return self


class SectionDef(Model):
    heading: str  # as rendered
    aliases: list[str] = []  # other headings read as this section
    missing: Missing = "none"
    description: str = ""


class LenientWhen(Model):
    """Items whose `field` is one of `values` (a draft) get warnings, not errors, for what they
    lack (spec 5.1)."""

    field: str
    values: list[str] = Field(alias="in")


def _snake_case(keys: list[str]) -> None:
    if bad := [key for key in keys if not KEY.match(key)]:
        raise ValueError(f"keys are snake_case ([a-z][a-z0-9_]*), not: {', '.join(bad)}")


class LeadDef(Model):
    """A typed value at the start of a line (spec 13.3): an item's title (`## 2026-11-19 ·
    Thursday`) or an entry's text (`10:00 Call the bank`), given to `field`."""

    field: str
    type: LeadType
    missing: Missing = "none"
    description: str = ""

    @field_validator("field")
    @classmethod
    def _key(cls, value: str) -> str:
        _snake_case([value])
        return value

    def as_field(self) -> FieldDef:
        return FieldDef(type=self.type, missing=self.missing, description=self.description)


class TagsDef(Model):
    """The `#word`s at the end of an entry's text (spec 13.3), given to the list `field`."""

    field: str
    of: Literal["string", "enum"] = "string"
    values: list[str] | None = None  # an enum's
    missing: Missing = "none"
    description: str = ""

    @field_validator("field")
    @classmethod
    def _key(cls, value: str) -> str:
        _snake_case([value])
        return value

    def as_field(self) -> FieldDef:
        return FieldDef(
            type="list",
            of=self.of,
            values=self.values,
            missing=self.missing,
            description=self.description,
        )


class EntriesDef(Model):
    """What an item's bullets are (spec 13.3)."""

    description: str = ""
    checkbox: Literal["allow", "require", "forbid"] = "allow"
    lead: LeadDef | None = None
    tags: TagsDef | None = None
    fields: dict[str, FieldDef] = {}  # in the order they are rendered
    additional_fields: Additional = "allow"

    @model_validator(mode="after")
    def _keys(self) -> Self:
        _snake_case(list(self.fields))
        own = [d.field for d in (self.lead, self.tags) if d is not None]
        if len(set(own)) < len(own) or set(own) & set(self.fields):
            raise ValueError("the lead's and the tags' fields are their own, not in `fields`")
        return self

    def all_fields(self) -> dict[str, FieldDef]:
        """Its fields, the lead's and the tags' first."""
        own = {d.field: d.as_field() for d in (self.lead, self.tags) if d is not None}
        return {**own, **self.fields}


class ItemDef(Model):
    description: str = ""
    title_lead: LeadDef | None = None
    fields: dict[str, FieldDef] = {}  # in the order they are rendered
    entries: EntriesDef | None = None  # what its bullets are, when its body is a list
    sections: dict[str, SectionDef] = {}  # in the order they are rendered
    lenient_when: LenientWhen | None = None
    additional_fields: Additional = "allow"
    additional_sections: Additional = "allow"

    @field_validator("fields", "sections")
    @classmethod
    def _snake_case(cls, value: dict[str, object]) -> dict[str, object]:
        _snake_case(list(value))
        return value

    @model_validator(mode="after")
    def _lead_own(self) -> Self:
        if self.title_lead is not None and self.title_lead.field in self.fields:
            raise ValueError("the title lead's field is its own, not in `fields`")
        return self

    def all_fields(self) -> dict[str, FieldDef]:
        """Its fields, the title lead's first."""
        lead = self.title_lead
        return {**({lead.field: lead.as_field()} if lead else {}), **self.fields}


class TypeDefinition(Model):
    id: str = Field(alias="$id")
    title: str
    description: str = ""
    extends: str | None = None  # a schema's `$id`, one level
    item: ItemDef

    @field_validator("id", "extends")
    @classmethod
    def _schema_id(cls, value: str | None) -> str | None:
        if value is not None and not SCHEMA_ID.match(value):
            raise ValueError(
                f"'{value}' is not `<name>@<version>`: a lowercase name (letters, digits, -) and "
                "a whole version from 1, such as decision-log@1"
            )
        return value


def parse_typedef(text: str, file: str) -> tuple[TypeDefinition | None, list[Diagnostic]]:
    """A schema file's text, or the `invalid-schema` diagnostics saying why it is none."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        return None, [_invalid(file, error.lineno, "", f"not valid JSON: {error.msg}")]
    try:
        return TypeDefinition.model_validate(data), []
    except ValidationError as error:
        return None, [
            _invalid(file, 1, ".".join(str(part) for part in e["loc"]), _message(e["msg"]))
            for e in error.errors()
        ]


def _message(pydantic_message: str) -> str:
    return pydantic_message.removeprefix("Value error, ")


def _invalid(file: str, line: int, path: str, message: str) -> Diagnostic:
    return Diagnostic(
        file=file,
        line=line,
        path=path,
        severity=Severity.ERROR,
        code="invalid-schema",
        message=message,
    )
