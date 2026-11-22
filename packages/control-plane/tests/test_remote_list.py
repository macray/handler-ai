"""Unit tests: the list of shared sessions sent to the devices around when what they are shown
changes (D.7, `Connector.session_shown`): at once for a turn or an ask, at most every 10 s for a
last line alone, never twice the same. No gateway: what would be sent stays in each link; the
clock is the test's."""

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from test_remote_devices import connector

from handler_contracts import SharedSession
from handler_control import remote
from handler_control.remote import Connector, Device, Link


def a_link(c: Connector, name: str, scope: str = "all") -> Link:
    device = Device(
        id=f"d_{name}",
        name=name,
        key=b"k" * 32,
        created_at=datetime.now(UTC),
        scope=cast(Any, scope),
    )
    link = Link(device, last_seen=time.monotonic())
    c.links[device.id] = link
    return link


def lists(link: Link) -> list[list[dict[str, Any]]]:
    return [
        f["m"]["params"]["sessions"]
        for f in link.frames
        if f["m"].get("method") == "_handler/remote/sessions_changed"
    ]


@pytest.mark.rule("phone.its-list-follows-the-sessions")
def test_last_alone_is_sent_at_most_every_10_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A change of a session's state is sent at once; the same list is not sent again; a change
    of its last line alone waits for 10 s after the last list sent, and what is sent meanwhile
    carries it; a device for apps only is never sent one.

    If this fails: the phone and the gateway get a list on every chunk of an agent's output, or
    Home says "working" for a session waiting on you."""
    c = connector(tmp_path)
    monkeypatch.setattr(c, "schedule_flush", lambda link: None)  # what is sent stays in the link
    phone, apps_only = a_link(c, "phone"), a_link(c, "kid", scope="apps")
    shown: dict[str, Any] = {"busy": False, "last": None, "since": datetime.now(UTC)}
    live = SimpleNamespace(remote=True, record=SimpleNamespace(state="running"))
    monkeypatch.setattr(c, "shared", lambda: [live])
    monkeypatch.setattr(
        c,
        "describe",
        lambda _live: SharedSession(
            id="s_1", origin="ui", program=None, scope="/p", pending_permissions=0, **shown
        ),
    )
    clock = [1000.0]
    c.clock = lambda: clock[0]

    async def go() -> None:
        def changed(**change: Any) -> None:
            shown.update(change)
            c.session_shown(cast(Any, live))

        changed(busy=True)  # a turn starts: at once
        assert [s[0]["busy"] for s in lists(phone)] == [True]
        changed()  # nothing a device is shown changed: not sent
        assert len(lists(phone)) == 1
        changed(last="Run npm test")  # a last line alone, just after a list: held
        assert len(lists(phone)) == 1 and c.list_later is not None
        changed(last="Read notes.md")  # one timer for them all
        clock[0] += remote.LIST_EVERY
        timer = c.list_later
        assert 9 < timer.when() - asyncio.get_running_loop().time() <= remote.LIST_EVERY
        timer.cancel()
        c.send_list()  # its 10 s are over: what it runs
        assert [s[0].get("last") for s in lists(phone)] == [None, "Read notes.md"]
        assert c.list_later is None
        clock[0] += 1
        changed(last="All 42 tests pass")  # held again
        assert len(lists(phone)) == 2 and c.list_later is not None
        changed(busy=False)  # the turn ends: at once, its last line with it
        assert lists(phone)[-1][0]["busy"] is False
        assert lists(phone)[-1][0]["last"] == "All 42 tests pass"
        assert c.list_later is None  # nothing left to send
        clock[0] += 60
        changed(last="Done")  # long after the last list: at once
        assert lists(phone)[-1][0]["last"] == "Done"
        live.remote = False
        changed(busy=True)  # a session that is not shared tells nobody
        assert len(lists(phone)) == 4

    asyncio.run(go())
    assert lists(apps_only) == []
