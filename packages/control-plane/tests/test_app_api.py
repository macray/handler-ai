"""Unit tests: the socket an app's backend asks handler on (H.9, H.11) reads both forms of a
request's target: Bun's fetch writes the absolute one when the sandbox has a proxy."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import pytest

from handler_control.app_api import AppApi


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
