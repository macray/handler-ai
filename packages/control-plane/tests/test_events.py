"""Changes (D.30): the web UI's event stream tells each topic changed, once per burst, and the
stores tell their changes."""

import asyncio
from pathlib import Path

from handler_control.api.events import Changes
from handler_control.inbox import Inbox
from handler_control.settings import Settings


def test_a_stream_gets_each_topic_changed_once_per_burst() -> None:
    """If this fails: a page misses a change (it shows what is no longer so), or reads again
    once per change of a burst."""

    async def scenario() -> list[str]:
        changes = Changes()
        stream = changes.follow()
        got = [await anext(stream)]  # the retry delay, once open
        reading = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0)
        for topic in ("inbox", "sessions", "inbox"):
            changes.tell(topic)
        got += [await reading, await anext(stream)]
        await stream.aclose()
        assert changes.streams == []  # a stream closed is told no more
        return got

    assert asyncio.run(scenario()) == ["retry: 2000\n\n", "data: inbox\n\n", "data: sessions\n\n"]


def test_the_inbox_tells_each_change(tmp_path: Path) -> None:
    settings = Settings(
        port=0,
        config_dir=tmp_path,
        state_dir=tmp_path,
        bindings_dir=tmp_path,
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
    )
    inbox, told = Inbox(settings), []
    inbox.watchers.append(lambda: told.append("inbox"))
    message = inbox.add(source="app", name="coach", person="owner", title="Hi", alert=False)
    inbox.mark_read(message.id)
    assert told == ["inbox", "inbox"]
