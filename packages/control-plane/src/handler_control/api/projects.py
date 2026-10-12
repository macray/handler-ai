"""Project routes: projects and their agents (D.8)."""

from datetime import datetime

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    AgentRequest,
    CreateProjectRequest,
    ProjectSettingsRequest,
)

from .. import caches, checks
from ..projects import ProjectRecord, folder_name
from .agents import apply_agent_live, stop_agent
from .common import (
    Context,
    ProblemError,
    check_problems,
    dump,
    parse_body,
    text_or_none,
)


def add_project_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    def out(project: ProjectRecord, status: int = 200) -> Response:
        return dump(ctx.to_project(project), status=status)

    @app.get("/v1/projects", dependencies=authed)
    def list_projects() -> Response:
        def recent(p: ProjectRecord) -> datetime:
            return ctx.projects.last_used(p) or p.created_at

        listed = sorted(ctx.projects.projects.values(), key=recent, reverse=True)
        return dump([ctx.to_project(p) for p in listed])

    @app.post("/v1/projects", dependencies=authed)
    async def create_project(request: Request) -> Response:
        body = parse_body(CreateProjectRequest, await request.body())
        with check_problems():
            checks.check_project(ctx.projects, body)
            checks.check_unique_names([checks.agent_name(a) for a in body.agents])
            checked = checks.new_project_agents(ctx.settings, ctx.projects, body)
        folder = checked[0].scope
        assert folder is not None  # a project's agents work in its folder
        project = ctx.projects.add(
            ProjectRecord(
                id=ctx.projects.new_id(),
                name=text_or_none(body.name) or folder_name(folder),
                description=text_or_none(body.description),
                folder=folder,
                caches=body.caches,
                context=body.context,
            )
        )
        default = next((i for i, a in enumerate(body.agents) if a.default), 0)
        for i, (a, settings) in enumerate(zip(body.agents, checked, strict=True)):
            ctx.projects.add_agent(
                project,
                settings,
                name=checks.agent_name(a),
                description=text_or_none(a.description),
                instructions=text_or_none(a.instructions),
                default=i == default,
                remote_start=a.remote_start,
                skills=a.skills,
            )
        ctx.remote.agents_changed()
        return out(project, 201)

    @app.get("/v1/projects/{project_id}", dependencies=authed)
    def inspect_project(project_id: str) -> Response:
        return out(ctx.get_project(project_id))

    @app.put("/v1/projects/{project_id}", dependencies=authed)
    async def update_project(project_id: str, request: Request) -> Response:
        project = ctx.get_project(project_id)
        body = parse_body(ProjectSettingsRequest, await request.body())
        with check_problems():
            folder = checks.project_folder(ctx.settings, ctx.projects, project, body)
        ctx.projects.update(
            project,
            name=text_or_none(body.name) or folder_name(folder),
            description=text_or_none(body.description),
            folder=folder,
            default_agent=body.default_agent or project.default_agent,
            caches=body.caches,
            context=body.context,
        )
        return out(project)

    @app.delete("/v1/projects/{project_id}", dependencies=authed)
    async def delete_project(project_id: str) -> Response:
        project = ctx.get_project(project_id)
        for record in ctx.projects.agents(project):
            await stop_agent(ctx, record)
        ctx.projects.delete(project)
        caches.remove_project(ctx.settings, project.id)
        ctx.remote.agents_changed()
        return Response(status_code=204)


def add_project_agent_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.post("/v1/projects/{project_id}/agents", dependencies=authed)
    async def create_agent(project_id: str, request: Request) -> Response:
        project = ctx.get_project(project_id)
        body = parse_body(AgentRequest, await request.body())
        with check_problems():
            names = [a.name or "" for a in ctx.projects.agents(project)]
            checks.check_unique_names([checks.agent_name(body), *names])
            settings = checks.checked_settings(ctx.settings, body, project.folder)
            checks.check_risks(None, settings, body)
            checks.check_context(ctx.settings, project.context, [settings])
            checks.check_skills(ctx.settings, body.skills, project)
        record = ctx.projects.add_agent(
            project,
            settings,
            name=checks.agent_name(body),
            description=text_or_none(body.description),
            instructions=text_or_none(body.instructions),
            default=body.default,
            remote_start=body.remote_start,
            skills=body.skills,
        )
        ctx.remote.agents_changed()
        return dump(ctx.to_agent(record), status=201)

    @app.put("/v1/projects/{project_id}/agents/{agent_id}", dependencies=authed)
    async def update_agent(project_id: str, agent_id: str, request: Request) -> Response:
        project = ctx.get_project(project_id)
        record = ctx.get_project_agent(project, agent_id)
        body = parse_body(AgentRequest, await request.body())
        with check_problems():
            others = [a.name or "" for a in ctx.projects.agents(project) if a.id != record.id]
            checks.check_unique_names([checks.agent_name(body), *others])
            settings = checks.checked_settings(ctx.settings, body, project.folder)
            checks.check_risks(record.settings, settings, body)
            checks.check_context(ctx.settings, project.context, [settings])
            checks.check_skills(ctx.settings, body.skills, project)
        ctx.projects.update_agent(
            project,
            record,
            settings,
            name=checks.agent_name(body),
            description=text_or_none(body.description),
            instructions=text_or_none(body.instructions),
            default=body.default,
            remote_start=body.remote_start,
            skills=body.skills,
        )
        ctx.remote.agents_changed()
        await apply_agent_live(record)
        return dump(ctx.to_agent(record))

    @app.delete("/v1/projects/{project_id}/agents/{agent_id}", dependencies=authed)
    async def delete_agent(project_id: str, agent_id: str) -> Response:
        project = ctx.get_project(project_id)
        record = ctx.get_project_agent(project, agent_id)
        if len(ctx.projects.agents(project)) == 1:
            raise ProblemError(409, "a project needs an agent", "add another one first")
        await stop_agent(ctx, record)
        ctx.projects.remove_agent(project, record)
        ctx.remote.agents_changed()
        return Response(status_code=204)
