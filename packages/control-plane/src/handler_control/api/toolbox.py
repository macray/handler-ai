"""Toolbox routes (D.2, B.7): what it is made of and who needs what, its system packages, the
user's lines, the generated Containerfile, its builds (applying a change, or updating); what a
confirmed save adds to it (B.6)."""

from collections.abc import Iterable

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    Build,
    SystemPackagesRequest,
    ToolboxContainerfile,
    ToolboxLines,
    ToolboxRebuildRequest,
)
from handler_harness import catalog
from handler_harness import toolbox as toolbox_parts

from .. import toolbox
from ..builds import TOOLBOX_TARGET
from .common import Context, ProblemError, dump, log, parse_body
from .images import start_build


def apply_adds(ctx: Context, adds: list[str], waiting: Iterable[str] = ()) -> Build | None:
    """System packages confirmed by a save or an install (B.6) turned on, then the toolbox
    applied, now or after the build running; the addons `waiting` for it are built once it
    switches. None: nothing to add, or queued."""
    if not adds:
        return None
    try:
        toolbox.turn_on(ctx.registry, adds)
    except toolbox.ToolboxChangeError as e:
        raise ProblemError(409, "system packages refused", str(e)) from None
    log.info("system packages turned on, confirmed: %s", ", ".join(adds))
    ctx.builds.waiting.update(waiting)
    return ctx.builds.start_soon(TOOLBOX_TARGET)


def apply_confirmed(ctx: Context, confirmed: list[str], uses: Iterable[str] = ()) -> None:
    """After a save: the system packages what is in use needs that the client confirmed
    (`toolboxAdds`, checked by save_rules), turned on and applied; `uses`: the saved agents'
    addons, built once it switches."""
    if not confirmed:
        return
    lacking = toolbox.to_add(ctx.settings, toolbox.needs_in_use(ctx.registry))
    apply_adds(ctx, [n for n in lacking.adds if n in confirmed], uses)


def add_toolbox_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/toolbox", dependencies=authed)
    def get_toolbox() -> Response:
        return dump(toolbox.info(ctx.settings, ctx.registry))

    @app.get("/v1/toolbox/system-packages", dependencies=authed)
    def system_packages() -> Response:
        return dump(toolbox.system_packages())

    @app.put("/v1/toolbox/system-packages", dependencies=authed)
    async def set_system_packages(request: Request) -> Response:
        """Saved to toolbox.toml; the next toolbox build applies it (nothing is built here)."""
        body = parse_body(SystemPackagesRequest, await request.body())
        try:
            toolbox.set_system_packages(ctx.registry, body.system_packages)
        except toolbox.ToolboxInUseError as e:
            raise ProblemError(409, "system package in use", str(e)) from None
        except toolbox.ToolboxChangeError as e:
            raise ProblemError(400, "system packages refused", str(e)) from None
        log.info("system packages set through the API: %s", ", ".join(body.system_packages))
        return get_toolbox()

    @app.get("/v1/toolbox/lines", dependencies=authed)
    def toolbox_lines() -> Response:
        return dump(ToolboxLines(content=toolbox_parts.lines()))

    @app.put("/v1/toolbox/lines", dependencies=authed)
    async def save_toolbox_lines(request: Request) -> Response:
        """Saved whole; the next toolbox build uses them (nothing is built here)."""
        body = parse_body(ToolboxLines, await request.body())
        toolbox_parts.save_lines(body.content)
        return toolbox_lines()

    @app.get("/v1/toolbox/containerfile", dependencies=authed)
    def toolbox_containerfile() -> Response:
        """The generated one, read-only: what the next toolbox build builds."""
        try:
            content = toolbox_parts.containerfile(catalog.toolbox(), toolbox_parts.lines())
        except (OSError, ValueError) as e:  # toolbox.toml, a system package: ToolboxError
            raise ProblemError(409, "toolbox cannot be generated", str(e)) from None
        return dump(ToolboxContainerfile(content=content))

    @app.post("/v1/toolbox/rebuild", dependencies=authed)
    async def rebuild_toolbox(request: Request) -> Response:
        """Apply what changed (the default), or `update` (system updates); no body: apply."""
        raw = await request.body()
        body = parse_body(ToolboxRebuildRequest, raw) if raw else ToolboxRebuildRequest()
        return start_build(ctx, TOOLBOX_TARGET, body.update)
