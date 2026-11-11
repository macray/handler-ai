"""Unit tests: when a scheduled automation is due, what it missed, its next slot (I.2)."""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from handler_contracts import Schedule
from handler_control.schedules import latest_slot, missed, next_slot


def local(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """That wall time of 2026 where the tests run, with that day's offset (not today's: DST)."""
    return datetime(2026, month, day, hour, minute).astimezone()


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """2026-09-28 is a Monday: day 28 = mon, 29 = tue…"""
    return local(9, day, hour, minute)


def schedule(**rule: object) -> Schedule:
    return Schedule.model_validate(rule)


@pytest.mark.rule("schedule.the-latest-slot-once")
def test_every_keeps_its_cadence() -> None:
    s = schedule(every="30m")
    assert latest_slot(s, at(28, 8), at(28, 8, 29)) is None
    assert latest_slot(s, at(28, 8), at(28, 8, 31)) == at(28, 8, 30)  # not the time it is seen
    assert next_slot(s, at(28, 8, 30), at(28, 8, 31)) == at(28, 9)
    assert schedule(every="2h").every_minutes == 120


@pytest.mark.rule("schedule.the-latest-slot-once")
def test_every_after_the_computer_was_off() -> None:
    s = schedule(every="1h")
    slot = latest_slot(s, at(28, 8), at(28, 12, 10))  # off from 08:10 to 12:10
    assert slot is not None and slot == at(28, 12)
    assert missed(s, at(28, 8), slot) == 3  # 09:00, 10:00, 11:00: only 12:00 runs


@pytest.mark.rule("schedule.the-latest-slot-once")
def test_at_runs_once_per_slot() -> None:
    s = schedule(at="08:30")
    turned_on = at(28, 9)  # after today's slot: nothing until tomorrow
    assert latest_slot(s, turned_on, at(28, 23)) is None
    assert next_slot(s, turned_on, at(28, 23)) == at(29, 8, 30)
    assert latest_slot(s, turned_on, at(29, 8, 30)) == at(29, 8, 30)
    assert latest_slot(s, at(29, 8, 30), at(29, 20)) is None


@pytest.mark.rule("schedule.the-latest-slot-once")
def test_missed_slots_run_once() -> None:
    s = schedule(at="08:30")
    last = at(28, 8, 30)
    now = at(30, 12)  # off on tuesday and wednesday morning
    slot = latest_slot(s, last, now)
    assert slot is not None and slot == at(30, 8, 30)
    assert missed(s, last, slot) == 1  # tuesday's
    assert latest_slot(s, slot, now + timedelta(hours=1)) is None  # ran: not again


@pytest.mark.rule("schedule.the-latest-slot-once")
def test_days() -> None:
    s = schedule(at="08:30", days=["mon", "fri"])
    assert latest_slot(s, at(28, 9), at(30, 9)) is None  # wednesday: monday's slot is past
    friday = local(10, 2, 8, 30)
    assert next_slot(s, at(28, 9), at(30, 9)) == friday
    assert latest_slot(s, at(28, 9), friday + timedelta(minutes=1)) == friday
    next_monday = local(10, 5, 9, 0)
    assert missed(s, at(28, 8, 30), latest_slot(s, at(28, 8, 30), next_monday) or friday) == 1


@pytest.mark.rule("schedule.the-latest-slot-once")
@pytest.mark.parametrize(
    "rule",
    [
        {},
        {"every": "30m", "at": "08:00"},
        {"every": "2m"},  # at least 5m
        {"every": "1d"},
        {"at": "8:30"},
        {"at": "24:00"},
        {"every": "1h", "days": ["mon"]},
        {"at": "08:00", "days": ["monday"]},
        {"at": "08:00", "days": []},
    ],
)
def test_invalid(rule: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        schedule(**rule)
