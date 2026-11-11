"""What an app's backend may ask handler (H.9, H.11): a small HTTP/1.x server on a Unix socket
in the app's socket folder (`/run/handler-app/handler.sock` in its sandbox), one per running
backend, so handler knows which app is asking without any token. Only with `needs.notify` or
`needs.agents`.

    POST /notify  {title, body?, person?}                → 200 {id} · 400 · 403 · 429
    POST /runs    {agent, fields?, start}                → 202 AppRun · 400 · 403 · 409 · 429
    GET  /runs/{id}                                      → 200 AppRun · 404
    POST /runs/{id}/cancel                               → 200 AppRun · 404 · 409

`person` is who gets a notification ("owner" by default); it must be the owner or a person the
app is shared with. `start` is the START_HEADER of the owner's request the backend is answering.
The template's `server/handler.ts` calls them.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger("handler.apps")

MAX_BYTES = 16 * 1024
TIMEOUT = 10.0

# (app, method, path, body: a JSON object, or None without one) → (status, answer)
Handler = Callable[[str, str, str, dict[str, Any] | None], Awaitable[tuple[int, dict[str, Any]]]]
REASONS = {
    200: "OK",
    202: "Accepted",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    429: "Too Many Requests",
}


class AppApi:
    def __init__(self, name: str, path: Path, handle: Handler) -> None:
        self.name = name
        self.path = path
        self.handle = handle
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
        head = (
            f"HTTP/1.1 {status} {REASONS.get(status, 'Error')}\r\n"
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
        if "://" in path:  # the absolute form, as Bun's fetch writes it when a proxy is set
            url = urlsplit(path)
            path = f"{url.path}?{url.query}" if url.query else url.path
        headers = {
            k.strip().lower(): v.strip()
            for k, _, v in (line.partition(":") for line in lines[1:] if line)
        }
        length = int(headers.get("content-length", "0"))
        if length > MAX_BYTES:
            return 400, {"error": f"body over {MAX_BYTES} bytes"}
        raw = await reader.readexactly(length)
        payload: dict[str, Any] | None = None
        if raw.strip():
            try:
                parsed = json.loads(raw)
            except ValueError:
                return 400, {"error": "body: JSON"}
            if not isinstance(parsed, dict):
                return 400, {"error": "body: a JSON object"}
            payload = parsed
        return await self.handle(self.name, method, path, payload)
