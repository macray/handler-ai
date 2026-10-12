"""Mini app routes: register, deploy, roll back, stop, open, log (H)."""

import contextlib
from collections.abc import Iterator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    AddAppRequest,
    AppLink,
    AppLog,
    SetAppPersonsRequest,
    SetAppSecretRequest,
    SetAppShortcutRequest,
)

from ..apps import AppError, AppNotFoundError, DeployError
from .common import Context, ProblemError, dump, parse_body


def add_app_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @contextlib.contextmanager
    def app_problems(title: str) -> Iterator[None]:
        try:
            yield
        except AppNotFoundError as e:
            raise ProblemError(404, "app not found", str(e)) from None
        except DeployError as e:
            raise ProblemError(422, "deploy failed", str(e)) from None
        except AppError as e:
            raise ProblemError(409, title, str(e)) from None

    @app.get("/v1/apps", dependencies=authed)
    def list_apps() -> Response:
        return dump(ctx.apps.views())

    @app.post("/v1/apps", dependencies=authed)
    async def add_app(request: Request) -> Response:
        body = parse_body(AddAppRequest, await request.body())
        with app_problems("cannot register this app"):
            record = ctx.apps.add(body.source_dir)
            return dump(ctx.apps.view(record.name), status=201)

    @app.get("/v1/apps/{name}", dependencies=authed)
    def get_app(name: str) -> Response:
        with app_problems("app"):
            return dump(ctx.apps.view(name))

    @app.delete("/v1/apps/{name}", dependencies=authed)
    async def remove_app(name: str) -> Response:
        with app_problems("cannot remove this app"):
            await ctx.apps.remove(name)
        return Response(status_code=204)

    @app.post("/v1/apps/{name}/deploy", dependencies=authed)
    async def deploy_app(name: str) -> Response:
        with app_problems("cannot deploy"):
            return dump(await ctx.apps.deploy(name))

    @app.post("/v1/apps/{name}/rollback", dependencies=authed)
    async def rollback_app(name: str) -> Response:
        with app_problems("cannot roll back"):
            return dump(await ctx.apps.rollback(name))

    @app.post("/v1/apps/{name}/stop", dependencies=authed)
    async def stop_app(name: str) -> Response:
        with app_problems("cannot stop"):
            return dump(await ctx.apps.stop(name))

    @app.put("/v1/apps/{name}/secrets/{secret}", dependencies=authed)
    async def set_app_secret(name: str, secret: str, request: Request) -> Response:
        body = parse_body(SetAppSecretRequest, await request.body())
        with app_problems("cannot set this secret"):
            return dump(await ctx.apps.set_secret(name, secret, body.value))

    @app.delete("/v1/apps/{name}/secrets/{secret}", dependencies=authed)
    async def unset_app_secret(name: str, secret: str) -> Response:
        with app_problems("cannot unset this secret"):
            return dump(await ctx.apps.set_secret(name, secret, None))

    @app.put("/v1/apps/{name}/persons", dependencies=authed)
    async def set_app_persons(name: str, request: Request) -> Response:
        body = parse_body(SetAppPersonsRequest, await request.body())
        with app_problems("cannot share this app"):
            return dump(ctx.apps.set_persons(name, body.persons))

    @app.put("/v1/apps/{name}/shortcut", dependencies=authed)
    async def set_app_shortcut(name: str, request: Request) -> Response:
        body = parse_body(SetAppShortcutRequest, await request.body())
        with app_problems("cannot set the shortcut"):
            return dump(await ctx.apps.set_shortcut(name, body.shortcut))

    @app.post("/v1/apps/{name}/open", dependencies=authed)
    def open_app(name: str) -> Response:
        with app_problems("cannot open"):
            return dump(AppLink(url=ctx.apps.open_link(name)))

    @app.get("/v1/apps/{name}/log", dependencies=authed)
    def app_log(name: str) -> Response:
        with app_problems("app"):
            return dump(AppLog(text=ctx.apps.log_tail(name)))
