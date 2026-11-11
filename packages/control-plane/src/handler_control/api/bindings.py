"""Binding routes: list, create, replace, delete (G.2, D.15)."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    BindingInfo,
    BindingRequest,
    StoreSecret,
)

from .. import (
    bindings,
    secrets,
)
from .common import Context, ProblemError, dump, log, parse_body


def binding_info(b: bindings.LoadedBinding, used_by: list[str]) -> BindingInfo:
    """Slot names only: secret references can name files or commands, clients don't need them."""
    if b.binding is None:
        return BindingInfo(name=b.name, error=b.error, used_by=used_by)
    bound = b.binding.secrets or {}
    return BindingInfo(
        name=b.name,
        addon=b.binding.tool,
        description=b.binding.description,
        settings=b.binding.settings or {},
        secrets=sorted(bound),
        hand_written=sorted(s for s, ref in bound.items() if not isinstance(ref, StoreSecret)),
        error=b.error,
        used_by=used_by,
    )


def binding_users(ctx: Context) -> dict[str, list[str]]:
    """The agents and projects that picked each binding (by their project and name, ad-hoc
    agents by id)."""
    found: dict[str, list[str]] = {}
    for record in ctx.registry.agents.values():
        project = ctx.projects.get(record.project_id) if record.project_id else None
        label = f"agents/{project.name}/{record.name}" if project else f"ad-hoc/{record.id}"
        for use in record.addons:
            if use.binding is not None:
                found.setdefault(use.binding, []).append(label)
    for project in ctx.projects.projects.values():
        for use in project.addons:
            if use.binding is not None:
                found.setdefault(use.binding, []).append(f"projects/{project.name}")
    return found


def add_binding_routes(app: FastAPI, ctx: Context) -> None:
    """G.2, D.15: written from the form (secret values go to the secret store), or by hand."""
    authed = [Depends(ctx.require_auth)]
    settings = ctx.settings
    store = secrets.SecretStore(settings.data_dir)

    def infos() -> list[BindingInfo]:
        users = binding_users(ctx)
        loaded = bindings.load_all(settings.bindings_dir)
        return [binding_info(b, users.get(b.name, [])) for b in loaded]

    def existing(name: str) -> bindings.LoadedBinding:
        loaded = bindings.get(settings.bindings_dir, name)
        if not loaded.path.is_file():
            raise ProblemError(404, "connection not found", name)
        return loaded

    @app.get("/v1/bindings", dependencies=authed)
    def list_bindings() -> Response:
        return dump(infos())

    @app.post("/v1/bindings", dependencies=authed)
    async def create_binding(request: Request) -> Response:
        body = parse_body(BindingRequest, await request.body())
        if bindings.get(settings.bindings_dir, body.name).path.is_file():
            raise ProblemError(409, "connection exists", body.name)
        try:
            bindings.save(settings.bindings_dir, store, body, None)
        except bindings.BindingError as e:
            raise ProblemError(422, "invalid connection", str(e)) from None
        log.info("connection %s created (%s)", body.name, body.addon)
        return dump(next(b for b in infos() if b.name == body.name), status=201)

    @app.put("/v1/bindings/{name}", dependencies=authed)
    async def replace_binding(name: str, request: Request) -> Response:
        """Replace it, and rename it while nothing selects it. Not its addon."""
        body = parse_body(BindingRequest, await request.body())
        old = existing(name)
        if body.name != name:
            if users := binding_users(ctx).get(name):
                raise ProblemError(409, "connection in use: cannot rename it", ", ".join(users))
            if bindings.get(settings.bindings_dir, body.name).path.is_file():
                raise ProblemError(409, "connection exists", body.name)
        try:
            bindings.save(settings.bindings_dir, store, body, old)
        except bindings.BindingError as e:
            raise ProblemError(422, "invalid connection", str(e)) from None
        log.info("connection %s saved", body.name)
        return dump(next(b for b in infos() if b.name == body.name))

    @app.delete("/v1/bindings/{name}", dependencies=authed)
    def delete_binding(name: str) -> Response:
        """It and its secrets in the store; refused while something selects it."""
        existing(name)
        if users := binding_users(ctx).get(name):
            raise ProblemError(409, "connection in use", ", ".join(users))
        bindings.delete(settings.bindings_dir, store, name)
        log.info("connection %s deleted", name)
        return Response(status_code=204)
