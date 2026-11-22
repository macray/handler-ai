"""The Library's schemas (D.29): one per `$id`, added and removed by the person only."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import SchemaInfo, SchemaRequest

from .. import knowledge_schemas
from .common import Context, ProblemError, dump, log, parse_body


def schema_info(schema: knowledge_schemas.LoadedSchema, content: bool = False) -> SchemaInfo:
    t = schema.typedef
    return SchemaInfo(
        id=schema.id,
        title=t.title if t else None,
        description=(t.description or None) if t else None,
        extends=t.extends if t else None,
        error=schema.error,
        content=knowledge_schemas.text(schema) if content else None,
    )


def add_schema_routes(app: FastAPI, ctx: Context) -> None:
    """Library → Schemas (knowledge_schemas.py): an agent gets those of its knowledge uses,
    read-only; none is ever written from a sandbox."""
    authed = [Depends(ctx.require_auth)]
    folder = ctx.settings.schemas_dir

    def existing(schema_id: str) -> knowledge_schemas.LoadedSchema:
        try:
            return knowledge_schemas.get(folder, schema_id)
        except knowledge_schemas.SchemaError:
            raise ProblemError(404, "schema not found", schema_id) from None

    @app.get("/v1/schemas", dependencies=authed)
    def list_schemas() -> Response:
        return dump([schema_info(s) for s in knowledge_schemas.load_all(folder)])

    @app.get("/v1/schemas/{schema_id}", dependencies=authed)
    def read_schema(schema_id: str) -> Response:
        return dump(schema_info(existing(schema_id), content=True))

    @app.post("/v1/schemas", dependencies=authed)
    async def add_schema(request: Request) -> Response:
        """A schema into the Library, under its `$id` (201); the same one already there: 200,
        nothing changed; a different one: 409 unless `replace`."""
        body = parse_body(SchemaRequest, await request.body())
        try:
            schema_id, changed = knowledge_schemas.add(folder, body.content, replace=body.replace)
        except knowledge_schemas.SchemaClashError as e:
            raise ProblemError(409, "schema exists", str(e)) from None
        except knowledge_schemas.SchemaError as e:
            raise ProblemError(422, "not a schema", str(e)) from None
        if changed:
            log.info("schema %s %s", schema_id, "replaced" if body.replace else "added")
        return dump(schema_info(existing(schema_id), content=True), status=201 if changed else 200)

    @app.delete("/v1/schemas/{schema_id}", dependencies=authed)
    def delete_schema(schema_id: str) -> Response:
        """Its file (204); 409 while an agent uses it or another schema extends it."""
        existing(schema_id)
        users = sorted(
            a.name or a.id
            for a in ctx.registry.agents.values()
            if any(u.schema_id == schema_id for u in a.schemas)
        )
        if users:
            raise ProblemError(409, "schema in use by agents", ", ".join(users))
        children = [
            s.id
            for s in knowledge_schemas.load_all(folder)
            if s.typedef and s.typedef.extends == schema_id
        ]
        if children:
            raise ProblemError(409, "schema extended", ", ".join(children))
        knowledge_schemas.remove(folder, schema_id)
        log.info("schema %s removed", schema_id)
        return Response(status_code=204)
