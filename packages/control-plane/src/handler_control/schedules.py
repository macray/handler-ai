"""When a scheduled automation is due (I.2) — pure, local time.

`last` is the slot it last ran for, or when it was turned on (a schedule does not run at once).
Slots missed while handlerd was not running (the computer off, asleep) run once: the latest one, and
the run says how many were missed before it.
"""

from datetime import datetime, timedelta

from handler_contracts import Schedule

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_DAYS = 400  # missed `at` slots are counted this far back


def _at_slot(schedule: Schedule, day: datetime) -> datetime | None:
    """`day`'s slot (local), None when `days` leaves that day out."""
    assert schedule.at is not None
    hour, minute = (int(x) for x in schedule.at.split(":"))
    slot = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return slot if not schedule.days or DAYS[slot.weekday()] in schedule.days else None


def latest_slot(schedule: Schedule, last: datetime, now: datetime) -> datetime | None:
    """The latest slot after `last` and at or before `now`; None: not due."""
    if (minutes := schedule.every_minutes) is not None:
        n = (now - last) // timedelta(minutes=minutes)
        return last + n * timedelta(minutes=minutes) if n >= 1 else None
    local = now.astimezone()
    for back in range(8):
        slot = _at_slot(schedule, local - timedelta(days=back))
        if slot is not None and slot <= local:
            return slot if slot > last else None
    raise AssertionError("a week always has a matching day")  # days is non-empty when set


def missed(schedule: Schedule, last: datetime, slot: datetime) -> int:
    """The slots after `last` and before `slot`: not run (only the latest one runs)."""
    if (minutes := schedule.every_minutes) is not None:
        return max(0, (slot - last) // timedelta(minutes=minutes) - 1)
    local, count = last.astimezone(), 0
    start = max(local, slot - timedelta(days=MAX_DAYS))
    for back in range((slot.astimezone().date() - start.date()).days + 1):
        found = _at_slot(schedule, start + timedelta(days=back))
        count += found is not None and last < found < slot
    return count


def next_slot(schedule: Schedule, last: datetime, now: datetime) -> datetime:
    """The next slot after `last` (in the past when one is due now)."""
    if (minutes := schedule.every_minutes) is not None:
        return last + timedelta(minutes=minutes)
    local = max(last, now - timedelta(days=8)).astimezone()
    for ahead in range(9):
        slot = _at_slot(schedule, local + timedelta(days=ahead))
        if slot is not None and slot > last:
            return slot
    raise AssertionError("a week always has a matching day")
