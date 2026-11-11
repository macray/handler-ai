"""Addon routes for installing (G.5): preview, install, remove. What sources offer is in
sources.py (D.26), listing addons in catalog.py (G.1), rebuilding their images in images.py
(G.4)."""

import asyncio
import contextlib

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    AddonInstalled,
    AddonInstallRequest,
    AddonPreviewRequest,
)
from handler_harness import addons as addon_catalog

from .. import addon_folders, addon_install, bindings, toolbox
from ..agents import addons_in_use
from ..builds import ADDON_PREFIX, BuildBusyError
from ..settings import Settings
from .catalog import addon_info
from .common import Context, ProblemError, dump, log, parse_body
from .toolbox import apply_adds


def add_addon_install_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]
    settings = ctx.settings

    @app.post("/v1/addons/preview", dependencies=authed)
    async def preview_addon(request: Request) -> Response:
        """What installing from a source would add, without installing (the trust screen)."""
        body = parse_body(AddonPreviewRequest, await request.body())
        try:
            return dump(await asyncio.to_thread(addon_install.preview, settings, body.source))
        except addon_install.AddonInstallError as e:
            raise ProblemError(422, "cannot install the tool", str(e)) from None

    @app.post("/v1/addons/install", dependencies=authed)
    async def install_addon(request: Request) -> Response:
        """The addon with the system packages it adds (confirmed: `toolboxAdds`), which are then
        turned on and the toolbox applied; its image is built once the toolbox gives what it
        needs (B.6), at once when it does."""
        body = parse_body(AddonInstallRequest, await request.body())
        try:
            installed = await asyncio.to_thread(
                addon_install.install, settings, body.source, body.digest, body.toolbox_adds
            )
        except addon_install.ToolboxNotConfirmedError as e:
            raise ProblemError(
                409, "toolbox changes not confirmed", str(e), toolbox_adds=e.adds
            ) from None
        except addon_install.AddonInstallError as e:
            raise ProblemError(422, "cannot install the tool", str(e)) from None
        name = installed.name
        log.info("tool %s installed from %s", name, body.source)
        build = None
        image = (await asyncio.to_thread(addon_info, settings, ctx.builds, name)).image
        if installed.adds:
            build = apply_adds(ctx, installed.adds, [name] if image else [])
        elif image is not None and not await asyncio.to_thread(needs_lacking, settings, name):
            # another build running: built later (Settings → Sandboxes,
            # `handler image rebuild addon:<name>`)
            with contextlib.suppress(BuildBusyError):
                build = ctx.builds.start(f"{ADDON_PREFIX}{name}")
        elif image is not None:  # built once the toolbox gives what it needs
            ctx.builds.waiting.add(name)
        info = await asyncio.to_thread(addon_info, settings, ctx.builds, name)
        return dump(AddonInstalled(addon=info, build=build), status=201)

    @app.delete("/v1/addons/{name}", dependencies=authed)
    async def remove_addon(name: str) -> Response:
        """An installed addon (G.5), while no agent, project or binding uses it; its folders go
        once no sandbox mounts them."""
        if agents := addons_in_use(list(ctx.registry.agents.values())).get(name):
            raise ProblemError(409, "tool in use by agents", ", ".join(agents))
        projects = ctx.projects.projects.values()
        if givers := [p.name for p in projects if any(u.addon == name for u in p.addons)]:
            raise ProblemError(409, "tool in use by projects", ", ".join(givers))
        users = [
            b.name for b in bindings.load_all(settings.bindings_dir)
            if b.binding is not None and b.binding.tool == name
        ]  # fmt: skip
        if users:
            raise ProblemError(409, "tool in use by connections", ", ".join(users))
        try:
            addon_install.remove(name)
        except addon_install.AddonInstallError as e:
            raise ProblemError(409, "not an installed tool", str(e)) from None
        await asyncio.to_thread(addon_folders.forget, settings, name)
        log.info("tool %s removed", name)
        return Response(status_code=204)


def needs_lacking(settings: Settings, name: str) -> list[str]:
    """The addon's needs the toolbox built now does not give."""
    record = toolbox.read_record(settings)
    commands = record.commands if record else {}
    return [c for c in addon_catalog.get(name).manifest.needs if c not in commands]
