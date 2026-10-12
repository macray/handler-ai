"""Projects — what you work on: a code folder, its caches setting, the skills it gives to all
its agents, and its agents.

An agent of a project is an agent (agents.py) with a `project_id`, so its sessions and sandboxes
are the same as for an ad-hoc one. Its settings are its own; this module keeps in step
what it gets from its project: the folder, the caches setting and the project's skills.

    ProjectRecord     one project, persisted in <state>/projects.json
    ProjectRegistry   load, save, create, update, delete; its agents, resolved
"""

import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from handler_contracts import CacheSharing, RemoteAgent, RemoteProject

from .agents import AgentRecord, AgentRegistry, CheckedSettings


@dataclass
class ProjectRecord:
    id: str
    name: str
    folder: str
    description: str | None = None
    skills: list[str] = field(default_factory=list)  # given to all its agents (set by D.17)
    default_agent: str | None = None
    caches: CacheSharing = "project"  # the toolbox's caches for its agents (caches.py)
    context: str | None = None  # its context: the accounts and providers it runs (contexts.py)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self.skills = sorted(set(self.skills))

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "folder": self.folder,
            "description": self.description,
            "skills": self.skills,
            "defaultAgent": self.default_agent,
            "caches": self.caches,
            "context": self.context,
            "createdAt": self.created_at.isoformat(),
        }

    @classmethod
    def from_json(cls, r: dict[str, Any]) -> "ProjectRecord":
        return cls(
            id=r["id"],
            name=r["name"],
            folder=r["folder"],
            description=r.get("description"),
            skills=r.get("skills", []),
            default_agent=r.get("defaultAgent"),
            caches=r.get("caches", "project"),
            context=r.get("context"),
            created_at=datetime.fromisoformat(r["createdAt"]),
        )


def folder_name(folder: str) -> str:
    return folder.rstrip("/").rsplit("/", 1)[-1] or folder


