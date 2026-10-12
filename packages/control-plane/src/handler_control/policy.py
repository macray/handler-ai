"""ACP policy pipeline — contract C.4, rules P1-P9.

A pure state machine, independent of any transport: feed it one JSON-RPC message at a time
(`from_client` / `from_agent`) and it returns what to send and to whom. The WebSocket relay
(relay.py) is just a transport around it.

    P1  initialize: force clientCapabilities fs/terminal off
    P2  session/new|load|resume: cwd must be inside the agent's scope
    P3  session/new|load|resume: HTTP MCP servers must be reachable under the network policy
        (checked after P8, so the platform's own servers are checked too)
    P4  agent→client fs/* and terminal/*: never forwarded, the agent gets an error
    P5  client→agent `$/…` notifications (heartbeats): dropped
    P6  `_…` extension methods: forwarded, logged
    P7  after session/new or session/load: apply session defaults (mode, config options) before
        the client sees the session; failure → the client gets an error, never a session in
        the wrong mode (a loaded session runs in a new sandbox: the agent's mode applies again)
    P8  session/new|load|resume: add the platform's MCP servers (its addons') to the
        client's; a client server with the same name is replaced
    P9  the first session/prompt of a session this connection started (session/new): the
        agent's instructions before its text (a daemon session does it itself, F.3)
"""

import itertools
import json
import logging
import posixpath
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from handler_contracts import (
    BLOCKED_AGENT_METHOD_PREFIXES,
    CWD_CHECKED_METHODS,
    FilteredNetwork,
    NetworkPolicy,
    NoNetwork,
    PolicyErrorCode,
    SessionDefaults,
    egress_target,
    is_within,
)

log = logging.getLogger("handler.policy")

Message = dict[str, Any]


@dataclass(frozen=True)
class ToAgent:
    msg: Message


@dataclass(frozen=True)
class ToClient:
    msg: Message


Action = ToAgent | ToClient


def parse(line: str) -> Message | None:
    """One line of an NDJSON stream as a JSON-RPC message; None when it is not a single object
    (C.1: batches and unparseable lines are dropped)."""
    try:
        msg = json.loads(line)
    except ValueError:
        return None
    return msg if isinstance(msg, dict) else None


def is_request(m: Message) -> bool:
    return "method" in m and "id" in m


def is_notification(m: Message) -> bool:
    return "method" in m and "id" not in m


def is_response(m: Message) -> bool:
    return "method" not in m and "id" in m


def error_response(req_id: Any, code: PolicyErrorCode, rule: str, message: str) -> Message:
    error = {"code": int(code), "message": message, "data": {"policy": rule}}
    return {"jsonrpc": "2.0", "id": req_id, "error": error}


def target_allowed(target: str, network: NetworkPolicy) -> bool:
    """Whether 'host:port' is reachable under the network policy (A.3: the port must match)."""
    if isinstance(network, NoNetwork):
        return False
    if not isinstance(network, FilteredNetwork):
        return True  # open
    host, _, port = target.rpartition(":")
    for entry in network.allow:
        entry_host, _, entry_port = entry.rpartition(":")
        if entry_port != port:
            continue
        if entry_host.startswith("*.") and host.endswith(entry_host[1:]):
            return True
        if host == entry_host:
            return True
    return False


@dataclass
class _HeldSession:
    """A session/new response held back while P7 applies the session defaults."""

    response: Message
    session_id: str
    queue: list[Message]  # injected requests still to send, in order
    failures: list[str] = field(default_factory=list)


