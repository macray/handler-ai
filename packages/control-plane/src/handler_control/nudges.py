"""Nudges (H.17): what an app asks a person to do. A nudge is an inbox message with a state:
open until the action it points at succeeds with it, its app says it is done (or withdraws it),
the person dismisses it, or its `until` comes (expired). The app declares each one in its
manifest under a name (`nudges.<name>`); what a click opens (an action's form, a page) is the
manifest's, never the call's.

Its alerts are Handler's, never the app's: its first one when it is sent, then reminders by the
app's `remind`, as the app says, none, or never alerting, per `<app>/<nudge>`, which the person may
also turn off (none sent; its open ones remind no more). One with a `when` is sent by handlerd at
its slots (`due`, the automations' slot logic: the latest slot missed, once), at the app's `when`
or the person's own; with `until = "next"`, its open ones expire at its next slot (`expire`):

    <state>/nudges.json     {"<app>/<nudge>": {setting?: "once" | "silent", off?: true,
                             when?: Schedule (yours), lastSlot?: the slot it was last sent for,
                             lastKey?: that slot's key}}
                            (no setting: as the app says; no when: the app's)

A reminder missed while handlerd was off comes once at its start (`tick`), never a burst.
"""

import contextlib
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel

from handler_contracts import (
    AppManifestNudge,
    AppManifestNudgeRemind,
    InboxMessage,
    InboxNudge,
    NudgeKey,
    NudgeSetting,
    NudgeState,
    Schedule,
)

from . import schedules
from .inbox import Inbox
from .settings import Settings

NUDGE_KEY: TypeAdapter[str] = TypeAdapter(NudgeKey)
# what tells how an action's run went (AppStore): "running", or its result's status, or "failed"
RunState = Callable[[str, str], str]


class Kept(BaseModel):
    """One `<app>/<nudge>` in nudges.json: the person's setting and when, its last slot."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    setting: NudgeSetting | None = None  # none: as the app says
    off: bool = False  # turned off by the person: none sent, its open ones remind no more
    when: Schedule | None = None  # none: the app's
    last_slot: datetime | None = None  # the slot it was last sent for, or since when it counts
    last_key: str | None = None  # the key of the slot it was last sent for


class NudgeError(Exception):
    """A nudge that cannot be sent or changed: its HTTP status, and why."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status


def slot_key(when: Schedule, slot: datetime) -> str:
    """A slot as a nudge's key, as often as it comes: its week (`2026-W47`) when it comes at most
    once a week, its day (`2026-11-16`) at most once a day, else its day and time
    (`2026-11-16T14:30`); local time."""
    local = slot.astimezone()
    minutes = when.every_minutes
    if minutes is None:
        weekly = when.days is not None and len(when.days) == 1
    else:
        weekly = minutes >= 7 * 1440
    if weekly:
        year, week, _ = local.isocalendar()
        return f"{year}-W{week:02d}"
    if minutes is None or minutes >= 1440:
        return local.strftime("%Y-%m-%d")
    return local.strftime("%Y-%m-%dT%H:%M")


def schedule(remind: AppManifestNudgeRemind | None, setting: NudgeSetting) -> tuple[int, int]:
    """Its reminders after the first alert, as (every N minutes, how many): (0, 0) for none."""
    if setting in ("once", "silent") or remind is None:
        return 0, 0
    return remind.every_minutes, remind.times


