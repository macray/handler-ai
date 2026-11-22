"""Pinned routes (D.28): the web UI's menu's projects and apps, in the person's order."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import Pin, Pins

from .. import pins
from .common import Context, dump, parse_body


def add_pin_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]
    state = ctx.settings.state_dir

    @app.get("/v1/pins", dependencies=authed)
    def list_pins() -> Response:
        return dump(Pins(items=pins.load(state)))

    @app.put("/v1/pins", dependencies=authed)
    async def set_pins(request: Request) -> Response:
        """The whole list: pin, unpin and reorder are one call. Kept without what names nothing
        (a project deleted since the list was read, Chat) and each pin once: the list kept is
        the answer."""
        body = parse_body(Pins, await request.body())
        kept = [p for p in dict.fromkeys(body.items) if exists(ctx, p)]
        pins.save(state, kept)
        return dump(Pins(items=kept))


def exists(ctx: Context, pin: Pin) -> bool:
    if pin.kind == "project":
        return pin.id in ctx.projects.projects
    return pin.id in ctx.apps.records  # Chat is no app (apps.CHAT): it is never pinned
