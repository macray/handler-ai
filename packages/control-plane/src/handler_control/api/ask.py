"""Ask (D.24): what the person says, routed to one of their apps' asks and run; Ask's history."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import AskHistorySettings, AssistantRequest

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
            return dump(
                await ctx.assistant.answer(body.turns, body.timezone, body.via, body.spoken)
            )
        except AssistantError as e:
            raise ProblemError(e.status, "Ask cannot answer", str(e)) from None

    @app.get("/v1/ask/history", dependencies=authed)
    def get_history() -> Response:
        return dump(ctx.assistant.history_view())

    @app.put("/v1/ask/history", dependencies=authed)
    async def put_history(request: Request) -> Response:
        body = parse_body(AskHistorySettings, await request.body())
        return dump(ctx.assistant.history.set_keep(body.keep))

    @app.delete("/v1/ask/history", dependencies=authed)
    def clear_history() -> Response:
        ctx.assistant.history.clear()
        return Response(status_code=204)

    @app.delete("/v1/ask/history/{record_id}", dependencies=authed)
    def delete_ask(record_id: str) -> Response:
        if not ctx.assistant.history.delete(record_id):
            raise ProblemError(404, "no such ask", f"no ask {record_id} in Ask's history")
        return Response(status_code=204)
