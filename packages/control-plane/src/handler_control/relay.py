"""ACP relay — contract C transport: one WebSocket ↔ one agent process, through the policy.

Security rules of the transport itself (on top of the policy):
  - only single JSON objects are forwarded; batches and unparseable lines are dropped, so the
    policy always sees every message the agent could act on;
  - forwarded messages are re-serialized from what the policy inspected (no parser differential);
  - one JSON-RPC message per WebSocket frame; binary frames close with 1003.
"""

import asyncio
import contextlib
import json
import logging
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from handler_contracts import AcpCloseCode

from .agents import AgentRecord, AgentRegistry
from .launcher import StartedAgent
from .policy import AcpPolicy, ToAgent, ToClient, parse
from .sandbox_process import read_stderr, stop

log = logging.getLogger("handler.relay")


class Relay:
    def __init__(
        self,
        ws: WebSocket,
        agent: StartedAgent,
        policy: AcpPolicy,
        record: AgentRecord,
        registry: AgentRegistry,
    ) -> None:
        self.ws = ws
        self.agent = agent
        self.proc: asyncio.subprocess.Process = agent.process  # ty: ignore[invalid-assignment]
        self.policy = policy
        self.record = record
        self.registry = registry
        self.ws_lock = asyncio.Lock()
        self.agent_lock = asyncio.Lock()
        self.close_code: int = AcpCloseCode.NORMAL
        self.close_reason = ""

    async def to_client(self, msg: dict[str, Any]) -> None:
        async with self.ws_lock:
            await self.ws.send_text(json.dumps(msg))

    async def to_agent(self, msg: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        async with self.agent_lock:
            self.proc.stdin.write(json.dumps(msg).encode() + b"\n")
            await self.proc.stdin.drain()

    async def execute(self, actions: list[ToAgent | ToClient]) -> None:
        for action in actions:
            if isinstance(action, ToAgent):
                await self.to_agent(action.msg)
            else:
                await self.to_client(action.msg)

    # ── the three pumps ─────────────────────────────────────────────────

    async def client_to_agent(self) -> None:
        while True:
            event = await self.ws.receive()
            if event["type"] == "websocket.disconnect":
                return
            if event.get("bytes") is not None:
                self.close_code, self.close_reason = AcpCloseCode.UNSUPPORTED_DATA, "binary frame"
                return
            for line in (event.get("text") or "").splitlines():
                if not line.strip():
                    continue
                msg = parse(line)
                if msg is None:
                    log.warning(
                        "[%s] dropped a non-object client message", self.agent.connection_id
                    )
                    continue
                await self.execute(self.policy.from_client(msg))

    async def agent_to_client(self) -> None:
        assert self.proc.stdout is not None
        while True:
            try:
                line = await self.proc.stdout.readline()
            except (ValueError, asyncio.LimitOverrunError):
                self.close_code, self.close_reason = (
                    AcpCloseCode.MESSAGE_TOO_BIG,
                    "agent message too big",
                )
                return
            if not line:
                code = await self.proc.wait()
                self.close_code = AcpCloseCode.AGENT_EXITED
                self.close_reason = f"agent exited ({code})"
                return
            msg = parse(line.decode(errors="replace"))
            if msg is None:
                log.warning("[%s] dropped a non-object agent message", self.agent.connection_id)
                continue
            await self.execute(self.policy.from_agent(msg))

    # ── lifecycle (C.3) ─────────────────────────────────────────────────

    async def serve(self) -> None:
        pumps = [
            asyncio.create_task(self.client_to_agent()),
            asyncio.create_task(self.agent_to_client()),
        ]
        cid = self.agent.connection_id
        stderr = asyncio.create_task(
            read_stderr(self.proc, cid, lambda e: self.registry.add_event(self.record, cid, e))
        )
        try:
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        except WebSocketDisconnect:
            pass
        finally:
            for task in pumps:
                task.cancel()
            await self.stop_agent()
            stderr.cancel()
            with contextlib.suppress(Exception):
                await self.ws.close(code=self.close_code, reason=self.close_reason[:120])

    async def stop_agent(self) -> None:
        """Closing the connection stops the sandbox (C.3)."""
        await stop(self.proc)
