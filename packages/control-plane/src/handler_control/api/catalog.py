"""Catalog routes: health, harnesses (B.1), addons (G.1), knowledge folders (D.5), directories
for the folder picker."""

import asyncio
import contextlib
import os
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    AddonInfo,
    AddonSlot,
    AddonSlotInfo,
    CreateDirectoryRequest,
    CreateKnowledgeFolderRequest,
    HarnessDescriptor,
    HarnessInfo,
    Health,
    SetKnowledgeRootRequest,
)
from handler_harness import addons as addon_catalog
from handler_harness import catalog, images

from .. import (
    __version__,
    addon_install,
    display,
    folders,
    knowledge,
    runtime,
    webui,
)
from .common import (
    Context,
    ProblemError,
    dump,
    knowledge_problems,
    parse_body,
)


def add_catalog_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/runtime", dependencies=authed)
    async def runtime_check() -> Response:
        """Can this host run sandboxes (A.8): `handler setup` and the web UI show it."""
        return dump(await asyncio.to_thread(runtime.check))

    @app.get("/v1/health")
    def health() -> Response:
        return dump(Health(status="ok", version=__version__, display=display.available()))

    @app.get("/v1/harnesses", dependencies=authed)
    async def list_harnesses() -> Response:
        # one runtime process per image: run together, not one after another
        harnesses = catalog.all_harnesses()
        return dump(
            list(await asyncio.gather(*(asyncio.to_thread(harness_info, h) for h in harnesses)))
        )

    @app.get("/v1/addons", dependencies=authed)
    async def list_addons() -> Response:
        return dump(await asyncio.to_thread(addon_infos))

    @app.get("/v1/knowledge", dependencies=authed)
    def list_knowledge() -> Response:
        return dump(knowledge.listing(*knowledge.root(ctx.settings)))

    @app.put("/v1/knowledge/root", dependencies=authed)
    async def set_knowledge_root(request: Request) -> Response:
        body = parse_body(SetKnowledgeRootRequest, await request.body())
        with knowledge_problems():
            knowledge.set_root(ctx.settings, body.root, body.create)
        return dump(knowledge.listing(*knowledge.root(ctx.settings)))

    @app.post("/v1/knowledge/folders", dependencies=authed)
    async def create_knowledge_folder(request: Request) -> Response:
        body = parse_body(CreateKnowledgeFolderRequest, await request.body())
        with knowledge_problems():
            knowledge.create_folder(knowledge.root(ctx.settings)[0], body.path)
        return dump(knowledge.listing(*knowledge.root(ctx.settings)), status=201)

    @app.get("/v1/knowledge/browse", dependencies=authed)
    def browse_knowledge(path: str = ".") -> Response:
        with knowledge_problems():
            return dump(knowledge.browse(knowledge.root(ctx.settings)[0], path))

    @app.get("/v1/knowledge/note", dependencies=authed)
    def read_knowledge_note(path: str) -> Response:
        with knowledge_problems():
            return dump(knowledge.read_note(knowledge.root(ctx.settings)[0], path))

    @app.get("/v1/directories", dependencies=authed)
    def list_directories(path: str | None = None) -> Response:
        try:
            return dump(webui.list_directories(folders.roots(ctx.settings), path))
        except webui.OutsideRootsError as e:
            raise ProblemError(403, "path not allowed", str(e)) from None

    @app.post("/v1/directories", dependencies=authed)
    async def create_directory(request: Request) -> Response:
        body = parse_body(CreateDirectoryRequest, await request.body())
        try:
            roots = folders.roots(ctx.settings)
            return dump(webui.create_directory(roots, body.parent, body.name), status=201)
        except webui.OutsideRootsError as e:
            raise ProblemError(403, "path not allowed", str(e)) from None
        except webui.DirectoryExistsError as e:
            raise ProblemError(409, "folder exists", str(e)) from None


def addon_infos() -> list[AddonInfo]:
    infos = []
    for name in addon_catalog.names():
        with contextlib.suppress(addon_catalog.UnknownAddonError):  # removed since listed
            infos.append(addon_info(name))
    return infos


def harness_info(h: catalog.Harness) -> HarnessInfo:
    """What `:latest` of the harness image holds — blocking calls to the runtime."""
    latest = runtime.inspect(images.ref(h.descriptor.image, images.LATEST))
    return HarnessInfo(
        name=h.name,
        product=h.descriptor.product,
        image=h.descriptor.image,
        image_present=latest is not None,
        version=runtime.version(latest.id, images.version_file(h)) if latest else None,
        built_at=latest.created if latest else None,
        provider_protocols=list(h.descriptor.provider_protocols),
        login=h.descriptor.login,
        login_file=login_file(h.descriptor),
        permissions=list(h.descriptor.permissions),
        session_modes={
            mode: m.session_mode for mode, m in h.descriptor.permissions.items() if m.session_mode
        },
        account_connectors=h.descriptor.account_connectors is not None,
    )


def login_file(descriptor: HarnessDescriptor) -> str | None:
    """A file login's file name, in the folder its login writes to (D.9)."""
    login = descriptor.login
    if login is None or login.file is None:
        return None
    return os.path.basename(descriptor.state_slots[login.file].target)


def addon_info(name: str) -> AddonInfo:
    """An addon and what `:latest` of its image holds — blocking calls to the runtime."""
    directory = str(addon_catalog.locate(name))
    try:
        addon = addon_catalog.get(name)
    except addon_catalog.InvalidAddonError as e:
        return AddonInfo(name=name, error=str(e), directory=directory)
    m = addon.manifest
    info = AddonInfo(
        name=m.name,
        description=m.description,
        image=m.image,
        commands=m.commands,
        skills=[s.name for s in addon.skills],
        settings=[slot_info(n, slot) for n, slot in sorted(m.settings.items())],
        secret_slots=[slot_info(n, slot) for n, slot in sorted(m.secret_slots.items())],
        egress=m.egress,
        directory=directory,
        builtin=addon.builtin,
        overrides_builtin=addon.overrides_builtin,
        **installed_from(addon),
    )
    if m.image is None:
        return info
    latest = runtime.inspect(images.ref(m.image, images.LATEST))
    return info.model_copy(
        update={
            "image_present": latest is not None,
            "version": runtime.version(latest.id, images.version_file(addon)) if latest else None,
            "built_at": latest.created if latest else None,
        }
    )


def installed_from(addon: addon_catalog.Addon) -> dict[str, Any]:
    """Where an installed addon came from (G.5), and whether the catalog now ships other content."""
    entry = None if addon.builtin else addon_install.lock().get(addon.name)
    if entry is None:
        return {}
    catalog = entry.source.startswith(addon_install.CATALOG_PREFIX)
    changed = catalog and addon_install.catalog_digest(addon.name) not in (None, entry.digest)
    return {"source": entry.source, "update_available": changed}


def slot_info(name: str, slot: AddonSlot) -> AddonSlotInfo:
    return AddonSlotInfo(name=name, required=slot.required, description=slot.description)
