"""Automation routes (I.9): the automations of the config folder, made (from an example or a
definition), checked before, changed (a definition written over its file) and deleted, on and
off, tries, runs and their logs; the examples handler ships; the runs on (or of) one session."""

import contextlib
from collections.abc import Iterator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import PlainTextResponse, Response

from handler_contracts import (
    AutomationDefinitionRequest,
    CreateAutomationRequest,
    TryAutomationRequest,
)

from .. import automation_config
from ..automations import (
    AutomationCappedError,
    AutomationConflictError,
    AutomationError,
    AutomationNotFoundError,
)
from .common import Context, ProblemError, dump, parse_body


def add_automation_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]
    automations = ctx.automations

    @contextlib.contextmanager
    def problems(title: str) -> Iterator[None]:
        try:
            yield
        except AutomationNotFoundError as e:
            raise ProblemError(404, "not found", str(e)) from None
        except AutomationCappedError as e:
            raise ProblemError(429, "daily cap reached", str(e)) from None
        except AutomationConflictError as e:
            raise ProblemError(409, title, str(e)) from None
        except (AutomationError, automation_config.AutomationConfigError) as e:
            raise ProblemError(400, title, str(e)) from None

    @app.get("/v1/automations", dependencies=authed)
    def list_automations() -> Response:
        return dump(automations.views())

    @app.get("/v1/automation-examples", dependencies=authed)
    def list_examples() -> Response:
        return dump(automation_config.examples())

    @app.post("/v1/automations", dependencies=authed)
    async def create_automation(request: Request) -> Response:
        body = parse_body(CreateAutomationRequest, await request.body())
        with problems("cannot create this automation"):
            made = automations.create(
                body.name, example=body.from_, definition=body.definition, enable=body.enable
            )
            return dump(made, status=201)

    @app.post("/v1/automations/check", dependencies=authed)
    async def check_automation(request: Request) -> Response:
        body = parse_body(AutomationDefinitionRequest, await request.body())
        return dump(automations.preview(body.definition))

    @app.get("/v1/automations/{name}", dependencies=authed)
    def get_automation(name: str) -> Response:
        with problems("automation"):
            return dump(automations.view(name))

    @app.put("/v1/automations/{name}", dependencies=authed)
    async def update_automation(name: str, request: Request) -> Response:
        body = parse_body(AutomationDefinitionRequest, await request.body())
        with problems("cannot change this automation"):
            return dump(automations.update(name, body.definition))

    @app.delete("/v1/automations/{name}", dependencies=authed)
    async def delete_automation(name: str) -> Response:
        with problems("cannot delete this automation"):
            await automations.delete(name)
        return Response(status_code=204)

    @app.get("/v1/automations/{name}/files/{path:path}", dependencies=authed)
    def get_file(name: str, path: str) -> Response:
        with problems("cannot read this file"):
            return PlainTextResponse(automation_config.read_file(automations.get(name).path, path))

    @app.post("/v1/automations/{name}/enable", dependencies=authed)
    async def enable(name: str) -> Response:
        with problems("cannot turn it on"):
            return dump(automations.enable(name))

    @app.post("/v1/automations/{name}/disable", dependencies=authed)
    async def disable(name: str) -> Response:
        with problems("cannot turn it off"):
            return dump(automations.disable(name))

    @app.post("/v1/automations/{name}/try", dependencies=authed)
    async def try_it(name: str, request: Request) -> Response:
        body = parse_body(TryAutomationRequest, await request.body())
        with problems("cannot try it"):
            return dump(automations.try_run(name, body.session_id), status=202)

    @app.get("/v1/automations/{name}/runs", dependencies=authed)
    def list_runs(name: str) -> Response:
        with problems("automation"):
            automations.get(name)
            return dump(automations.runs(name))

    @app.get("/v1/automations/{name}/runs/{run_id}", dependencies=authed)
    def get_run(name: str, run_id: str) -> Response:
        with problems("run"):
            return dump(automations.get_run(name, run_id))

    @app.get("/v1/automations/{name}/runs/{run_id}/log", dependencies=authed)
    def run_log(name: str, run_id: str) -> Response:
        with problems("run"):
            return PlainTextResponse(automations.run_log(name, run_id))

    @app.post("/v1/automations/{name}/runs/{run_id}/cancel", dependencies=authed)
    async def cancel_run(name: str, run_id: str) -> Response:
        with problems("cannot cancel it"):
            return dump(await automations.cancel(name, run_id))

    @app.get("/v1/sessions/{session_id}/automation-runs", dependencies=authed)
    def session_runs(session_id: str) -> Response:
        ctx.get_session(session_id)
        return dump(automations.runs_of_session(session_id))
