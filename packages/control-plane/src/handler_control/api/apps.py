"""App routes: install an app file and export one (H.15), give its needs (secrets, folders,
agents), deploy, roll back, stop, open, log (H). An app from a source: sources.py (D.26)."""

import contextlib
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    ActionRequest,
    AppLink,
    AppLog,
    AutomationAppCall,
    SetAppAgentRequest,
    SetAppAskableRequest,
    SetAppFileRequest,
    SetAppPersonsRequest,
    SetAppSecretRequest,
)

from ..apps import AppError, AppNotFoundError, DeployError, InputError
from ..automations import AutomationError
from .common import Context, ProblemError, dump, parse_body


@contextlib.contextmanager
def app_problems(title: str) -> Iterator[None]:
    try:
        yield
    except AppNotFoundError as e:
        raise ProblemError(404, "app not found", str(e)) from None
    except DeployError as e:
        raise ProblemError(422, "deploy failed", str(e)) from None
    except InputError as e:
        raise ProblemError(400, "invalid input", str(e)) from None
    except AppError as e:
        raise ProblemError(409, title, str(e)) from None


def add_app_action_routes(app: FastAPI, ctx: Context) -> None:
    """An app's actions, what the person asks it (H.12): done now, or its agent's run read
    again."""
    authed = [Depends(ctx.require_auth)]

    @app.put("/v1/apps/{name}/askable", dependencies=authed)
    async def set_app_askable(name: str, request: Request) -> Response:
        body = parse_body(SetAppAskableRequest, await request.body())
        with app_problems("app"):
            return dump(ctx.apps.set_askable(name, body.askable))

    @app.post("/v1/apps/{name}/actions/{action}", dependencies=authed)
    async def act(name: str, action: str, request: Request) -> Response:
        body = parse_body(ActionRequest, await request.body())
        with app_problems("cannot ask this app"):
            return dump(await ctx.apps.act(name, action, body.fields))

    @app.get("/v1/apps/{name}/actions/{action}/runs/{run_id}", dependencies=authed)
    def action_run(name: str, action: str, run_id: str) -> Response:
        with app_problems("action"):
            return dump(ctx.apps.action_run(name, action, run_id))


def add_app_code_routes(app: FastAPI, ctx: Context) -> None:
    """An app's code kept by Handler (H.15): an app file installed, a draft used, an export."""
    authed = [Depends(ctx.require_auth)]

    @app.post("/v1/apps", dependencies=authed)
    async def add_app(request: Request) -> Response:
        """An app file (a zip): a new app (201), or the next version of one you have (200)."""
        with app_problems("cannot install this file"):
            record, new = ctx.apps.add_file(await request.body())
            return dump(ctx.apps.view(record.name), status=201 if new else 200)

    @app.post("/v1/apps/from-draft/{session_id}", dependencies=authed)
    async def add_app_draft(session_id: str) -> Response:
        """A session's draft of an app's code used (H.15): the app's next version (200), or a
        new app (201); the session goes with it, as a draft thrown away."""
        record = ctx.get_session(session_id)
        if record.app_draft is None:
            raise ProblemError(409, "not a draft", "this session works on no app's draft")
        with app_problems("cannot use this draft"):
            app, new = ctx.apps.add_draft(Path(record.scope), record.app_draft.get("app"))
        if (opened := ctx.apps.preview_of(session_id)) is not None:
            await ctx.apps.close_draft(opened)
        await ctx.sessions.delete(session_id)
        return dump(ctx.apps.view(app.name), status=201 if new else 200)

    @app.post("/v1/apps/from-draft/{session_id}/open", dependencies=authed)
    async def open_app_draft(session_id: str) -> Response:
        """A session's draft started at its own address, on copies (H.16)."""
        record = ctx.get_session(session_id)
        if record.app_draft is None:
            raise ProblemError(409, "not a draft", "this session works on no app's draft")
        with app_problems("cannot open this draft"):
            opened = await ctx.apps.open_draft(
                session_id, Path(record.scope), record.app_draft.get("app")
            )
        return dump(opened)

    @app.get("/v1/apps/{name}/export", dependencies=authed)
    def export_app(name: str) -> Response:
        with app_problems("cannot export"):
            filename, data = ctx.apps.export(name)
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return Response(data, media_type="application/zip", headers=headers)


def add_app_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]
    add_app_action_routes(app, ctx)
    add_app_code_routes(app, ctx)

    @app.get("/v1/apps", dependencies=authed)
    def list_apps() -> Response:
        return dump(ctx.apps.views())

    @app.get("/v1/apps/{name}", dependencies=authed)
    def get_app(name: str) -> Response:
        with app_problems("app"):
            return dump(ctx.apps.view(name))

    @app.delete("/v1/apps/{name}", dependencies=authed)
    async def remove_app(name: str) -> Response:
        with app_problems("cannot uninstall this app"):
            await ctx.apps.remove(name)
        await remove_parts(ctx, name)
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

    @app.put("/v1/apps/{name}/files/{need}", dependencies=authed)
    async def set_app_file(name: str, need: str, request: Request) -> Response:
        body = parse_body(SetAppFileRequest, await request.body())
        with app_problems("cannot give this folder"):
            return dump(await ctx.apps.set_file(name, need, body.path, body.create))

    @app.put("/v1/apps/{name}/agents/{need}", dependencies=authed)
    async def set_app_agent(name: str, need: str, request: Request) -> Response:
        body = parse_body(SetAppAgentRequest, await request.body())
        with app_problems("cannot give this agent"):
            return dump(ctx.apps.set_agent(name, need, body.agent_id))

    @app.put("/v1/apps/{name}/persons", dependencies=authed)
    async def set_app_persons(name: str, request: Request) -> Response:
        body = parse_body(SetAppPersonsRequest, await request.body())
        with app_problems("cannot share this app"):
            return dump(ctx.apps.set_persons(name, body.persons))

    @app.post("/v1/apps/{name}/open", dependencies=authed)
    def open_app(name: str) -> Response:
        with app_problems("cannot open"):
            return dump(AppLink(url=ctx.apps.open_link(name)))

    @app.get("/v1/apps/{name}/log", dependencies=authed)
    def app_log(name: str) -> Response:
        with app_problems("app"):
            return dump(AppLog(text=ctx.apps.log_tail(name)))


async def remove_parts(ctx: Context, app: str) -> None:
    """An app uninstalled takes its parts along (H.14): the agents set up for it, and the
    automations that run them or call its routes. The files you gave it stay."""
    parts = [a for a in ctx.registry.agents.values() if a.app == app]
    ids = {a.id for a in parts}
    for view in ctx.automations.views():
        run = view.definition.run if view.definition else None
        if view.agent_id in ids or (isinstance(run, AutomationAppCall) and run.app == app):
            with contextlib.suppress(AutomationError):
                await ctx.automations.delete(view.name)
    for agent in parts:
        await ctx.agents.delete(agent, with_home=True)
