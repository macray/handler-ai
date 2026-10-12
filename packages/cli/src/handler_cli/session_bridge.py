"""`handler attach --stdio` and `handler acp AGENT`: a daemon-held session (F) as a plain stdio ACP
agent, for editors (Zed) and terminal ACP clients.

Such a client starts a conversation with `session/new`; a session already has one. So the bridge
answers `session/new` with the session's own: it sends `session/load` instead (the daemon replays
what was said) and adds the `sessionId` to the answer. A `session/load` of another id is pointed at
the session's. The daemon's `_handler/*` notifications (state for its own clients) are not passed
on. Everything else goes through unchanged, and the policy (C.4) applies in the daemon as usual.
"""

import json
import sys
import threading
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Subprotocol

from handler_contracts import ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX, AcpCloseCode

from .client import Daemon


class SessionBridge:
    def __init__(self, daemon: Daemon, session_id: str) -> None:
        self.daemon = daemon
        self.session_id = session_id
        self.new_ids: set[Any] = set()  # the client's session/new requests, answered by a load
        self.lock = threading.Lock()

    def acp_session(self) -> dict[str, Any]:
        return self.daemon.call("GET", f"/v1/sessions/{self.session_id}")

    def to_daemon(self, msg: dict[str, Any]) -> dict[str, Any]:
        method = msg.get("method")
        if method in ("session/new", "session/load") and "id" in msg:
            info = self.acp_session()  # asked after initialize: the agent runs, its id is known
            params = {"sessionId": info["acpSessionId"], "cwd": info["scope"], "mcpServers": []}
            if method == "session/new":
                with self.lock:
                    self.new_ids.add(msg["id"])
            return msg | {"method": "session/load", "params": params}
        return msg

    def to_client(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        if isinstance(method, str) and method.startswith("_handler/"):
            return None
        with self.lock:
            answered_new = "method" not in msg and msg.get("id") in self.new_ids
            self.new_ids.discard(msg.get("id"))
        if answered_new and isinstance(msg.get("result"), dict):
            acp_id = self.acp_session()["acpSessionId"]
            return msg | {"result": msg["result"] | {"sessionId": acp_id}}
        return msg

    def stdin_to_ws(self, ws: ClientConnection) -> None:
        try:
            for line in sys.stdin.buffer:
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    ws.send(json.dumps(self.to_daemon(msg)))
        except ConnectionClosed:
            return
        ws.close()  # the client closed our stdin: detach (the agent keeps running)

    def run(self, acp_url: str) -> int:
        token = self.daemon.token
        protocols = [Subprotocol(ACP_SUBPROTOCOL), Subprotocol(BEARER_SUBPROTOCOL_PREFIX + token)]
        with connect(acp_url, subprotocols=protocols, max_size=None) as ws:
            threading.Thread(target=self.stdin_to_ws, args=(ws,), daemon=True).start()
            try:
                for message in ws:
                    for line in str(message).splitlines():
                        if line.strip() and (out := self.to_client(json.loads(line))) is not None:
                            sys.stdout.write(json.dumps(out) + "\n")
                            sys.stdout.flush()
            except ConnectionClosed:
                pass
        if ws.close_code in (None, AcpCloseCode.NORMAL):
            return 0
        print(f"handler: session closed ({ws.close_code}) {ws.close_reason}", file=sys.stderr)
        return 1


def run_session_bridge(daemon: Daemon, session: dict[str, Any]) -> int:
    return SessionBridge(daemon, session["id"]).run(session["acpUrl"])
