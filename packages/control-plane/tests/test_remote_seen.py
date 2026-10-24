"""The envelopes taken from devices (docs/dev/design/remote.md §4): before they expire, once,
whichever way they came. A gateway may hold one back, or move a live one to the queue."""

from pathlib import Path

import pytest

from handler_control import remote
from handler_control.remote import Seen

MIN = 60 * 1000
DAY = 24 * 60 * MIN
T0 = 1_790_000_000_000  # unix ms


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The time Seen reads (unix ms): set `clock[0]`."""
    at = [T0]
    monkeypatch.setattr(remote.time, "time", lambda: at[0] / 1000)
    return at


def test_taken_once_before_it_expires(tmp_path: Path, clock: list[int]) -> None:
    seen = Seen(tmp_path / "seen.json")
    assert seen.take("live", T0 + 5 * MIN) is None
    assert seen.take("live", T0 + 5 * MIN) == "replayed"
    assert seen.take("old", T0 - 1) == "expired"
    assert seen.take("forever", T0 + 8 * DAY) == "expires too late"


def test_a_live_command_moved_to_the_queue_later_is_refused(
    tmp_path: Path, clock: list[int]
) -> None:
    """The gateway keeps a live command and hands it over again as queued, after any short
    replay memory: it expired with its own 5 minutes."""
    seen = Seen(tmp_path / "seen.json")
    assert seen.take("cmd", T0 + 5 * MIN) is None
    clock[0] = T0 + 11 * MIN
    assert Seen(tmp_path / "seen.json").take("cmd", T0 + 5 * MIN) == "expired"


def test_a_queued_call_is_remembered_as_long_as_it_could_be_taken(
    tmp_path: Path, clock: list[int]
) -> None:
    seen = Seen(tmp_path / "seen.json")
    assert seen.take("queued", T0 + 7 * DAY) is None
    clock[0] = T0 + 6 * DAY
    again = Seen(tmp_path / "seen.json")  # a restart in between
    assert again.take("queued", T0 + 7 * DAY) == "replayed"
    assert again.take("other", T0 + 6 * DAY + 5 * MIN) is None  # expired ids are dropped meanwhile
    clock[0] = T0 + 7 * DAY + 1
    assert Seen(tmp_path / "seen.json").ids == {}
