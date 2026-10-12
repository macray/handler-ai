"""Built-in agent routes (D.18): the agents handler ships, each with the agent set up from it, if
any. One is set up by creating an ad-hoc agent with its name as `origin` (api/agents.py)."""

from fastapi import Depends, FastAPI
from fastapi.responses import Response

from .. import builtin_agents
from .common import Context, dump


def add_builtin_agent_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/builtin-agents", dependencies=authed)
    def list_builtin_agents() -> Response:
        set_up = {r.origin: r.id for r in list(ctx.registry.agents.values()) if r.origin}
        return dump(
            [
                b.agent.model_copy(update={"agent_id": set_up.get(b.agent.name)})
                for b in builtin_agents.load_all()
            ]
        )
