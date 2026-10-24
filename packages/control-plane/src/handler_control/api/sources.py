"""Source routes (D.26): the git repositories Handler reads to offer apps, agents and addons; what
each offers, read with that kind's own rules, with a few words on what each does (its notes) and
its page (its README and manifest); an app taken from one, an agents file's agents read from one
for their set-up page. An addon from one goes through its preview (G.5:
`source:<source>/<name>`)."""

import asyncio
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    AddonManifest,
    AddSourceRequest,
    AgentsFile,
    AppManifest,
    Source,
    SourceItem,
    SourceItemDetail,
    SourceNote,
)
from handler_harness import addons as addon_catalog

from .. import addon_install, agents_files, sources
from ..apps import AppError, read_manifest
from .apps import app_problems
from .common import Context, ProblemError, dump, parse_body


def problem(e: sources.SourceError) -> ProblemError:
    return ProblemError(e.status, e.title, str(e))


def add_source_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]
    settings = ctx.settings

    @app.get("/v1/sources", dependencies=authed)
    async def list_sources() -> Response:
        """Each source as read last; one never read, or not for a day, read again first."""
        listed = sources.listed(settings)
        stale = [s for s in listed if sources.stale(settings, s.id)]
        await asyncio.gather(*(asyncio.to_thread(sources.fetch, settings, s) for s in stale))
        return dump(await asyncio.to_thread(lambda: [view(ctx, s) for s in listed]))

    @app.post("/v1/sources", dependencies=authed)
    async def add_source(request: Request) -> Response:
        body = parse_body(AddSourceRequest, await request.body())
        try:
            added = await asyncio.to_thread(sources.add, settings, body.url)
        except sources.SourceError as e:
            raise problem(e) from None
        return dump(await asyncio.to_thread(view, ctx, added), status=201)

    @app.post("/v1/sources/{source_id}/refresh", dependencies=authed)
    async def refresh_source(source_id: str) -> Response:
        try:
            source = sources.get(settings, source_id)
        except sources.SourceError as e:
            raise problem(e) from None
        await asyncio.to_thread(sources.fetch, settings, source)
        return dump(await asyncio.to_thread(view, ctx, source))

    @app.delete("/v1/sources/{source_id}", dependencies=authed)
    def remove_source(source_id: str) -> Response:
        try:
            sources.remove(settings, source_id)
        except sources.SourceError as e:
            raise problem(e) from None
        return Response(status_code=204)

    add_source_item_routes(app, ctx)


def add_source_item_routes(app: FastAPI, ctx: Context) -> None:
    """What one source offers: an item's page, an app taken, agents read."""
    authed = [Depends(ctx.require_auth)]
    settings = ctx.settings

    @app.get("/v1/sources/{source_id}/{kind}/{name}", dependencies=authed)
    async def source_item(source_id: str, kind: str, name: str) -> Response:
        """An item's page: its README and what its manifest says, before anything is installed."""
        if kind not in KINDS:
            raise ProblemError(404, "unknown kind", f"{kind}: apps, agents or addons")
        try:
            return dump(await asyncio.to_thread(detail, ctx, source_id, KINDS[kind], name))
        except sources.SourceError as e:
            raise problem(e) from None
        except addon_install.AddonInstallError as e:
            raise ProblemError(409, "not offered", str(e)) from None

    @app.post("/v1/sources/{source_id}/apps/{name}", dependencies=authed)
    async def app_from_source(source_id: str, name: str) -> Response:
        """Its code taken (H.15): a new app (201, its install page next), or the next version
        of one you have (200, its page offers to deploy it)."""
        try:
            folder = sources.item(settings, source_id, "app", name)
        except sources.SourceError as e:
            raise problem(e) from None
        with app_problems("cannot take this app"):
            record, new = ctx.apps.add_from_source(source_id, folder)
            return dump(ctx.apps.view(record.name), status=201 if new else 200)

    @app.post("/v1/sources/{source_id}/agents/{name}", dependencies=authed)
    async def agents_from_source(source_id: str, name: str) -> Response:
        """Read as an agents file is (D.23): its set-up page next, by its name."""
        try:
            folder = sources.item(settings, source_id, "agents", name)
            return dump(agents_files.stage_folder(settings, folder), status=201)
        except sources.SourceError as e:
            raise problem(e) from None
        except agents_files.AgentsFileError as e:
            raise ProblemError(e.status, e.title, str(e)) from None


KINDS: dict[str, sources.SourceKind] = {"apps": "app", "agents": "agents", "addons": "addon"}
MAX_README = 256 * 1024


def detail(ctx: Context, source_id: str, kind: sources.SourceKind, name: str) -> SourceItemDetail:
    listed = sources.get(ctx.settings, source_id)
    found = next((f for f in sources.items(ctx.settings, source_id) if f[:2] == (kind, name)), None)
    if found is None:
        raise sources.SourceError(404, "unknown item", f"{source_id} offers no {kind} named {name}")
    item, folder = offered(ctx, source_id, found), found[2]
    page = SourceItemDetail(source=view(ctx, listed, items=False), item=item)
    if folder is None or item.error:
        return page
    readme = folder / "README.md"
    text = readme.read_text(errors="replace")[:MAX_README] if readme.is_file() else None
    extra: dict[str, object] = {"readme": text}
    if kind == "app":
        extra["app"] = read_manifest(folder)
    elif kind == "agents":
        extra["agents"] = agents_files.read(folder)
    else:
        extra["addon"] = addon_install.preview(ctx.settings, f"source:{source_id}/{name}")
    return page.model_copy(update=extra)


