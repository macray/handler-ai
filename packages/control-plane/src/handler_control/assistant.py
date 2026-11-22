"""Ask (D.24): what the person says, routed to one action of one of their apps (H.12), then run.

The router is the agent given for one of Handler's needs (D.18, `ask-router`): an agent on the model
alone, set up from the need's definition, whose instructions are the router's prompt. Each Ask is
one run of it (origin "ask", one model call, no tool ever): its form is what was said, now where the
person is, and every askable app's actions with their forms; its result says `pick` (an app's
action, its form filled), `needs` (one question) or `none`. A pick is checked against the action's
form, then run as the owner (AppStore.act): its answer comes back with the pick, or, for an agent's
action still running, is read again on the app (and reaches the inbox).

The client sends the whole exchange each time; a reply is one more turn. Each ask is kept in
Ask's history (ask_history.py) as it ended, whatever answered it or failed; one that failed or
that no app does is also told to the inbox. A job's action still running is read again when the
history is, and its record says how it ended.

A nudge's form (H.17) is filled the same way from what was said, its action alone offered: the
filled form goes back to the person, who sends it; nothing runs from it.
"""

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from handler_contracts import (
    ActionOption,
    AskHistory,
    AskRecord,
    AskTurn,
    AskVia,
    AssistantAnswer,
    NudgeFill,
    SessionInput,
)

from . import handler_needs, interfaces, save_rules
from .agents import AgentRecord
from .apps import AppError, AppNotFoundError, AppStore
from .ask_history import AskHistoryStore
from .nudges import NudgeError
from .sessions import SessionStore
from .settings import Settings

ROUTER = "ask-router"  # the need whose agent routes (data/handler-needs/)


