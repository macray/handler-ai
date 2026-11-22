"""Agent definitions (D.18): everything an agent is but what it runs as and where it works, in a
folder. An agents file's agents are definitions (D.23, agents_files.py), and so are those of
Handler's needs (D.18, handler_needs.py). The web UI fills
the agent's form with one and the user chooses its models; from then on the agent's settings are the
user's, nothing follows the definition.

    agent.toml       [agent]: its name, description, sandbox, the addons and knowledge folders it
                     needs, the library's skills it picks
    instructions.md  its instructions (optional)
    interface.json   its interface (optional, D.18)
    skills/<name>/   skills that come with it: installed in the library when it is set up (a
                     skill of that name already there is kept: it may be the user's)
    schemas/<$id>.schema.json   schemas that come with it (D.29): into the Library when it is
                     set up; a different one with that `$id` there refuses it (the person
                     decides, in Library → Schemas)
"""

import json
import tomllib
from pathlib import Path

import tomlkit
from pydantic import ValidationError

from handler_contracts import AgentDefinition

from . import knowledge_schemas, skills

# what agent.toml holds besides [agent]'s own names (`name`, `description`)
_FILES = {"instructions", "interface"}


class DefinitionError(ValueError):
    pass


def read(folder: Path) -> AgentDefinition:
    """DefinitionError with why it cannot be read."""
    try:
        meta = tomllib.loads((folder / "agent.toml").read_text())
        agent = meta.pop("agent", {})
        if meta:
            raise ValueError(f"agent.toml: only [agent], not {', '.join(sorted(meta))}")
        if (folder / "instructions.md").exists():
            agent["instructions"] = (folder / "instructions.md").read_text().strip()
        if (folder / "interface.json").exists():
            agent["interface"] = json.loads((folder / "interface.json").read_text())
        fields = {f"agent_{k}" if k in ("name", "description") else k: v for k, v in agent.items()}
        shipped = shipped_skills(folder)
        return AgentDefinition.model_validate(
            fields | {"skills": [*fields.get("skills", []), *shipped]}
        )
    except FileNotFoundError as e:
        raise DefinitionError(f"{Path(e.filename or folder).name} is missing") from None
    except (OSError, ValueError, ValidationError) as e:
        raise DefinitionError(str(e)) from None


def write(folder: Path, definition: AgentDefinition, skills_dir: Path, schemas_dir: Path) -> None:
    """The definition into a new folder, its skills copied from the library (all of them come
    with it: `skills/`, none named in agent.toml), and the schemas it uses (`schemas/`, D.29)."""
    folder.mkdir(parents=True)
    own = definition.model_dump(mode="json", exclude=_FILES | {"skills"}, exclude_defaults=True)
    agent = {k.removeprefix("agent_"): v for k, v in own.items()}
    (folder / "agent.toml").write_text(tomlkit.dumps({"agent": agent}))
    if definition.instructions:
        (folder / "instructions.md").write_text(definition.instructions + "\n")
    if definition.interface is not None:
        interface = definition.interface.model_dump(mode="json", by_alias=True, exclude_none=True)
        (folder / "interface.json").write_text(json.dumps(interface, indent=2) + "\n")
    for name in definition.skills:
        target = folder / "skills" / name
        target.mkdir(parents=True)
        skills.copy(skills_dir / name, target)
    used = [u.schema_id for u in definition.schemas]
    for file, content in knowledge_schemas.files(schemas_dir, used).items():
        (folder / "schemas").mkdir(exist_ok=True)
        (folder / "schemas" / file).write_text(content, encoding="utf-8")


def shipped_skills(folder: Path) -> list[str]:
    shipped = folder / "skills"
    return sorted(p.name for p in shipped.iterdir()) if shipped.is_dir() else []


def install_skills(folder: Path, skills_dir: Path) -> list[str]:
    """A definition's shipped skills (`folder`/skills) into the library, those not there yet
    (global). Returns their names, every one of them (installed now or before)."""
    names = shipped_skills(folder)
    for name in names:
        if not skills.exists(skills_dir, name):
            target = skills_dir / name
            target.mkdir(parents=True)
            skills.copy(folder / "skills" / name, target)
    return names


def shipped_schemas(folder: Path, schemas_dir: Path, differs: str) -> list[str]:
    """The schemas a folder ships (`folder`/schemas, D.29: an agent definition's, an app's),
    each checked: SchemaError when one is not a schema; SchemaClashError when the Library has a
    different one of that `$id` (`differs`: what the person may do then)."""
    shipped = folder / "schemas"
    files = sorted(shipped.glob(f"*{knowledge_schemas.SUFFIX}")) if shipped.is_dir() else []
    contents = [f.read_text(encoding="utf-8") for f in files]
    for content in contents:
        typedef = knowledge_schemas.parse(content, "schema")
        path = knowledge_schemas.path_of(schemas_dir, typedef.id)
        if path.exists() and path.read_text(encoding="utf-8") != content:
            raise knowledge_schemas.SchemaClashError(
                f"{typedef.id} in your Library differs from the one {differs}"
            )
    return contents


def install_schemas(folder: Path, schemas_dir: Path, differs: str) -> list[str]:
    """A folder's shipped schemas into the Library, those not there yet; returns their `$id`s.
    All checked first (`shipped_schemas`): a clash adds none."""
    contents = shipped_schemas(folder, schemas_dir, differs)
    return [knowledge_schemas.add(schemas_dir, content)[0] for content in contents]
