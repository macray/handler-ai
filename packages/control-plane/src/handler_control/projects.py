"""Projects — what you work on: a code folder, its caches setting, the skills and addons it gives
to all its agents, and its agents.

An agent of a project is an agent (agents.py) with a `project_id`, so its sessions and sandboxes
are the same as for an ad-hoc one. Its settings are its own; this module keeps in step
what it gets from its project: the folder, the caches setting, the project's skills and addons.

    ProjectRecord     one project, persisted in <state>/projects.json
    ProjectRegistry   load, save, create, update, delete; its agents, resolved
"""

import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from handler_contracts import AddonUse, CacheSharing, RemoteAgent, RemoteProject

from . import pins
from .agents import AgentRecord, AgentRegistry, describe


@dataclass
class ProjectRecord:
    id: str
    name: str
    folder: str
    description: str | None = None
    skills: list[str] = field(default_factory=list)  # given to all its agents (set by D.17)
    addons: list[AddonUse] = field(default_factory=list)  # given to all its agents (G.3)
    default_agent: str | None = None
    caches: CacheSharing = "project"  # the toolbox's caches for its agents (caches.py)
    area: str | None = None  # its area: the accounts and providers it runs (areas.py)
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
            "addons": [
                u.model_dump(mode="json", by_alias=True, exclude_none=True) for u in self.addons
            ],
            "defaultAgent": self.default_agent,
            "caches": self.caches,
            "area": self.area,
            "createdAt": self.created_at.isoformat(),
        }

    @classmethod
    def from_json(cls, r: dict[str, Any]) -> "ProjectRecord":
        return cls(
            id=r["id"],
            name=r["name"],
            folder=r["folder"],
            description=r["description"],
            skills=r["skills"],
            addons=[AddonUse.model_validate(u) for u in r["addons"]],
            default_agent=r["defaultAgent"],
            caches=r["caches"],
            area=r["area"],
            created_at=datetime.fromisoformat(r["createdAt"]),
        )


class NamedAgentError(LookupError):
    """No agent, or more than one, of that name there; `field`: "project" or "agent"."""

    def __init__(self, field: str, detail: str) -> None:
        super().__init__(detail)
        self.field = field


def folder_name(folder: str) -> str:
    return folder.rstrip("/").rsplit("/", 1)[-1] or folder


def branch_of(folder: str) -> str | None:
    """The git branch checked out in the folder, as its page shows it: read from `.git/HEAD` (a
    worktree's `.git` file points to its own), never by running git. None: not a git folder, or
    no branch (a detached HEAD)."""
    git = Path(folder) / ".git"
    try:
        if git.is_file():
            pointer = git.read_text().strip()
            if not pointer.startswith("gitdir: "):
                return None
            git = (git.parent / pointer.removeprefix("gitdir: ")).resolve()
        head = (git / "HEAD").read_text().strip()
    except (OSError, UnicodeDecodeError):
        return None
    return head.removeprefix("ref: refs/heads/") if head.startswith("ref: refs/heads/") else None


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
                    name=a.name or describe(a.model),
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

    def named_agent(self, name: str, project: str | None) -> AgentRecord:
        """The agent of that name in the project of that name (None: an agent of no project), as
        an automation names one (I.1)."""
        pid = None
        if project is not None:
            found = [p for p in self.projects.values() if p.name == project]
            if not found:
                raise NamedAgentError("project", f"no project named {project}")
            pid = found[0].id
        agents = [
            a for a in self.registry.agents.values() if a.name == name and a.project_id == pid
        ]
        where = f"in project {project}" if project else "of no project"
        if not agents:
            raise NamedAgentError("agent", f"no agent named {name} {where}")
        if len(agents) > 1:
            raise NamedAgentError("agent", f"{len(agents)} agents named {name} {where}")
        return agents[0]

    def label(self, agent: AgentRecord) -> str | None:
        """How a session's agent is named in short: "project · agent" for an agent of a
        project."""
        project = self.get(agent.project_id or "")
        if project is None:
            return agent.name
        return f"{project.name} · {agent.name or agent.model.harness}"

    def last_used(self, project: ProjectRecord) -> datetime | None:
        used = [w.last_used_at for w in self.agents(project) if w.last_used_at]
        return max(used) if used else None

    # ── writing ─────────────────────────────────────────────────────────

    def resolve(self, project: ProjectRecord, agent: AgentRecord) -> None:
        """What the agent gets from its project: its folder, the caches setting, the project's
        skills and addons, and its area."""
        agent.scope = project.folder
        agent.caches = project.caches
        agent.area = project.area
        agent.project_skills = list(project.skills)
        agent.project_addons = list(project.addons)

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

    def add_agent(self, project: ProjectRecord, agent: AgentRecord, default: bool = False) -> None:
        """Register a new agent of the project (checked, agent_service.py): what it gets from
        its project resolved; its default when asked, or when it has none yet."""
        agent.project_id = project.id
        self.resolve(project, agent)
        self.registry.add(agent)
        if default or project.default_agent is None:
            self.set_default(project, agent.id)

    def delete(self, project: ProjectRecord) -> None:
        """Remove it (its agents are deleted first, agent_service.py), and its pin."""
        self.projects.pop(project.id, None)
        self.save()
        pins.forget(self.file.parent, "project", project.id)

    def set_default(self, project: ProjectRecord, agent_id: str | None) -> None:
        project.default_agent = agent_id
        self.save()

    def agent_gone(self, project: ProjectRecord, agent_id: str) -> None:
        """One of its agents was deleted: its default becomes the first of the others."""
        if project.default_agent == agent_id:
            rest = [a for a in self.agents(project) if a.id != agent_id]
            self.set_default(project, rest[0].id if rest else None)

    # ── skills (D.17): the projects that give them to all their agents, the agents picking them ──

    def skill_projects(self, name: str) -> list[ProjectRecord]:
        """The projects that give a skill to all their agents."""
        return [p for p in self.projects.values() if name in p.skills]

    def skill_users(self, name: str) -> list[AgentRecord]:
        return [w for w in self.registry.agents.values() if name in w.skills]

    def give_skills(self, project: ProjectRecord, names: list[str]) -> None:
        """The skills `project` gives to all its agents (D.17): those of its agents that picked
        one of them drop it."""
        project.skills = sorted(set(names))
        for agent in self.agents(project):
            agent.skills = [s for s in agent.skills if s not in project.skills]
        self._resolve_all()

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

    # ── addons (G.3): given by a project to all its agents, as skills ─────

    def give_addons(self, project: ProjectRecord, uses: list[AddonUse]) -> None:
        """The addons `project` gives to all its agents (checked with them, save_rules): those of
        its agents that picked one of them drop it."""
        project.addons = sorted(uses, key=lambda u: u.addon)
        given = {u.addon for u in project.addons}
        for agent in self.agents(project):
            agent.addons = [u for u in agent.addons if u.addon not in given]
        self._resolve_all()

    def _resolve_all(self) -> None:
        for project in self.projects.values():
            for agent in self.agents(project):
                self.resolve(project, agent)
        self.registry.save()
        self.save()
