"""Unit tests: a paired device's attachments held only while it is around (remote design): one
that sent nothing for its lease, or whose output piled up past its outbox, is detached and told
why; and who is pushed an inbox message. No gateway here: what would be sent stays in the
device's link; the push service is a stand-in."""

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from handler_contracts import InboxMessage, PushKeys, WebPush
from handler_control import remote
from handler_control.agents import AgentRegistry
from handler_control.app_runs import AppRuns
from handler_control.apps import AppStore
from handler_control.inbox import Inbox
from handler_control.projects import ProjectRegistry
from handler_control.remote import Connector, Device, Link
from handler_control.sessions import SessionStore
from handler_control.settings import Settings


class Live:
    """A session's side of an attachment: which attachments it was told are gone."""

    def __init__(self) -> None:
        self.removed: list[object] = []

    def remove(self, attachment: object) -> None:
        self.removed.append(attachment)


def connector(tmp_path: Path) -> Connector:
    settings = Settings(
        port=0, config_dir=tmp_path, state_dir=tmp_path / "state", bindings_dir=tmp_path,
        allowed_origins=frozenset(), web_ui_dir=tmp_path,
    )  # fmt: skip
    registry = AgentRegistry(settings.state_dir)
    sessions, inbox = SessionStore(settings, registry), Inbox(settings)
    runs = AppRuns(settings, sessions, ProjectRegistry(tmp_path, registry), inbox)
    return Connector(settings, sessions, AppStore(settings, "t0ken", inbox, runs))


def a_link(c: Connector, name: str, live: Live, seen_ago: float) -> Link:
    device = Device(id=f"d_{name}", name=name, key=b"k" * 32, created_at=datetime.now(UTC))
    link = Link(device, last_seen=time.monotonic() - seen_ago)
    link.attachments = {f"s_{name}": (cast(Any, live), cast(Any, f"attachment-{name}"))}
    c.links[device.id] = link
    return link


def notices(link: Link) -> list[dict[str, Any]]:
    return [
        f["m"]["params"] for f in link.frames if f["m"].get("method") == "_handler/remote/closed"
    ]


