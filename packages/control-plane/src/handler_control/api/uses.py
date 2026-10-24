"""What uses what (D.22): a thing's uses and used-by."""

from typing import get_args

from fastapi import Depends, FastAPI
from fastapi.responses import Response

from handler_contracts import UseKind

from .common import Context, ProblemError, dump


def add_use_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/uses/{kind}/{ident:path}", dependencies=authed)
    def uses(kind: str, ident: str) -> Response:
        if kind not in get_args(UseKind):
            raise ProblemError(404, "no such kind of thing", kind)
        return dump(ctx.uses.of(kind, ident))  # ty: ignore[invalid-argument-type]
