"""Built-in agents (D.18): agents handler ships in `data/builtin-agents/<name>/`, each set up at
most once (the agent's `origin` is its name). One is everything an agent is but what it runs as and
where it works: the web UI fills the agent's form with it and the user chooses its models; from
then on the agent's settings are the user's, nothing follows the built-in.

    agent.toml       description, and [agent]: its name, description, sandbox, skills
    instructions.md  its instructions (optional)
    interface.json   its interface (optional, D.18)
    skills/<name>/   skills that come with it: installed in the library when it is set up (a
                     skill of that name already there is kept: it may be the user's)
"""

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from handler_contracts import BuiltinAgent

from . import skills

ROOT = Path(__file__).parent / "data" / "builtin-agents"


class BuiltinError(ValueError):
    pass


@dataclass(frozen=True)
class LoadedBuiltin:
    agent: BuiltinAgent
    folder: Path


def load(folder: Path) -> LoadedBuiltin:
    """BuiltinError when its files are invalid (a bug of handler: tests load every built-in
    agent)."""
    try:
        meta = tomllib.loads((folder / "agent.toml").read_text())
        agent = meta.pop("agent", {})
        if (folder / "instructions.md").exists():
            agent["instructions"] = (folder / "instructions.md").read_text().strip()
        if (folder / "interface.json").exists():
            agent["interface"] = json.loads((folder / "interface.json").read_text())
        shipped = (
            sorted(p.name for p in (folder / "skills").iterdir())
            if (folder / "skills").is_dir()
            else []
        )
        fields = {f"agent_{k}" if k in ("name", "description") else k: v for k, v in agent.items()}
        builtin = BuiltinAgent.model_validate(
            meta | fields | {"name": folder.name, "skills": [*fields.get("skills", []), *shipped]}
        )
    except (OSError, ValueError, ValidationError) as e:
        raise BuiltinError(f"built-in agent {folder.name}: {e}") from None
    return LoadedBuiltin(builtin, folder)


def load_all(root: Path = ROOT) -> list[LoadedBuiltin]:
    return [load(p) for p in sorted(root.iterdir()) if (p / "agent.toml").is_file()]


def get(name: str, root: Path = ROOT) -> LoadedBuiltin | None:
    folder = root / name
    return (
        load(folder) if skills.NAME.fullmatch(name) and (folder / "agent.toml").is_file() else None
    )


def install_skills(loaded: LoadedBuiltin, skills_dir: Path) -> list[str]:
    """Its shipped skills into the library, those not there yet (global). Returns their names,
    every one of them (installed now or before)."""
    shipped = loaded.folder / "skills"
    names = sorted(p.name for p in shipped.iterdir()) if shipped.is_dir() else []
    for name in names:
        if not skills.exists(skills_dir, name):
            target = skills_dir / name
            target.mkdir(parents=True)
            skills.copy(shipped / name, target)
    return names
