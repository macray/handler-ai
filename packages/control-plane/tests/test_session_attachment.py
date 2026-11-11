"""Unit tests: one attached client of a session (F.7), its own queue between the agent and the
client, so that a client that stops reading never holds up the agent nor the other clients."""

import asyncio

import pytest

from handler_contracts import AcpCloseCode
from handler_control.sessions import QUEUE_SIZE, Attachment


class Client:
    """A client's WebSocket: what it was sent, how it was closed; `reading` False: it stops
    reading, its sends never return (its socket's buffer is full)."""

    def __init__(self, reading: bool = True) -> None:
        self.reading = reading
        self.got: list[str] = []
        self.closed: tuple[int, str] | None = None

    async def send(self, text: str) -> None:
        if not self.reading:
            await asyncio.Event().wait()
        self.got.append(text)

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)


async def _until(condition: object, timeout: float = 5) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():  # ty: ignore[call-non-callable]
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0)


@pytest.mark.rule("attach.a-slow-client-never-holds-up-the-agent")
def test_a_client_that_stops_reading_is_closed_as_too_slow_while_another_gets_everything() -> None:
    """The agent's messages, one more than a client's queue holds, go to a client that stopped
    reading and to one that reads: putting never waits, the first is closed with 4003, the other
    gets every message.

    If this fails: one slow phone stalls the agent for everyone, or is never told to attach
    again and silently misses part of the conversation."""

    async def scenario() -> None:
        slow, reader = Client(reading=False), Client()
        attachments = [Attachment(slow.send, slow.close), Attachment(reader.send, reader.close)]
        sent = QUEUE_SIZE + 2  # one taken by the slow client's stuck send, then a full queue
        for n in range(sent):
            for attachment in attachments:
                attachment.put({"n": n})  # not a coroutine: the agent never waits on a client
            await asyncio.sleep(0)  # the agent's loop goes on between its messages
        await _until(lambda: slow.closed is not None and len(reader.got) == sent)
        assert slow.closed == (AcpCloseCode.TOO_SLOW, "too slow")
        assert reader.closed is None

    asyncio.run(scenario())
