"""Agent routes: every agent listed, inspected, renamed, its egress switched, its terminal program
started (D.16); ad-hoc agents (D.1) also created, updated and deleted here (D.2)."""

import contextlib

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    AdHocAgentRequest,
    EgressEvent,
    PatchAgentRequest,
    TerminalStart,
)

from .. import (
    builtin_agents,
    checks,
    launcher,
    terminals,
)
from ..agents import (
    AdHocOwn,
    AgentRecord,
    CheckedSettings,
    apply_network,
    switch_egress,
)
from .common import Context, ProblemError, check_problems, dump, parse_body, text_or_none


def add_agent_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    def checked(
        body: AdHocAgentRequest, current: AgentRecord | None = None
    ) -> tuple[CheckedSettings, AdHocOwn]:
        """Its settings checked, what they widen confirmed (D.8); set up from a built-in agent
        (D.18), the built-in's skills are in the library first (it picks them)."""
        with check_problems():
            if builtin := checks.check_origin(ctx.registry, body.origin, current):
                builtin_agents.install_skills(builtin, ctx.settings.skills_dir)
            settings = checks.checked_settings(ctx.settings, body, body.scope)
            checks.check_ad_hoc_identity(ctx.registry, settings.scope, body.name, current)
            checks.check_risks(current.settings if current else None, settings, body)
            checks.check_skills(ctx.settings, body.skills, None)
        own = AdHocOwn(
            text_or_none(body.description),
            text_or_none(body.instructions),
            sorted(body.skills),
            body.origin,
        )
        return settings, own

    @app.post("/v1/agents", dependencies=authed)
    async def create_ad_hoc_agent(request: Request) -> Response:
        body = parse_body(AdHocAgentRequest, await request.body())
        settings, own = checked(body)
        record = ctx.registry.create(settings, body.name, own)
        return dump(ctx.to_agent(record), status=201)

    def ad_hoc_only(record: AgentRecord) -> None:
        if record.project_id is not None:
            raise ProblemError(
                409,
                "an agent of a project",
                f"change it through /v1/projects/{record.project_id}/agents/{record.id}",
            )

    @app.put("/v1/agents/{agent_id}", dependencies=authed)
    async def update_ad_hoc_agent(agent_id: str, request: Request) -> Response:
        record = ctx.get_agent(agent_id)
        ad_hoc_only(record)
        body = parse_body(AdHocAgentRequest, await request.body())
        settings, own = checked(body, record)
        ctx.registry.update(record, settings, body.name, own)
        failures = await apply_network(record, settings.egress)
        if failures:
            raise ProblemError(
                502, "saved, but not applied to every live connection", "; ".join(failures)
            )
        return dump(ctx.to_agent(record))

    @app.get("/v1/agents", dependencies=authed)
    def list_agents() -> Response:
        # a copy: sync routes read it in a worker thread, the event loop changes it
        agents = list(ctx.registry.agents.values())
        return dump([ctx.to_agent(r) for r in agents])

    @app.get("/v1/agents/{agent_id}", dependencies=authed)
    def inspect_agent(agent_id: str) -> Response:
        return dump(ctx.to_agent(ctx.get_agent(agent_id)))

    @app.get("/v1/agents/{agent_id}/egress-events", dependencies=authed)
    def egress_events(agent_id: str) -> Response:
        return dump([EgressEvent.model_validate(e) for e in ctx.get_agent(agent_id).events])

    @app.patch("/v1/agents/{agent_id}", dependencies=authed)
    async def patch_agent(agent_id: str, request: Request) -> Response:
        record = ctx.get_agent(agent_id)
        body = parse_body(PatchAgentRequest, await request.body())
        current = ctx.to_agent(record)
        if current.network != "filtered":
            raise ProblemError(409, "egress can only be switched on filtered agents")
        ctx.registry.set_egress(record, body.egress)  # future connections
        failures = await switch_egress(record, body.egress)  # running ones (A.4)
        if failures:
            raise ProblemError(502, "egress not switched on every connection", "; ".join(failures))
        return dump(ctx.to_agent(record))

    @app.delete("/v1/agents/{agent_id}", dependencies=authed)
    async def delete_ad_hoc_agent(agent_id: str) -> Response:
        record = ctx.get_agent(agent_id)
        ad_hoc_only(record)
        await stop_agent(ctx, record)
        ctx.registry.delete(agent_id)
        return Response(status_code=204)

    add_terminal_route(app, ctx)


def add_terminal_route(app: FastAPI, ctx: Context) -> None:
    @app.post("/v1/agents/{agent_id}/terminal", dependencies=[Depends(ctx.require_auth)])
    async def start_terminal(agent_id: str, request: Request) -> Response:
        """D.16: its terminal program's sandbox, ready for the client's `attach`."""
        record = ctx.get_agent(agent_id)
        body = parse_body(TerminalStart, await request.body())
        with check_problems():
            runs = checks.session_model(ctx.settings, record, body.model)
        try:
            started = await terminals.start(ctx.settings, record, ctx.registry, body, runs)
        except (launcher.AgentStartError, terminals.TerminalStartError, OSError) as e:
            raise ProblemError(409, "the terminal cannot start", str(e)) from None
        return dump(started, status=201)


async def stop_agent(ctx: Context, record: AgentRecord) -> None:
    """Stop what runs on it: connections and sessions (these keep their folders, F.3)."""
    for conn in list(record.connections.values()):
        with contextlib.suppress(ProcessLookupError):
            conn.process.terminate()  # its relay (or terminal client) then ends
    await ctx.sessions.stop_agent(record.id)


async def apply_agent_live(record: AgentRecord) -> None:
    """Its hosts and log-only on the agent's running sandboxes (A.4)."""
    if failures := await apply_network(record, record.egress):
        raise ProblemError(
            502, "saved, but not applied to every live connection", "; ".join(failures)
        )
