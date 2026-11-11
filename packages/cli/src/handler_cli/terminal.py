"""The terminal client of `handler run` and `handler attach`: a daemon-held session
(F) in the terminal, as one more attachment (F.7) — the web UI and a paired phone can show the same
session at the same time.

Plain ACP over the session's WebSocket: `initialize`, `session/load` (the daemon replays the
conversation), then prompts typed on stdin. The agent's text streams to stdout; tool calls are one
line each; a permission request lists its options, the next line answers it (the first answer, from
any client, wins). Ctrl-C cancels the turn in progress, or detaches when there is none; Ctrl-D and
`/detach` detach: the agent keeps running (`handler attach` comes back to it). `/stop` stops it.

stdin is read by a daemon thread (a blocked read must not keep the process alive after detaching).
"""

import asyncio
import contextlib
import itertools
import json
import signal
import sys
import threading
from typing import Any, TextIO

with contextlib.suppress(ImportError):  # not on every platform
    import readline  # noqa: F401 — line editing and history for input()

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed
from websockets.typing import Subprotocol

from handler_contracts import ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX, AcpCloseCode

from .client import ClientError, Daemon

Message = dict[str, Any]
HELP = "Enter: send · Ctrl-C: cancel the turn (or detach) · Ctrl-D, /detach: detach · /stop: stop"


class SessionClosedError(Exception):
    """handlerd closed the session's WebSocket: what was asked gets no answer."""


class Screen:
    """What is printed: streamed text, one line per event, colors when stdout is a terminal."""

    def __init__(self, out: TextIO) -> None:
        self.out = out
        self.color = out.isatty()
        self.midline = False  # the last write did not end a line
        self.stream: str | None = None  # the kind of chunk being streamed

    def paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def line(self, text: str) -> None:
        if self.midline:
            self.out.write("\n")
        self.out.write(text + "\n")
        self.out.flush()
        self.midline, self.stream = False, None

    def chunk(self, kind: str, text: str) -> None:
        if self.stream != kind and self.midline:
            self.out.write("\n")
        if kind == "thought":
            text = self.paint(text, "2")
        self.out.write(text)
        self.out.flush()
        self.midline, self.stream = not text.endswith("\n"), kind

    def update(self, u: Message) -> None:
        kind = u.get("sessionUpdate")
        content = u.get("content") or {}
        text = content.get("text", "") if isinstance(content, dict) else ""
        if kind == "agent_message_chunk":
            self.chunk("agent", text)
        elif kind == "agent_thought_chunk":
            self.chunk("thought", text)
        elif kind == "user_message_chunk":
            self.line(self.paint("> ", "1;36") + text)
        elif kind == "tool_call":
            self.line(self.paint(f"• {u.get('title') or u.get('kind') or 'tool'}", "33"))
        elif kind == "tool_call_update" and u.get("status") == "failed":
            self.line(self.paint(f"  ✗ {u.get('title') or 'failed'}", "31"))
        elif kind == "plan":
            for entry in u.get("entries") or []:
                mark = {"completed": "✓", "in_progress": "…"}.get(entry.get("status"), "·")
                self.line(self.paint(f"  {mark} {entry.get('content', '')}", "2"))


