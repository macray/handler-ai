"""Plans (D.27): a plan (a file of an agent's folder, or a draft) read and parsed, approved by the
digest read (with the runner chosen on review, if any) and run; the plans approved, run again from
a step, cancelled, deleted; the drafts, made for a project or from a plan, saved, thrown away. The
owner's token only, as every route: nothing in a sandbox reaches them
(`plan.started-by-you-only`)."""

import contextlib
from collections.abc import Iterator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    ApprovePlanRequest,
    CreatePlanDraftRequest,
    ReadPlanRequest,
    RunPlanRequest,
    SavePlanDraftRequest,
)

from ..plan_drafts import DraftError
from ..plans import PlanError, Source, file_of
from .common import Context, ProblemError, dump, parse_body


@contextlib.contextmanager
def plan_problems() -> Iterator[None]:
    try:
        yield
    except (PlanError, DraftError) as e:
        raise ProblemError(e.status, e.title, e.detail) from None


def source(ctx: Context, body: ReadPlanRequest) -> Source:
    """Where the plan is: a draft, or a file in an agent's folder (named, or a session's)."""
    if body.draft_id is not None:
        return ctx.drafts.source(body.draft_id)
    assert body.path is not None  # with an agent or a session
    if body.session_id is not None:
        return file_of(ctx.get_agent(ctx.get_session(body.session_id).agent_id), body.path)
    assert body.agent_id is not None  # one of the three
    return file_of(ctx.get_agent(body.agent_id), body.path)


def add_plan_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.post("/v1/plans/read", dependencies=authed)
    async def read_plan(request: Request) -> Response:
        body = parse_body(ReadPlanRequest, await request.body())
        with plan_problems():
            return dump(ctx.plans.read(source(ctx, body), body.runner_id))

    @app.post("/v1/plans", dependencies=authed)
    async def approve_plan(request: Request) -> Response:  # async: it runs on the event loop
        body = parse_body(ApprovePlanRequest, await request.body())
        with plan_problems():
            plan = ctx.plans.approve(source(ctx, body), body.digest, body.runner_id)
            return dump(plan, status=201)

    @app.get("/v1/plans", dependencies=authed)
    def list_plans(agentId: str | None = None, projectId: str | None = None) -> Response:  # noqa: N803 — query parameter names
        folder = ctx.get_project(projectId).folder if projectId is not None else None
        return dump(ctx.plans.list(agentId, folder))

    @app.get("/v1/plans/{plan_id}", dependencies=authed)
    def get_plan(plan_id: str) -> Response:
        with plan_problems():
            return dump(ctx.plans.view(plan_id))

    @app.post("/v1/plans/{plan_id}/run", dependencies=authed)
    async def run_plan(plan_id: str, request: Request) -> Response:
        body = parse_body(RunPlanRequest, await request.body())
        with plan_problems():
            if body.allow:
                await ctx.plans.allow(plan_id, body.from_, body.allow)
            return dump(ctx.plans.run(plan_id, body.from_))

    @app.post("/v1/plans/{plan_id}/cancel", dependencies=authed)
    async def cancel_plan(plan_id: str) -> Response:
        with plan_problems():
            return dump(await ctx.plans.cancel(plan_id))

    @app.delete("/v1/plans/{plan_id}", dependencies=authed)
    async def delete_plan(plan_id: str) -> Response:
        with plan_problems():
            ctx.plans.delete(plan_id)
        return Response(status_code=204)

    @app.post("/v1/plan-drafts", dependencies=authed)
    async def create_plan_draft(request: Request) -> Response:
        body = parse_body(CreatePlanDraftRequest, await request.body())
        with plan_problems():
            if body.project_id is not None:
                return dump(ctx.drafts.create(body.project_id), status=201)
            assert body.from_plan is not None  # one of the two
            plan = ctx.plans.plan(body.from_plan)  # Edit as a new draft
            project = ctx.projects.by_folder(plan.folder)
            if project is None:
                why = f"{plan.folder} is no project's folder: a draft is a project's"
                raise ProblemError(409, "its folder is no project's", why)
            text = ctx.plans.text(plan.id)
            return dump(ctx.drafts.create(project.id, text, from_plan=plan.id), status=201)

    @app.get("/v1/plan-drafts", dependencies=authed)
    def list_plan_drafts(projectId: str | None = None) -> Response:  # noqa: N803 — query parameter name
        return dump(ctx.drafts.list(projectId))

    @app.get("/v1/plan-drafts/{draft_id}", dependencies=authed)
    def get_plan_draft(draft_id: str) -> Response:
        with plan_problems():
            return dump(ctx.drafts.get(draft_id))

    @app.put("/v1/plan-drafts/{draft_id}", dependencies=authed)
    async def save_plan_draft(draft_id: str, request: Request) -> Response:
        body = parse_body(SavePlanDraftRequest, await request.body())
        with plan_problems():
            return dump(ctx.drafts.save(draft_id, body.text, body.digest))

    @app.delete("/v1/plan-drafts/{draft_id}", dependencies=authed)
    def delete_plan_draft(draft_id: str) -> Response:
        with plan_problems():
            ctx.drafts.delete(draft_id)
        return Response(status_code=204)