class AcpPolicy:
    def __init__(
        self,
        *,
        scope: str,
        network: NetworkPolicy,
        session_defaults: SessionDefaults | None = None,
        instructions: str | None = None,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        self.scope = scope
        self.network = network
        self.defaults = session_defaults
        self.instructions = instructions
        self.on_event = on_event or log.info
        self._session_ids: dict[Any, str | None] = {}  # session/new|load request id → its sessionId
        self._uninstructed: set[str] = set()  # sessions started here, their first prompt to come
        self._held: dict[str, _HeldSession] = {}  # injected request id → held session
        self._ids = itertools.count(1)

    # ── client → agent ──────────────────────────────────────────────────

    def from_client(self, m: Message) -> list[Action]:
        method = m.get("method")
        if is_notification(m) and isinstance(method, str) and method.startswith("$/"):
            return []  # P5
        if method == "initialize" and is_request(m):
            return [ToAgent(self._force_capabilities(m))]  # P1
        if method in CWD_CHECKED_METHODS and is_request(m):
            m = self._add_mcp_servers(m)  # P8
            if refusal := self.check_session_params(m):
                return [ToClient(refusal)]  # P2 / P3
            if method in ("session/new", "session/load"):
                self._session_ids[m["id"]] = (m.get("params") or {}).get("sessionId")
        if method == "session/prompt" and is_request(m):
            m = self._p9_instruct(m)
        if isinstance(method, str) and method.startswith("_"):
            self.on_event(f"extension {method} (client→agent)")  # P6
        return [ToAgent(m)]

    def _p9_instruct(self, m: Message) -> Message:
        params = m.get("params") or {}
        session_id = params.get("sessionId")
        if not self.instructions or session_id not in self._uninstructed:
            return m
        self._uninstructed.discard(session_id)
        return m | {"params": params | {"prompt": instructed(self.instructions, params)}}

    def _force_capabilities(self, m: Message) -> Message:
        params = dict(m.get("params") or {})
        caps = dict(params.get("clientCapabilities") or {})
        caps["fs"] = {"readTextFile": False, "writeTextFile": False}
        caps["terminal"] = False
        params["clientCapabilities"] = caps
        return m | {"params": params}

    def _add_mcp_servers(self, m: Message) -> Message:
        platform = (self.defaults.mcp_servers if self.defaults else None) or []
        if not platform:
            return m
        params = dict(m.get("params") or {})
        theirs = params.get("mcpServers") or []
        if not isinstance(theirs, list):
            return m  # malformed: forwarded as is, the agent refuses it
        names = {s.name for s in platform}
        client = []
        for server in theirs:
            if isinstance(server, dict) and server.get("name") in names:
                self.on_event(f"client MCP server '{server['name']}' replaced by the platform's")
            else:
                client.append(server)
        own = [s.model_dump(mode="json", by_alias=True, exclude_none=True) for s in platform]
        params["mcpServers"] = client + own
        return m | {"params": params}

    def check_session_params(self, m: Message) -> Message | None:
        params = m.get("params") or {}
        cwd = params.get("cwd")
        inside = (
            isinstance(cwd, str)
            and cwd.startswith("/")
            and is_within(posixpath.normpath(cwd), self.scope)
        )
        if not inside:
            return error_response(
                m["id"], PolicyErrorCode.CWD_OUTSIDE_SCOPE, "P2", f"cwd must be inside {self.scope}"
            )
        for server in params.get("mcpServers") or []:
            url = server.get("url") if isinstance(server, dict) else None
            if not isinstance(url, str):
                continue
            try:
                target = egress_target(url)
            except (KeyError, ValueError):  # not http(s), or a bad port
                target = url
            if not target_allowed(target, self.network):
                return error_response(
                    m["id"], PolicyErrorCode.MCP_NOT_ALLOWED, "P3",
                    f"MCP server {target} is not reachable under the network policy",
                )  # fmt: skip
        return None

    # ── agent → client ──────────────────────────────────────────────────

    def from_agent(self, m: Message) -> list[Action]:
        method = m.get("method")
        if isinstance(method, str) and method.startswith(BLOCKED_AGENT_METHOD_PREFIXES):
            self.on_event(f"blocked agent→client {method}")
            if is_request(m):  # P4
                reply = error_response(
                    m["id"], PolicyErrorCode.NOT_PERMITTED, "P4", "not permitted by sandbox policy"
                )
                return [ToAgent(reply)]
            return []
        if isinstance(method, str) and method.startswith("_"):
            self.on_event(f"extension {method} (agent→client)")  # P6
        if is_response(m):
            if isinstance(m["id"], str) and m["id"] in self._held:
                return self._p7_progress(m)
            if m["id"] in self._session_ids:
                return self._p7_start(m, self._session_ids.pop(m["id"]))
        return [ToClient(m)]

    # ── P7: session defaults ────────────────────────────────────────────

    def _p7_start(self, response: Message, loaded: str | None) -> list[Action]:
        result = response.get("result")
        session_id = result.get("sessionId", loaded) if isinstance(result, dict) else None
        if loaded is None and isinstance(session_id, str):
            self._uninstructed.add(session_id)  # P9: a new session, its first prompt instructed
        if not self.defaults or not isinstance(session_id, str):
            return [ToClient(response)]
        queue: list[Message] = []
        if self.defaults.mode_id:
            params = {"sessionId": session_id, "modeId": self.defaults.mode_id}
            queue.append({"method": "session/set_mode", "params": params})
        for config_id, value in (self.defaults.config_options or {}).items():
            params = {"sessionId": session_id, "configId": config_id, "value": value}
            queue.append({"method": "session/set_config_option", "params": params})
        if not queue:
            return [ToClient(response)]
        held = _HeldSession(response=response, session_id=session_id, queue=queue)
        return self._p7_send_next(held)

    def _p7_send_next(self, held: _HeldSession) -> list[Action]:
        request = held.queue.pop(0)
        req_id = f"handler-p7-{next(self._ids)}"
        self._held[req_id] = held
        return [ToAgent({"jsonrpc": "2.0", "id": req_id, **request})]

    def _p7_progress(self, response: Message) -> list[Action]:
        held = self._held.pop(response["id"])
        if "error" in response:
            held.failures.append(str(response["error"].get("message", response["error"])))
        if held.queue and not held.failures:
            return self._p7_send_next(held)
        if held.failures:
            detail = "; ".join(held.failures)
            self.on_event(f"session defaults failed for {held.session_id}: {detail}")
            reply = error_response(
                held.response["id"], PolicyErrorCode.SESSION_DEFAULTS_FAILED, "P7",
                f"session defaults could not be applied: {detail}",
            )  # fmt: skip
            return [ToClient(reply)]
        return [ToClient(self._patched(held.response))]

    def _patched(self, response: Message) -> Message:
        assert self.defaults is not None
        result = dict(response["result"])
        if self.defaults.mode_id and isinstance(result.get("modes"), dict):
            result["modes"] = result["modes"] | {"currentModeId": self.defaults.mode_id}
        wanted = self.defaults.config_options or {}
        if wanted and isinstance(result.get("configOptions"), list):
            result["configOptions"] = [
                o | {"currentValue": wanted[o["id"]]}
                if isinstance(o, dict) and o.get("id") in wanted
                else o
                for o in result["configOptions"]
            ]
        return response | {"result": result}


def instructed(instructions: str, params: Message) -> list[Any]:
    """A prompt's blocks with the agent's instructions before its text, a blank line between
    them, in one text block: every adapter reads it (some would drop a second one)."""
    blocks = list(params.get("prompt") or [])
    if blocks and isinstance(blocks[0], dict) and blocks[0].get("type") == "text":
        first = blocks[0]
        return [first | {"text": f"{instructions}\n\n{first.get('text', '')}"}, *blocks[1:]]
    return [{"type": "text", "text": instructions}, *blocks]
