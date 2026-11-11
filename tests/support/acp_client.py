"""Minimal synchronous ACP client, for tests only — over a process's stdio or a WebSocket.

Deliberately small and dependency-light so tests show the protocol plainly. It answers
agent→client requests itself: permission requests per `on_permission` (and counts them;
"ignore" leaves them unanswered, like a person who has not looked yet), anything else (fs/*,
terminal/*) with a JSON-RPC error, as the platform's policy does (P4).
"""

import json
import queue
import subprocess
import threading
from collections.abc import Callable, Iterator
from typing import Any, Literal

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection


class AcpError(RuntimeError):
    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(f"{error.get('code')}: {error.get('message')}")
        self.error = error


class AcpClient:
    def __init__(
        self,
        send: Callable[[str], None],
        receive: Iterator[str],
        close: Callable[[], None],
        on_permission: Literal["allow", "deny", "ignore"] = "deny",
    ) -> None:
        self._send_line = send
        self._close = close
        self.on_permission = on_permission
        self.permission_requests: list[dict[str, Any]] = []
        self.other_agent_requests: list[str] = []
        self.updates: list[dict[str, Any]] = []
        self._next_id = 0
        self._inbox: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._closing = False
        threading.Thread(target=self._read, args=(receive,), daemon=True).start()

    # ── transports ──────────────────────────────────────────────────────

    @classmethod
    def over_process(cls, proc: subprocess.Popen[bytes], **kw: Any) -> "AcpClient":
        assert proc.stdin is not None and proc.stdout is not None
        stdin, stdout = proc.stdin, proc.stdout

        def send(line: str) -> None:
            stdin.write((line + "\n").encode())
            stdin.flush()

        def close() -> None:
            stdin.close()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=30)

        return cls(send, (line.decode() for line in stdout if line.strip()), close, **kw)

    @classmethod
    def over_websocket(
        cls, ws: ClientConnection, close: Callable[[], None] | None = None, **kw: Any
    ) -> "AcpClient":
        def receive() -> Iterator[str]:
            try:
                while True:
                    yield str(ws.recv())
            except ConnectionClosed:
                return

        return cls(ws.send, receive(), close or ws.close, **kw)

    # ── protocol ────────────────────────────────────────────────────────

    def _read(self, receive: Iterator[str]) -> None:
        for text in receive:
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    self._inbox.put(json.loads(line))
                except json.JSONDecodeError:
                    if not self._closing:
                        raise
                    break  # an agent told to stop may exit in the middle of a line
        self._inbox.put(None)

    def send(self, msg: dict[str, Any]) -> None:
        self._send_line(json.dumps({"jsonrpc": "2.0", **msg}))

    def _handle_agent_request(self, msg: dict[str, Any]) -> None:
        if msg["method"] == "session/request_permission":
            self.permission_requests.append(msg["params"])
            if self.on_permission == "ignore":
                return
            kinds = ("allow_once", "allow_always") if self.on_permission == "allow" else (
                "reject_once", "reject_always"
            )  # fmt: skip
            options = msg["params"]["options"]
            choice = next((o for o in options if o["kind"] in kinds), options[0])
            outcome = {"outcome": "selected", "optionId": choice["optionId"]}
            self.send({"id": msg["id"], "result": {"outcome": outcome}})
        else:
            self.other_agent_requests.append(msg["method"])
            error = {"code": -32003, "message": "not permitted by sandbox policy"}
            self.send({"id": msg["id"], "error": error})

    def request(self, method: str, params: dict[str, Any], timeout: float = 120) -> Any:
        self._next_id += 1
        rid = self._next_id
        self.send({"id": rid, "method": method, "params": params})
        while True:
            msg = self._inbox.get(timeout=timeout)
            if msg is None:
                raise EOFError(f"connection closed while waiting for {method}")
            if "method" in msg and "id" in msg:
                self._handle_agent_request(msg)
            elif "method" in msg:
                self.updates.append(msg)
            elif msg.get("id") == rid:
                if "error" in msg:
                    raise AcpError(msg["error"])
                return msg.get("result")

    def wait_notification(self, method: str, timeout: float = 30) -> dict[str, Any]:
        """Handle incoming traffic until a notification `method` arrives; return its params."""
        while True:
            msg = self._inbox.get(timeout=timeout)
            if msg is None:
                raise EOFError(f"connection closed while waiting for {method}")
            if "method" in msg and "id" in msg:
                self._handle_agent_request(msg)
            elif "method" in msg:
                self.updates.append(msg)
                if msg["method"] == method:
                    return msg.get("params") or {}

    # ── convenience ─────────────────────────────────────────────────────

    def initialize(self, capabilities: dict[str, Any] | None = None) -> Any:
        caps = capabilities or {
            "fs": {"readTextFile": False, "writeTextFile": False},
            "terminal": False,
        }
        info = {"name": "handler-tests", "version": "0"}
        return self.request(
            "initialize", {"protocolVersion": 1, "clientCapabilities": caps, "clientInfo": info}
        )

    def new_session(self, cwd: str) -> Any:
        return self.request("session/new", {"cwd": cwd, "mcpServers": []})

    def prompt(self, session_id: str, text: str, timeout: float = 300) -> Any:
        params = {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]}
        return self.request("session/prompt", params, timeout=timeout)

    def text(self) -> str:
        """All agent_message_chunk text received so far."""
        chunks = [
            u["params"]["update"]["content"].get("text", "")
            for u in self.updates
            if u.get("method") == "session/update"
            and u["params"]["update"].get("sessionUpdate") == "agent_message_chunk"
        ]
        return "".join(chunks)

    def close(self) -> None:
        self._closing = True
        self._close()
