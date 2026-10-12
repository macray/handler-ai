"""`handler acp`: bridge stdio (an editor such as Zed, or any ACP client) to an agent's ACP
WebSocket.

The editor talks NDJSON on our stdin/stdout; handlerd applies the policy (P1-P7) and runs the agent
in its sandbox. One JSON-RPC message per line one way, per frame the other way.
"""

import sys
import threading

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Subprotocol

from handler_contracts import ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX, AcpCloseCode


def _stdin_to_ws(ws: ClientConnection) -> None:
    try:
        for line in sys.stdin.buffer:
            if line.strip():
                ws.send(line.decode().rstrip("\n"))
    except ConnectionClosed:
        return
    ws.close()  # the editor closed our stdin: end the connection (the sandbox stops)


def run_bridge(acp_url: str, token: str) -> int:
    protocols = [Subprotocol(ACP_SUBPROTOCOL), Subprotocol(BEARER_SUBPROTOCOL_PREFIX + token)]
    with connect(acp_url, subprotocols=protocols, max_size=None) as ws:
        threading.Thread(target=_stdin_to_ws, args=(ws,), daemon=True).start()
        try:
            for message in ws:
                text = message if isinstance(message, str) else message.decode()
                sys.stdout.write(text + "\n")
                sys.stdout.flush()
        except ConnectionClosed:
            pass
    if ws.close_code in (None, AcpCloseCode.NORMAL):
        return 0
    print(f"handler acp: connection closed ({ws.close_code}) {ws.close_reason}", file=sys.stderr)
    return 1
