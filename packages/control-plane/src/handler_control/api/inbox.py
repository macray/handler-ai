"""The person's inbox: apps' notifications and automations' results (H.9, I.3)."""

from fastapi import Depends, FastAPI
from fastapi.responses import Response

from .common import Context, ProblemError, dump


def add_inbox_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/inbox", dependencies=authed)
    def inbox() -> Response:
        return dump(ctx.inbox.list())

    @app.post("/v1/inbox/{message_id}/read", dependencies=authed)
    def mark_read(message_id: str) -> Response:
        message = ctx.inbox.mark_read(message_id)
        if message is None:
            raise ProblemError(404, "message not found", message_id)
        return dump(message)