class ProjectRegistry:
    def __init__(self, state_dir: Path, registry: AgentRegistry) -> None:
        self.file = state_dir / "projects.json"
        self.registry = registry
        self.projects: dict[str, ProjectRecord] = {}
        if self.file.exists():
            for r in json.loads(self.file.read_text()):
                self.projects[r["id"]] = ProjectRecord.from_json(r)

    def save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps([p.to_json() for p in self.projects.values()], indent=2))
        tmp.replace(self.file)

    def new_id(self) -> str:
        pid = "p_" + secrets.token_hex(5)
        while pid in self.projects:
            pid = "p_" + secrets.token_hex(5)
        return pid

    # ── reading ─────────────────────────────────────────────────────────

    def get(self, pid: str) -> ProjectRecord | None:
        return self.projects.get(pid)

    def by_folder(self, folder: str) -> ProjectRecord | None:
        return next((p for p in self.projects.values() if p.folder == folder), None)

    def agents(self, project: ProjectRecord) -> list[AgentRecord]:
        """Its agents: the default one first, then by name."""
        agents = [w for w in list(self.registry.agents.values()) if w.project_id == project.id]
        return sorted(agents, key=lambda w: (w.id != project.default_agent, (w.name or "").lower()))

    def remote_agents(self) -> list[RemoteProject]:
        """The projects and their agents paired devices may start sessions with (D.7)."""
        listed: list[RemoteProject] = []
        for project in sorted(self.projects.values(), key=lambda p: p.name.lower()):
            agents = [
                RemoteAgent(
                    id=a.id,
                    name=a.name or a.models[0].harness,
                    description=a.description,
                    default=a.id == project.default_agent,
                )
                for a in self.agents(project)
                if a.remote_start
            ]
            if agents:
                listed.append(
                    RemoteProject(project_id=project.id, project=project.name, agents=agents)
                )
        return listed

    def label(self, agent: AgentRecord) -> str | None:
        """How a session's agent is named in short: "project · agent" for an agent of a
        project."""
        project = self.get(agent.project_id or "")
        if project is None:
            return agent.name
        return f"{project.name} · {agent.name or agent.models[0].harness}"

    def last_used(self, project: ProjectRecord) -> datetime | None:
        used = [w.last_used_at for w in self.agents(project) if w.last_used_at]
        return max(used) if used else None

    # ── writing ─────────────────────────────────────────────────────────

    def resolve(self, project: ProjectRecord, agent: AgentRecord) -> None:
        """What the agent gets from its project: its folder, the caches setting, the project's
        skills and its context."""
        agent.scope = project.folder
        agent.caches = project.caches
        agent.context = project.context
        agent.project_skills = list(project.skills)

    def add(self, project: ProjectRecord) -> ProjectRecord:
        self.projects[project.id] = project
        self.save()
        return project

    def update(self, project: ProjectRecord, **fields: Any) -> None:
        """Change its own settings; its agents follow at once (the caller applies what can change
        in running sandboxes)."""
        for key, value in fields.items():
            setattr(project, key, value)
        project.__post_init__()
        for agent in self.agents(project):
            self.resolve(project, agent)
        self.registry.save()
        self.save()

    def delete(self, project: ProjectRecord) -> list[AgentRecord]:
        """Remove it and its agents; returns the agents (the caller stops their sessions)."""
        agents = self.agents(project)
        for agent in agents:
            self.registry.agents.pop(agent.id, None)
        self.projects.pop(project.id, None)
        self.registry.save()
        self.save()
        return agents

    def add_agent(
        self,
        project: ProjectRecord,
        settings: CheckedSettings,
        *,
        name: str,
        description: str | None,
        instructions: str | None,
        default: bool = False,
        remote_start: bool = False,
        skills: list[str] | None = None,
    ) -> AgentRecord:
        agent = AgentRecord(
            **settings.model_dump(),
            name=name,
            project_id=project.id,
            description=description,
            instructions=instructions,
            remote_start=remote_start,
            skills=sorted(set(skills or [])),
        )
        self.resolve(project, agent)
        self.registry.add(agent)
        if default or project.default_agent is None:
            project.default_agent = agent.id
            self.save()
        return agent

    def update_agent(
        self,
        project: ProjectRecord,
        agent: AgentRecord,
        settings: CheckedSettings,
        *,
        name: str,
        description: str | None,
        instructions: str | None,
        default: bool = False,
        remote_start: bool = False,
        skills: list[str] | None = None,
    ) -> None:
        agent.set_settings(settings)
        agent.name, agent.description, agent.instructions = name, description, instructions
        agent.remote_start = remote_start
        agent.skills = sorted(set(skills or []))
        self.resolve(project, agent)
        self.registry.save()
        if default and project.default_agent != agent.id:
            project.default_agent = agent.id
            self.save()

    def remove_agent(self, project: ProjectRecord, agent: AgentRecord) -> None:
        self.registry.agents.pop(agent.id, None)
        self.registry.save()
        if project.default_agent == agent.id:
            rest = self.agents(project)
            project.default_agent = rest[0].id if rest else None
            self.save()

    # ── skills (D.17): the projects that give them to all their agents, the agents picking them ──

    def skill_projects(self, name: str) -> list[ProjectRecord]:
        """The projects that give a skill to all their agents."""
        return [p for p in self.projects.values() if name in p.skills]

    def skill_users(self, name: str) -> list[AgentRecord]:
        return [w for w in self.registry.agents.values() if name in w.skills]

    def give_skill(self, old: str | None, new: str, givers: list[ProjectRecord]) -> None:
        """Skill `old` (None: a new one) is now `new`, given by `givers` to all their agents: the
        agents picking it follow a rename, and drop it when their project gives it."""
        ids = {p.id for p in givers}
        for p in self.projects.values():
            given = {new} if p.id in ids else set()
            p.skills = sorted(({*p.skills} - {old or new, new}) | given)
        for agent in self.skill_users(old or new):
            kept: set[str] = set() if agent.project_id in ids else {new}
            agent.skills = sorted(({*agent.skills} - {old or new}) | kept)
        self._resolve_all()

    def drop_skill(self, name: str) -> None:
        """A deleted skill: no project gives it, no agent uses it."""
        for p in self.projects.values():
            p.skills = [s for s in p.skills if s != name]
        for agent in self.skill_users(name):
            agent.skills = [s for s in agent.skills if s != name]
        self._resolve_all()

    def _resolve_all(self) -> None:
        for project in self.projects.values():
            for agent in self.agents(project):
                self.resolve(project, agent)
        self.registry.save()
        self.save()
