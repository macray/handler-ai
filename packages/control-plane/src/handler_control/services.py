"""Service interfaces (docs/dev/design/services.md): what handlerd offers to whatever it runs,
as data in `data/interfaces/<name>/v<N>/` (`interface.toml`, `tools.json`: MCP tool
definitions). Only what `llm/v1`, the first, needs: loaded, checked, and validators for its tools.

    load            an interface, checked (S2 closed schemas, S3 its errors, S5 tool names)
    ServiceError    a call's failure, one of the interface's errors (S3)
"""

import json
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator

INTERFACES = Path(__file__).resolve().parent / "data" / "interfaces"  # platform data, read-only


class ServiceError(Exception):
    """A call failed with one of its interface's errors (S3): what the caller sees."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


class InterfaceDataError(ValueError):
    """An interface's files break a rule of docs/dev/design/services.md §4.2."""


@dataclass(frozen=True)
class Tool:
    name: str
    definition: dict[str, Any]  # as served by tools/list (S1: the interface's own words)
    input: Validator
    output: Validator


@dataclass(frozen=True)
class Interface:
    id: str  # "llm/v1"
    name: str
    limits: dict[str, Any]
    errors: dict[str, str]  # code → meaning: the only errors a call may end with
    tools: dict[str, Tool]


def open_objects(schema: Any, where: str = "") -> list[str]:
    """S2: the objects with `properties` that do not forbid others (a map, without
    `properties`, is not a record and may stay open)."""
    found = []
    if isinstance(schema, dict):
        if "properties" in schema and schema.get("additionalProperties") is not False:
            found.append(where or "/")
        for key, value in schema.items():
            found += open_objects(value, f"{where}/{key}")
    elif isinstance(schema, list):
        for i, value in enumerate(schema):
            found += open_objects(value, f"{where}/{i}")
    return found


@cache
def load(interface_id: str) -> Interface:
    """`name/vN`, checked once."""
    folder = INTERFACES / interface_id
    meta = tomllib.loads((folder / "interface.toml").read_text())
    name, version = meta["name"], meta["version"]
    if interface_id != f"{name}/v{version}":
        raise InterfaceDataError(f"{interface_id}: its interface.toml names {name} v{version}")
    errors = meta.get("errors") or {}
    if not errors:
        raise InterfaceDataError(f"{interface_id}: no [errors] (S3)")
    tools = {}
    for definition in json.loads((folder / "tools.json").read_text()):
        tool = definition["name"]
        if not tool.startswith(f"{name}_"):
            raise InterfaceDataError(f"{interface_id}: tool {tool} must start with {name}_ (S5)")
        for part in ("inputSchema", "outputSchema"):
            Draft202012Validator.check_schema(definition[part])
            if found := open_objects(definition[part]):
                raise InterfaceDataError(f"{tool}.{part}: open objects at {', '.join(found)} (S2)")
        tools[tool] = Tool(
            tool,
            definition,
            Draft202012Validator(definition["inputSchema"]),
            Draft202012Validator(definition["outputSchema"]),
        )
    return Interface(interface_id, name, meta.get("limits") or {}, errors, tools)
