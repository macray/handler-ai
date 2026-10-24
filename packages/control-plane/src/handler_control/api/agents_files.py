"""Agents file routes (D.23): a project's agents exported as a file; a file read for its agents to
be set up, then read by name; a file read and not set up (or set up) forgotten. Setting one up is
creating its agents with its origin (D.2, D.8): their skills and checks come with them."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import AgentsFileCheck, ExportAgentsRequest

from .. import agents_files
from ..agents import AgentRecord
from .common import Context, ProblemError, dump, parse_body

MAX_FILE = 16 * 2**20  # an agents file, zipped


def add_agents_file_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    def problem(e: agents_files.AgentsFileError) -> ProblemError:
        return ProblemError(e.status, e.title, str(e))

    @app.get("/v1/agents-files/{name}", dependencies=authed)
    def inspect_agents_file(name: str) -> Response:
        try:
            found = agents_files.get(ctx.settings, name)
        except agents_files.AgentsFileError as e:
            raise problem(e) from None
        if found is None:
            raise ProblemError(404, "unknown agents file", name)
        return dump(found)

    @app.post("/v1/agents-files/export", dependencies=authed)
    async def export_agents(request: Request) -> Response:
        body = parse_body(ExportAgentsRequest, await request.body())
        project = ctx.get_project(body.project_id)
        agents: list[AgentRecord] = []
        for agent_id in dict.fromkeys(body.agent_ids):
            agent = ctx.get_agent(agent_id)
            if agent.project_id != body.project_id:
                raise ProblemError(400, "not one project", f"{agent_id} is not an agent of it")
            agents.append(agent)
        checks = {
            a.id: [AgentsFileCheck(**c.model_dump()) for c in ctx.checks.load(a.id).checks]
            for a in agents
        }
        try:
            drafted = agents_files.draft(ctx.settings, body, agents, project, checks)
            if body.dry_run:
                return dump(drafted)
            name, data = agents_files.pack(ctx.settings, drafted.file)
        except agents_files.AgentsFileError as e:
            raise problem(e) from None
        headers = {"Content-Disposition": f'attachment; filename="{name}"'}
        return Response(data, media_type="application/zip", headers=headers)

    @app.post("/v1/agents-files/import", dependencies=authed)
    async def import_agents(request: Request) -> Response:
        data = await request.body()
        if len(data) > MAX_FILE:
            raise ProblemError(413, "file too large", f"more than {MAX_FILE // 2**20} MiB")
        try:
            return dump(agents_files.stage(ctx.settings, data), status=201)
        except agents_files.AgentsFileError as e:
            raise problem(e) from None

    @app.delete("/v1/agents-files/{name}", dependencies=authed)
    def forget_agents_file(name: str) -> Response:
        try:
            agents_files.delete(ctx.settings, name)
        except agents_files.AgentsFileError as e:
            raise problem(e) from None
        return Response(status_code=204)