class AssistantError(Exception):
    """Ask cannot route now: no router given, its model unusable. Its HTTP status, and why."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status


class Assistant:
    def __init__(
        self,
        settings: Settings,
        apps: AppStore,
        sessions: SessionStore,
        history: AskHistoryStore,
    ) -> None:
        self.settings = settings
        self.apps = apps
        self.sessions = sessions
        self.history = history

    def router(self) -> AgentRecord:
        """The Ask router given (D.18); 409 when none is."""
        agent_id = handler_needs.given(self.settings.state_dir).get(ROUTER)
        agent = self.sessions.registry.get(agent_id) if agent_id else None
        if agent is None:
            raise AssistantError(409, "no Ask router: set one up first (it needs a model)")
        return agent

    def ready(self) -> bool:
        """A router is given and an app can be asked something: the phone can Ask too."""
        return (
            bool(handler_needs.given(self.settings.state_dir).get(ROUTER)) and self.apps.askable()
        )

    def options(self) -> list[tuple[str, str, dict[str, Any]]]:
        """What can be asked now: (app, action, its view) of each installed app's actions in Ask."""
        found: list[tuple[str, str, dict[str, Any]]] = []
        for app in self.apps.views():
            if app.current is None:
                continue
            for action in (a for a in app.actions if a.in_ask):
                view = action.model_dump(
                    mode="json", by_alias=True, exclude_none=True, exclude={"in_ask"}
                )
                found.append((app.name, action.name, view | {"app": app.description or ""}))
        return found

    async def answer(
        self, turns: list[AskTurn], timezone: str | None, via: AskVia, spoken: bool
    ) -> AssistantAnswer:
        """What was said, routed and run; kept in Ask's history as it ended, either way."""
        try:
            answer = await self.routed(turns, timezone)
        except AssistantError as e:
            self.kept(self.history.add(via, spoken, turns, error=str(e)))
            raise
        self.kept(self.history.add(via, spoken, turns, answer))
        return answer

    def unheard(self, via: AskVia, error: str) -> None:
        """What was said could not be written down (D.25): an ask with no words, failed."""
        self.kept(self.history.add(via, True, [], error=f"Nothing was written down: {error}"))

    def kept(self, record: AskRecord) -> None:
        """An ask that failed, or that no app does, also goes to the inbox."""
        if record.outcome not in ("failed", "none"):
            return
        said = next((t.text for t in reversed(record.turns) if t.who == "you"), None)
        answer = record.answer
        picked = f"{answer.app} · {answer.action}" if answer and answer.app else None
        title = {"none": "No app does that"}.get(record.outcome) or (
            f"{picked} failed" if picked else "Ask could not answer"
        )
        self.apps.inbox.add(
            source="ask",
            name="Ask",
            person="owner",
            title=title,
            status="failed",
            summary=(f"“{said}”: " if said else "") + record.summary,
            app=answer.app if answer and answer.run else None,
        )

    def history_view(self) -> AskHistory:
        """Ask's history, a job's action still running read again: how it ended, once it did."""
        for record in self.history.view().asks:
            answer = record.answer
            run = answer.run if answer else None
            if answer is None or run is None or run.state != "running" or run.run_id is None:
                continue
            assert answer.app is not None and answer.action is not None
            try:
                now = self.apps.action_run(answer.app, answer.action, run.run_id)
            except AppNotFoundError:  # the app or its run gone since
                continue
            if now.state != "running":
                self.history.ended(record.id, answer.model_copy(update={"run": now}))
        return self.history.view()

    async def routed(self, turns: list[AskTurn], timezone: str | None) -> AssistantAnswer:
        options = self.options()
        listed = [
            ActionOption(app=a, action=k, description=v["description"]) for a, k, v in options
        ]
        if not options:
            summary = "None of your apps can be asked anything yet."
            return AssistantAnswer(kind="none", summary=summary, actions=listed)
        said = "\n".join(f"{'You' if t.who == 'you' else 'Handler'}: {t.text}" for t in turns)
        value, run_id = await self.route(said, timezone, options)
        return await self.act(value, options, listed, run_id)

    async def route(
        self, said: str, timezone: str | None, options: list[tuple[str, str, dict[str, Any]]]
    ) -> tuple[dict[str, Any], str]:
        """One run of the router (origin "ask") on what was said and the actions offered: (its
        result, its session's id); 409 without a router or a usable model, 502 without a result."""
        router = self.router()
        try:
            runs = save_rules.session_model(self.settings, router, None)
        except save_rules.CheckError as e:
            raise AssistantError(409, f"the Ask router's model: {e}") from None
        fields = {"said": said, "now": now_where(timezone), "actions": catalog(options)}
        rec = self.sessions.create(router, runs, origin="ask", run=SessionInput(fields=fields))
        value, why = await self.sessions.result_of(rec.id)
        if value is None:
            raise AssistantError(502, f"the Ask router gave no answer: {why}")
        return value, rec.id

    async def fill(self, message_id: str, said: str, timezone: str | None) -> NudgeFill:
        """What was said about an open nudge of the owner's (H.17), as its action's form filled:
        one run of the router with that action alone offered; nothing runs from it."""
        message = self.apps.nudges.get(message_id)
        nudge = message.nudge
        assert nudge is not None and message.app is not None
        if nudge.action is None:
            raise NudgeError(409, "this nudge opens a page, not a form")
        action = next(
            (a for a in self.apps.view(message.app).actions if a.name == nudge.action), None
        )
        if action is None:
            raise NudgeError(409, f"{message.app} has no action {nudge.action} any more")
        view = action.model_dump(mode="json", by_alias=True, exclude_none=True)
        options = [(message.app, action.name, view | {"app": ""})]
        already = json.dumps(nudge.fields or {}, ensure_ascii=False)
        told = f"You: {said}\n(The form, as filled in so far: {already})"
        value, _ = await self.route(told, timezone, options)
        filled = value.get("fields") if value.get("kind") == "pick" else None
        if not isinstance(filled, dict):
            question = str(value.get("question") or value.get("summary") or "")
            return NudgeFill(said=said, question=question or "I could not fill it in from that.")
        found = interfaces.errors(action.fields, filled) if action.fields else []
        return NudgeFill(said=said, fields=filled, question=found[0] if found else None)

    async def act(
        self,
        value: dict[str, Any],
        options: list[tuple[str, str, dict[str, Any]]],
        listed: list[ActionOption],
        router_run: str,
    ) -> AssistantAnswer:
        """The router's result, checked, and a pick run."""
        kind, summary = value.get("kind"), str(value.get("summary") or "")
        app, action = value.get("app"), value.get("action")
        chosen = next((v for a, k, v in options if (a, k) == (app, action)), None)
        if kind == "needs" and chosen is not None:
            question = str(value.get("question") or summary or "Can you say more?")
            return AssistantAnswer(
                kind="needs",
                summary=question,
                app=app,
                action=action,
                question=question,
                router_run=router_run,
            )
        if kind != "pick" or chosen is None:
            summary = summary or "None of your apps does that."
            return AssistantAnswer(
                kind="none", summary=summary, actions=listed, router_run=router_run
            )
        assert isinstance(app, str) and isinstance(action, str)
        fields = value.get("fields") if isinstance(value.get("fields"), dict) else {}
        assert isinstance(fields, dict)
        form = chosen.get("fields")
        if form is not None and (found := interfaces.errors(form, fields)):
            question = f"I could not fill in {action} for {app}: {found[0]}. Can you say it again?"
            return AssistantAnswer(
                kind="needs",
                summary=question,
                app=app,
                action=action,
                question=question,
                fields=fields,
                router_run=router_run,
            )
        try:
            run = await self.apps.act(app, action, fields, asked=True)
        except AppError as e:
            raise AssistantError(409, f"{app} · {action}: {e}") from None
        return AssistantAnswer(
            kind="pick",
            summary=summary or f"{app} · {chosen['description']}",
            app=app,
            action=action,
            why=value.get("why") or None,
            fields=fields,
            run=run,
            router_run=router_run,
        )


def now_where(timezone: str | None) -> str:
    """Now, where the person is ("Tuesday 2026-10-20 09:41, Europe/Paris"): the router works
    dates out from it."""
    try:
        zone = ZoneInfo(timezone) if timezone else None
    except (ZoneInfoNotFoundError, ValueError):
        zone = None
    now = datetime.now(zone) if zone else datetime.now(UTC).astimezone()
    return f"{now:%A %Y-%m-%d %H:%M}, {timezone if zone else now.tzname()}"


def catalog(options: list[tuple[str, str, dict[str, Any]]]) -> str:
    """Each app, then each of its actions: what the router reads."""
    lines: list[str] = []
    for app in dict.fromkeys(a for a, _, _ in options):
        about = next(v["app"] for a, _, v in options if a == app)
        lines.append(f"## App {app}" + (f": {about}" if about else ""))
        for a, action, view in options:
            if a != app:
                continue
            lines.append(f"- action `{action}`: {view['description']}")
            if view.get("examples"):
                lines.append(f"  said like: {'; '.join(view['examples'])}")
            if view.get("fields"):
                lines.append(f"  its form: {json.dumps(view['fields'], ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines).strip()
