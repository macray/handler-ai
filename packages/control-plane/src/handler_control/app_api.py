"""What a mini app's backend may ask handler (H.9): a small HTTP/1.x server on a Unix socket in the
app's socket folder (`/run/handler-app/handler.sock` in its sandbox), one per running backend, so
handler knows which app is asking without any token. Only with `needs.notify`.

    POST /notify  {title, body?, person?}   → 200 {id} · 400 · 403 · 429

`person` is who gets it ("owner" by default); it must be the owner or a person the app is shared
with. The template's `server/handler.ts` calls it.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

log = logging.getLogger("handler.apps")

MAX_BYTES = 16 * 1024
TIMEOUT = 10.0

Handler = Callable[[str, dict[str, Any]], Awaitable[tuple[int, dict[str, Any]]]]


class AppApi:
    def __init__(self, name: str, path: Path, notify: Handler) -> None:
        self.name = name
        self.path = path
        self.notify = notify
        self.server: asyncio.Server | None = None

    async def start(self) -> None:
        self.path.unlink(missing_ok=True)
        self.server = await asyncio.start_unix_server(self.serve, path=str(self.path))

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.server.wait_closed(), 2.0)
        self.path.unlink(missing_ok=True)

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            status, body = await asyncio.wait_for(self.answer(reader), TIMEOUT)
        except (TimeoutError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            status, body = 400, {"error": "bad request"}
        data = json.dumps(body).encode()
        reason = {200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found"}
        head = (
            f"HTTP/1.1 {status} {reason.get(status, 'Error')}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(data)}\r\n"
            "Connection: close\r\n\r\n"
        )
        with contextlib.suppress(OSError):
            writer.write(head.encode() + data)
            await writer.drain()
            writer.close()

    async def answer(self, reader: asyncio.StreamReader) -> tuple[int, dict[str, Any]]:
        head = await reader.readuntil(b"\r\n\r\n")
        if len(head) > MAX_BYTES:
            return 400, {"error": "headers too long"}
        lines = head.decode("latin-1").split("\r\n")
        method, path, _ = lines[0].split(" ", 2)
        headers = {
            k.strip().lower(): v.strip()
            for k, _, v in (line.partition(":") for line in lines[1:] if line)
        }
        length = int(headers.get("content-length", "0"))
        if length > MAX_BYTES:
            return 400, {"error": f"body over {MAX_BYTES} bytes"}
        raw = await reader.readexactly(length)
        if (method, path) != ("POST", "/notify"):
            return 404, {"error": "only POST /notify"}
        try:
            payload = json.loads(raw)
        except ValueError:
            return 400, {"error": "body: JSON"}
        if not isinstance(payload, dict):
            return 400, {"error": "body: a JSON object"}
        return await self.notify(self.name, payload)