def view(ctx: Context, source: sources.Listed, items: bool = True) -> Source:
    state = sources.read(ctx.settings, source.id)
    return Source(
        id=source.id,
        url=source.url,
        official=source.official,
        name=state.manifest.name if state.manifest else None,
        description=state.manifest.description if state.manifest else None,
        commit=state.commit,
        fetched_at=state.fetched_at,
        error=state.error,
        items=[offered(ctx, source.id, f) for f in sources.items(ctx.settings, source.id)]
        if items
        else [],
    )


def offered(ctx: Context, source_id: str, found: sources.Found) -> SourceItem:
    """One item, read with its kind's rules: an error says why it is not offered."""
    kind, name, folder, why = found
    if folder is None:
        return SourceItem(kind=kind, name=name, error=why)
    try:
        if kind == "app":
            return app_item(ctx, source_id, name, folder)
        if kind == "agents":
            file = agents_files.read(folder)
            return SourceItem(
                kind=kind,
                name=name,
                description=file.description,
                version=str(file.version),
                notes=agents_notes(file),
            )
        return addon_item(source_id, name, folder)
    except (AppError, ValueError) as e:  # an addon's InvalidAddonError is a ValueError
        return SourceItem(kind=kind, name=name, error=str(e))


def app_item(ctx: Context, source_id: str, name: str, folder: Path) -> SourceItem:
    """Installed: an app of that name; an update: its code came from this source, which now
    holds another version."""
    manifest = read_manifest(folder)
    if manifest.name != name:
        raise AppError(f"its app.toml names another app, {manifest.name}")
    record = ctx.apps.records.get(name)
    update = False
    if record is not None and record.from_source == source_id:
        try:
            update = read_manifest(ctx.apps.source(name)).version != manifest.version
        except AppError:
            update = True  # its copy unreadable: the source's would replace it
    return SourceItem(
        kind="app",
        name=name,
        description=manifest.description,
        version=manifest.version,
        installed=record is not None,
        update=update,
        notes=app_notes(manifest),
    )


def addon_item(source_id: str, name: str, folder: Path) -> SourceItem:
    """Installed: an addon of that name was (G.5); an update: from this source, which now holds
    other content."""
    addon = addon_catalog.load(folder)
    if addon.manifest.name != name:
        raise ValueError(f"its addon.toml names another addon, {addon.manifest.name}")
    entry = addon_install.lock().get(name)
    here = f"{addon_install.SOURCE_PREFIX}{source_id}/{name}"
    return SourceItem(
        kind="addon",
        name=name,
        description=addon.manifest.description,
        installed=entry is not None,
        update=entry is not None
        and entry.source == here
        and addon_install.digest(folder) != entry.digest,
        notes=addon_notes(addon.manifest),
    )


# ── notes: what an item does, in a few words, the weakening ones first ──


def count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def ordered(notes: list[SourceNote]) -> list[SourceNote]:
    return sorted(notes, key=lambda n: not n.weakens)


def app_notes(manifest: AppManifest) -> list[SourceNote]:
    needs = manifest.needs
    notes = [
        SourceNote(text=f"reaches {count(len(needs.egress), 'site', 'sites')}", weakens=True)
        if needs.egress
        else None,
        SourceNote(text=f"uses {count(len(needs.files), 'folder', 'folders')} of yours")
        if needs.files
        else SourceNote(text="only its own data"),
        SourceNote(text=f"brings {count(len(needs.agents), 'agent', 'agents')}")
        if needs.agents
        else None,
        SourceNote(text=f"asks for {count(len(needs.secrets), 'secret', 'secrets')}")
        if needs.secrets
        else None,
        SourceNote(text="notifies you") if needs.notify else None,
    ]
    return ordered([n for n in notes if n is not None])


def addon_notes(manifest: AddonManifest) -> list[SourceNote]:
    notes = [
        SourceNote(text=f"reaches {count(len(manifest.egress), 'site', 'sites')}", weakens=True)
        if manifest.egress
        else None,
        SourceNote(text="builds an image on this computer", weakens=True)
        if manifest.image
        else None,
        SourceNote(text=f"asks for {count(len(manifest.secret_slots), 'secret', 'secrets')}")
        if manifest.secret_slots
        else None,
    ]
    return ordered([n for n in notes if n is not None]) or [SourceNote(text="skills only")]


def agents_notes(file: AgentsFile) -> list[SourceNote]:
    defs = [a.definition for a in file.agents]
    hosts = {e for d in defs for e in d.allow}
    addons = sorted({a for d in defs for a in d.addons})
    notes = [
        SourceNote(text=count(len(defs), "agent", "agents")),
        SourceNote(text="reaches any host", weakens=True)
        if any(d.network == "open" for d in defs)
        else SourceNote(
            text=f"reaches {count(len(hosts), 'more site', 'more sites')}", weakens=True
        )
        if hosts
        else None,
        SourceNote(text="runs containers", weakens=True)
        if any(d.confinement != "strict" for d in defs)
        else None,
        SourceNote(text="uses your screen", weakens=True) if any(d.display for d in defs) else None,
        SourceNote(text=f"needs {', '.join(addons)}") if addons else None,
    ]
    return ordered([n for n in notes if n is not None])
