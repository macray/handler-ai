"""The person's inbox: what handler tells a person, like mail. Apps'
notifications (H.9), automations' results and failures (I.3), plans stopped or steps that
completed with hosts refused (D.27), hosts refused to a session while nobody could answer (F.9)
alike; nothing a sandbox writes directly.

    <state>/inbox.json      the last KEEP messages, oldest first

A message for the owner is also shown on the desktop; `listeners` (the remote connector) push it
to the person's phones. A nudge (H.17, nudges.py) is a message with a state: open ones are listed
first and kept until they end.
"""

import asyncio
import contextlib
import json
import secrets
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from handler_contracts import InboxMessage, InboxStatus

from . import desktop
from .interfaces import RESULT_STATUSES
from .settings import Settings

KEEP = 200


def told_result(result: dict[str, Any]) -> dict[str, Any]:
    """An agent run's result (D.18) as a message's fields: its `status` and `summary` (which its
    schema requires, I.1), `data` the whole of it."""
    status: InboxStatus = result["status"] if result.get("status") in RESULT_STATUSES else "ok"
    summary = result.get("summary")
    return {
        "status": status,
        "summary": summary if isinstance(summary, str) else None,
        "data": result,
    }


class Inbox:
    def __init__(self, settings: Settings) -> None:
        self.file = settings.state_dir / "inbox.json"
        self.messages: list[InboxMessage] = []
        self.listeners: list[Callable[[InboxMessage], None]] = []  # phones (Web Push)
        self.watchers: list[Callable[[], None]] = []  # told after each save (the web UI, D.30)
        self.lock = threading.Lock()  # inbox.json: changed, written by one route at a time
        with contextlib.suppress(FileNotFoundError, ValueError, ValidationError):
            raw = json.loads(self.file.read_text())
            self.messages = [InboxMessage.model_validate(m) for m in raw]

    def add(self, *, alert: bool = True, **fields: Any) -> InboxMessage:
        """A new message (`InboxMessage`'s fields but `id`, `at`, `read`), kept and, unless
        `alert` is False (a nudge you silenced, H.17), told."""
        message = InboxMessage(id=secrets.token_hex(8), at=datetime.now(UTC), **fields)
        with self.lock:
            self.messages = _kept([*self.messages, message])
            self._save()
        if alert:
            self.alert(message)
        return message

    def alert(self, message: InboxMessage) -> None:
        """Tell the person a message is there: the desktop for the owner, their phones."""
        if message.person == "owner":
            app = message.source == "app"
            title = f"{message.name}: {message.title}" if app else message.title
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, desktop.notify, title, message.summary)
        for listener in self.listeners:
            listener(message)

    def list(self, person: str | None = None, limit: int = 50) -> list[InboxMessage]:
        """Open nudges first (H.17), then newest first; a person's only when `person` is given."""
        mine = [m for m in self.messages if person is None or m.person == person]
        newest = list(reversed(mine))
        return ([m for m in newest if _open(m)] + [m for m in newest if not _open(m)])[:limit]

    def update(self, message_id: str, change: Callable[[InboxMessage], InboxMessage]) -> None:
        """Replace one message by what `change` makes of it (a nudge's state, H.17)."""
        with self.lock:
            for i, m in enumerate(self.messages):
                if m.id == message_id:
                    self.messages[i] = change(m)
                    self._save()
                    return

    def remove(self, gone: Callable[[InboxMessage], bool]) -> None:
        with self.lock:
            kept = [m for m in self.messages if not gone(m)]
            if len(kept) != len(self.messages):
                self.messages = kept
                self._save()

    def get(self, message_id: str) -> InboxMessage | None:
        return next((m for m in self.messages if m.id == message_id), None)

    def mark_read(self, message_id: str) -> InboxMessage | None:
        with self.lock:
            for i, m in enumerate(self.messages):
                if m.id == message_id:
                    self.messages[i] = m.model_copy(update={"read": True})
                    self._save()
                    return self.messages[i]
        return None

    def _save(self) -> None:
        data = [m.model_dump(mode="json", by_alias=True, exclude_none=True) for m in self.messages]
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self.file)
        for watcher in self.watchers:
            watcher()


def _open(m: InboxMessage) -> bool:
    return m.nudge is not None and m.nudge.state == "open"


def _kept(messages: list[InboxMessage]) -> list[InboxMessage]:
    """The last KEEP messages, oldest first; an open nudge is kept until it ends, whatever the
    count (H.17)."""
    drop = max(0, len(messages) - KEEP)
    kept: list[InboxMessage] = []
    for m in messages:
        if drop and not _open(m):
            drop -= 1
            continue
        kept.append(m)
    return kept
