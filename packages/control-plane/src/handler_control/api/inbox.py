"""The person's inbox: apps' notifications and nudges, automations' results, plans stopped, hosts
refused while nobody watched (H.9, H.17, I.3, D.27, F.9); a message's hosts refused answered from
it; a nudge dismissed, its page opened, its form filled from what was said."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import AppLink, InboxAnswerRequest, InboxMessage, NudgeFillRequest

from .. import refusals
from ..apps import AppError, AppNotFoundError
from ..assistant import AssistantError
from ..automations import AutomationError
from ..nudges import NudgeError
from ..plans import PlanError
from .common import Context, ProblemError, dump, parse_body


def add_inbox_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    def answered(m: InboxMessage) -> InboxMessage:
        """Its hosts refused with your answer, as its agent's lists say now."""
        if not m.refused:
            return m
        agent = ctx.registry.get(m.agent_id) if m.agent_id else None
        return m.model_copy(update={"refused": refusals.decided(m.refused, agent)})

    @app.get("/v1/inbox", dependencies=authed)
    def inbox() -> Response:
        return dump([answered(m) for m in ctx.inbox.list()])

    @app.post("/v1/inbox/{message_id}/read", dependencies=authed)
    def mark_read(message_id: str) -> Response:
        message = ctx.inbox.mark_read(message_id)
        if message is None:
            raise ProblemError(404, "message not found", message_id)
        return dump(message)

    @app.post("/v1/inbox/{message_id}/answer", dependencies=authed)
    async def answer(message_id: str, request: Request) -> Response:
        """*Allow* or *Keep blocked* (rule inbox.a-refused-host-is-answered-from-it): saved for
        its agent and applied; a session's agent told; with `again`, its plan run from its step
        or its automation run again."""
        body = parse_body(InboxAnswerRequest, await request.body())
        message = ctx.inbox.get(message_id)
        if message is None:
            raise ProblemError(404, "message not found", message_id)
        if others := [h for h in body.hosts if h not in {r.host for r in message.refused}]:
            raise ProblemError(409, "not refused in this message", ", ".join(others))
        if body.again and (body.decision != "allowed" or message.source == "session"):
            raise ProblemError(409, "run again: only a run's hosts, allowed")
        agent = ctx.registry.get(message.agent_id) if message.agent_id else None
        if agent is None:
            raise ProblemError(409, "its agent was deleted", message.agent)
        failures = await refusals.decide(ctx.registry, agent, body.hosts, body.decision)
        if message.source == "session" and message.session_id is not None:
            for host in body.hosts:
                await ctx.sessions.answered(message.session_id, host, body.decision)
        if body.again:
            try:
                if message.plan_id is not None and message.step is not None:
                    ctx.plans.run(message.plan_id, message.step)
                elif message.run_id is not None:
                    run = ctx.automations.get_run(message.name, message.run_id)
                    ctx.automations.try_run(message.name, run.session_id)
            except PlanError as e:
                raise ProblemError(e.status, e.title, e.detail) from None
            except AutomationError as e:
                raise ProblemError(409, "cannot run it again", str(e)) from None
        ctx.inbox.mark_read(message_id)
        if failures:
            raise ProblemError(409, "saved, but not applied", "; ".join(failures))
        return dump(answered(ctx.inbox.get(message_id) or message))


def add_nudge_routes(app: FastAPI, ctx: Context) -> None:
    """A nudge in the inbox (H.17): dismissed, its page opened, its form filled from speech."""
    authed = [Depends(ctx.require_auth)]

    @app.post("/v1/inbox/{message_id}/dismiss", dependencies=authed)
    def dismiss(message_id: str) -> Response:
        """An open nudge dismissed by the person (H.17): no more reminders."""
        try:
            ctx.apps.nudges.get(message_id)
            return dump(ctx.apps.nudges.end(message_id, "dismissed"))
        except NudgeError as e:
            raise ProblemError(e.status, "cannot dismiss", str(e)) from None

    @app.post("/v1/inbox/{message_id}/open", dependencies=authed)
    def open_nudge(message_id: str) -> Response:
        """A one-time link to the page of its app an open nudge opens (H.17)."""
        try:
            return dump(AppLink(url=ctx.apps.nudge_link(message_id)))
        except AppNotFoundError as e:
            raise ProblemError(404, "nudge not found", str(e)) from None
        except AppError as e:
            raise ProblemError(409, "cannot open", str(e)) from None

    @app.post("/v1/inbox/{message_id}/fill", dependencies=authed)
    async def fill(message_id: str, request: Request) -> Response:
        """What the person said fills the form of the nudge's action, never sent (H.17)."""
        body = parse_body(NudgeFillRequest, await request.body())
        try:
            return dump(await ctx.assistant.fill(message_id, body.said, body.timezone))
        except NudgeError as e:
            raise ProblemError(e.status, "cannot fill", str(e)) from None
        except AssistantError as e:
            raise ProblemError(e.status, "cannot fill", str(e)) from None
