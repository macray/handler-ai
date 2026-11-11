"""WebSocket endpoints: an agent's ACP connection (C), a session's (F.4)."""

from datetime import UTC, datetime

from fastapi import FastAPI, WebSocket
from fastapi.responses import Response
from pydantic import ValidationError

from handler_contracts import (
    ACP_SUBPROTOCOL,
    AcpCloseCode,
    ModelAccess,
)
from handler_harness import starting_instructions

from .. import (
    addon_folders,
    auth,
    launcher,
    save_rules,
)
from ..agents import (
    AgentRecord,
    LiveConnection,
    RunsAs,
)
from ..policy import AcpPolicy
from ..relay import Relay
from ..sessions import SessionError
from .common import Context, log


def add_acp_endpoint(app: FastAPI, ctx: Context) -> None:
    @app.websocket("/v1/agents/{agent_id}/acp")
    async def acp(ws: WebSocket, agent_id: str) -> None:
        protocols = list(ws.scope.get("subprotocols") or [])
        known = ctx.registry.get(agent_id) is not None
        if denial := websocket_denial(ctx, ws, protocols, known, "agent"):
            await ws.send_denial_response(denial)
            return
        record = ctx.get_agent(agent_id)
        try:
            runs = connection_model(ctx, record, ws)
        except save_rules.CheckError as e:
            status = 409 if isinstance(e, save_rules.ConflictError) else 400
            await ws.send_denial_response(Response(f"{e.title}: {e}", status_code=status))
            return
        await ws.accept(subprotocol=ACP_SUBPROTOCOL if ACP_SUBPROTOCOL in protocols else None)
        try:
            started = await launcher.start(ctx.settings, record, runs)
        except (launcher.AgentStartError, OSError) as e:
            log.warning("agent %s: failed to start: %s", agent_id, e)
            reason = f"agent failed to start: {e}"[:120]
            await ws.close(code=AcpCloseCode.AGENT_EXITED, reason=reason)
            return
        conn = LiveConnection(
            id=started.connection_id,
            sandbox=started.spec.name,
            since=datetime.now(UTC),
            process=started.process,
            egress_base=started.egress_base,
        )
        policy = AcpPolicy(
            scope=started.spec.workdir,
            network=started.spec.network,
            session_defaults=started.launch.session_defaults,
            instructions=starting_instructions(record.instructions, record.network),  # P9
            on_event=lambda text: log.info("[%s] policy: %s", conn.id, text),
        )
        record.connections[conn.id] = conn
        ctx.registry.touch(record)
        try:
            await Relay(ws, started, policy, record, ctx.registry).serve()
        finally:
            record.connections.pop(conn.id, None)
            addon_folders.sweep_soon(ctx.settings)  # a folder it mounted may be free

    @app.websocket("/v1/sessions/{session_id}/acp")
    async def session_acp(ws: WebSocket, session_id: str) -> None:
        protocols = list(ws.scope.get("subprotocols") or [])
        known = session_id in ctx.sessions.records
        if denial := websocket_denial(ctx, ws, protocols, known, "session"):
            await ws.send_denial_response(denial)
            return
        await ws.accept(subprotocol=ACP_SUBPROTOCOL if ACP_SUBPROTOCOL in protocols else None)
        try:
            live = await ctx.sessions.ensure_running(session_id)  # F.6.1: never started twice
        except SessionError as e:
            await ws.close(code=AcpCloseCode.AGENT_EXITED, reason=str(e)[:120])
            return
        await live.attach(ws)


def connection_model(ctx: Context, record: AgentRecord, ws: WebSocket) -> RunsAs:
    """The model a plain connection runs with (C.1): the one its URL names (`harness`, `account`
    or `provider`, `model`: the agent's or any other, D.19), else the agent's."""
    fields = ("harness", "account", "provider", "model")
    query = {k: v for k in fields if (v := ws.query_params.get(k))}
    if not query:
        return record.runs_as()
    try:
        given = ModelAccess.model_validate(query)
    except ValidationError as e:
        raise save_rules.CheckError("model access unusable", str(e)) from None
    return save_rules.session_model(ctx.settings, record, given)


def websocket_denial(
    ctx: Context, ws: WebSocket, protocols: list[str], known: bool, what: str
) -> Response | None:
    """C.1: Origin (403), the token via subprotocol or the web UI's cookie (401), known
    agent/session (404), before accepting."""
    if not auth.origin_allowed(ws.headers.get("origin"), ctx.settings.allowed_origins):
        return Response("origin not allowed", status_code=403)
    bearer = auth.bearer_from_subprotocols(protocols)
    if not ctx.authenticated(ws.headers, ws.cookies.get(auth.UI_COOKIE), bearer):
        return Response("missing or invalid token", status_code=401)
    if not known:
        return Response(f"{what} not found", status_code=404)
    return None