class Nudges:
    def __init__(self, settings: Settings, inbox: Inbox) -> None:
        self.file = settings.state_dir / "nudges.json"
        self.inbox = inbox
        self.lock = threading.Lock()
        self.kept: dict[str, Kept] = {}
        with contextlib.suppress(FileNotFoundError, ValueError):
            raw = json.loads(self.file.read_text())
            self.kept = {k: Kept.model_validate(v) for k, v in raw.items()}

    # ── how often each one alerts you, when it comes ────────────────────

    def setting(self, app: str, name: str) -> NudgeSetting:
        return self._kept(app, name).setting or "default"

    def own_when(self, app: str, name: str) -> Schedule | None:
        return self._kept(app, name).when

    def is_off(self, app: str, name: str) -> bool:
        return self._kept(app, name).off

    def set_off(self, app: str, name: str, off: bool) -> None:
        """Off: none of its name is sent (the caller's to skip), its open ones stay, reminding no
        more; on again: their reminders as their setting says, from now."""
        self._keep(app, name, off=off)
        now = datetime.now(UTC)
        for m in self.open(app, name):
            self._change(m.id, off=off)
            changed = self.inbox.get(m.id) or m
            self._change(m.id, next_alert_at=self._next(changed, now))

    def set_setting(self, app: str, name: str, setting: NudgeSetting) -> None:
        """Held for that nudge's next ones; its open ones' next reminder follows it at once."""
        self._keep(app, name, setting=None if setting == "default" else setting)
        now = datetime.now(UTC)
        for m in self.open(app, name):
            self._change(m.id, setting=setting)
            changed = self.inbox.get(m.id) or m
            self._change(m.id, next_alert_at=self._next(changed, now))

    def set_when(self, app: str, name: str, when: Schedule | None) -> None:
        """Yours replaces the app's (None: the app's again), counted from now (not at once), for
        its next ones; its open ones say it."""
        self._keep(app, name, when=when, last_slot=datetime.now(UTC))
        for m in self.open(app, name):
            self._change(m.id, own_when=when)

    def due(self, app: str, name: str, when: Schedule, now: datetime) -> datetime | None:
        """The slot it is to be sent for now, taken (once: the latest missed); None: not due. Its
        first look counts from now."""
        kept = self._kept(app, name)
        last = kept.last_slot
        slot = None if last is None else schedules.latest_slot(when, last, now)
        if slot is None:
            if last is None:
                self._keep(app, name, last_slot=now)
            return None
        key = slot_key(when, slot)
        self._keep(app, name, last_slot=slot, last_key=key)
        # a `when` changed after its slot was sent: the same week (day) is not asked twice
        return None if key == kept.last_key else slot

    def next_at(self, app: str, name: str, when: Schedule, now: datetime) -> datetime:
        """Its next slot (in the past when one is due now)."""
        return schedules.next_slot(when, self._kept(app, name).last_slot or now, now)

    def forget(self, app: str) -> None:
        """An app uninstalled: its nudges and their settings go."""
        with self.lock:
            self.kept = {k: v for k, v in self.kept.items() if not k.startswith(f"{app}/")}
            self._save()
        self.inbox.remove(lambda m: m.kind == "nudge" and m.app == app)

    # ── sent by an app, ended ───────────────────────────────────────────

    def send(
        self,
        app: str,
        name: str,
        declared: AppManifestNudge,
        payload: dict[str, Any],
        *,
        persons: list[str],
        form: dict[str, Any] | None,
    ) -> InboxMessage:
        """A nudge into the person's inbox, replacing the open one of its name and key, alerted
        unless the person silenced it."""
        title, body = payload.get("title"), payload.get("body")
        key, fields, person = payload.get("key"), payload.get("fields"), payload.get("person")
        if not isinstance(title, str) or not 0 < len(title) <= 120:
            raise NudgeError(400, "title: 1 to 120 characters")
        if body is not None and (not isinstance(body, str) or len(body) > 1000):
            raise NudgeError(400, "body: at most 1000 characters")
        if key is not None:
            try:
                NUDGE_KEY.validate_python(key, strict=True)
            except ValidationError:
                raise NudgeError(
                    400, "key: 1 to 100 characters, letters, digits and - _ . : only"
                ) from None
        if fields is not None and (not isinstance(fields, dict) or declared.action is None):
            raise NudgeError(400, "fields: an object, for a nudge that opens an action's form")
        person = person or "owner"
        if not isinstance(person, str) or (person != "owner" and person not in persons):
            raise NudgeError(403, f"{app} is not shared with {person}")
        if declared.action is not None and person != "owner":
            raise NudgeError(403, "a nudge opening an action's form goes to the owner only")
        until = _until(payload.get("until"))
        now = datetime.now(UTC)
        if until is not None and until <= now:
            raise NudgeError(400, "until: a time to come")
        if form is not None and fields:
            fields = {k: v for k, v in fields.items() if k in form.get("properties", {})}
        self.inbox.remove(
            lambda m: (
                m.app == app
                and m.person == person
                and m.nudge is not None
                and m.nudge.state == "open"
                and (m.nudge.name, m.nudge.key) == (name, key)
            )
        )
        setting = self.setting(app, name)
        every, times = schedule(declared.remind, setting)
        alerted = setting != "silent"
        nudge = InboxNudge(
            name=name,
            key=key,
            action=declared.action,
            form=form if declared.action is not None else None,
            fields=fields or None,
            until=until,
            remind=declared.remind,
            setting=setting,
            if_ignored=declared.if_ignored,
            when=declared.when,
            own_when=self.own_when(app, name) if declared.when is not None else None,
            alerts=1 if alerted else 0,
            next_alert_at=now + timedelta(minutes=every) if alerted and times else None,
        )
        message = self.inbox.add(
            alert=False,
            source="app",
            name=app,
            person=person,
            title=title,
            summary=body,
            app=app,
            kind="nudge",
            nudge=nudge,
        )
        if declared.open is not None:
            joiner = "&" if "?" in declared.open else "?"
            self._change(message.id, open=f"{declared.open}{joiner}nudge={message.id}")
            message = self.inbox.get(message.id) or message
        if alerted:
            self.inbox.alert(message)
        return message

    def get(self, message_id: str, app: str | None = None) -> InboxMessage:
        """An open nudge (of `app` when given): 404 when there is none, 409 when it ended."""
        m = self.inbox.get(message_id)
        if m is None or m.nudge is None or (app is not None and m.app != app):
            raise NudgeError(404, f"no nudge {message_id}")
        if m.nudge.state != "open":
            raise NudgeError(409, f"this nudge is {m.nudge.state} already")
        return m

    def end(self, message_id: str, state: NudgeState) -> InboxMessage:
        self._change(
            message_id, state=state, ended_at=datetime.now(UTC), next_alert_at=None, run_id=None
        )
        self.inbox.mark_read(message_id)
        m = self.inbox.get(message_id)
        assert m is not None
        return m

    def expire(self, app: str, name: str) -> list[InboxMessage]:
        """Its open ones expire (`until = "next"`: its next slot came), whatever their key."""
        return [self.end(m.id, "expired") for m in self.open(app, name)]

    def withdraw(self, app: str, message_id: str) -> None:
        """Its app says it is no longer needed: gone from the inbox."""
        self.get(message_id, app)
        self.inbox.remove(lambda m: m.id == message_id)

    def keyed(self, app: str, payload: dict[str, Any], declared: list[str]) -> list[InboxMessage]:
        """The open nudges a `{name, key}` names, whoever they went to (none: an empty list):
        how its app closes one whose id it never learnt (sent at its `when`). 403 a name it does
        not declare, 400 a key that is none."""
        name, key = payload.get("name"), payload.get("key")
        if not isinstance(name, str) or name not in declared:
            raise NudgeError(403, f"name: one of its nudges ({', '.join(declared)})")
        try:
            NUDGE_KEY.validate_python(key, strict=True)
        except ValidationError:
            raise NudgeError(
                400, "key: 1 to 100 characters, letters, digits and - _ . : only"
            ) from None
        return [m for m in self.open(app, name) if m.nudge is not None and m.nudge.key == key]

    def running(self, message_id: str, run_id: str) -> None:
        """Its action is an agent's run, under way: done once it succeeds (`tick`)."""
        self._change(message_id, run_id=run_id)

    def action_ended(self, message_id: str, status: str) -> None:
        """Its action answered: done when it succeeded (ok or attention); else it stays open."""
        m = self.inbox.get(message_id)
        if m is None or m.nudge is None or m.nudge.state != "open":
            return
        if status in ("ok", "attention"):
            self.end(message_id, "done")
        else:
            self._change(message_id, run_id=None)

    # ── reminders, expiry ───────────────────────────────────────────────

    def tick(self, run_state: RunState, now: datetime | None = None) -> None:
        """Every open nudge as it should be now: its agent's run ended, its `until` past, its
        reminder due (one, however late)."""
        now = now or datetime.now(UTC)
        for m in self.open():
            n = m.nudge
            assert n is not None and m.app is not None
            if n.run_id is not None:
                state = run_state(m.app, n.run_id)
                if state != "running":
                    self.action_ended(m.id, state)
                    continue
            if n.until is not None and n.until <= now:
                self.end(m.id, "expired")
                continue
            if n.next_alert_at is not None and n.next_alert_at <= now:
                self.remind(m, now)

    def remind(self, m: InboxMessage, now: datetime) -> None:
        assert m.nudge is not None
        m = m.model_copy(
            update={"nudge": m.nudge.model_copy(update={"alerts": m.nudge.alerts + 1})}
        )
        assert m.nudge is not None
        self._change(m.id, alerts=m.nudge.alerts, next_alert_at=self._next(m, now))
        self.inbox.update(m.id, lambda x: x.model_copy(update={"read": False}))
        self.inbox.alert(self.inbox.get(m.id) or m)

    def _next(self, m: InboxMessage, now: datetime) -> datetime | None:
        """When its next reminder comes, after the alerts it had: none when it had them all."""
        assert m.nudge is not None and m.app is not None
        if self.is_off(m.app, m.nudge.name):
            return None
        every, times = schedule(m.nudge.remind, self.setting(m.app, m.nudge.name))
        left = times - max(0, m.nudge.alerts - 1)
        return now + timedelta(minutes=every) if every and left > 0 and m.nudge.alerts else None

    # ── helpers ─────────────────────────────────────────────────────────

    def open(self, app: str | None = None, name: str | None = None) -> list[InboxMessage]:
        return [
            m
            for m in self.inbox.messages
            if m.nudge is not None
            and m.nudge.state == "open"
            and (app is None or m.app == app)
            and (name is None or m.nudge.name == name)
        ]

    def _change(self, message_id: str, **fields: Any) -> None:
        def change(m: InboxMessage) -> InboxMessage:
            assert m.nudge is not None
            return m.model_copy(update={"nudge": m.nudge.model_copy(update=fields)})

        self.inbox.update(message_id, change)

    def _kept(self, app: str, name: str) -> Kept:
        return self.kept.get(f"{app}/{name}") or Kept()

    def _keep(self, app: str, name: str, **fields: Any) -> None:
        """Those fields of `<app>/<nudge>` changed and saved; an entry left empty goes."""
        with self.lock:
            kept = self._kept(app, name).model_copy(update=fields)
            if kept == Kept():
                self.kept.pop(f"{app}/{name}", None)
            else:
                self.kept[f"{app}/{name}"] = kept
            self._save()

    def _save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        raw = {
            k: v.model_dump(mode="json", by_alias=True, exclude_none=True)
            for k, v in self.kept.items()
        }
        tmp.write_text(json.dumps(raw))
        tmp.replace(self.file)


def _until(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        when = InboxNudge.model_validate({"name": "x", "until": value}).until
    except ValidationError:
        raise NudgeError(400, "until: a time with its offset (2026-11-12T22:00:00+01:00)") from None
    return when
