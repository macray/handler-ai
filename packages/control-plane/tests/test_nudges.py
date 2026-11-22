"""Unit tests: nudges (H.17), what an app asks a person to do: declared in its manifest, sent on
its socket, open in the inbox until done, dismissed or expired, reminded by Handler as the person
set it. The app's backend is never started: its socket's calls go to `from_app` directly."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from pydantic import ValidationError

from handler_contracts import (
    ActionResult,
    ActionRun,
    ActionStatus,
    AppManifest,
    AppManifestNudgeRemind,
    InboxMessage,
    InboxNudge,
    NudgeFill,
    NudgeParams,
    Schedule,
)
from handler_control import assistant as assistant_module
from handler_control import desktop
from handler_control.agents import AgentRegistry
from handler_control.app_runs import AppRuns
from handler_control.apps import AppError, AppRecord, AppStore, Deployment
from handler_control.assistant import Assistant
from handler_control.inbox import KEEP, Inbox
from handler_control.nudges import NUDGE_KEY, NudgeError, schedule, slot_key
from handler_control.remote import Connector, Device, RemoteError
from handler_control.sessions import SessionStore
from handler_control.settings import Settings

MANIFEST = """apiVersion = "handler.app/v1"
name = "worklog"
version = "1.0.0"

[actions.log]
description = "Log what you did"
route = "POST /api/log"
fields = { type = "object", properties = { done = { type = "string" } } }

[nudges.daily-log]
description = "Add what you did today"
action = "log"
remind = { every = "2h", times = 2 }
ifIgnored = "The day stays empty"

[nudges.review]
description = "Look at your week"
open = "/week"
"""


def manifest(**nudges: Any) -> AppManifest:
    return AppManifest.model_validate(
        {
            "apiVersion": "handler.app/v1",
            "name": "w",
            "version": "1.0.0",
            "actions": {"log": {"description": "Log", "route": "POST /api/log"}},
            "nudges": nudges,
        }
    )


@pytest.mark.rule("nudge.declared-only")
@pytest.mark.parametrize(
    "nudge",
    [
        {"description": "x"},  # opens nothing
        {"description": "x", "action": "log", "open": "/a"},  # both
        {"description": "x", "action": "nope"},  # no such action
        {"description": "x", "open": "week"},  # not a path
        {"description": "x", "open": "//evil.example/"},  # another site
        {"description": "x", "open": "/a", "remind": {"every": "10m"}},  # too often
        {"description": "x", "open": "/a", "remind": {"every": "1w"}},  # minutes, hours or days
        {"description": "x", "open": "/a", "remind": {"every": "1h", "times": 6}},
    ],
)
def test_a_nudge_the_manifest_cannot_hold_is_refused(nudge: dict[str, Any]) -> None:
    """A nudge opens one of its app's actions or a page of its own; its reminders come at most
    every 30 minutes, at most 5 times.

    If this fails: an app's nudge opens another site, or nags every minute."""
    with pytest.raises(ValidationError):
        manifest(n=nudge)


@pytest.mark.rule("nudge.declared-only")
def test_declaring_nudges_opens_handler_s_socket() -> None:
    assert manifest(n={"description": "x", "open": "/a"}).handler_api
    assert not manifest().handler_api


# ── an app installed, its socket asked ──────────────────────────────────


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppStore:
    monkeypatch.setattr(desktop, "notify", lambda *_: True)
    s = make_store(tmp_path)
    install(s)
    return s


def make_store(tmp_path: Path) -> AppStore:
    settings = Settings(
        port=7430,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path / "bindings",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path / "ui",
        data_dir=tmp_path / "data",
    )
    inbox, registry = Inbox(settings), AgentRegistry(settings.state_dir)
    sessions = SessionStore(settings, registry)
    runs = AppRuns(settings, sessions, inbox)
    return AppStore(settings, token="t0ken", inbox=inbox, runs=runs)


def install(s: AppStore, text: str = MANIFEST) -> None:
    folder = s.version_dir("worklog", 1)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "app.toml").write_text(text)
    s.records["worklog"] = AppRecord(
        name="worklog", deployments=[Deployment(1, "1.0.0", datetime.now(UTC))]
    )


