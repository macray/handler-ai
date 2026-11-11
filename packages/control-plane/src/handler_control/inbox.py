"""The person's inbox: what handler tells a person, like mail. Apps'
notifications (H.9), automations' results and failures (I.3), plans stopped or steps that
completed with hosts refused (D.27), hosts refused to a session while nobody could answer (F.9)
alike; nothing a sandbox writes directly.

    <state>/inbox.json      the last KEEP messages, oldest first

A message for the owner is also shown on the desktop; `listeners` (the remote connector) push it
to the person's phones.
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
        self.lock = threading.Lock()  # inbox.json: changed, written by one route at a time
        with contextlib.suppress(FileNotFoundError, ValueError, ValidationError):
            raw = json.loads(self.file.read_text())
            self.messages = [InboxMessage.model_validate(m) for m in raw]

    def add(self, **fields: Any) -> InboxMessage:
        """A new message (`InboxMessage`'s fields but `id`, `at`, `read`), kept and told."""
        message = InboxMessage(id=secrets.token_hex(8), at=datetime.now(UTC), **fields)
        with self.lock:
            self.messages = [*self.messages, message][-KEEP:]
            self._save()
        if message.person == "owner":
            app = message.source == "app"
            title = f"{message.name}: {message.title}" if app else message.title
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, desktop.notify, title, message.summary)
        for listener in self.listeners:
            listener(message)
        return message

    def list(self, person: str | None = None, limit: int = 50) -> list[InboxMessage]:
        """Newest first; a person's only when `person` is given."""
        mine = [m for m in self.messages if person is None or m.person == person]
        return list(reversed(mine))[:limit]

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
