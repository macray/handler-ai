"""Unit tests: the socket an app's backend asks handler on (H.9, H.11) reads both forms of a
request's target: Bun's fetch writes the absolute one when the sandbox has a proxy."""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from handler_control.app_api import MAX_BYTES, MAX_DOCUMENT_BYTES, AppApi


@pytest.mark.parametrize("target", ["/runs/r_1?x=1", "http://handler/runs/r_1?x=1"])
def test_reads_the_path_of_either_form(target: str) -> None:
    seen: list[tuple[str, str, str, dict[str, Any] | None]] = []

    async def handle(
        app: str, method: str, path: str, body: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        seen.append((app, method, path, body))
        return 200, {"ok": True}

    async def run() -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            api = AppApi("notes", Path(tmp) / "handler.sock", handle)
            await api.start()
            reader, writer = await asyncio.open_unix_connection(str(api.path))
            body = b'{"a": 1}'
            head = f"POST {target} HTTP/1.1\r\nHost: handler\r\nContent-Length: {len(body)}\r\n\r\n"
            writer.write(head.encode() + body)
            answer = await reader.read()
            writer.close()
            await api.close()
            return answer

    answer = asyncio.run(run())
    assert answer.startswith(b"HTTP/1.1 200 OK")
    assert seen == [("notes", "POST", "/runs/r_1?x=1", {"a": 1})]


def test_a_call_handler_fails_to_do_gets_500() -> None:
    """A call whose handling raises OSError (a run's sandbox that cannot start, say) gets its
    answer, 500, and its connection closed.

    If this fails: the app's backend waits on a call that never ends, until its own timeout."""

    async def handle(
        app: str, method: str, path: str, body: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        raise OSError(28, "No space left on device")

    async def run() -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            api = AppApi("notes", Path(tmp) / "handler.sock", handle)
            await api.start()
            reader, writer = await asyncio.open_unix_connection(str(api.path))
            writer.write(b"POST /runs HTTP/1.1\r\nHost: handler\r\nContent-Length: 0\r\n\r\n")
            answer = await asyncio.wait_for(reader.read(), 5)
            writer.close()
            await api.close()
            return answer

    answer = asyncio.run(run())
    assert answer.startswith(b"HTTP/1.1 500 Internal Server Error")
    assert answer.endswith(b'{"error": "handler failed; see its log"}')


def ask(head: str, body: bytes = b"") -> tuple[bytes, list[tuple[str, int]]]:
    """One call on a fresh socket: the answer, and what reached the handler (path, body size)."""
    seen: list[tuple[str, int]] = []

    async def handle(
        app: str, method: str, path: str, body: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        seen.append((path, len(json.dumps(body))))
        return 200, {}

    async def run() -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            api = AppApi("notes", Path(tmp) / "handler.sock", handle)
            await api.start()
            reader, writer = await asyncio.open_unix_connection(str(api.path))
            writer.write(head.encode() + body)
            answer = await asyncio.wait_for(reader.read(), 5)
            writer.close()
            await api.close()
            return answer

    return asyncio.run(run()), seen


def padded(size: int) -> bytes:
    """A JSON object of exactly `size` bytes."""
    return json.dumps({"document": "x" * (size - len('{"document": ""}'))}).encode()


def post(path: str, length: int) -> str:
    return f"POST {path} HTTP/1.1\r\nContent-Length: {length}\r\n\r\n"


@pytest.mark.rule("app.its-calls-are-bounded")
@pytest.mark.parametrize("path", ["/notify", "/smd/parse", "/runs"])
def test_a_body_over_16_kib_is_refused_unread(path: str) -> None:
    """Every call but a document written: a body of 16 KiB is read, one over it refused before
    it is read.

    If this fails: an app's backend makes handlerd read as much as it sends."""
    answer, seen = ask(post(path, MAX_BYTES + 1))
    assert answer.startswith(b"HTTP/1.1 400 ")
    assert seen == []
    answer, seen = ask(post(path, MAX_BYTES), padded(MAX_BYTES))
    assert answer.startswith(b"HTTP/1.1 200 ")
    assert seen == [(path, MAX_BYTES)]


@pytest.mark.rule("app.its-calls-are-bounded")
def test_a_document_written_takes_1_mib_not_more() -> None:
    """`POST /smd/write` takes a body up to 1 MiB (a whole document's JSON); over that, refused
    before it is read.

    If this fails: an app cannot write a long document (a CV) through Handler, or makes handlerd
    read as much as it sends."""
    size = MAX_DOCUMENT_BYTES
    answer, seen = ask(post("/smd/write", size), padded(size))
    assert answer.startswith(b"HTTP/1.1 200 ")
    assert seen == [("/smd/write", size)]
    answer, seen = ask(post("/smd/write", size + 1))
    assert answer.startswith(b"HTTP/1.1 400 ")
    assert seen == []
