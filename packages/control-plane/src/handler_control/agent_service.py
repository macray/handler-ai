"""Agents created, changed and deleted, whatever their home (D.1, D.2, D.8, H.14): the one place
that knows everything an agent's save or deletion involves.

    checked   the rules of save_rules.py, in order, for its home: a project's (its folder, a
              name unique in it, its area), an app's (set up from its need) or Chat's (no
              folder, no form), or none (its folder and name unique outside projects)
    create    registered, its project's default if asked, the checks of what it is set up from
    update    its settings and own fields replaced; what can change live applied to its sandboxes
    delete    what runs on it stopped, its checks and improvements forgotten, Handler's needs
              it was given for left without it, then removed

Who must know (the paired phones) listens to the registry's saves.
"""

import contextlib
from pathlib import Path

from handler_contracts import AgentOrigin, AgentRequest

from . import agents_files, definitions, handler_needs, save_rules
from .agent_checks import CheckStore
from .agents import AgentRecord, CheckedSettings, apply_network
from .apps import AppError, AppStore
from .improvements import ImprovementStore
from .projects import ProjectRecord, ProjectRegistry
from .sessions import SessionStore
from .settings import Settings


class AgentServiceError(Exception):
    """Cannot be done to this agent now (a status, a title, the detail)."""

    def __init__(self, status: int, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.title = status, title


class AgentService:
    def __init__(
        self,
        settings: Settings,
        *,
        projects: ProjectRegistry,
        sessions: SessionStore,
        checks: CheckStore,
        improvements: ImprovementStore,
        apps: AppStore,
    ) -> None:
        self.settings = settings
        self.projects = projects
        self.registry = projects.registry
        self.sessions = sessions
        self.checks = checks
        self.improvements = improvements
        self.apps = apps

    # ── saving ──────────────────────────────────────────────────────────

    def project_of(self, body: AgentRequest) -> ProjectRecord | None:
        if body.project_id is None:
            return None
        project = self.projects.get(body.project_id)
        if project is None:
            raise save_rules.CheckError("unknown project", body.project_id)
        return project

    def checked(
        self, body: AgentRequest, current: AgentRecord | None = None
    ) -> tuple[CheckedSettings, Path | None]:
        """Its settings checked for its home, what a save widens confirmed (D.8), and the
        definition a new one is set up from (D.18, D.23, H.2): its skills are in the library first
        (it picks them). save_rules.CheckError and its kinds."""
        project = self.project_of(body)
        origin = self.set_up_from(body, current)
        name = save_rules.agent_name(body, project)
        folder = project.folder if project else body.scope
        settings = save_rules.checked_settings(self.settings, body, folder)
        if project is not None:
            others = [a.name or "" for a in self.projects.agents(project) if a is not current]
            save_rules.check_unique_names([name or "", *others])
            save_rules.check_area(self.settings, project.area, [settings])
        elif body.app is None and not body.chat:
            save_rules.check_outside_identity(self.registry, settings.scope, name, current)
        save_rules.check_risks(current.settings if current else None, settings, body)
        save_rules.check_skills(self.settings, body, project)
        save_rules.check_instructions(body.instructions, body.interface)
        return settings, origin

    def set_up_from(self, body: AgentRequest, current: AgentRecord | None = None) -> Path | None:
        """Its home and what it is set up from, checked; the definition's folder for a new one,
        whose skills are then in the library (it picks them)."""
        save_rules.check_home(body, current, self.apps.records)
        origin = save_rules.check_origin(self.settings, body.origin, current, self._definition)
        if origin is not None:
            definitions.install_skills(origin, self.settings.skills_dir)
        return origin

    def _definition(self, origin: AgentOrigin) -> Path:
        try:
            return self.apps.definition_dir(origin)
        except AppError as e:
            raise save_rules.CheckError("unknown app need", str(e)) from None

    def create(
        self, body: AgentRequest, settings: CheckedSettings, origin: Path | None
    ) -> AgentRecord:
        """A new agent, `checked` first."""
        project = self.project_of(body)
        record = AgentRecord(
            **settings.model_dump(), project_id=body.project_id, app=body.app, chat=body.chat
        )
        self._own(record, body, project)
        if project is not None:
            self.projects.add_agent(project, record, body.default)
        else:
            self.registry.add(record)
        if origin is not None:  # an agents file's agents have checks
            self.checks.adopt(record.id, agents_files.read_checks(origin))
        return record

    async def update(
        self, record: AgentRecord, body: AgentRequest, settings: CheckedSettings
    ) -> list[str]:
        """Its settings and own fields replaced, `checked` first; returns the live sandboxes the
        network change did not reach (A.4)."""
        project = self.project_of(body)
        record.set_settings(settings)
        self._own(record, body, project)
        self.registry.save()
        if project is not None and body.default and project.default_agent != record.id:
            self.projects.set_default(project, record.id)
        return await apply_network(record, record.egress)

    def _own(self, record: AgentRecord, body: AgentRequest, project: ProjectRecord | None) -> None:
        def text(value: str | None) -> str | None:
            return (value or "").strip() or None

        record.name = save_rules.agent_name(body, project)
        record.description = text(body.description)
        record.instructions = text(body.instructions)
        record.skills = sorted(set(body.skills))
        record.origin = body.origin
        record.remote_start = body.remote_start and project is not None
        if project is not None:
            self.projects.resolve(project, record)

    # ── deleting ────────────────────────────────────────────────────────

    async def delete(self, record: AgentRecord, *, with_home: bool = False) -> None:
        """Removed with all it involves. Unless its home goes too (`with_home`: its project or
        its app removed), an app's part stays (removed with its app, H.14) and a project keeps
        at least one agent."""
        project = self.projects.get(record.project_id or "")
        if not with_home:
            if record.app is not None:
                why = f"it is one of the app {record.app}'s parts: removed with it"
                raise AgentServiceError(409, "an app's agent", why)
            if project is not None and len(self.projects.agents(project)) == 1:
                raise AgentServiceError(409, "a project needs an agent", "add another one first")
        await self.stop(record)
        await self.improvements.forget(record.id)
        await self.checks.forget(record.id)
        handler_needs.forget(self.settings.state_dir, record.id)
        self.registry.delete(record.id)
        if project is not None:
            self.projects.agent_gone(project, record.id)

    async def delete_project(self, project: ProjectRecord) -> None:
        for record in self.projects.agents(project):
            await self.delete(record, with_home=True)
        self.projects.delete(project)

    async def stop(self, record: AgentRecord) -> None:
        """Stop what runs on it: connections and sessions (these keep their folders, F.3)."""
        for conn in list(record.connections.values()):
            with contextlib.suppress(ProcessLookupError):
                conn.process.terminate()  # its relay (or terminal client) then ends
        await self.sessions.stop_agent(record.id)
