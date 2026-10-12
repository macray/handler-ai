"""Addon routes for installing (G.5): the catalog handler ships, preview, install, remove. Listing
addons is in catalog.py (G.1), rebuilding their images in images.py (G.4)."""

import asyncio
import contextlib

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    AddonCatalogEntry,
    AddonInstalled,
    AddonInstallRequest,
    AddonPreviewRequest,
)
from handler_harness import addons as addon_catalog
from handler_harness import images

from .. import addon_install, bindings, runtime
from ..builds import ADDON_PREFIX, BuildBusyError
from .catalog import addon_info
from .common import Context, ProblemError, dump, log, parse_body


def catalog_entries() -> list[AddonCatalogEntry]:
    installed = addon_install.lock()
    entries = []
    for name in addon_catalog.catalog_names():
        addon = addon_catalog.load(addon_catalog.CATALOG_DIR / name)
        entries.append(
            AddonCatalogEntry(
                name=name,
                description=addon.manifest.description,
                installed=name in installed,
            )
        )
    return entries


def add_addon_install_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]
    settings = ctx.settings

    @app.get("/v1/addon-catalog", dependencies=authed)
    def addon_catalog_list() -> Response:
        return dump(catalog_entries())

    @app.post("/v1/addons/preview", dependencies=authed)
    async def preview_addon(request: Request) -> Response:
        """What installing from a source would add, without installing (the trust screen)."""
        body = parse_body(AddonPreviewRequest, await request.body())
        try:
            return dump(await asyncio.to_thread(addon_install.preview, settings, body.source))
        except addon_install.AddonInstallError as e:
            raise ProblemError(422, "cannot install the addon", str(e)) from None

    @app.post("/v1/addons/install", dependencies=authed)
    async def install_addon(request: Request) -> Response:
        body = parse_body(AddonInstallRequest, await request.body())
        try:
            name = await asyncio.to_thread(
                addon_install.install, settings, body.source, body.digest
            )
        except addon_install.AddonInstallError as e:
            raise ProblemError(422, "cannot install the addon", str(e)) from None
        log.info("addon %s installed from %s", name, body.source)
        info = await asyncio.to_thread(addon_info, name)
        build = None
        if info.image is not None:
            # another build running: built later (Settings → Images,
            # `handler image rebuild addon:<name>`)
            with contextlib.suppress(BuildBusyError):
                build = ctx.builds.start(f"{ADDON_PREFIX}{name}")
        return dump(AddonInstalled(addon=info, build=build), status=201)

    @app.delete("/v1/addons/{name}", dependencies=authed)
    async def remove_addon(name: str) -> Response:
        """An installed addon (G.5), while no binding uses it; its image goes if unused."""
        users = [
            b.name for b in bindings.load_all(settings.bindings_dir)
            if b.binding is not None and b.binding.addon == name
        ]  # fmt: skip
        if users:
            raise ProblemError(409, "addon in use by bindings", ", ".join(users))
        image = None
        if (directory := addon_catalog.locate(name)) is not None:
            image = addon_catalog.load(directory).manifest.image
        try:
            addon_install.remove(name)
        except addon_install.AddonInstallError as e:
            raise ProblemError(409, "not an installed addon", str(e)) from None
        if image is not None and (latest := runtime.inspect(images.ref(image, images.LATEST))):
            await asyncio.to_thread(runtime.remove, latest.id)
        log.info("addon %s removed", name)
        return Response(status_code=204)