@pytest.mark.rule("phone.a-quiet-device-is-detached")
def test_a_device_quiet_past_its_lease_is_detached_and_told(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A device that sent nothing for longer than its lease (shortened here) is detached from
    its sessions and told (1001, "device idle"); one seen within it keeps them.

    If this fails: a sleeping phone keeps a session alive for ever."""
    monkeypatch.setattr(remote, "LEASE", 0.6)
    c = connector(tmp_path)
    quiet_live, around_live = Live(), Live()
    quiet = a_link(c, "quiet", quiet_live, seen_ago=1.0)
    around = a_link(c, "around", around_live, seen_ago=0.0)

    async def a_while() -> None:
        leases = asyncio.create_task(c.leases())
        await asyncio.sleep(0.3)  # beyond one check (every LEASE / 6), within the lease
        leases.cancel()

    asyncio.run(a_while())
    assert quiet.attachments == {} and quiet_live.removed == ["attachment-quiet"]
    assert notices(quiet) == [{"s": "s_quiet", "code": 1001, "reason": "device idle"}]
    assert list(around.attachments) == ["s_around"] and around_live.removed == []


@pytest.mark.rule("phone.a-quiet-device-is-detached")
def test_a_device_too_far_behind_is_detached_and_told(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its unsent output past its outbox (shortened here): what waited is dropped, it is
    detached and told (4003, "too slow"), to load again from where it was.

    If this fails: a stuck gateway fills handlerd's memory with one device's output."""
    monkeypatch.setattr(remote, "OUTBOX_BYTES", 2000)
    c = connector(tmp_path)
    live = Live()
    link = a_link(c, "behind", live, seen_ago=0.0)

    async def output() -> None:
        update = {"jsonrpc": "2.0", "method": "session/update", "params": {"x": "y" * 300}}
        for _ in range(5):
            c.send(link, "s_behind", update)
        assert len(link.frames) == 5 and link.attachments  # within its outbox
        c.send(link, "s_behind", update)

    asyncio.run(output())
    assert link.attachments == {} and live.removed == ["attachment-behind"]
    assert [f["m"].get("method") for f in link.frames] == ["_handler/remote/closed"]
    assert notices(link) == [{"s": "s_behind", "code": 4003, "reason": "too slow"}]


# ── pushes (A5) ─────────────────────────────────────────────────────────


KEYS = PushKeys(p256dh="BPhone", auth="secret")  # not checked past push_subscribe


def a_phone(c: Connector, name: str, person: str, endpoint: str | None) -> Device:
    device = Device(
        id=f"d_{name}", name=name, key=b"k" * 32, created_at=datetime.now(UTC), person=person,
        push=WebPush(endpoint=endpoint, keys=KEYS) if endpoint else None,
    )  # fmt: skip
    c.devices[device.id] = device
    c.save_devices()
    return device


def pushed_on(c: Connector, person: str, statuses: dict[str, int]) -> list[str]:
    """An inbox message for `person`: the endpoints pushed to (each answering its status)."""
    pushed: list[str] = []

    async def push(http: Any, vapid: Any, to: WebPush, contact: str) -> int:
        pushed.append(to.endpoint)
        return statuses.get(to.endpoint, 201)

    async def told() -> None:
        with pytest.MonkeyPatch.context() as m:
            m.setattr(remote.webpush, "push", push)
            message = InboxMessage(
                id="m1", source="app", name="coach", person=person, title="Hi", at=datetime.now(UTC)
            )
            c.on_message(message)
            await asyncio.gather(*c.pushes)

    asyncio.run(told())
    return pushed


@pytest.mark.rule("push.the-person-s-devices-only")
def test_an_inbox_message_is_pushed_to_its_person_s_subscribed_devices_only(
    tmp_path: Path,
) -> None:
    """If this fails: a family member is told of your messages, or you are not told of yours."""
    c = connector(tmp_path)
    a_phone(c, "mine", "owner", "https://push.example/mine")
    a_phone(c, "my-tablet", "owner", None)  # not subscribed
    a_phone(c, "alice-s", "alice", "https://push.example/alice")
    assert pushed_on(c, "owner", {}) == ["https://push.example/mine"]
    assert pushed_on(c, "alice", {}) == ["https://push.example/alice"]


@pytest.mark.rule("push.the-person-s-devices-only")
@pytest.mark.parametrize(
    ("status", "forgotten"),
    [
        pytest.param(410, True, id="gone"),
        pytest.param(404, True, id="not-found"),
        pytest.param(500, False, id="a-failing-service-keeps-it"),
        pytest.param(429, False, id="a-busy-service-keeps-it"),
    ],
)
def test_a_subscription_the_push_service_says_is_gone_is_forgotten(
    tmp_path: Path, status: int, forgotten: bool
) -> None:
    """If this fails: a phone that unsubscribed is pushed for ever, or one is dropped for a
    service's passing failure."""
    c = connector(tmp_path)
    a_phone(c, "mine", "owner", "https://push.example/mine")
    pushed_on(c, "owner", {"https://push.example/mine": status})
    kept = connector(tmp_path).devices["d_mine"].push  # as kept
    assert (kept is None) == forgotten
    if kept:
        assert kept == WebPush(endpoint="https://push.example/mine", keys=KEYS)


def a_test_push_on(
    c: Connector, device: Device, status: int | None
) -> tuple[dict[str, Any], list[str]]:
    """The device asks for a test push (its push service answering `status`; None: unreachable):
    the answer it gets, and the endpoints pushed to."""
    pushed: list[str] = []

    async def push(http: Any, vapid: Any, to: WebPush, contact: str) -> int:
        pushed.append(to.endpoint)
        if status is None:
            raise remote.httpx.ConnectError("no route to host")
        return status

    async def asked() -> dict[str, Any]:
        with pytest.MonkeyPatch.context() as m:
            m.setattr(remote.webpush, "push", push)
            return (await c.push_test(device, {})).model_dump(by_alias=True)

    return asyncio.run(asked()), pushed


@pytest.mark.rule("push.the-person-s-devices-only")
def test_a_test_push_goes_to_the_asking_device_only(tmp_path: Path) -> None:
    """If this fails: a test from one phone rings the others, or tells "sent" when it was not."""
    c = connector(tmp_path)
    mine = a_phone(c, "mine", "owner", "https://push.example/mine")
    a_phone(c, "my-tablet", "owner", "https://push.example/tablet")
    assert a_test_push_on(c, mine, 201) == (
        {"sent": True, "problem": None},
        ["https://push.example/mine"],
    )


@pytest.mark.parametrize(
    ("status", "problem"),
    [
        pytest.param(410, "no longer knows this device", id="gone"),
        pytest.param(403, "refused it (HTTP 403)", id="refused"),
        pytest.param(None, "could not reach the push service", id="unreachable"),
    ],
)
def test_a_test_push_says_why_it_was_not_sent(
    tmp_path: Path, status: int | None, problem: str
) -> None:
    """If this fails: the person sees no notification and no reason."""
    c = connector(tmp_path)
    mine = a_phone(c, "mine", "owner", "https://push.example/mine")
    answer, _ = a_test_push_on(c, mine, status)
    assert answer["sent"] is False and problem in answer["problem"]


def test_a_test_push_from_a_device_not_subscribed_says_so(tmp_path: Path) -> None:
    c = connector(tmp_path)
    off = a_phone(c, "off", "owner", None)
    assert a_test_push_on(c, off, 201) == (
        {"sent": False, "problem": "notifications are off on this device"},
        [],
    )
