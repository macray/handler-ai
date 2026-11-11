"""Automations as configured (I.1, I.7): the folders of `<config>/automations/`, what keeps one
from running in them, and its state (on or off, since when, the cursors, its schedule's last slot).

The folder is the truth: read on every use. handler writes it only when the owner creates one (an
example copied, or the web UI's form written as automation.toml); never a sandbox (invariant 6).
The state is handlerd's: `<state>/automations/<name>/state.json`, with what the names of its file
were bound to (I.1): the agent it runs, the agents and projects `only` names, by id, and the names
they were read from.

    load, load_all     a folder's automation.toml, parsed (or why it is not)
    problems           what keeps it from running, read from its folder alone (I.1)
    read_state, write_state
    examples, copy_example   the examples handler ships (data/automations/)
    write_new, write_definition   a definition written as (a new) automation's automation.toml
"""

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import tomlkit
from pydantic import ValidationError

from handler_contracts import (
    AUTOMATION_FILE,
    Automation,
    AutomationExample,
    is_within,
)

from . import knowledge, providers, secrets
from .files import describe, write_private

EXAMPLES = Path(__file__).resolve().parent / "data" / "automations"  # platform data, read-only
NAME = r"^[a-z0-9][a-z0-9-]{0,63}$"
LLM_PROTOCOLS = ("openai-chat", "anthropic")  # what the `llm` service speaks (I.5)
MAX_FILE = 1024 * 1024  # a file shown through the API
MAX_FILES = 200  # files listed


class AutomationConfigError(ValueError):
    """An automation's folder or file cannot be used as asked."""


class AutomationExistsError(AutomationConfigError):
    pass


@dataclass(frozen=True)
class Loaded:
    name: str
    path: Path  # its folder
    definition: Automation | None
    error: str | None = None  # why automation.toml cannot be used


def load(path: Path) -> Loaded:
    name = path.name
    if not re.match(NAME, name):
        return Loaded(name, path, None, f"invalid name '{name}': lowercase letters, digits, '-'")
    file = path / AUTOMATION_FILE
    if not file.is_file():
        return Loaded(name, path, None, f"no {AUTOMATION_FILE} in {path}")
    try:
        return Loaded(name, path, Automation.from_toml(file.read_text()))
    except ValidationError as e:
        return Loaded(name, path, None, f"{AUTOMATION_FILE}: {describe(e)}")
    except (OSError, ValueError) as e:  # unreadable, TOML syntax
        return Loaded(name, path, None, f"{AUTOMATION_FILE}: {e}")


def get(directory: Path, name: str) -> Loaded | None:
    """None when there is no such folder."""
    if "/" in name or name.startswith(".") or not (directory / name).is_dir():
        return None
    return load(directory / name)


def load_all(directory: Path) -> list[Loaded]:
    if not directory.is_dir():
        return []
    return [load(p) for p in sorted(directory.iterdir()) if p.is_dir() and p.name[0] != "."]


def files(path: Path) -> list[str]:
    """Its files, relative to its folder, sorted; hidden ones and caches left out."""
    found: list[str] = []
    for current, dirs, names in os.walk(path):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        found += [
            os.path.relpath(os.path.join(current, n), path) for n in names if not n.startswith(".")
        ]
        if len(found) >= MAX_FILES:
            break
    return sorted(found)[:MAX_FILES]


def read_file(path: Path, relative: str) -> str:
    """One of its files as text, confined to its folder."""
    base = os.path.realpath(path)
    target = os.path.realpath(os.path.join(base, relative))
    if not is_within(target, base) or target == base or not os.path.isfile(target):
        raise AutomationConfigError(f"{relative}: not a file of the automation")
    if os.path.getsize(target) > MAX_FILE:
        raise AutomationConfigError(f"{relative}: larger than {MAX_FILE // 1024} KiB")
    return Path(target).read_text(encoding="utf-8", errors="replace")


# ── problems (I.1) ──────────────────────────────────────────────────────


def llm_problems(providers_dir: Path, store: secrets.SecretStore, model: str) -> list[str]:
    """Why `provider/model` cannot be called by the `llm` service."""
    provider_name, _, model_id = model.partition("/")
    loaded = providers.get(providers_dir, provider_name)
    if loaded.provider is None:
        return [f"services.llm {model}: {loaded.error}"]
    if loaded.provider.model_named(model_id) is None:
        return [f"services.llm {model}: not a model of provider {provider_name}"]
    if loaded.provider.endpoint_for(LLM_PROTOCOLS) is None:
        protocols = " or ".join(LLM_PROTOCOLS)
        return [f"services.llm {model}: provider {provider_name} has no {protocols} endpoint"]
    return [f"services.llm {model}: {p}" for p in providers.problems(loaded.provider, store)]


