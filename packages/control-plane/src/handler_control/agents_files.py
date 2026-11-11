"""Agents files (D.23): agents written so they can be set up again in another project, as a
whole: their definitions without what is yours (the models they run as, their folder, the connections
and notes folders they were given), with what they need instead. A project's
agents exported (a zip, made on the fly, never kept), and set up again in another project from it.

    <state>/agent-imports/<name>/   a file being imported: until its agents are set up (the
                                    set-up page deletes it), or a day
      agents.toml           name (in a file), description, version, place ("project": set up in
                            a project, its agents working in its folder; "outside": folderless
                            agents)
      agents/<part>/        each agent: its definition (definitions.py) + checks.json (D.20:
                            name, input, answer, compare)

An agent set up from one keeps its origin (kind "agents-file", its name, version and part): its
skills go to the library and its checks to the agent (agent_service.py), nothing follows the file
afterwards.
"""

import json
import re
import shutil
import tempfile
import time
import tomllib
from pathlib import Path

import tomlkit
from pydantic import ValidationError

from handler_contracts import (
    AgentDefinition,
    AgentOrigin,
    AgentsExport,
    AgentsFile,
    AgentsFileAgent,
    AgentsFileCheck,
    ExportAgentsRequest,
)

from . import definitions, files, skills
from .agents import AgentRecord, describe
from .projects import ProjectRecord
from .settings import Settings

META_FILE = "agents.toml"
CHECKS_FILE = "checks.json"
MAX_FILES, MAX_BYTES = 2000, 32 * 2**20  # an agents file: definitions and skills
STAGED_FOR = 24 * 3600  # a file read but never set up is forgotten after a day


