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
    ChooseRuntimeRequest,
    CreateDirectoryRequest,
    CreateKnowledgeFolderRequest,
    HarnessDescriptor,
    HarnessInfo,
    Health,
    SandboxRuntime,
    SetKnowledgeRootRequest,
)
from handler_harness import addons as addon_catalog
from handler_harness import catalog, images

from .. import (
    __version__,
    addon_folders,
    addon_install,
    display,
    folders,
    knowledge,
    runtime,
    sandbox_process,
    toolbox,
    webui,
)
from ..builds import BuildStore
from ..settings import Settings
from .common import (
    Context,
    ProblemError,
    dump,
    knowledge_problems,
    parse_body,
)


def running(ctx: Context) -> str:
    """What runs in the current runtime, in words; "" when nothing does."""
    found = []
    if (
        ctx.sessions.live
        or ctx.sessions.starting
        or any(a.connections for a in ctx.registry.agents.values())
    ):
        found.append("agents")
    if ctx.apps.live or ctx.apps.starting:
        found.append("apps")
    if ctx.builds.running:
        found.append("an image build")
    return ", ".join(found)


def add_catalog_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/runtime", dependencies=authed)
    async def runtime_check() -> Response:
        """Can this host run sandboxes (A.8): `handler setup` and the web UI show it."""
        return dump(await asyncio.to_thread(runtime.check))

    @app.get("/v1/runtimes", dependencies=authed)
    async def list_runtimes() -> Response:
        """The sandbox runtimes installed here, the one in use marked, each with its host check
        (A.8): what switching to it would give (D.2)."""
        current = sandbox_process.current()
        names = sorted({*sandbox_process.installed(), current})
        checks = await asyncio.gather(*(asyncio.to_thread(runtime.check_of, n) for n in names))
        return dump(
            [
                SandboxRuntime(name=n, current=n == current, check=c)
                for n, c in zip(names, checks, strict=True)
            ]
        )

    @app.put("/v1/runtime", dependencies=authed)
    async def choose_runtime(request: Request) -> Response:
        """Use another runtime (D.2): refused while anything runs in the current one, whose
        sandboxes and images the other does not see. Its host check (A.8) is the answer."""
        body = parse_body(ChooseRuntimeRequest, await request.body())
        if body.name != sandbox_process.current():
            if busy := running(ctx):
                raise ProblemError(409, "sandboxes running", f"stop them first: {busy}")
            try:
                runtime.choose(ctx.settings, body.name)
            except runtime.ForAnotherSystemError as e:
                raise ProblemError(404, "runtime for another system", str(e)) from None
            except runtime.RuntimeChoiceError as e:
                raise ProblemError(404, "runtime not installed", str(e)) from None
            ctx.updates.runtime_chosen()  # its own images: the filter, the tools in use (D.4)
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
        return dump(await asyncio.to_thread(addon_infos, ctx.settings, ctx.builds))

    @app.get("/v1/knowledge", dependencies=authed)
    def list_knowledge() -> Response:
        return dump(knowledge.listing(*knowledge.root(ctx.settings)))

    @app.get("/v1/knowledge/check", dependencies=authed)
    def check_knowledge_root(path: str) -> Response:
        with knowledge_problems():
            return dump(knowledge.check_root(path))

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

    add_directory_routes(app, ctx)


def add_directory_routes(app: FastAPI, ctx: Context) -> None:
    """The folder pickers' (D.13): a folder's sub-folders, those changed last, a new folder."""
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/directories", dependencies=authed)
    def list_directories(path: str | None = None) -> Response:
        try:
            return dump(webui.list_directories(folders.roots(ctx.settings), path))
        except webui.OutsideRootsError as e:
            raise ProblemError(403, "path not allowed", str(e)) from None

    @app.get("/v1/directories/recent", dependencies=authed)
    def recent_directories() -> Response:
        return dump(webui.recent_directories(folders.roots(ctx.settings)))

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


def addon_infos(settings: Settings, builds: BuildStore) -> list[AddonInfo]:
    infos = []
    for name in addon_catalog.names():
        with contextlib.suppress(addon_catalog.UnknownAddonError):  # removed since listed
            infos.append(addon_info(settings, builds, name))
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


def addon_info(settings: Settings, builds: BuildStore, name: str) -> AddonInfo:
    """An addon, what its folder holds (its image extracted, addon_folders), its state (G.5)."""
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
        needs=m.needs,
        caches=m.caches,
        skills=[s.name for s in addon.skills],
        settings=[slot_info(n, slot) for n, slot in sorted(m.settings.items())],
        secret_slots=[slot_info(n, slot) for n, slot in sorted(m.secret_slots.items())],
        egress=m.egress,
        directory=directory,
        builtin=addon.builtin,
        overrides_builtin=addon.overrides_builtin,
        **installed_from(settings, addon),
    )
    built = m.image is None or addon_folders.built(settings, name)
    record = toolbox.read_record(settings)
    lacking = [c for c in m.needs if record is None or c not in record.commands]
    state, detail = builds.addon_state(name, built and not lacking)
    if state == "installed":
        detail = not_ready(settings, lacking, built)
    info = info.model_copy(update={"state": state, "state_detail": detail})
    if m.image is None:
        return info
    return info.model_copy(
        update={
            "image_present": addon_folders.built(settings, name),
            "version": addon_folders.version(settings, addon),
            "built_at": addon_folders.built_at(settings, name),
        }
    )


def not_ready(settings: Settings, lacking: list[str], built: bool) -> str | None:
    """Why an addon no build prepares is not ready: what the toolbox lacks of its needs (and
    what would give it), its tool not built."""
    if lacking:
        found = toolbox.to_add(settings, [toolbox.Need((c,), "") for c in lacking])
        why = [f"{', '.join(c)}: turn on the system package {n}" for n, c in found.adds.items()]
        why += [f"{c}: no system package gives it, add it to your lines" for c in found.unprovided]
        if not why:  # given by what is on, not applied yet
            return f"needs {', '.join(lacking)}: apply the toolbox"
        return f"the toolbox lacks {'; '.join(why)}"
    return None if built else "not built yet"


def installed_from(settings: Settings, addon: addon_catalog.Addon) -> dict[str, Any]:
    """Where an installed addon came from (G.5), and whether its source (D.26), as read last,
    now holds other content."""
    entry = None if addon.builtin else addon_install.lock().get(addon.name)
    if entry is None:
        return {}
    from_source = entry.source.startswith(addon_install.SOURCE_PREFIX)
    now = addon_install.source_digest(settings, entry.source) if from_source else None
    return {"source": entry.source, "update_available": now not in (None, entry.digest)}


def slot_info(name: str, slot: AddonSlot) -> AddonSlotInfo:
    return AddonSlotInfo(name=name, required=slot.required, description=slot.description)