def problems(
    loaded: Loaded,
    *,
    providers_dir: Path,
    store: secrets.SecretStore,
    knowledge_root: Path,
) -> list[str]:
    """What keeps it from running (I.1), read from its file alone: the file, its models, its
    notes."""
    if (definition := loaded.definition) is None:
        return [loaded.error or "invalid"]
    found: list[str] = []
    for model in definition.services.llm if definition.services else []:
        found += llm_problems(providers_dir, store, model)
    for append in definition.append:
        try:
            knowledge.check_note(knowledge_root, append.to)
        except knowledge.KnowledgeError as e:
            found.append(f"append.to {e}")
    return found


# ── state ───────────────────────────────────────────────────────────────


@dataclass
class State:
    enabled: bool = False
    since: datetime | None = None  # turned on then: stops before are not read (I.7)
    cursors: dict[str, int] = field(default_factory=dict)  # session id → last seq a run covered
    last_slot: datetime | None = None  # the schedule's slot it last ran for (I.2)
    # what its names were bound to (I.1): the agent run's, {"id", "name", "project"} (the names
    # it was read from); `only`'s agents (a name: every agent of that name then) and projects
    agent: dict[str, Any] | None = None
    only_agents: dict[str, list[str]] = field(default_factory=dict)
    only_projects: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "since": self.since.isoformat() if self.since else None,
            "cursors": self.cursors,
            "lastSlot": self.last_slot.isoformat() if self.last_slot else None,
            "agent": self.agent,
            "onlyAgents": self.only_agents,
            "onlyProjects": self.only_projects,
        }


def state_dir(state_root: Path, name: str) -> Path:
    return state_root / "automations" / name


def read_state(state_root: Path, name: str) -> State:
    try:
        data = json.loads((state_dir(state_root, name) / "state.json").read_text())
    except (OSError, ValueError):
        return State()
    try:
        return State(
            enabled=bool(data.get("enabled")),
            since=datetime.fromisoformat(data["since"]) if data.get("since") else None,
            cursors={str(k): int(v) for k, v in (data.get("cursors") or {}).items()},
            last_slot=datetime.fromisoformat(data["lastSlot"]) if data.get("lastSlot") else None,
            agent=data.get("agent"),
            only_agents={str(k): list(v) for k, v in (data.get("onlyAgents") or {}).items()},
            only_projects={str(k): str(v) for k, v in (data.get("onlyProjects") or {}).items()},
        )
    except (ValueError, TypeError):
        return State()


def write_state(state_root: Path, name: str, state: State) -> None:
    write_private(state_dir(state_root, name) / "state.json", json.dumps(state.to_json(), indent=2))


# ── examples ────────────────────────────────────────────────────────────


def examples() -> list[AutomationExample]:
    found = []
    for loaded in load_all(EXAMPLES):
        description = loaded.definition.description if loaded.definition else None
        found.append(AutomationExample(name=loaded.name, description=description))
    return found


def copy_example(directory: Path, name: str, example: str) -> Path:
    """`example` copied as `name` (off: the state is handlerd's, and a new one is off)."""
    source = EXAMPLES / example
    if "/" in example or example.startswith(".") or not (source / AUTOMATION_FILE).is_file():
        raise AutomationConfigError(f"no example automation named {example}")
    target = directory / name
    if target.exists():
        raise AutomationExistsError(f"an automation named {name} exists ({target})")
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    return target


def write_new(directory: Path, name: str, definition: Automation) -> Path:
    """A new automation `name` whose automation.toml says `definition` (off, as a copy)."""
    target = directory / name
    if target.exists():
        raise AutomationExistsError(f"an automation named {name} exists ({target})")
    directory.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    write_definition(target, definition)
    return target


def write_definition(path: Path, definition: Automation) -> None:
    """`definition` as the folder's automation.toml, over what it had (its comments too)."""
    data = definition.model_dump(
        mode="json", by_alias=True, exclude_none=True, exclude_defaults=True
    )
    doc = tomlkit.document()
    doc.add(
        tomlkit.comment("Written by handler's web UI; edit it there or here (docs/automations.md).")
    )
    for key, value in data.items():
        if key == "when" and isinstance(value, dict):
            when = tomlkit.inline_table()
            when.update(value)
            doc[key] = when
        else:
            doc[key] = value
    (path / AUTOMATION_FILE).write_text(tomlkit.dumps(doc))