class AgentsFileError(ValueError):
    def __init__(self, status: int, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.title = status, title


def root(settings: Settings) -> Path:
    """Where files being imported wait for their agents to be set up."""
    return settings.state_dir / "agent-imports"


def origin(name: str, version: int, part: str) -> AgentOrigin:
    return AgentOrigin(kind="agents-file", name=name, version=version, agent=part)


# ── reading ─────────────────────────────────────────────────────────────


def read(folder: Path) -> AgentsFile:
    """ValueError with why it cannot be read."""
    try:
        meta = tomllib.loads((folder / META_FILE).read_text())
        parts = sorted(p for p in (folder / "agents").iterdir() if p.is_dir())
        agents = [
            AgentsFileAgent(part=p.name, definition=definitions.read(p), checks=read_checks(p))
            for p in parts
        ]
        return AgentsFile.model_validate(meta | {"name": folder.name, "agents": agents})
    except FileNotFoundError as e:
        raise ValueError(f"{Path(e.filename or folder).name} is missing") from None
    except (OSError, ValidationError) as e:
        raise ValueError(str(e)) from None


def read_offered(folder: Path) -> AgentsFile:
    """A source's agents (D.26: its folder named as the file), read as `stage_folder` takes
    them: ValueError with why they cannot be."""
    file = read(folder)
    _named(folder, folder.name)
    return file


def _named(folder: Path, expected: str | None = None) -> str:
    """The name its agents.toml gives (`expected`, when given): ValueError when it gives none."""
    try:
        meta = tomllib.loads((folder / META_FILE).read_text())
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{META_FILE}: {e}") from None
    name = str(meta.get("name", ""))
    if not skills.NAME.fullmatch(name):
        raise ValueError(f"its name {name!r} is not one (lowercase letters, digits, -)")
    if expected is not None and name != expected:
        raise ValueError(f"its {META_FILE} names another file, {name}")
    return name


def read_checks(part: Path) -> list[AgentsFileCheck]:
    if not (part / CHECKS_FILE).exists():
        return []
    checks = json.loads((part / CHECKS_FILE).read_text())
    return [AgentsFileCheck.model_validate(c) for c in checks]


def folder_of(settings: Settings, name: str) -> Path | None:
    found = root(settings) / name
    return found if skills.NAME.fullmatch(name) and (found / META_FILE).is_file() else None


def get(settings: Settings, name: str) -> AgentsFile | None:
    """AgentsFileError when it is there but cannot be read."""
    found = folder_of(settings, name)
    if found is None:
        return None
    try:
        return read(found)
    except ValueError as e:
        raise AgentsFileError(409, "agents file unreadable", f"{name}: {e}") from None


def part_folder(settings: Settings, origin: AgentOrigin) -> Path:
    """The folder of the agent an origin sets up (the file read, at its version)."""
    name, version, part = origin.name, origin.version, origin.agent
    file = get(settings, name)
    if file is None:
        raise AgentsFileError(400, "unknown agents file", name)
    if version != file.version:
        raise AgentsFileError(
            409, "agents file changed", f"{name} is at version {file.version}, not {version}"
        )
    if part not in {a.part for a in file.agents}:
        raise AgentsFileError(400, "unknown agents file agent", f"{name} has no agent {part}")
    return root(settings) / name / "agents" / part


# ── exporting ───────────────────────────────────────────────────────────


def draft(
    settings: Settings,
    body: ExportAgentsRequest,
    agents: list[AgentRecord],
    project: ProjectRecord,
    checks: dict[str, list[AgentsFileCheck]],
) -> AgentsExport:
    """The file the agents make, and what of yours it leaves out."""
    parts: list[AgentsFileAgent] = []
    replaced: list[str] = []
    for agent in agents:
        definition, said = as_definition(agent, project)
        part = unique(slug(definition.agent_name), {p.part for p in parts})
        parts.append(AgentsFileAgent(part=part, definition=definition, checks=checks[agent.id]))
        replaced += [f"{definition.agent_name}: {line}" for line in said]
    file = AgentsFile(
        name=body.name,
        description=(body.description or "").strip() or None,
        version=1,
        place="project",
        agents=parts,
    )
    return AgentsExport(file=file, replaced=replaced)


def as_definition(agent: AgentRecord, project: ProjectRecord) -> tuple[AgentDefinition, list[str]]:
    """The agent as a definition, and what of yours it leaves out, in words."""
    said: list[str] = []
    runs_on = describe(agent.model)
    if agent.model_alone:  # a provider, and no folder: one model call a turn (D.18)
        said.append(f"runs on {runs_on} → a provider, chosen at set-up")
    else:
        said.append(f"runs on {runs_on} → its model, chosen at set-up")
        said.append(f"works in {project.folder} → the folder of the project it is set up in")
    for use in agent.addons:
        if use.binding is not None:
            said.append(f"connection {use.binding} → one of {use.addon}, chosen at set-up")
    for use in agent.project_addons:
        said.append(f"tool {use.addon}, given by its project → it uses it")
    for folder in agent.knowledge:
        said.append(f"notes folder {folder} → one chosen at set-up ({folder} if you have it)")
    for name in agent.project_skills:
        said.append(f"skill {name}, given by its project → it picks it")
    definition = AgentDefinition(
        agent_name=agent.name or Path(agent.scope or "agent").name,
        agent_description=agent.description,
        instructions=agent.instructions,
        network=agent.network,
        egress=agent.egress or "enforce",
        allow=agent.allow,
        confinement=agent.confinement,
        permissions=agent.permissions,
        skills=sorted({*agent.skills, *agent.project_skills}),
        interface=agent.interface,
        addons=sorted({u.addon for u in agent.addon_uses}),
        knowledge=agent.knowledge,
        display=agent.display,
        model_alone=agent.model_alone,
    )
    return definition, said


def slug(name: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", name.lower()))[:60] or "agent"


def unique(part: str, taken: set[str]) -> str:
    n, found = 2, part
    while found in taken:
        found, n = f"{part}-{n}", n + 1
    return found


def write(folder: Path, file: AgentsFile, skills_dir: Path) -> None:
    """Its files in `folder` (made), its skills from the library."""
    folder.mkdir(parents=True)
    meta: dict[str, object] = {"name": file.name, "version": file.version}
    if file.description:
        meta["description"] = file.description
    meta["place"] = file.place
    (folder / META_FILE).write_text(tomlkit.dumps(meta))
    for agent in file.agents:
        part = folder / "agents" / agent.part
        definitions.write(part, agent.definition, skills_dir)
        if agent.checks:
            checks = [c.model_dump(mode="json", by_alias=True) for c in agent.checks]
            (part / CHECKS_FILE).write_text(json.dumps(checks, indent=2) + "\n")


def pack(settings: Settings, file: AgentsFile) -> tuple[str, bytes]:
    """The agents file: its name to save it as, and the zip."""
    with tempfile.TemporaryDirectory() as tmp:
        write(Path(tmp) / file.name, file, settings.skills_dir)
        return f"{file.name}-agents.zip", files.zipped(Path(tmp) / file.name)


# ── importing ───────────────────────────────────────────────────────────


def _staging(settings: Settings) -> Path:
    where = root(settings)
    where.mkdir(parents=True, exist_ok=True)
    for old in where.iterdir():  # read, never set up
        if time.time() - old.stat().st_mtime > STAGED_FOR:
            shutil.rmtree(old, ignore_errors=True)
    return Path(tempfile.mkdtemp(dir=where, prefix="."))


def stage(settings: Settings, data: bytes) -> AgentsFile:
    """An agents file read, kept until its agents are set up (the set-up page reads it by name,
    then deletes it). AgentsFileError: not an agents file."""
    tmp = _staging(settings)
    try:
        files.unzip(data, tmp / "file", MAX_FILES, MAX_BYTES)
        inside = [p for p in (tmp / "file").iterdir()]
        folder = inside[0] if len(inside) == 1 and inside[0].is_dir() else tmp / "file"
        return _keep(settings, folder)
    except (OSError, ValueError) as e:
        raise AgentsFileError(400, "not an agents file", str(e)) from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def stage_folder(settings: Settings, source: Path) -> AgentsFile:
    """The agents a source offers (D.26, `source`: its item, named as the file), read as a file
    is."""
    tmp = _staging(settings)
    try:
        shutil.copytree(source, tmp / source.name)  # a source's tree holds no link
        return _keep(settings, tmp / source.name, source.name)
    except (OSError, ValueError) as e:
        raise AgentsFileError(409, "not an agents file", f"{source.name}: {e}") from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _keep(settings: Settings, folder: Path, expected: str | None = None) -> AgentsFile:
    """`folder` (an agents file's content, in the staging folder) read and kept under its name
    (`expected`, when given)."""
    name = _named(folder, expected)
    file = read(folder)  # the folder's name is not the file's: checked first
    target = root(settings) / name
    shutil.rmtree(target, ignore_errors=True)
    folder.rename(target)
    return file.model_copy(update={"name": name})


def delete(settings: Settings, name: str) -> None:
    found = folder_of(settings, name)
    if found is None:
        raise AgentsFileError(404, "unknown agents file", name)
    shutil.rmtree(found)
