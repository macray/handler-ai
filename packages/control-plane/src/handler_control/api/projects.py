"""Project routes (D.8): projects, made with their first agents; their agents are changed through
the agent routes (agents.py)."""

from datetime import datetime

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    CreateProjectRequest,
    ProjectSettingsRequest,
    SetProjectPinnedRequest,
)

from .. import caches, save_rules
from ..projects import ProjectRecord, folder_name
from .common import (
    Context,
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
            save_rules.check_project(ctx.projects, body)
            names = [save_rules.agent_name(a, None) or "" for a in body.agents]
            if "" in names:
                raise save_rules.CheckError("name required", "a project's agents are named")
            save_rules.check_unique_names(names)
            for a in body.agents:
                ctx.agents.set_up_from(a)
            checked = save_rules.new_project_agents(ctx.settings, ctx.projects, body)
        folder = checked[0].scope
        assert folder is not None  # a project's agents work in its folder
        project = ctx.projects.add(
            ProjectRecord(
                id=ctx.projects.new_id(),
                name=text_or_none(body.name) or folder_name(folder),
                description=text_or_none(body.description),
                folder=folder,
                caches=body.caches,
                area=body.area,
            )
        )
        default = next((i for i, a in enumerate(body.agents) if a.default), 0)
        for i, a in enumerate(body.agents):
            agent = a.model_copy(update={"project_id": project.id, "default": i == default})
            with check_problems():  # checked above
                settings, origin = ctx.agents.checked(agent)
            ctx.agents.create(agent, settings, origin)
        ctx.projects.give_skills(project, body.skills)
        return out(project, 201)

    @app.get("/v1/projects/{project_id}", dependencies=authed)
    def inspect_project(project_id: str) -> Response:
        return out(ctx.get_project(project_id))

    @app.put("/v1/projects/{project_id}", dependencies=authed)
    async def update_project(project_id: str, request: Request) -> Response:
        project = ctx.get_project(project_id)
        body = parse_body(ProjectSettingsRequest, await request.body())
        with check_problems():
            folder = save_rules.project_folder(ctx.settings, ctx.projects, project, body)
        ctx.projects.update(
            project,
            name=text_or_none(body.name) or folder_name(folder),
            description=text_or_none(body.description),
            folder=folder,
            default_agent=body.default_agent or project.default_agent,
            caches=body.caches,
            area=body.area,
        )
        ctx.projects.give_skills(project, body.skills)
        return out(project)

    @app.put("/v1/projects/{project_id}/pinned", dependencies=authed)
    async def pin_project(project_id: str, request: Request) -> Response:
        project = ctx.get_project(project_id)
        body = parse_body(SetProjectPinnedRequest, await request.body())
        ctx.projects.update(project, pinned=body.pinned)
        return out(project)

    @app.delete("/v1/projects/{project_id}", dependencies=authed)
    async def delete_project(project_id: str) -> Response:
        project = ctx.get_project(project_id)
        await ctx.agents.delete_project(project)
        caches.remove_project(ctx.settings, project.id)
        return Response(status_code=204)