def call(s: AppStore, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    async def go() -> Any:
        return await s.from_app("worklog", method, path, body)

    return asyncio.run(go())


def alerts(s: AppStore) -> list[str]:
    told: list[str] = []
    s.inbox.listeners.append(lambda m: told.append(m.id))
    return told


def nudge_of(s: AppStore, message_id: str) -> InboxMessage:
    m = s.inbox.get(message_id)
    assert m is not None and m.nudge is not None
    return m


def its(s: AppStore, message_id: str) -> InboxNudge:
    """The nudge part of an inbox message."""
    n = nudge_of(s, message_id).nudge
    assert n is not None
    return n


@pytest.mark.rule("nudge.declared-only")
def test_an_app_sends_only_the_nudges_it_declares(store: AppStore) -> None:
    """A name its manifest does not declare is refused (403): what a nudge opens is the
    manifest's, never the call's (an `action` or `open` in the call is ignored).

    If this fails: an app makes Handler open any of its pages, or any action, by a nudge."""
    assert call(store, "POST", "/nudge", {"name": "other", "title": "Hi"})[0] == 403
    status, body = call(
        store, "POST", "/nudge", {"name": "review", "title": "Your week", "open": "/admin"}
    )
    assert status == 200
    m = nudge_of(store, body["id"])
    assert m.kind == "nudge" and m.nudge is not None
    assert m.nudge.open == f"/week?nudge={m.id}"


@pytest.mark.rule("nudge.action-ones-to-the-owner")
def test_an_action_s_nudge_goes_to_the_owner_only(store: AppStore) -> None:
    """An action runs as the owner: a nudge opening one goes to nobody else (403); a nudge
    opening a page may go to a person the app is shared with.

    If this fails: a family member's answer runs an action as you."""
    store.records["worklog"].persons = ["alice"]
    to_alice = {"title": "Hi", "person": "alice"}
    assert call(store, "POST", "/nudge", {"name": "daily-log", **to_alice})[0] == 403
    assert call(store, "POST", "/nudge", {"name": "review", **to_alice})[0] == 200
    to_bob = {"name": "review", "title": "x", "person": "bob"}
    assert call(store, "POST", "/nudge", to_bob)[0] == 403


@pytest.mark.rule("nudge.its-form-is-the-action-s")
def test_a_nudge_carries_its_action_s_form_filled_in(store: AppStore) -> None:
    """The nudge keeps its action's form and the app's draft of it, a field the form does not
    have dropped.

    If this fails: the form shown asks something else than the action takes."""
    body = {"name": "daily-log", "title": "Today?", "fields": {"done": "PR #12", "x": 1}}
    m = nudge_of(store, call(store, "POST", "/nudge", body)[1]["id"])
    assert m.nudge is not None
    assert m.nudge.form == {"type": "object", "properties": {"done": {"type": "string"}}}
    assert m.nudge.fields == {"done": "PR #12"}


@pytest.mark.rule("nudge.one-per-name-and-key")
def test_a_nudge_of_the_same_name_and_key_replaces_the_open_one(store: AppStore) -> None:
    """Sent again with its name and key, the open nudge is replaced; another key is another
    nudge.

    If this fails: the inbox fills with the same reminder."""
    first = call(store, "POST", "/nudge", {"name": "daily-log", "key": "d1", "title": "a"})[1]
    second = call(store, "POST", "/nudge", {"name": "daily-log", "key": "d1", "title": "b"})[1]
    other = call(store, "POST", "/nudge", {"name": "daily-log", "key": "d2", "title": "c"})[1]
    ids = [m.id for m in store.inbox.list()]
    assert first["id"] not in ids
    assert {second["id"], other["id"]} <= set(ids)


def done_by(status: ActionStatus) -> Callable[..., Any]:
    async def act_by_code(name: str, action: str, *_: Any, **__: Any) -> ActionRun:
        return ActionRun(
            app=name,
            action=action,
            state="succeeded",
            result=ActionResult(status=status, summary="Logged."),
        )

    return act_by_code


@pytest.mark.rule("nudge.open-until-done-dismissed-or-expired")
def test_a_nudge_is_done_when_its_action_succeeds_with_it(
    store: AppStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The action done from the nudge: done when it succeeded (ok or attention), still open when
    it failed; opening or reading it never makes it done.

    If this fails: a nudge goes away though nothing was done, or stays though it was."""
    sent = call(store, "POST", "/nudge", {"name": "daily-log", "title": "Today?"})[1]["id"]
    store.inbox.mark_read(sent)
    assert its(store, sent).state == "open"
    monkeypatch.setattr(store, "_act_by_code", done_by("failed"))
    asyncio.run(store.act("worklog", "log", {"done": "x"}, sent))
    assert its(store, sent).state == "open"
    monkeypatch.setattr(store, "_act_by_code", done_by("attention"))
    asyncio.run(store.act("worklog", "log", {"done": "x"}, sent))
    assert its(store, sent).state == "done"
    with pytest.raises(AppError):  # once done, an action is no longer done from it
        asyncio.run(store.act("worklog", "log", {}, sent))


@pytest.mark.rule("nudge.its-form-is-the-action-s")
def test_the_action_s_code_is_told_which_nudge_it_answers(
    store: AppStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its route gets `X-HANDLER-Nudge: <id>; key=<key>` (the key as is, none without one) when
    the action is done from a nudge, and no such header otherwise; a key a header value could not
    carry as is is refused when the nudge is sent.

    If this fails: the app cannot tell which nudge an answer is for, and matches it by its text."""
    got: list[str | None] = []

    def backend(request: httpx.Request) -> httpx.Response:
        got.append(request.headers.get("x-handler-nudge"))
        return httpx.Response(200, json={"status": "ok", "summary": "Logged."})

    client = httpx.AsyncClient(transport=httpx.MockTransport(backend), base_url="http://app")

    async def running(_name: str) -> Any:
        return SimpleNamespace(client=client)

    monkeypatch.setattr(store, "ensure_running", running)
    for bad in ("2026 W47", "été", "a;b", "a\nb", "", "x" * 101, 47):
        status, answer = call(
            store, "POST", "/nudge", {"name": "daily-log", "key": bad, "title": "?"}
        )
        assert status == 400 and "letters, digits" in answer["error"], bad
    keyed = {"name": "daily-log", "key": "role:acme_2024-W47.1", "title": "Week?"}
    with_key = call(store, "POST", "/nudge", keyed)[1]["id"]
    without = call(store, "POST", "/nudge", {"name": "daily-log", "title": "Today?"})[1]["id"]
    asyncio.run(store.act("worklog", "log", {"done": "x"}, with_key))
    asyncio.run(store.act("worklog", "log", {"done": "x"}, without))
    asyncio.run(store.act("worklog", "log", {"done": "x"}))
    assert got == [f"{with_key}; key=role:acme_2024-W47.1", without, None]


@pytest.mark.rule("action.its-code-is-told-where-it-was-asked", "action.its-answer-may-name-a-page")
def test_the_action_s_code_is_told_where_it_was_asked_and_may_name_a_page(
    store: AppStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its route gets `X-HANDLER-Via`: `ask` for Ask's pick, `nudge` from a nudge, `try` when
    the person filled its form; its answer may name the page of its UI showing what it did, a
    path of its own only.

    If this fails: the app cannot say "added by Ask", or Ask's Open lands on another site."""
    got: list[str | None] = []
    opens = ["/?line=todo%2Fcall-the-bank", "//evil.test/"]

    def backend(request: httpx.Request) -> httpx.Response:
        got.append(request.headers.get("x-handler-via"))
        return httpx.Response(200, json={"status": "ok", "summary": "Added.", "open": opens.pop(0)})

    client = httpx.AsyncClient(transport=httpx.MockTransport(backend), base_url="http://app")

    async def running(_name: str) -> Any:
        return SimpleNamespace(client=client)

    monkeypatch.setattr(store, "ensure_running", running)
    sent = call(store, "POST", "/nudge", {"name": "daily-log", "title": "Today?"})[1]["id"]
    asked = asyncio.run(store.act("worklog", "log", {"done": "x"}, asked=True))
    assert asked.result is not None and asked.result.open == "/?line=todo%2Fcall-the-bank"
    elsewhere = asyncio.run(store.act("worklog", "log", {"done": "x"}, sent))
    assert elsewhere.state == "failed" and "open" in (elsewhere.error or "")
    opens.append("/")
    asyncio.run(store.act("worklog", "log", {"done": "x"}))
    assert got == ["ask", "nudge", "try"]


@pytest.mark.rule("nudge.open-until-done-dismissed-or-expired")
def test_its_app_ends_it_and_the_person_dismisses_it(store: AppStore) -> None:
    """Its app says it is done, or withdraws it (gone); another app cannot; `until` past makes
    it expired.

    If this fails: a nudge stays open for ever, or one app closes another's."""
    a = call(store, "POST", "/nudge", {"name": "review", "key": "a", "title": "a"})[1]["id"]
    b = call(store, "POST", "/nudge", {"name": "review", "key": "b", "title": "b"})[1]["id"]
    with pytest.raises(NudgeError) as other:  # another app's: not found
        store.nudges.get(a, "other")
    assert other.value.status == 404
    assert call(store, "POST", f"/nudge/{a}/done")[0] == 200
    assert its(store, a).state == "done"
    assert call(store, "DELETE", f"/nudge/{b}")[0] == 200
    assert store.inbox.get(b) is None
    soon = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    c = call(store, "POST", "/nudge", {"name": "review", "title": "c", "until": soon})[1]["id"]

    async def later() -> None:
        store.nudges.tick(store.run_state, datetime.now(UTC) + timedelta(hours=2))

    asyncio.run(later())
    assert its(store, c).state == "expired"
    past = {"name": "review", "title": "d", "until": "2020-01-01T00:00:00Z"}
    assert call(store, "POST", "/nudge", past)[0] == 400


@pytest.mark.rule("nudge.one-per-name-and-key")
@pytest.mark.rule("nudge.open-until-done-dismissed-or-expired")
def test_its_app_closes_a_nudge_by_its_name_and_key(store: AppStore) -> None:
    """`POST /nudge/done` or `DELETE /nudge` with `{name, key}` ends the open ones of that name
    and key, whoever they went to, and says which (none: an empty list); another key stays; a
    name it does not declare is refused, a key that is none too.

    If this fails: a question answered on the app's page stays open in your inbox, its app never
    having learnt the id of the nudge Handler sent for it."""
    store.records["worklog"].persons = ["alice"]
    q1 = call(store, "POST", "/nudge", {"name": "review", "key": "q:1", "title": "a"})[1]["id"]
    to_alice = {"name": "review", "key": "q:1", "title": "a", "person": "alice"}
    alices = call(store, "POST", "/nudge", to_alice)[1]["id"]
    q2 = call(store, "POST", "/nudge", {"name": "review", "key": "q:2", "title": "b"})[1]["id"]
    status, answer = call(store, "POST", "/nudge/done", {"name": "review", "key": "q:1"})
    assert status == 200 and sorted(answer["ids"]) == sorted([q1, alices])
    assert its(store, q1).state == its(store, alices).state == "done"
    assert its(store, q2).state == "open"
    assert call(store, "POST", "/nudge/done", {"name": "review", "key": "q:1"}) == (
        200,
        {"ids": []},
    )
    assert call(store, "DELETE", "/nudge", {"name": "review", "key": "q:2"}) == (200, {"ids": [q2]})
    assert store.inbox.get(q2) is None
    assert call(store, "POST", "/nudge/done", {"name": "other", "key": "q:1"})[0] == 403
    for bad in ({"name": "review"}, {"name": "review", "key": "a b"}):
        assert call(store, "DELETE", "/nudge", bad)[0] == 400


@pytest.mark.rule("nudge.reminders-are-handlerd-s")
def test_an_open_nudge_is_reminded_as_its_app_says_once_however_late(store: AppStore) -> None:
    """Alerted when sent, then every 2 hours, 2 times (the app's `remind`); a reminder missed
    for a day comes once, never a burst; none once it is done.

    If this fails: an ignored nudge is forgotten, or floods your phone after a night off."""
    told = alerts(store)
    sent = call(store, "POST", "/nudge", {"name": "daily-log", "title": "Today?"})[1]["id"]
    assert told == [sent]
    start = datetime.now(UTC)

    async def at(hours: float) -> None:
        store.nudges.tick(store.run_state, start + timedelta(hours=hours))

    asyncio.run(at(1))
    assert told == [sent]
    asyncio.run(at(24))  # a day late: one reminder
    assert told == [sent, sent]
    asyncio.run(at(25))
    assert told == [sent, sent]
    asyncio.run(at(26.1))
    assert told == [sent, sent, sent]
    asyncio.run(at(100))  # its 2 reminders had: no more
    assert told == [sent, sent, sent]


@pytest.mark.rule("nudge.remind-setting-per-nudge-name")
def test_remind_me_less_holds_for_that_nudge_and_its_next_ones_only(
    store: AppStore, tmp_path: Path
) -> None:
    """ "Silent" on daily-log: its next ones come with no alert at all; review is untouched; the
    setting survives a restart; "once" stops reminders of an open one at once.

    If this fails: toning one nudge down silences them all, or not even that one."""
    told = alerts(store)
    first = call(store, "POST", "/nudge", {"name": "daily-log", "key": "1", "title": "a"})[1]["id"]
    store.set_nudge_setting("worklog", "daily-log", "once")
    assert its(store, first).next_alert_at is None
    assert its(store, first).setting == "once"  # the inbox says it, for any device
    store.set_nudge_setting("worklog", "daily-log", "silent")
    second = call(store, "POST", "/nudge", {"name": "daily-log", "key": "2", "title": "b"})[1]
    page = call(store, "POST", "/nudge", {"name": "review", "title": "c"})[1]
    assert told == [first, page["id"]]
    assert second["id"] in {m.id for m in store.inbox.list()}
    again = make_store(tmp_path)
    assert again.nudges.setting("worklog", "daily-log") == "silent"
    assert again.nudges.setting("worklog", "review") == "default"
    views = {n.name: n.setting for n in store.view("worklog").nudges}
    assert views == {"daily-log": "silent", "review": "default"}


@pytest.mark.rule("nudge.remind-setting-per-nudge-name")
def test_reminders_are_the_app_s_or_none() -> None:
    remind = AppManifestNudgeRemind(every="2h", times=2)
    assert schedule(remind, "default") == (120, 2)
    assert schedule(remind, "once") == (0, 0)
    assert schedule(remind, "silent") == (0, 0)
    assert schedule(None, "default") == (0, 0)
    daily = AppManifestNudgeRemind(every="1d", times=2)  # "Every day"
    assert schedule(daily, "default") == (1440, 2)


@pytest.mark.rule("inbox.keeps-the-last-200")
def test_an_open_nudge_is_kept_and_listed_first_whatever_the_count(store: AppStore) -> None:
    """Over KEEP messages, the oldest go but an open nudge.

    If this fails: a nudge you have not answered disappears under notifications."""
    sent = call(store, "POST", "/nudge", {"name": "review", "title": "Your week"})[1]["id"]

    async def flood() -> None:
        for i in range(KEEP + 5):
            store.inbox.add(source="app", name="worklog", person="owner", title=f"{i}")

    asyncio.run(flood())
    assert store.inbox.get(sent) is not None
    assert len(store.inbox.messages) == KEEP
    assert store.inbox.list()[0].id == sent


@pytest.mark.rule("app.uninstalled-leaves-nothing-of-it")
def test_uninstalled_its_nudges_and_their_settings_go(store: AppStore) -> None:
    call(store, "POST", "/nudge", {"name": "review", "title": "Your week"})
    store.set_nudge_setting("worklog", "review", "once")
    store.set_nudge_off("worklog", "review", True)
    asyncio.run(store.remove("worklog"))
    assert [m for m in store.inbox.messages if m.app == "worklog"] == []
    assert store.nudges.setting("worklog", "review") == "default"
    assert not store.nudges.is_off("worklog", "review")


@pytest.mark.rule("app-origin.opened-by-a-one-time-link")
def test_a_page_nudge_s_link_opens_its_page_once(store: AppStore) -> None:
    """The link of a page's nudge opens the app at that page (its path, `?nudge=<id>`), once;
    an action's nudge has no page.

    If this fails: a nudge's link lands elsewhere, or opens the app twice."""
    page = call(store, "POST", "/nudge", {"name": "review", "title": "Your week"})[1]["id"]
    url = store.nudge_link(page)
    code = url.split("code=")[1]
    assert store.redeem("worklog", code) == f"/week?nudge={page}"
    assert store.redeem("worklog", code) is None
    form = call(store, "POST", "/nudge", {"name": "daily-log", "title": "Today?"})[1]["id"]
    with pytest.raises(AppError):
        store.nudge_link(form)


@pytest.mark.rule("app-notify.only-to-whom-it-is-shared-with")
def test_nudges_count_with_notifications_reminders_do_not(store: AppStore) -> None:
    """30 notifications or nudges an hour; Handler's reminders are not counted."""
    for _ in range(29):
        assert asyncio.run(store.notification("worklog", {"title": "x"}))[0] == 200
    assert call(store, "POST", "/nudge", {"name": "review", "title": "c"})[0] == 200
    assert call(store, "POST", "/nudge", {"name": "review", "key": "2", "title": "c"})[0] == 429


@pytest.mark.rule("nudge.declared-only")
def test_a_trial_run_s_nudges_go_nowhere(store: AppStore) -> None:
    assert asyncio.run(store.trial("worklog", "POST", "/nudge", {"name": "review"})) == (
        200,
        {"id": None},
    )
    assert store.inbox.messages == []


# ── what was said fills a nudge's form ──────────────────────────────────


class Router:
    """Sessions that answer every run of the router with `value`, and record its form."""

    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value
        self.forms: list[dict[str, Any]] = []

    def create(self, *_: Any, run: Any, **__: Any) -> Any:
        self.forms.append(run.fields)
        return SimpleNamespace(id="s-router")

    async def result_of(self, _: str) -> tuple[dict[str, Any], str]:
        return self.value, ""


def filled(
    store: AppStore, monkeypatch: pytest.MonkeyPatch, value: dict[str, Any], message_id: str
) -> tuple[NudgeFill, Router]:
    router = Router(value)
    asker = Assistant(store.settings, store, cast(Any, router), cast(Any, None))
    monkeypatch.setattr(asker, "router", lambda: None)
    monkeypatch.setattr(assistant_module.save_rules, "session_model", lambda *_: None)

    async def never(*_: Any, **__: Any) -> Any:
        raise AssertionError("an action ran from what was said")

    monkeypatch.setattr(store, "act", never)
    return asyncio.run(asker.fill(message_id, "I fixed the login bug", "Europe/Paris")), router


@pytest.mark.rule("nudge.voice-fills-never-sends")
def test_what_was_said_fills_the_form_and_runs_nothing(
    store: AppStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The router gets the nudge's action alone; its pick's fields come back to fill the form,
    and nothing runs: the person sends it.

    If this fails: speaking to a nudge logs something you have not checked."""
    sent = call(store, "POST", "/nudge", {"name": "daily-log", "title": "Today?"})[1]["id"]
    pick = {"kind": "pick", "app": "worklog", "action": "log", "fields": {"done": "login bug"}}
    answer, router = filled(store, monkeypatch, pick, sent)
    assert (answer.fields, answer.question) == ({"done": "login bug"}, None)
    assert "action `log`" in router.forms[0]["actions"]
    assert "daily-log" not in router.forms[0]["actions"]
    assert its(store, sent).state == "open"
    none, _ = filled(store, monkeypatch, {"kind": "none", "summary": "Say more?"}, sent)
    assert (none.fields, none.question) == (None, "Say more?")


@pytest.mark.rule("nudge.voice-fills-never-sends")
def test_only_an_open_action_nudge_of_the_owner_s_is_filled(
    store: AppStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = call(store, "POST", "/nudge", {"name": "review", "title": "Your week"})[1]["id"]
    with pytest.raises(NudgeError) as refused:
        filled(store, monkeypatch, {"kind": "none"}, page)
    assert refused.value.status == 409


@pytest.mark.rule("nudge.dismissed-only-by-its-person")
def test_a_nudge_is_dismissed_from_its_person_s_devices_only(store: AppStore) -> None:
    """A phone dismisses only a nudge of its device's person.

    If this fails: the owner's phone silences what an app asked of a family member, or theirs
    silences the owner's."""
    store.records["worklog"].persons = ["alice"]
    to_alice = {"name": "review", "title": "Your week", "person": "alice"}
    alices = call(store, "POST", "/nudge", to_alice)[1]["id"]
    owners = call(store, "POST", "/nudge", {"name": "review", "key": "o", "title": "Yours"})[1]
    connector = Connector(
        store.settings, SessionStore(store.settings, AgentRegistry(store.settings.state_dir)), store
    )

    def phone(person: str) -> Device:
        return Device(id=f"d_{person}", name=person, key=b"k" * 32, created_at=datetime.now(UTC))

    owner_phone, alice_phone = phone("owner"), phone("alice")
    alice_phone.person = "alice"
    for device, nudge in ((owner_phone, alices), (alice_phone, owners["id"])):
        with pytest.raises(RemoteError, match="not your nudge"):
            connector.nudge_dismiss(device, NudgeParams(id=nudge))
        assert its(store, nudge).state == "open"
    assert connector.nudge_dismiss(alice_phone, NudgeParams(id=alices)).nudge is not None
    assert its(store, alices).state == "dismissed"


@pytest.mark.rule("app.its-calls-are-bounded")
@pytest.mark.parametrize(
    "too_much",
    [
        pytest.param({"title": ""}, id="no-title"),
        pytest.param({"title": "t" * 121}, id="title-over-120"),
        pytest.param({"body": "b" * 1001}, id="body-over-1000"),
        pytest.param({"key": "k" * 101}, id="key-over-100"),
    ],
)
def test_a_nudge_too_long_is_refused(store: AppStore, too_much: dict[str, Any]) -> None:
    """If this fails: an app fills your inbox and your phone's screen with its text."""
    assert call(store, "POST", "/nudge", {"name": "review", "title": "Hi", **too_much})[0] == 400
    at_most = {"title": "t" * 120, "body": "b" * 1000, "key": "k" * 100}
    assert call(store, "POST", "/nudge", {"name": "review", **at_most})[0] == 200


# ── sent by handlerd at its `when` ──────────────────────────────────────

WEEKLY = (
    MANIFEST
    + """
[nudges.weekly]
description = "Add what you did this week"
action = "log"
when = { at = "16:00", days = ["fri"] }
"""
)
PREPARED = (
    MANIFEST
    + """
[nudges.asked]
description = "Answer what the app asks"
action = "log"
when = { every = "1d" }
prepare = "POST /api/nudges/asked"
"""
)


def local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """A time of this computer's clock, as schedules read it."""
    return datetime(year, month, day, hour, minute).astimezone()


def at_slots(s: AppStore, now: datetime) -> list[InboxMessage]:
    """handlerd's look at the slots at `now`, and what it put in the inbox then."""
    before = {m.id for m in s.inbox.messages}

    async def go() -> None:
        s.send_due_nudges(now)
        await asyncio.gather(*s.sending)

    asyncio.run(go())
    return [m for m in s.inbox.messages if m.id not in before]


def answering(
    s: AppStore, monkeypatch: pytest.MonkeyPatch, *answers: httpx.Response
) -> list[httpx.Request]:
    """The app's backend answering its `prepare` calls with `answers`, in turn."""
    calls: list[httpx.Request] = []
    left = list(answers)

    def backend(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return left.pop(0)

    client = httpx.AsyncClient(transport=httpx.MockTransport(backend), base_url="http://app")

    async def running(_name: str) -> Any:
        return SimpleNamespace(client=client)

    monkeypatch.setattr(s, "ensure_running", running)
    return calls


def keys(messages: list[InboxMessage]) -> list[tuple[str, str | None]]:
    return [(m.nudge.name, m.nudge.key) for m in messages if m.nudge is not None]


@pytest.mark.rule("nudge.sent-at-its-when")
@pytest.mark.parametrize(
    "nudge",
    [
        {"description": "x", "open": "/a", "prepare": "POST /api/n"},  # prepare without when
        {"description": "x", "open": "/a", "when": {"every": "1d"}, "prepare": "GET /api/n"},
        {"description": "x", "open": "/a", "when": {"every": "1w"}},
        {"description": "x", "open": "/a", "when": {"days": ["fri"]}},
        {"description": "x", "open": "/a", "until": "next"},  # until its next slot, without when
        {"description": "x", "open": "/a", "when": {"every": "1d"}, "until": "2026-11-20"},
    ],
)
def test_a_when_or_prepare_the_manifest_cannot_hold_is_refused(nudge: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        manifest(n=nudge)
    assert manifest(n={"description": "x", "open": "/a", "when": {"every": "2d"}}).nudges


@pytest.mark.rule("nudge.sent-at-its-when")
def test_a_scheduled_nudge_comes_at_its_slot_once_however_late(store: AppStore) -> None:
    """A nudge with a `when` and no `prepare`: sent by handlerd at its slot, its description as
    title, the slot's week as key, to the owner; not at once when first seen; after a month off,
    only the latest slot missed comes.

    If this fails: a weekly nudge never comes, comes twice, or a month of them at once."""
    install(store, WEEKLY)
    assert at_slots(store, local(2026, 11, 16, 12)) == []  # its first look: from now on
    assert at_slots(store, local(2026, 11, 20, 15, 59)) == []
    (sent,) = at_slots(store, local(2026, 11, 20, 16, 1))
    assert sent.nudge is not None and sent.person == "owner"
    assert (sent.title, sent.nudge.key, sent.nudge.form) == (
        "Add what you did this week",
        "2026-W47",
        {"type": "object", "properties": {"done": {"type": "string"}}},
    )
    assert sent.nudge.when is not None and sent.nudge.when.at == "16:00"
    assert at_slots(store, local(2026, 11, 20, 18)) == []
    assert keys(at_slots(store, local(2026, 12, 19, 9))) == [("weekly", "2026-W51")]
    again = make_store(store.settings.state_dir.parent)  # handlerd restarted: the slot is kept
    install(again, WEEKLY)
    assert at_slots(again, local(2026, 12, 19, 10)) == []


@pytest.mark.rule("nudge.sent-at-its-when")
@pytest.mark.parametrize(
    ("when", "key"),
    [
        ({"at": "16:00", "days": ["fri"]}, "2026-W47"),
        ({"at": "16:00", "days": ["mon", "fri"]}, "2026-11-20"),
        ({"at": "16:00"}, "2026-11-20"),
        ({"every": "14d"}, "2026-W47"),
        ({"every": "1d"}, "2026-11-20"),
        ({"every": "2h"}, "2026-11-20T16:00"),
    ],
)
def test_a_slot_s_key_is_its_week_its_day_or_its_time(when: dict[str, Any], key: str) -> None:
    """As often as it comes: at most once a week, keyed by its week; once a day, by its day;
    more, by its day and time; each fits a nudge's key."""
    got = slot_key(Schedule.model_validate(when), local(2026, 11, 20, 16))
    assert got == key and NUDGE_KEY.validate_python(got) == key


@pytest.mark.rule("nudge.sent-at-its-when")
def test_prepare_is_called_as_the_owner_and_says_what_to_send(
    store: AppStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At each slot, its `prepare` route is called as the owner with no start token (it cannot
    start a run): 204 sends none; one nudge (its key the slot's unless it gives one) filled in
    by the app; or several of its name, each with its own key.

    If this fails: the app's timed code could start its agent with nobody asking (a loop), or
    sends a nudge with nothing to ask."""
    install(store, PREPARED)
    one = {"title": "Your role at Acme?", "body": "For your CV", "fields": {"done": "x"}}
    several = [{"title": "Q1?", "key": "q1"}, {"title": "Q2?", "key": "q2"}]
    calls = answering(
        store,
        monkeypatch,
        httpx.Response(204),
        httpx.Response(200, json=one),
        httpx.Response(200, json=several),
    )
    at_slots(store, local(2026, 11, 16, 12))
    assert at_slots(store, local(2026, 11, 17, 13)) == []  # 204: none this time
    (sent,) = at_slots(store, local(2026, 11, 18, 13))
    assert sent.nudge is not None
    assert (sent.title, sent.summary, sent.nudge.key, sent.nudge.fields) == (
        "Your role at Acme?",
        "For your CV",
        "2026-11-18",
        {"done": "x"},
    )
    assert keys(at_slots(store, local(2026, 11, 19, 13))) == [("asked", "q1"), ("asked", "q2")]
    assert [(r.method, r.url.path) for r in calls] == [("POST", "/api/nudges/asked")] * 3
    for r in calls:
        assert r.headers["x-handler-person"] == "owner"
        assert "x-handler-start" not in r.headers


@pytest.mark.rule("nudge.sent-at-its-when")
@pytest.mark.parametrize(
    ("answer", "why"),
    [
        pytest.param(httpx.Response(500, json={"error": "no data"}), "no data", id="error"),
        pytest.param(httpx.Response(200, json={"body": "x"}), "answered no nudge", id="no-title"),
        pytest.param(
            httpx.Response(200, json=[{"title": "a"}, {"title": "b"}]), "own key", id="no-keys"
        ),
        pytest.param(
            httpx.Response(200, json=[{"title": "a", "key": f"k{i}"} for i in range(11)]),
            "at most 10",
            id="too-many",
        ),
    ],
)
def test_a_failed_prepare_is_told_and_not_retried(
    store: AppStore, monkeypatch: pytest.MonkeyPatch, answer: httpx.Response, why: str
) -> None:
    """Its route failing or answering what is no nudge: nothing sent, the reason in the app's
    log and in your inbox; that slot is not tried again.

    If this fails: a scheduled nudge silently never comes, or retries every 20 seconds."""
    install(store, PREPARED)
    calls = answering(store, monkeypatch, answer)
    at_slots(store, local(2026, 11, 16, 12))
    (told,) = at_slots(store, local(2026, 11, 17, 13))
    assert told.nudge is None and told.status == "failed" and told.app == "worklog"
    assert why in (told.summary or "") and "2026-11-17" in (told.summary or "")
    assert why in store.log_tail("worklog")
    assert at_slots(store, local(2026, 11, 17, 14)) == [] and len(calls) == 1


@pytest.mark.rule("nudge.sent-at-its-when")
def test_a_when_changed_after_its_slot_asks_not_twice_for_the_same_week(store: AppStore) -> None:
    """A weekly nudge sent Friday, then moved to Sunday on Saturday: that Sunday is the same
    week, not asked again; the next Sunday is.

    If this fails: moving a weekly nudge to a later day asks you twice for a week you answered."""
    install(store, WEEKLY)
    at_slots(store, local(2026, 11, 16, 12))
    assert keys(at_slots(store, local(2026, 11, 20, 16, 1))) == [("weekly", "2026-W47")]
    store.nudges.set_when("worklog", "weekly", Schedule(at="10:00", days=["sun"]))
    store.nudges._keep("worklog", "weekly", last_slot=local(2026, 11, 21, 9))  # set Saturday
    assert at_slots(store, local(2026, 11, 22, 10, 1)) == []
    assert keys(at_slots(store, local(2026, 11, 29, 10, 1))) == [("weekly", "2026-W48")]


UNTIL_NEXT = (
    MANIFEST
    + """
[nudges.weekly]
description = "Add what you did this week"
action = "log"
ifIgnored = "That week stays empty"
when = { at = "16:00", days = ["fri"] }
until = "next"

[nudges.asked]
description = "Answer what the app asks"
action = "log"
when = { every = "1d" }
prepare = "POST /api/nudges/asked"
until = "next"
"""
)


@pytest.mark.rule("nudge.sent-at-its-when")
def test_until_next_expires_the_open_one_at_its_next_slot(
    store: AppStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With `until = "next"`, a scheduled nudge still open when its next slot comes expires then
    (its `ifIgnored` shown), whatever the new one's key, even when `prepare` sends none that
    time; without it, last week's stays open beside this week's.

    If this fails: a weekly nudge you skipped piles up beside the next week's in your inbox."""
    install(store, UNTIL_NEXT)
    answering(
        store,
        monkeypatch,
        httpx.Response(200, json=[{"title": "Q1?", "key": "q1"}, {"title": "Q2?", "key": "q2"}]),
        httpx.Response(200, json={"title": "Q1?", "key": "q1"}),
        httpx.Response(204),
    )
    at_slots(store, local(2026, 11, 16, 12))

    def weekly(sent: list[InboxMessage]) -> InboxMessage:
        (m,) = [m for m in sent if m.nudge is not None and m.nudge.name == "weekly"]
        return m

    week47 = weekly(at_slots(store, local(2026, 11, 20, 16, 1)))  # and that day's questions
    week48 = weekly(at_slots(store, local(2026, 11, 27, 16, 1)))
    assert its(store, week47.id).state == "expired" and its(store, week48.id).state == "open"
    assert its(store, week47.id).if_ignored == "That week stays empty"
    asked = store.nudges.open("worklog", "asked")
    assert keys(asked) == [("asked", "q1")]  # the 11-20's q1 and q2 expired at the 11-27's
    at_slots(store, local(2026, 11, 28, 13))  # 204: nothing to ask, the slot came still
    assert store.nudges.open("worklog", "asked") == []
    assert its(store, asked[0].id).state == "expired"
    install(store, WEEKLY)  # without it, a skipped week stays open beside the next
    (w49,) = at_slots(store, local(2026, 12, 4, 16, 1))
    assert {its(store, week48.id).state, its(store, w49.id).state} == {"open"}


@pytest.mark.rule("nudge.remind-setting-per-nudge-name")
def test_your_when_replaces_the_app_s(store: AppStore, tmp_path: Path) -> None:
    """Yours replaces the app's for that nudge (counted from when you set it), is kept, shown on
    the app's page and on its open ones, and goes back to the app's; a nudge its code sends has
    no time to change.

    If this fails: changing when one nudge comes moves another, or is lost at a restart."""
    install(store, WEEKLY)
    at_slots(store, local(2026, 11, 16, 12))
    (open_one,) = at_slots(store, local(2026, 11, 20, 16, 1))
    daily = Schedule(at="09:00")
    view = {n.name: n for n in store.set_nudge_when("worklog", "weekly", daily).nudges}
    assert view["weekly"].when is not None and view["weekly"].when.days == ["fri"]
    assert view["weekly"].own_when == daily and view["weekly"].next_at is not None
    assert its(store, open_one.id).own_when == daily
    assert make_store(tmp_path).nudges.own_when("worklog", "weekly") == daily
    with pytest.raises(AppError, match="no time to change"):
        store.set_nudge_when("worklog", "daily-log", daily)
    view = {n.name: n for n in store.set_nudge_when("worklog", "weekly", None).nudges}
    assert view["weekly"].own_when is None and its(store, open_one.id).own_when is None


@pytest.mark.rule("nudge.off-sends-none", "nudge.sent-at-its-when")
def test_a_nudge_turned_off_sends_none_and_its_open_ones_remind_no_more(
    store: AppStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off: its slots pass with nothing sent and its `prepare` not called, its code's call is
    not sent (no id), its open ones stay but remind no more; on again: from its next slot (the
    ones passed while off never come), its open ones reminded again. Only that nudge.

    If this fails: a nudge you turned off still comes, or a week of them comes when you turn it
    back on, or one you did not turn off stops."""
    install(store, PREPARED)
    calls = answering(store, monkeypatch, httpx.Response(200, json={"title": "Q?"}))
    at_slots(store, local(2026, 11, 16, 12))  # its first look
    opened = call(store, "POST", "/nudge", {"name": "daily-log", "key": "1", "title": "a"})[1]
    assert its(store, opened["id"]).next_alert_at is not None

    store.set_nudge_off("worklog", "asked", True)
    store.set_nudge_off("worklog", "daily-log", True)
    assert its(store, opened["id"]).next_alert_at is None and its(store, opened["id"]).off
    assert opened["id"] in {m.id for m in store.inbox.list()}  # still there, answerable
    assert at_slots(store, local(2026, 11, 17, 13)) == [] and calls == []
    assert call(store, "POST", "/nudge", {"name": "daily-log", "title": "b"}) == (200, {"id": None})
    review = call(store, "POST", "/nudge", {"name": "review", "title": "c"})[1]["id"]
    assert review is not None  # another nudge of the app: untouched
    assert {n.name: n.off for n in store.view("worklog").nudges} == {
        "daily-log": True,
        "review": False,
        "asked": True,
    }

    store.set_nudge_off("worklog", "asked", False)
    store.set_nudge_off("worklog", "daily-log", False)
    assert its(store, opened["id"]).next_alert_at is not None  # reminded again
    assert at_slots(store, local(2026, 11, 17, 14)) == []  # the slot passed while off: never
    (sent,) = at_slots(store, local(2026, 11, 18, 13))  # its next one
    assert sent.title == "Q?" and len(calls) == 1
