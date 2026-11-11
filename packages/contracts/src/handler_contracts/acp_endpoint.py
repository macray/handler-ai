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
    # remote access to the session was switched off (remote design)
    REMOTE_DISABLED = 4004


class SessionErrorCode(IntEnum):
    """JSON-RPC errors of a Session's ACP endpoint (F.4)."""

    ONE_SESSION_PER_ATTACHMENT = -32010
    TURN_IN_PROGRESS = -32011
    UNATTENDED = -32012  # a run of a job takes no prompt (D.18)
    NOT_REFUSED_HERE = -32013  # a card's answer for a host not blocked in this session (F.9)
    NOT_APPLIED = -32014  # a card's answer saved, not applied to every running sandbox (F.9)


class PolicyErrorCode(IntEnum):
    """JSON-RPC error codes emitted by the policy pipeline (C.4); `data.policy` names the rule."""

    CWD_OUTSIDE_SCOPE = -32001  # P2
    MCP_NOT_ALLOWED = -32002  # P3
    NOT_PERMITTED = -32003  # P4
    SESSION_DEFAULTS_FAILED = -32004  # P7


PolicyRule = Literal["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]

AGENT_REQUESTS = ("session/request_permission",)
"""The agent→client requests passed (P4): any other is answered with an error, never passed."""

AGENT_NOTIFICATIONS = ("session/update",)
"""The agent→client notifications passed, besides extensions (`_…`, P6): any other is dropped
(P4)."""

SESSION_METHODS = ("session/new", "session/load", "session/resume")
"""Client→agent methods that start or reopen a conversation: they get the platform's MCP servers
(P8) and their `cwd` is checked (P2), as is that of any other request carrying one."""


def acp_path(agent_id: str) -> str:
    """URL path of an agent's ACP endpoint."""
    return f"/v1/agents/{quote(agent_id, safe='')}/acp"


def session_acp_path(session_id: str) -> str:
    """URL path of a Session's ACP endpoint (F.4)."""
    return f"/v1/sessions/{quote(session_id, safe='')}/acp"
