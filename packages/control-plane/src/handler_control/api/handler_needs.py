"""Handler's needs routes (D.18): its own features that need an agent, with the definition an
agent is set up from for each, the agent given and the person's that fit. One is set up by
creating an agent with the need's origin (D.2), then given (`PUT`)."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import HandlerNeed, SetHandlerNeedAgentRequest

from .. import handler_needs
from .common import Context, ProblemError, dump, parse_body


def add_handler_need_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    def view(need: HandlerNeed, given: dict[str, str]) -> HandlerNeed:
        agents = list(ctx.registry.agents.values())
        agent_id = given.get(need.name)
        return need.model_copy(
            update={
                "agent_id": agent_id if agent_id and ctx.registry.get(agent_id) else None,
                "fits": [
                    a.id
                    for a in agents
                    if handler_needs.misfit(need, a.origin, a.interface, a.scope) is None
                ],
            }
        )

    @app.get("/v1/handler-needs", dependencies=authed)
    def list_handler_needs() -> Response:
        given = handler_needs.given(ctx.settings.state_dir)
        return dump([view(n, given) for n in handler_needs.load_all()])

    @app.put("/v1/handler-needs/{name}", dependencies=authed)
    async def give_handler_need_agent(name: str, request: Request) -> Response:
        body = parse_body(SetHandlerNeedAgentRequest, await request.body())
        need = handler_needs.get(name)
        if need is None:
            raise ProblemError(404, "unknown handler need", name)
        agent = ctx.registry.get(body.agent_id)
        if agent is None:
            raise ProblemError(404, "agent not found", body.agent_id)
        if why := handler_needs.misfit(need, agent.origin, agent.interface, agent.scope):
            raise ProblemError(409, "does not fit", why)
        handler_needs.give(ctx.settings.state_dir, name, agent.id)
        ctx.remote.agents_changed()  # Ask's router: the owner's phone may Ask now (D.24)
        return dump(view(need, handler_needs.given(ctx.settings.state_dir)))
