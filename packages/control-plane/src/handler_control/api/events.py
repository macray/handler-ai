"""Changes (D.30): what changed in handlerd, by topic, for the web UI's open pages to read again.

`GET /v1/events` is a server-sent events stream: each event's data is a topic, never what
changed. Changes in a burst are told once. Two ways a topic is told: a change made through the
API (from any tab, the CLI, an editor) tells its area, the path's first part after `/v1/`
(`agents`, `projects`, `automations`, `plans`…); what handlerd changes by itself is told by its
store (`sessions`, `inbox`, `apps`, `agents`, `automations`, `plans`, `builds`,
`ask`). A page reads what
it shows again on its topics, and everything again when the stream (re)opens: a change told
while it was closed is never missed."""

import asyncio
from collections.abc import AsyncGenerator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response, StreamingResponse
from starlette.middleware.base import RequestResponseEndpoint

from .common import Context

WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
KEEPALIVE = 25.0  # seconds: a comment line, so a dead connection is found


class Changes:
    """Each open stream's topics changed since it last sent (a set: a burst told once)."""

    def __init__(self) -> None:
        self.streams: list[tuple[set[str], asyncio.Event]] = []

    def tell(self, topic: str) -> None:
        for pending, ready in self.streams:
            pending.add(topic)
            ready.set()

    async def follow(self) -> AsyncGenerator[str]:
        """The stream's lines: a retry delay first, then each topic changed, a comment between."""
        pending: set[str] = set()
        ready = asyncio.Event()
        self.streams.append((pending, ready))
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    await asyncio.wait_for(ready.wait(), KEEPALIVE)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                ready.clear()
                topics = sorted(pending)
                pending.clear()
                for topic in topics:
                    yield f"data: {topic}\n\n"
        finally:
            self.streams.remove((pending, ready))


def add_event_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]
    changes = Changes()
    sessions = lambda *_: changes.tell("sessions")  # noqa: E731
    ctx.sessions.watchers.append(sessions)
    ctx.sessions.waiting_listeners.append(sessions)
    ctx.sessions.shown_listeners.append(sessions)
    ctx.inbox.watchers.append(lambda: changes.tell("inbox"))
    ctx.apps.watchers.append(lambda: changes.tell("apps"))
    agents = lambda: changes.tell("agents")  # noqa: E731
    for store in (ctx.registry, ctx.checks, ctx.improvements):  # an agent's checks are its own
        store.watchers.append(agents)
    ctx.automations.watchers.append(lambda: changes.tell("automations"))
    ctx.plans.watchers.append(lambda: changes.tell("plans"))
    ctx.builds.watchers.append(lambda: changes.tell("builds"))
    ctx.assistant.history.watchers.append(lambda: changes.tell("ask"))

    @app.middleware("http")
    async def tell_writes(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """A change made through the API tells its area (`/v1/<area>/…`)."""
        response = await call_next(request)
        path = request.url.path.split("/")
        if request.method in WRITES and response.status_code < 400 and path[1:2] == ["v1"]:
            changes.tell(path[2])
        return response

    @app.get("/v1/events", dependencies=authed)
    def events() -> StreamingResponse:
        headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        return StreamingResponse(changes.follow(), media_type="text/event-stream", headers=headers)
