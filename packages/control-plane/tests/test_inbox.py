"""The inbox's file (H.9, I.3)."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from handler_control import desktop
from handler_control.inbox import Inbox
from handler_control.settings import Settings


def test_messages_marked_read_at_once_are_all_kept_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mark all read: one request per message, their routes running in threads at once."""
    monkeypatch.setattr(desktop, "notify", lambda *_: None)
    settings = Settings(
        port=0,
        config_dir=tmp_path,
        state_dir=tmp_path,
        bindings_dir=tmp_path,
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
    )
    inbox = Inbox(settings)

    async def told() -> list[str]:  # a message for the owner is shown on the desktop from the loop
        told = [inbox.add(person="owner", source="automation", name="a", title=f"{i}", status="ok")
                for i in range(40)]  # fmt: skip
        return [m.id for m in told]

    ids = asyncio.run(told())
    with ThreadPoolExecutor(20) as pool:
        assert all(pool.map(inbox.mark_read, ids))
    assert all(m.read for m in Inbox(settings).list())
