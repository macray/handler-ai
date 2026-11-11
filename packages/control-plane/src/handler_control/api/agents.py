"""Agent routes: every agent, whatever its home (a project, an app or Chat, none: D.1), created,
listed, inspected, changed and deleted (D.2, through agent_service.py); its egress switched, its
terminal program started (D.16)."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    AgentRequest,
    EgressEvent,
    PatchAgentRequest,
    TerminalStart,
)

from .. import (
    launcher,
    save_rules,
    terminals,
)
from ..agents import switch_egress
from .common import Context, ProblemError, check_problems, dump, parse_body
from .toolbox import apply_confirmed


def add_agent_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.post("/v1/agents", dependencies=authed)
    async def create_agent(request: Request) -> Response:
        body = parse_body(AgentRequest, await request.body())
        with check_problems():
            settings, origin = ctx.agents.checked(body)
            record = ctx.agents.create(body, settings, origin)
        apply_confirmed(ctx, body.toolbox_adds, (u.addon for u in record.addon_uses))
        return dump(ctx.to_agent(record), status=201)

    @app.put("/v1/agents/{agent_id}", dependencies=authed)
    async def update_agent(agent_id: str, request: Request) -> Response:
        record = ctx.get_agent(agent_id)
        body = parse_body(AgentRequest, await request.body())
        with check_problems():
            settings, _ = ctx.agents.checked(body, record)
        failures = await ctx.agents.update(record, body, settings)
        apply_confirmed(ctx, body.toolbox_adds, (u.addon for u in record.addon_uses))
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

    @app.delete("/v1/agents/{agent_id}", dependencies=authed)
    async def delete_agent(agent_id: str) -> Response:
        record = ctx.get_agent(agent_id)
        with check_problems():
            await ctx.agents.delete(record)
        return Response(status_code=204)

    add_egress_routes(app, ctx)
    add_terminal_route(app, ctx)


def add_egress_routes(app: FastAPI, ctx: Context) -> None:
    """What a filtered agent's sandboxes tried to reach, and enforcing or only logging (A.4)."""
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/agents/{agent_id}/egress-events", dependencies=authed)
    def egress_events(agent_id: str) -> Response:
        return dump([EgressEvent.model_validate(e) for e in ctx.get_agent(agent_id).events])

    @app.patch("/v1/agents/{agent_id}", dependencies=authed)
    async def patch_agent(agent_id: str, request: Request) -> Response:
        record = ctx.get_agent(agent_id)
        body = parse_body(PatchAgentRequest, await request.body())
        if record.network != "filtered":
            raise ProblemError(409, "egress can only be switched on filtered agents")
        ctx.registry.set_egress(record, body.egress)  # future connections
        failures = await switch_egress(record, body.egress)  # running ones (A.4)
        if failures:
            raise ProblemError(502, "egress not switched on every connection", "; ".join(failures))
        return dump(ctx.to_agent(record))


def add_terminal_route(app: FastAPI, ctx: Context) -> None:
    @app.post("/v1/agents/{agent_id}/terminal", dependencies=[Depends(ctx.require_auth)])
    async def start_terminal(agent_id: str, request: Request) -> Response:
        """D.16: its terminal program's sandbox, ready for the client's `attach`."""
        record = ctx.get_agent(agent_id)
        body = parse_body(TerminalStart, await request.body())
        with check_problems():
            runs = save_rules.session_model(ctx.settings, record, body.model)
        try:
            started = await terminals.start(ctx.settings, record, ctx.registry, body, runs)
        except (launcher.AgentStartError, terminals.TerminalStartError, OSError) as e:
            raise ProblemError(409, "the terminal cannot start", str(e)) from None
        return dump(started, status=201)
