"""D.19: project contexts (contexts.py): list, create, change the colour of, delete."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import ANY_CONTEXT, ContextInfo, ContextRequest

from .. import accounts, contexts, providers
from .common import Context, ProblemError, dump, parse_body


def add_context_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]
    settings = ctx.settings

    @app.get("/v1/contexts", dependencies=authed)
    def list_contexts() -> Response:
        return dump(context_infos(ctx))

    @app.post("/v1/contexts", dependencies=authed)
    async def create_context(request: Request) -> Response:
        body = parse_body(ContextRequest, await request.body())
        known = contexts.load(settings)
        if any(n.lower() == body.name.lower() for n in known):
            raise ProblemError(409, "context exists", body.name)
        contexts.save(settings, known | {body.name: body.color})
        return dump(info(ctx, body.name), status=201)

    @app.put("/v1/contexts/{name}", dependencies=authed)
    async def update_context(name: str, request: Request) -> Response:
        body = parse_body(ContextRequest, await request.body())
        known = known_or_404(ctx, name)
        if body.name != name:
            raise ProblemError(409, "a context's name cannot change", name)
        contexts.save(settings, known | {name: body.color})
        return dump(info(ctx, name))

    @app.delete("/v1/contexts/{name}", dependencies=authed)
    def delete_context(name: str) -> Response:
        """Refused while a project, an account or a provider names it."""
        known = known_or_404(ctx, name)
        used = info(ctx, name)
        if users := [*used.projects, *used.accounts, *used.providers]:
            raise ProblemError(409, "context in use", ", ".join(users))
        contexts.save(settings, {n: c for n, c in known.items() if n != name})
        return Response(status_code=204)


def known_or_404(ctx: Context, name: str) -> dict[str, str]:
    known = contexts.load(ctx.settings)
    if name not in known:
        raise ProblemError(404, "context not found", name)
    return known


def check_contexts(ctx: Context, names: list[str]) -> None:
    """An account's or a provider's contexts: each one that exists, or `any` (400 otherwise)."""
    known = contexts.load(ctx.settings)
    if unknown := [n for n in names if n != ANY_CONTEXT and n not in known]:
        raise ProblemError(400, "unknown context", ", ".join(unknown))


def info(ctx: Context, name: str) -> ContextInfo:
    return next(i for i in context_infos(ctx) if i.name == name)


def context_infos(ctx: Context) -> list[ContextInfo]:
    """The contexts, each with what is in it or made for it."""
    settings = ctx.settings
    projects = list(ctx.projects.projects.values())
    made = [
        (a.name, a.account.contexts) for a in accounts.load_all(settings.accounts_dir) if a.account
    ]
    given = [
        (p.name, p.provider.contexts)
        for p in providers.load_all(settings.providers_dir)
        if p.provider
    ]
    return [
        ContextInfo(
            name=name,
            color=color,  # ty: ignore[invalid-argument-type] — checked against ContextColor by load
            projects=sorted(p.name for p in projects if p.context == name),
            accounts=[a for a, used in made if name in used],
            providers=[p for p, used in given if name in used],
        )
        for name, color in contexts.load(settings).items()
    ]
