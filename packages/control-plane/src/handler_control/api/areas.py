"""D.19: areas (areas.py): list, create, change the colour of, delete."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import ANY_AREA, AreaInfo, AreaRequest

from .. import accounts, areas, providers
from .common import Context, ProblemError, dump, parse_body


def add_area_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]
    settings = ctx.settings

    @app.get("/v1/areas", dependencies=authed)
    def list_areas() -> Response:
        return dump(area_infos(ctx))

    @app.post("/v1/areas", dependencies=authed)
    async def create_area(request: Request) -> Response:
        body = parse_body(AreaRequest, await request.body())
        known = areas.load(settings)
        if any(n.lower() == body.name.lower() for n in known):
            raise ProblemError(409, "area exists", body.name)
        areas.save(settings, known | {body.name: body.color})
        return dump(info(ctx, body.name), status=201)

    @app.put("/v1/areas/{name}", dependencies=authed)
    async def update_area(name: str, request: Request) -> Response:
        body = parse_body(AreaRequest, await request.body())
        known = known_or_404(ctx, name)
        if body.name != name:
            raise ProblemError(409, "an area's name cannot change", name)
        areas.save(settings, known | {name: body.color})
        return dump(info(ctx, name))

    @app.delete("/v1/areas/{name}", dependencies=authed)
    def delete_area(name: str) -> Response:
        """Refused while a project, an account or a provider names it."""
        known = known_or_404(ctx, name)
        used = info(ctx, name)
        if users := [*used.projects, *used.accounts, *used.providers]:
            raise ProblemError(409, "area in use", ", ".join(users))
        areas.save(settings, {n: c for n, c in known.items() if n != name})
        return Response(status_code=204)


def known_or_404(ctx: Context, name: str) -> dict[str, str]:
    known = areas.load(ctx.settings)
    if name not in known:
        raise ProblemError(404, "area not found", name)
    return known


def check_areas(ctx: Context, names: list[str]) -> None:
    """An account's or a provider's areas: each one that exists, or `any` (400 otherwise)."""
    known = areas.load(ctx.settings)
    if unknown := [n for n in names if n != ANY_AREA and n not in known]:
        raise ProblemError(400, "unknown area", ", ".join(unknown))


def info(ctx: Context, name: str) -> AreaInfo:
    return next(i for i in area_infos(ctx) if i.name == name)


def area_infos(ctx: Context) -> list[AreaInfo]:
    """The areas, each with what is in it or made for it."""
    settings = ctx.settings
    projects = list(ctx.projects.projects.values())
    made = [
        (a.name, a.account.areas) for a in accounts.load_all(settings.accounts_dir) if a.account
    ]
    given = [
        (p.name, p.provider.areas) for p in providers.load_all(settings.providers_dir) if p.provider
    ]
    return [
        AreaInfo(
            name=name,
            color=color,  # ty: ignore[invalid-argument-type] — checked against AreaColor by load
            projects=sorted(p.name for p in projects if p.area == name),
            accounts=[a for a, used in made if name in used],
            providers=[p for p, used in given if name in used],
        )
        for name, color in areas.load(settings).items()
    ]
