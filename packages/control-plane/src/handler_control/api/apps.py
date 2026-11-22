"""App routes: install an app file and export one (H.15), give its needs (secrets, folders) and
who works on its jobs, deploy, roll back, stop, open, log (H). An app from a source: sources.py (D.26)."""

import contextlib
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    ActionRequest,
    AppAskRequest,
    AppLink,
    AppLog,
    AppOpenRequest,
    AutomationAppCall,
    AutomationJobRun,
    NudgeOffRequest,
    NudgeSettingRequest,
    NudgeWhenRequest,
    SetAppFileRequest,
    SetAppPersonsRequest,
    SetAppSecretRequest,
    WhoWorks,
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
    """An app's actions, what the person asks it (H.12): done now, or its job's run read
    again."""
    authed = [Depends(ctx.require_auth)]

    @app.put("/v1/apps/{name}/ask", dependencies=authed)
    async def set_app_ask(name: str, request: Request) -> Response:
        body = parse_body(AppAskRequest, await request.body())
        with app_problems("app"):
            return dump(ctx.apps.set_ask(name, body.not_in_ask))

    @app.post("/v1/apps/{name}/actions/{action}", dependencies=authed)
    async def act(name: str, action: str, request: Request) -> Response:
        body = parse_body(ActionRequest, await request.body())
        with app_problems("cannot ask this app"):
            return dump(await ctx.apps.act(name, action, body.fields, body.nudge))

    @app.put("/v1/apps/{name}/nudges/{nudge}", dependencies=authed)
    async def set_nudge_setting(name: str, nudge: str, request: Request) -> Response:
        """How that nudge reminds you (H.17): held for its next ones."""
        body = parse_body(NudgeSettingRequest, await request.body())
        with app_problems("app"):
            return dump(ctx.apps.set_nudge_setting(name, nudge, body.setting))

    @app.put("/v1/apps/{name}/nudges/{nudge}/off", dependencies=authed)
    async def set_nudge_off(name: str, nudge: str, request: Request) -> Response:
        """That nudge turned off, or on again (H.17)."""
        body = parse_body(NudgeOffRequest, await request.body())
        with app_problems("app"):
            return dump(ctx.apps.set_nudge_off(name, nudge, body.off))

    @app.put("/v1/apps/{name}/nudges/{nudge}/when", dependencies=authed)
    async def set_nudge_when(name: str, nudge: str, request: Request) -> Response:
        """When handlerd sends that nudge (H.17): yours replacing the app's, null the app's."""
        body = parse_body(NudgeWhenRequest, await request.body())
        with app_problems("app"):
            return dump(ctx.apps.set_nudge_when(name, nudge, body.when))

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

    @app.get("/v1/apps/{name}/runs", dependencies=authed)
    def app_runs(name: str) -> Response:
        """Its runs handlerd keeps (H.11: its last 50), newest first, for its page."""
        with app_problems("app"):
            ctx.apps.get(name)
            return dump(ctx.apps.runs.recent(name))

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

    @app.post("/v1/apps/{name}/update", dependencies=authed)
    async def update_app(name: str) -> Response:
        """The version its source offers taken, then deployed (H.6)."""
        with app_problems("cannot update"):
            return dump(await ctx.apps.update(name))

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

    @app.put("/v1/apps/{name}/who-works", dependencies=authed)
    async def set_app_who_works(name: str, request: Request) -> Response:
        """Who runs its jobs (H.2): a program on an account or provider, or the model alone."""
        body = parse_body(WhoWorks, await request.body())
        with app_problems("cannot choose who works"):
            return dump(ctx.apps.set_who_works(name, body))

    @app.put("/v1/apps/{name}/jobs/{job}/who-works", dependencies=authed)
    async def set_job_who_works(name: str, job: str, request: Request) -> Response:
        """Who runs that job instead of the app's Who works (H.2)."""
        body = parse_body(WhoWorks, await request.body())
        with app_problems("cannot choose who works"):
            return dump(ctx.apps.set_job_who_works(name, job, body))

    @app.delete("/v1/apps/{name}/jobs/{job}/who-works", dependencies=authed)
    def unset_job_who_works(name: str, job: str) -> Response:
        """That job run by the app's Who works again (H.2)."""
        with app_problems("cannot choose who works"):
            return dump(ctx.apps.set_job_who_works(name, job, None))

    @app.put("/v1/apps/{name}/persons", dependencies=authed)
    async def set_app_persons(name: str, request: Request) -> Response:
        body = parse_body(SetAppPersonsRequest, await request.body())
        with app_problems("cannot share this app"):
            return dump(ctx.apps.set_persons(name, body.persons))

    @app.post("/v1/apps/{name}/open", dependencies=authed)
    async def open_app(name: str, request: Request) -> Response:
        path = parse_body(AppOpenRequest, await request.body() or b"{}").path  # none: its home
        with app_problems("cannot open"):
            return dump(AppLink(url=ctx.apps.open_link(name, path)))

    @app.get("/v1/apps/{name}/log", dependencies=authed)
    def app_log(name: str) -> Response:
        with app_problems("app"):
            return dump(AppLog(text=ctx.apps.log_tail(name)))


async def remove_parts(ctx: Context, app: str) -> None:
    """An app uninstalled takes its parts along (H.14): the automations that run its jobs or call
    its routes (its jobs' runs and harness state go with the app, `AppRuns.forget`). The files
    you gave it stay."""
    for view in ctx.automations.views():
        run = view.definition.run if view.definition else None
        if isinstance(run, AutomationAppCall | AutomationJobRun) and run.app == app:
            with contextlib.suppress(AutomationError):
                await ctx.automations.delete(view.name)