class Terminal:
    def __init__(self, daemon: Daemon, session: Message, out: TextIO = sys.stdout) -> None:
        self.daemon = daemon
        self.session = session
        self.screen = Screen(out)
        self.ids = itertools.count(1)
        self.waiting: dict[int, asyncio.Future[Message]] = {}
        self.permission: Message | None = None  # the request the next line answers
        self.busy = False
        self.prompt_id: int | None = None
        self.lines: asyncio.Queue[str | None] = asyncio.Queue()
        self.ws: ClientConnection | None = None
        self.done = asyncio.Event()
        self.result = 0
        self.background: set[asyncio.Task[None]] = set()

    # ── wire ────────────────────────────────────────────────────────────

    async def send(self, msg: Message) -> None:
        assert self.ws is not None
        await self.ws.send(json.dumps({"jsonrpc": "2.0"} | msg))

    async def request(self, method: str, params: Message) -> Message:
        rid = next(self.ids)
        future: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
        self.waiting[rid] = future
        await self.send({"id": rid, "method": method, "params": params})
        response = await future
        if "error" in response:
            raise RuntimeError(f"{method}: {response['error'].get('message')}")
        return response.get("result") or {}

    async def receive(self) -> None:
        assert self.ws is not None
        try:
            async for raw in self.ws:
                for line in str(raw).splitlines():
                    if line.strip():
                        self.handle(json.loads(line))
        except ConnectionClosed:
            pass
        for future in self.waiting.values():
            if not future.done():
                future.set_exception(SessionClosedError())
        self.waiting.clear()
        if not self.done.is_set():
            self.screen.line(self.screen.paint(f"[session closed: {self.why_closed()}]", "31"))
            self.result = 1
            self.done.set()

    def why_closed(self) -> str:
        """The close's reason; the session's error, whole, when it ended (a close's reason is cut
        at 120 characters)."""
        assert self.ws is not None
        reason = self.ws.close_reason or "closed"
        if self.ws.close_code not in (AcpCloseCode.AGENT_EXITED, AcpCloseCode.SESSION_STOPPED):
            return reason
        try:
            error = self.daemon.call("GET", f"/v1/sessions/{self.session['id']}").get("error")
        except ClientError:
            error = None
        return error or reason

    def handle(self, m: Message) -> None:
        method, mid = m.get("method"), m.get("id")
        if method is None and mid in self.waiting:
            self.waiting.pop(mid).set_result(m)
            return
        if method is None and mid == self.prompt_id:
            self.end_turn((m.get("result") or {}).get("stopReason", "error"))
            return
        params = m.get("params") or {}
        if method == "session/update":
            self.screen.update(params.get("update") or {})
        elif method == "session/request_permission" and mid is not None:
            self.ask(m)
        elif method == "_handler/permission_resolved":
            if self.permission and self.permission.get("id") == params.get("requestId"):
                self.permission = None
                self.screen.line(self.screen.paint("  (answered elsewhere)", "2"))
        elif method == "_handler/turn_ended":
            self.end_turn(params.get("stopReason", "end_turn"))
        elif method == "_handler/session_state":
            self.busy = bool(params.get("busy"))

    def ask(self, request: Message) -> None:
        self.permission = request
        params = request.get("params") or {}
        title = (params.get("toolCall") or {}).get("title") or "the agent asks"
        options = params.get("options") or []
        choices = "  ".join(f"{i}) {o.get('name')}" for i, o in enumerate(options, 1))
        self.screen.line(self.screen.paint(f"? {title}", "1;33"))
        self.screen.line(f"  {choices}   (type a number)")

    def end_turn(self, stop: str) -> None:
        self.busy, self.prompt_id = False, None
        if stop != "end_turn":
            self.screen.line(self.screen.paint(f"[{stop}]", "2"))
        elif self.screen.midline:
            self.screen.line("")

    # ── you ─────────────────────────────────────────────────────────────

    async def typed(self, line: str) -> None:
        text = line.strip()
        if self.permission is not None:
            options = (self.permission.get("params") or {}).get("options") or []
            if text.isdigit() and 1 <= int(text) <= len(options):
                answer = {
                    "outcome": {
                        "outcome": "selected",
                        "optionId": options[int(text) - 1]["optionId"],
                    }
                }
                request, self.permission = self.permission, None
                await self.send({"id": request["id"], "result": answer})
            else:
                self.screen.line(f"  type a number from 1 to {len(options)}")
            return
        if not text:
            return
        if text in ("/detach", "/quit", "/exit"):
            self.detach()
        elif text == "/stop":
            self.daemon.call("POST", f"/v1/sessions/{self.session['id']}/stop")
            self.done.set()
        elif text == "/help":
            self.screen.line(HELP)
        elif self.busy:
            self.screen.line("  a turn is in progress (Ctrl-C cancels it)")
        else:
            self.busy = True
            self.prompt_id = rid = next(self.ids)
            params = {
                "sessionId": self.session["acpSessionId"],
                "prompt": [{"type": "text", "text": line}],
            }
            await self.send({"id": rid, "method": "session/prompt", "params": params})

    def interrupt(self) -> None:
        if self.busy:
            cancel = {
                "method": "session/cancel",
                "params": {"sessionId": self.session["acpSessionId"]},
            }
            task = asyncio.ensure_future(self.send(cancel))
            self.background.add(task)
            task.add_done_callback(self.background.discard)
            self.screen.line(self.screen.paint("[cancelling…]", "2"))
        else:
            self.detach()

    def detach(self) -> None:
        self.screen.line(
            self.screen.paint(
                f"[detached: the agent keeps running — handler attach {self.session['id']}]", "2"
            )
        )
        self.done.set()

    def read_stdin(self, loop: asyncio.AbstractEventLoop) -> None:
        while True:
            try:
                line = input()
            except (EOFError, OSError):
                loop.call_soon_threadsafe(self.lines.put_nowait, None)
                return
            except KeyboardInterrupt:
                continue
            loop.call_soon_threadsafe(self.lines.put_nowait, line)

    async def keyboard(self) -> None:
        while not self.done.is_set():
            line = await self.lines.get()
            if line is None:
                self.detach()
                return
            await self.typed(line)

    # ── run ─────────────────────────────────────────────────────────────

    async def run(self, url: str, token: str) -> int:
        protocols = [Subprotocol(ACP_SUBPROTOCOL), Subprotocol(BEARER_SUBPROTOCOL_PREFIX + token)]
        async with connect(url, subprotocols=protocols, max_size=None) as ws:
            self.ws = ws
            receiver = asyncio.create_task(self.receive())
            try:
                await self.request(
                    "initialize", {"protocolVersion": 1, "clientCapabilities": {}}
                )  # once it runs
                self.session = self.daemon.call("GET", f"/v1/sessions/{self.session['id']}")
                params = {
                    "sessionId": self.session["acpSessionId"],
                    "cwd": self.session["scope"],
                    "mcpServers": [],
                }
                await self.request("session/load", params)
            except (SessionClosedError, ConnectionClosed):
                await receiver  # it did not start: the receiver says why
                return self.result
            self.screen.line(self.screen.paint(HELP, "2"))
            loop = asyncio.get_running_loop()
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(signal.SIGINT, self.interrupt)
            threading.Thread(target=self.read_stdin, args=(loop,), daemon=True).start()
            keyboard = asyncio.create_task(self.keyboard())
            await self.done.wait()
            keyboard.cancel()
            receiver.cancel()
        return self.result


def attach(daemon: Daemon, session: Message) -> int:
    """Attach the terminal to a session until you detach or it ends."""
    return asyncio.run(Terminal(daemon, session).run(session["acpUrl"], daemon.token))
