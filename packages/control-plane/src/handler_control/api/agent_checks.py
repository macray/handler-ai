"""An agent's checks (D.20): kept from its runs, renamed, deleted, run when the person asks; and
its improvements (D.21): its instructions rewritten until its checks pass, an attempt kept."""

import contextlib
from collections.abc import Iterator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    CheckUpdateRequest,
    KeepAttemptRequest,
    KeepCheckRequest,
    StartImprovementRequest,
)

from ..agent_checks import CheckError
from .common import Context, ProblemError, dump, parse_body


@contextlib.contextmanager
def check_problems() -> Iterator[None]:
    try:
        yield
    except CheckError as e:
        raise ProblemError(e.status, "check", e.detail) from None


def add_agent_check_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/agents/{agent_id}/checks", dependencies=authed)
    def agent_checks(agent_id: str) -> Response:
        return dump(ctx.checks.view(ctx.get_agent(agent_id)))

    @app.post("/v1/agents/{agent_id}/checks", dependencies=authed)
    async def keep_check(agent_id: str, request: Request) -> Response:
        body = parse_body(KeepCheckRequest, await request.body())
        with check_problems():
            return dump(ctx.checks.keep(ctx.get_agent(agent_id), body), status=201)

    @app.put("/v1/agents/{agent_id}/checks/{check_id}", dependencies=authed)
    async def update_check(agent_id: str, check_id: str, request: Request) -> Response:
        body = parse_body(CheckUpdateRequest, await request.body())
        with check_problems():
            return dump(ctx.checks.update(ctx.get_agent(agent_id), check_id, body))

    @app.delete("/v1/agents/{agent_id}/checks/{check_id}", dependencies=authed)
    def delete_check(agent_id: str, check_id: str) -> Response:
        with check_problems():
            ctx.checks.delete(ctx.get_agent(agent_id).id, check_id)
        return Response(status_code=204)

    @app.post("/v1/agents/{agent_id}/checks/run", dependencies=authed)
    async def run_checks(agent_id: str) -> Response:
        with check_problems():
            return dump(ctx.checks.start(ctx.get_agent(agent_id)), status=202)

    @app.get("/v1/agents/{agent_id}/improvements", dependencies=authed)
    def improvements(agent_id: str) -> Response:
        found = ctx.improvements.load(ctx.get_agent(agent_id).id)
        return dump(list(reversed(found)))

    @app.post("/v1/agents/{agent_id}/improvements", dependencies=authed)
    async def improve(agent_id: str, request: Request) -> Response:
        body = parse_body(StartImprovementRequest, await request.body())
        with check_problems():
            return dump(ctx.improvements.start(ctx.get_agent(agent_id), body), status=202)

    @app.post("/v1/agents/{agent_id}/improvements/{improvement_id}/stop", dependencies=authed)
    def stop_improvement(agent_id: str, improvement_id: str) -> Response:
        with check_problems():
            return dump(ctx.improvements.stop(ctx.get_agent(agent_id).id, improvement_id))

    @app.post("/v1/agents/{agent_id}/improvements/{improvement_id}/keep", dependencies=authed)
    async def keep_attempt(agent_id: str, improvement_id: str, request: Request) -> Response:
        body = parse_body(KeepAttemptRequest, await request.body())
        with check_problems():
            return dump(ctx.improvements.keep(ctx.get_agent(agent_id), improvement_id, body))
