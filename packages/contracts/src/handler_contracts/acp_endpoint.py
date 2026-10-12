"""Contract C — ACP endpoint and policy (`handler.acp-endpoint/v1`).

Mostly behavioural; these are the wire-level constants every implementation and client share.
"""

from enum import IntEnum
from typing import Literal
from urllib.parse import quote

ACP_ENDPOINT_API_VERSION = "handler.acp-endpoint/v1"

ACP_SUBPROTOCOL = "acp.v1"
"""WebSocket subprotocol the server must select (C.1)."""

BEARER_SUBPROTOCOL_PREFIX = "bearer."
"""Prefix of the subprotocol carrying the token: `bearer.<token>` (C.1)."""

DEFAULT_MAX_MESSAGE_BYTES = 16 * 1024 * 1024
"""Default maximum JSON-RPC message size (C.1)."""


class AcpCloseCode(IntEnum):
    NORMAL = 1000
    PROTOCOL_ERROR = 1002
    UNSUPPORTED_DATA = 1003
    MESSAGE_TOO_BIG = 1009
    AGENT_EXITED = 1011
    ATTACHED_ELSEWHERE = 4001  # F.7: more attachments than allowed, the oldest is closed
    SESSION_STOPPED = 4002  # F.4: stop, idle timeout or agent exit
    TOO_SLOW = 4003  # F.7: the client did not read its traffic fast enough
    # remote access to the session was switched off (docs/dev/design/remote.md)
    REMOTE_DISABLED = 4004


class SessionErrorCode(IntEnum):
    """JSON-RPC errors of a Session's ACP endpoint (F.4)."""

    ONE_SESSION_PER_ATTACHMENT = -32010
    TURN_IN_PROGRESS = -32011
    UNATTENDED = -32012  # a run of an agent with an interface takes no prompt (D.18)


class PolicyErrorCode(IntEnum):
    """JSON-RPC error codes emitted by the policy pipeline (C.4); `data.policy` names the rule."""

    CWD_OUTSIDE_SCOPE = -32001  # P2
    MCP_NOT_ALLOWED = -32002  # P3
    NOT_PERMITTED = -32003  # P4
    SESSION_DEFAULTS_FAILED = -32004  # P7


PolicyRule = Literal["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]

BLOCKED_AGENT_METHOD_PREFIXES = ("fs/", "terminal/")
"""Agent→client methods never forwarded (P4)."""

CWD_CHECKED_METHODS = ("session/new", "session/load", "session/resume")
"""Client→agent methods whose `cwd` is checked against the scope (P2), and which get the
platform's MCP servers (P8)."""


def acp_path(agent_id: str) -> str:
    """URL path of an agent's ACP endpoint."""
    return f"/v1/agents/{quote(agent_id, safe='')}/acp"


def session_acp_path(session_id: str) -> str:
    """URL path of a Session's ACP endpoint (F.4)."""
    return f"/v1/sessions/{quote(session_id, safe='')}/acp"
