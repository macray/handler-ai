"""Ask (D.24): what the person says, routed to one of their apps' asks and run."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import AssistantRequest

from ..assistant import AssistantError
from .common import Context, ProblemError, dump, parse_body


def add_ask_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.post("/v1/ask", dependencies=authed)
    async def ask(request: Request) -> Response:
        body = parse_body(AssistantRequest, await request.body())
        if body.turns[-1].who != "you":
            raise ProblemError(400, "the last turn is yours", "what do you ask?")
        try:
            return dump(await ctx.assistant.answer(body.turns, body.timezone))
        except AssistantError as e:
            raise ProblemError(e.status, "Ask cannot answer", str(e)) from None
