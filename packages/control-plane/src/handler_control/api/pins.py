"""Pinned routes (D.28): the web UI's menu's projects and apps, in the person's order."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import Pin, Pins

from .. import pins
from .common import Context, ProblemError, dump, parse_body


def add_pin_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]
    state = ctx.settings.state_dir

    @app.get("/v1/pins", dependencies=authed)
    def list_pins() -> Response:
        return dump(Pins(items=pins.load(state)))

    @app.put("/v1/pins", dependencies=authed)
    async def set_pins(request: Request) -> Response:
        """The whole list: pin, unpin and reorder are one call; refused whole when one pin names
        nothing, or the same twice."""
        body = parse_body(Pins, await request.body())
        if unknown := [p for p in body.items if not exists(ctx, p)]:
            raise ProblemError(
                422, "nothing to pin", ", ".join(f"{p.kind} {p.id}" for p in unknown)
            )
        if len(set(body.items)) != len(body.items):
            raise ProblemError(422, "pinned twice", "each project or app is pinned once")
        pins.save(state, body.items)
        return dump(body)


def exists(ctx: Context, pin: Pin) -> bool:
    if pin.kind == "project":
        return pin.id in ctx.projects.projects
    return pin.id in ctx.apps.records  # Chat is no app (apps.CHAT): it is never pinned
