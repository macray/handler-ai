"""Sessions (contract F) — daemon-held chat sessions: one sandbox each, outliving its WebSocket.

A client attaches with plain ACP. The daemon answers `initialize` (cached) and `session/load`
(replay of the event log) itself, then relays through the policy (C.4). Several clients may be
attached (F.7): every one gets the agent's traffic, the first answer to a permission request
wins, and what one client changes (prompt, mode, option) is shown to the others. Detaching never
stops the agent or its turn.

    SessionStore   records on disk, live sessions, single-flight start, stop, delete
    LiveSession    one running agent: its own requests, the clients' (ids rewritten),
                   pending permission requests, the event log, the idle timer
    Attachment     one attached client (a WebSocket, or in-process: the remote connector),
                   with its own bounded queue so a slow client cannot hold up the agent

A session may be started with a request (sent by the daemon as its first turn). A run of an
agent with an interface (D.18) is started with an input instead, and is unattended: its
permission requests are answered by its interface's policy, its turn is cancelled after its
timeout, no client may prompt it, and its result is read from its final message (one more turn
when it is missing or invalid); then it stops, its answer (the agent's last message) kept.

Storage, one folder per session under <state>/sessions/<id>/ (F.2):
    session.json    the record
    events.ndjson   the event log (F.5), secret values redacted
    agent/          bound to the harness's per-session state slot
    work/           a folderless agent's (D.18): the folder the session works in
"""

import asyncio
import contextlib
import itertools
import json
import logging
import secrets as pysecrets
import shutil
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from starlette.websockets import WebSocket

from handler_contracts import (
    AcpCloseCode,
    AgentInterface,
    Session,
    SessionErrorCode,
    SessionInput,
    SessionLifecycle,
    SessionOrigin,
    SessionOutput,
    session_acp_path,
)

from . import __version__, interfaces, launcher, session_files, skill_scan, skills
from .agents import AgentRecord, AgentRegistry, LiveConnection, RunsAs
from .policy import AcpPolicy, ToAgent, ToClient, instructed, is_request, is_response, parse
from .sandbox_process import read_stderr, stop
from .secrets import redactor
from .settings import Settings

log = logging.getLogger("handler.sessions")

Message = dict[str, Any]
START_TIMEOUT = 300.0  # initialize + session/new|load, image start included
TITLE_LENGTH = 80  # a title taken from the first request
CANCEL_GRACE = 30.0  # after a timeout's session/cancel, for the agent to end its turn
QUEUE_SIZE = 10_000  # messages waiting for one client; more: it is closed as too slow (F.7)

# how a session stopped (F.5), on its `lifecycle stopped` event: read by automations (I.2)
StopHow = Literal["explicit", "idle", "exited", "error", "run_ended", "daemon_restarted", "deleted"]


def with_session_id(msg: Message, old: str | None, new: str | None) -> Message:
    """`msg` with `params.sessionId` set to `new` (only where it is `old`, unless None)."""
    params = msg.get("params")
    if not isinstance(params, dict) or "sessionId" not in params:
        return msg
    if old is not None and params["sessionId"] != old:
        return msg
    return msg | {"params": params | {"sessionId": new}}


class SessionError(RuntimeError):
    """The session cannot be started or attached (the reason is shown to the client)."""


def now() -> datetime:
    return datetime.now(UTC)


def error(req_id: Any, code: int, message: str) -> Message:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


@dataclass
class SessionRecord:
    id: str
    agent_id: str
    harness: str  # which of its agent's models it was started with: the harness, on the
    # account or provider below, with `model`
    scope: str
    created_at: datetime
    last_activity_at: datetime
    account: str | None = None
    provider: str | None = None
    model: str | None = None
    acp_session_id: str | None = None
    # the agent's id of its session, when not `acp_session_id`: restarted before its first turn,
    # the agent's session is a new one; the clients keep the recorded id (F.6)
    agent_session_id: str | None = None
    title: str | None = None
    state: SessionLifecycle = "starting"
    can_resume: bool = False
    error: str | None = None
    harness_version: str | None = None
    origin: SessionOrigin = "ui"
    last_stop_reason: str | None = None
    answer: str | None = None  # a run's: the agent's last message, kept when it ended
    interface: dict[str, Any] | None = None  # a run (D.18): its agent's interface when it started
    input: dict[str, Any] | None = None  # a run: SessionInput, the subject's digest set
    output: dict[str, Any] | None = None  # a run: SessionOutput, once its turn ended
    # its agent's instructions, until they go with the first prompt a client sends (F.3)
    instructions: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self) | {
            "created_at": self.created_at.isoformat(),
            "last_activity_at": self.last_activity_at.isoformat(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "SessionRecord":
        fields: dict[str, Any] = data | {
            "created_at": datetime.fromisoformat(data["created_at"]),
            "last_activity_at": datetime.fromisoformat(data["last_activity_at"]),
        }
        return cls(**fields)


class EventLog:
    """events.ndjson (F.5): append-only, `seq` strictly increasing from 1."""

    def __init__(self, path: Path, on_stopped: Callable[[], None] | None = None) -> None:
        self.path = path
        self.on_stopped = on_stopped  # told after a `lifecycle stopped` event is written
        self.redact = redactor([])
        self.seq = 0
        self.open_turn = False  # the last `turn` event is a start
        self.had_turn = False  # a conversation the agent may keep: something to load (F.6)
        if path.exists():
            for event in self._read():
                self.seq = event["seq"]
                if event["kind"] == "turn":
                    self.open_turn = event["phase"] == "start"
                    self.had_turn = True

    def _read(self) -> list[dict[str, Any]]:
        events = []
        for line in self.path.read_text().splitlines():
            with contextlib.suppress(ValueError, KeyError):
                events.append(json.loads(line))
        return events

    def append(self, kind: str, **fields: Any) -> None:
        self.seq += 1
        if kind == "turn":
            self.open_turn = fields["phase"] == "start"
            self.had_turn = True
        line = json.dumps({"seq": self.seq, "t": now().isoformat(), "kind": kind} | fields)
        with self.path.open("a") as f:
            f.write(self.redact(line) + "\n")
        if kind == "lifecycle" and fields.get("event") == "stopped" and self.on_stopped:
            self.on_stopped()

    def updates(self, after: int = 0) -> list[tuple[int, Any]]:
        if not self.path.exists():
            return []
        return [
            (e["seq"], e["update"])
            for e in self._read()
            if e.get("kind") == "update" and e["seq"] > after
        ]

    def answer(self) -> str | None:
        """The agent's message after the last prompt."""
        text: list[str] = []
        for _, update in self.updates():
            kind = update.get("sessionUpdate")
            if kind == "user_message_chunk":
                text = []
            elif kind == "agent_message_chunk":
                content = update.get("content") or {}
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    text.append(content["text"])
        return "".join(text).strip() or None


class Attachment:
    """One attached client (F.7). Messages are queued and written by the attachment's own task:
    putting never blocks the agent, and a client that falls `QUEUE_SIZE` messages behind is
    closed (4003) — it re-attaches and gets the log from where it was (`afterSeq`)."""

    def __init__(
        self,
        send: Callable[[str], Awaitable[None]],
        close: Callable[[int, str], Awaitable[None]],
        kind: str = "websocket",
    ) -> None:
        self._send = send
        self._close = close
        self.kind = kind  # "websocket" | "remote"
        self.ready = False  # the client has its replay: live messages may follow
        self.closed = False
        self.queue: asyncio.Queue[Message | tuple[int, str]] = asyncio.Queue(QUEUE_SIZE)
        self.writer = asyncio.create_task(self._write())

    @classmethod
    def of(cls, ws: WebSocket) -> "Attachment":
        async def close(code: int, reason: str) -> None:
            await ws.close(code=code, reason=reason)

        return cls(ws.send_text, close)

    def put(self, msg: Message) -> None:
        if self.closed:
            return
        try:
            self.queue.put_nowait(msg)
        except asyncio.QueueFull:
            self.closed = True
            self._close_now(AcpCloseCode.TOO_SLOW, "too slow")

    def close(self, code: int, reason: str) -> None:
        """Close after what is already queued has been sent."""
        if self.closed:
            return
        self.closed = True
        try:
            self.queue.put_nowait((code, reason[:120]))
        except asyncio.QueueFull:
            self._close_now(code, reason[:120])

    def _close_now(self, code: int, reason: str) -> None:
        """Drop what is queued and close (the writer task becomes the closing one)."""
        self.writer.cancel()
        self.writer = asyncio.create_task(self._close_quietly(code, reason))

    def discard(self) -> None:
        """The client is gone: stop writing to it (a close already queued is still sent)."""
        if not self.closed:
            self.closed = True
            self.writer.cancel()

    async def _write(self) -> None:
        while True:
            item = await self.queue.get()
            if isinstance(item, tuple):
                await self._close_quietly(*item)
                return
            with contextlib.suppress(Exception):  # a closing client: it will re-attach
                await self._send(json.dumps(item))

    async def _close_quietly(self, code: int, reason: str) -> None:
        with contextlib.suppress(Exception):
            await self._close(code, reason)


class LiveSession:
    """One running agent. Every method runs on the event loop; `out` orders what the client gets."""

    def __init__(
        self, store: "SessionStore", record: SessionRecord, agent: AgentRecord, runs: RunsAs
    ) -> None:
        self.store = store
        self.record = record
        self.agent = agent
        self.runs = runs  # the agent's model it runs with
        self.log = store.event_log(record.id)
        self.proc: asyncio.subprocess.Process | None = None
        self.policy: AcpPolicy | None = None
        self.init_result: Message = {}
        self.modes: Any = None
        self.config_options: Any = None
        self.clients: list[Attachment] = []  # oldest first
        self.remote = False  # reachable through the remote connector (docs/dev/design/remote.md)
        self.agent_lock = asyncio.Lock()
        self.ids = itertools.count(1)
        self.own: dict[str, asyncio.Future[Message]] = {}  # the daemon's own requests
        self.forwarded: dict[str, Forwarded] = {}  # our id → the client's request
        self.pending: dict[Any, Message] = {}  # agent→client requests awaiting an answer
        self.prompt_id: str | None = None  # the turn in progress (our id of its session/prompt)
        self.turn_started_at: datetime | None = None
        self.stop_reason: str | None = None  # why the daemon stopped it, if it did
        self.stop_how: StopHow = "exited"  # how, for the log (F.5)
        self.replaying = False  # updates are the agent's replay of history we have: not relayed
        self.translate = False  # the agent's session id is not the clients': translated (F.6)
        self.idle: asyncio.TimerHandle | None = None
        self.tasks: list[asyncio.Task[None]] = []

    @property
    def busy(self) -> bool:
        return self.prompt_id is not None

    # ── start ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        rec, settings = self.record, self.store.settings
        state_dir = self.store.folder(rec.id) / "agent"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.log.redact = self.store.redactor(self.agent, self.runs)
        subject = None
        if rec.input is not None and (given := SessionInput.model_validate(rec.input)).subject:
            try:
                subject = interfaces.subject_mount(settings.skills_dir, given.subject)
            except skills.SkillError as e:
                raise SessionError(str(e)) from None
        started = await launcher.start(
            settings,
            self.agent,
            self.runs,
            rec.id,
            str(state_dir),
            folder=rec.scope,
            subject=subject,
        )
        session_files.record_mounts(self.store.mounts(rec.id), started.spec, now())
        rec.harness_version = await launcher.harness_version(rec.harness)
        self.proc = started.process  # ty: ignore[invalid-assignment]
        self.policy = AcpPolicy(
            scope=rec.scope,
            network=started.spec.network,
            session_defaults=started.launch.session_defaults,
            on_event=lambda text: log.info("[%s] policy: %s", rec.id, text),
        )
        self.agent.connections[rec.id] = LiveConnection(
            id=rec.id,
            sandbox=started.spec.name,
            since=now(),
            process=self.proc,
            egress_base=started.egress_base,
        )
        assert self.proc is not None
        registry = self.store.registry
        self.tasks = [
            asyncio.create_task(self.agent_pump()),
            asyncio.create_task(
                read_stderr(self.proc, rec.id, lambda e: registry.add_event(self.agent, rec.id, e))
            ),
        ]
        caps = {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}
        info = {"name": "handlerd", "version": __version__}
        self.init_result = await self.request(
            "initialize", {"protocolVersion": 1, "clientCapabilities": caps, "clientInfo": info}
        )
        rec.can_resume = bool((self.init_result.get("agentCapabilities") or {}).get("loadSession"))
        params = {"cwd": rec.scope, "mcpServers": []}
        if rec.acp_session_id and self.log.had_turn:
            if not rec.can_resume:
                raise SessionError("this agent cannot resume sessions")
            # the agent replays its history: already in our log, unless we have none (F.5)
            replay = not self.log.updates()
            self.translate = rec.agent_session_id is not None
            loaded = rec.agent_session_id or rec.acp_session_id
            result = await self.request(
                "session/load", params | {"sessionId": loaded}, replay=replay
            )
        else:  # also a session stopped before its first turn: the agent kept nothing to load
            self.translate = rec.acp_session_id is not None
            result = await self.request("session/new", params)
            if self.translate:
                rec.agent_session_id = result["sessionId"]
            else:
                rec.acp_session_id = result["sessionId"]
        self.modes, self.config_options = result.get("modes"), result.get("configOptions")
        rec.state, rec.error = "running", None
        self.log.append("lifecycle", event="started")
        self.store.save(rec)
        self.schedule_idle()

    async def request(self, method: str, params: Message, *, replay: bool = True) -> Message:
        """A request of the daemon itself, through the policy (P1, P2, P7 apply)."""
        rid = f"handler-d-{next(self.ids)}"
        future: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
        self.own[rid] = future
        self.replaying = not replay
        try:
            await self.execute({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            response = await asyncio.wait_for(future, START_TIMEOUT)
        finally:
            self.own.pop(rid, None)
            self.replaying = False
        if "error" in response:
            raise SessionError(f"{method}: {response['error'].get('message', response['error'])}")
        return response.get("result") or {}

    # ── agent side ──────────────────────────────────────────────────────

    async def execute(self, msg: Message) -> None:
        """Client-side message (the daemon's or the client's) → policy → agent / back."""
        assert self.policy is not None
        for action in self.policy.from_client(msg):
            await self.dispatch(action)

    async def dispatch(self, action: ToAgent | ToClient) -> None:
        if isinstance(action, ToAgent):
            await self.to_agent(action.msg)
        else:
            await self.route(action.msg)

    async def to_agent(self, msg: Message) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        if self.translate and self.record.agent_session_id is not None:
            msg = with_session_id(msg, self.record.acp_session_id, self.record.agent_session_id)
        async with self.agent_lock:
            with contextlib.suppress(ConnectionError):
                self.proc.stdin.write(json.dumps(msg).encode() + b"\n")
                await self.proc.stdin.drain()

    async def agent_pump(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None and self.policy is not None
        try:
            while True:
                try:
                    line = await self.proc.stdout.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    log.warning("[%s] agent message too big: stopping", self.record.id)
                    self.stop_reason, self.stop_how = "agent message too big", "error"
                    break
                if not line:
                    break
                msg = parse(line.decode(errors="replace"))
                if msg is None:
                    log.warning("[%s] dropped a non-object agent message", self.record.id)
                    continue
                if self.translate:  # its one session, whatever id the agent gave it
                    msg = with_session_id(msg, None, self.record.acp_session_id)
                for action in self.policy.from_agent(msg):
                    await self.dispatch(action)
        finally:
            await self.ended()

    def responded(self, m: Message) -> None:
        """The agent's answer to a request: the daemon's own, or a client's (ids restored)."""
        if (future := self.own.get(m["id"])) is not None:
            if not future.done():
                future.set_result(m)
            return
        entry = self.forwarded.pop(m["id"], None)
        if entry is None:
            return
        if entry.client in self.clients:  # else: detached, the turn goes on
            entry.client.put(m | {"id": entry.id})
        if "error" not in m:
            self.mirror(entry, m.get("result"))
        if entry.method == "session/prompt":
            stop = (m.get("result") or {}).get("stopReason", "error")
            self.end_turn(stop)
            self.broadcast(notification("_handler/turn_ended", stopReason=stop), entry.client)
            self.broadcast_state()

    async def route(self, m: Message) -> None:
        """An agent message for the client side, after the policy."""
        if is_response(m):
            self.responded(m)
            return
        if m.get("method") == "session/update":
            update = (m.get("params") or {}).get("update") or {}
            if self.replaying:
                return
            self.observe_update(update)
            # user messages are logged from the prompts themselves (the agent may echo them)
            if not (self.busy and update.get("sessionUpdate") == "user_message_chunk"):
                self.log.append("update", update=update)
            self.broadcast(m)
        elif is_request(m) and self.record.interface is not None:  # a run: no one to ask
            await self.to_agent(self.auto_answer(m))
        elif is_request(m):  # session/request_permission (P4 answered fs/*, terminal/*)
            self.pending[m["id"]] = m
            self.broadcast(m)
            self.broadcast_state()
        else:
            self.broadcast(m)

    def auto_answer(self, request: Message) -> Message:
        """A run is in mode `bypass` (D.18): a request its harness still sends gets its first
        allow option; `cancelled` when there is none."""
        params = request.get("params") or {}
        options = params.get("options") or []
        kinds = ("allow_once", "allow_always")
        chosen = next((o for k in kinds for o in options if o.get("kind") == k), None)
        outcome: Message = {"outcome": "cancelled"}
        if chosen is not None:
            outcome = {"outcome": "selected", "optionId": chosen["optionId"]}
        title = (params.get("toolCall") or {}).get("title")
        self.log.append("lifecycle", event="permission answered", detail=f"{title}: {outcome}")
        return {"jsonrpc": "2.0", "id": request["id"], "result": {"outcome": outcome}}

    def observe_update(self, update: Message) -> None:
        kind = update.get("sessionUpdate")
        if kind == "session_info_update" and "title" in update:
            self.record.title = update["title"]
        elif kind == "current_mode_update" and isinstance(self.modes, dict):
            self.modes = self.modes | {"currentModeId": update.get("currentModeId")}
        elif kind == "config_option_update":
            self.config_options = update.get("configOptions")

    def mirror(self, entry: "Forwarded", result: Any) -> None:
        """A client changed the mode or an option: keep it for later `session/load` answers
        (F.4), and show it to the other clients (F.7)."""
        update: Message | None = None
        if entry.method == "session/set_mode" and isinstance(self.modes, dict):
            mode = entry.params.get("modeId")
            self.modes = self.modes | {"currentModeId": mode}
            update = {"sessionUpdate": "current_mode_update", "currentModeId": mode}
        elif entry.method == "session/set_config_option" and isinstance(result, dict):
            if (options := result.get("configOptions")) is not None:
                self.config_options = options
                update = {"sessionUpdate": "config_option_update", "configOptions": options}
        if update is not None:
            params = {"sessionId": self.record.acp_session_id, "update": update}
            self.broadcast(notification("session/update", **params), entry.client)

    def end_turn(self, stop_reason: str) -> None:
        self.prompt_id = self.turn_started_at = None
        self.record.last_stop_reason = stop_reason
        self.log.append("turn", phase="end", stopReason=stop_reason)
        self.touch()
        self.schedule_idle()

    async def ended(self) -> None:
        """The agent is gone (exit, stop, idle timeout): the session becomes `stopped`."""
        rec = self.record
        code = await self.proc.wait() if self.proc else None
        for task in self.tasks:
            if task is not asyncio.current_task():
                task.cancel()
        self.cancel_idle()
        for future in self.own.values():
            if not future.done():
                future.set_exception(SessionError(f"agent exited ({code})"))
        reason = self.stop_reason or f"agent exited ({code})"
        if self.busy:
            self.log.append("turn", phase="end", stopReason="stopped")
            self.prompt_id = self.turn_started_at = None
        self.forwarded.clear()
        self.pending.clear()
        self.remote = False  # reset: switched on again by hand after a restart
        self.agent.connections.pop(rec.id, None)
        self.store.live.pop(rec.id, None)
        if rec.state == "running":
            rec.state = "stopped"
            rec.error = None if self.stop_reason or code == 0 else reason
            self.log.append("lifecycle", event="stopped", detail=reason, how=self.stop_how)
            self.store.save(rec)
        clients, self.clients = self.clients, []
        for client in clients:
            client.close(AcpCloseCode.SESSION_STOPPED, reason)
        self.store.changed()

    async def stop(self, reason: str, how: StopHow) -> None:
        self.stop_reason, self.stop_how = reason, how
        if self.proc is not None:
            await stop(self.proc)

    # ── client side (F.4) ───────────────────────────────────────────────

    async def attach(self, ws: WebSocket) -> None:
        """Serve one attached WebSocket until it closes, or the daemon closes it."""
        client = self.add(Attachment.of(ws))
        try:
            while not client.closed:
                event = await ws.receive()
                if event["type"] == "websocket.disconnect":
                    return
                if event.get("bytes") is not None:
                    client.close(AcpCloseCode.UNSUPPORTED_DATA, "binary frame")
                    return
                for line in (event.get("text") or "").splitlines():
                    if client.closed:
                        return
                    if line.strip() and (msg := parse(line)) is not None:
                        await self.from_client(client, msg)
        finally:
            self.remove(client)

    def add(self, client: Attachment) -> Attachment:
        """A new attachment; beyond `HANDLER_SESSION_MAX_ATTACH`, the oldest is closed (4001)."""
        while len(self.clients) >= self.store.settings.session_max_attach:
            oldest = self.clients.pop(0)
            oldest.close(AcpCloseCode.ATTACHED_ELSEWHERE, "attached elsewhere")
        self.clients.append(client)
        self.cancel_idle()
        self.broadcast_state()
        return client

    def remove(self, client: Attachment) -> None:
        """The client has gone (or was closed): the agent and its turn go on."""
        if client in self.clients:
            self.clients.remove(client)
            client.discard()
            self.broadcast_state()
        self.schedule_idle()

    async def from_client(self, client: Attachment, m: Message) -> None:
        method = m.get("method")
        if is_response(m):  # an answer to a permission request: the first one wins (F.7)
            if (request := self.pending.pop(m["id"], None)) is not None:
                await self.to_agent(m)
                self.resolved(request, m, client)
            return  # an answer to a request already answered, or unknown: dropped
        request = is_request(m)
        raw = m.get("params")
        params: Message = raw if isinstance(raw, dict) else {}
        if method == "initialize" and request:
            client.put({"jsonrpc": "2.0", "id": m["id"], "result": self.init_result})
            return
        if method == "session/load" and request:
            self.load(client, m, params)
            return
        session_id = params.get("sessionId")
        other = session_id is not None and session_id != self.record.acp_session_id
        if request and (method in ("session/new", "session/resume") or other):
            code = SessionErrorCode.ONE_SESSION_PER_ATTACHMENT
            client.put(error(m["id"], code, "one session per attachment"))
            return
        if method == "session/prompt" and request:
            if self.record.interface is not None:
                code = SessionErrorCode.UNATTENDED
                client.put(error(m["id"], code, "unattended: a run takes no prompt"))
                return
            if self.busy:
                code = SessionErrorCode.TURN_IN_PROGRESS
                client.put(error(m["id"], code, "turn in progress"))
                return
            if self.record.instructions:
                params = params | {"prompt": instructed(self.record.instructions, params)}
                m = m | {"params": params}
                self.record.instructions = None
                self.store.save(self.record)
            self.begin_turn(params.get("prompt") or [], client)
        if request:
            ours = f"handler-c-{next(self.ids)}"
            self.forwarded[ours] = Forwarded(client, m["id"], str(method), params)
            if method == "session/prompt":
                self.prompt_id = ours
            m = m | {"id": ours}
        await self.execute(m)

    def resolved(self, request: Message, answer: Message, by: Attachment) -> None:
        """Tell the other clients a permission request was answered, so they drop it."""
        tool_call = (request.get("params") or {}).get("toolCall") or {}
        outcome = (answer.get("result") or {}).get("outcome")
        self.broadcast(
            notification(
                "_handler/permission_resolved",
                requestId=request["id"],
                toolCallId=tool_call.get("toolCallId"),
                outcome=outcome,
            ),
            by,
        )
        self.broadcast_state()
        self.schedule_idle()

    async def first_prompt(self, blocks: list[Message], timeout: float | None = None) -> None:
        """The request a session was created with, sent by the daemon itself as its first turn:
        the attached clients see it like another client's prompt (F.7). After `timeout` seconds
        the turn is cancelled (and ends as `timed_out`)."""
        rid = f"handler-d-{next(self.ids)}"
        future: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
        self.own[rid] = future
        self.begin_turn(blocks, None)
        self.prompt_id = rid
        params = {"sessionId": self.record.acp_session_id, "prompt": blocks}
        timed_out = False
        try:
            await self.execute(
                {"jsonrpc": "2.0", "id": rid, "method": "session/prompt", "params": params}
            )
            try:
                response = await asyncio.wait_for(asyncio.shield(future), timeout)
            except TimeoutError:
                timed_out = True
                await self.cancel_turn()
                response = await asyncio.wait_for(future, CANCEL_GRACE)
        except (SessionError, TimeoutError):
            return  # the agent is gone (`ended` closed the turn), or ignored the cancel
        finally:
            self.own.pop(rid, None)
        if self.prompt_id != rid:
            return
        stop = (response.get("result") or {}).get("stopReason", "error")
        stop = "timed_out" if timed_out else stop
        self.end_turn(stop)
        self.broadcast(notification("_handler/turn_ended", stopReason=stop))
        self.broadcast_state()

    async def cancel_turn(self) -> None:
        """session/cancel for the turn in progress, whoever started it."""
        if self.busy:
            params = {"sessionId": self.record.acp_session_id}
            await self.execute({"jsonrpc": "2.0", "method": "session/cancel", "params": params})

    def begin_turn(self, prompt: list[Any], by: Attachment | None) -> None:
        self.cancel_idle()
        for block in prompt:
            update = {"sessionUpdate": "user_message_chunk", "content": block}
            self.log.append("update", update=update)
            params = {"sessionId": self.record.acp_session_id, "update": update}
            self.broadcast(
                notification("session/update", **params, _meta={"handler.dev/seq": self.log.seq}),
                by,
            )
        self.log.append("turn", phase="start")
        self.touch()
        self.prompt_id = "starting"  # busy from now on; set to the forwarded id right after
        self.turn_started_at = now()
        self.broadcast_state()

    def load(self, client: Attachment, m: Message, params: Message) -> None:
        """The attach proper: replay the log, answer with the current state, re-send pending
        permission requests; from then on the client gets live traffic."""
        assert self.policy is not None
        if params.get("sessionId") != self.record.acp_session_id:
            code = SessionErrorCode.ONE_SESSION_PER_ATTACHMENT
            client.put(error(m["id"], code, "one session per attachment"))
            return
        if refusal := self.policy.check_session_params(m):  # P2 / P3
            client.put(refusal)
            return
        meta = params.get("_meta")
        after = meta.get("handler.dev/afterSeq", 0) if isinstance(meta, dict) else 0
        result = {
            k: v
            for k, v in (("modes", self.modes), ("configOptions", self.config_options))
            if v is not None
        }
        # no await from here on: nothing can be broadcast between the replay and `ready`
        for seq, update in self.log.updates(after if isinstance(after, int) else 0):
            params_ = {"sessionId": self.record.acp_session_id, "update": update}
            client.put(notification("session/update", **params_, _meta={"handler.dev/seq": seq}))
        client.put({"jsonrpc": "2.0", "id": m["id"], "result": result})
        client.put(notification("_handler/session_state", **self.state()))
        for pending in self.pending.values():
            client.put(pending)
        client.ready = True

    def state(self) -> Message:
        return {
            "state": self.record.state,
            "busy": self.busy,
            "turnStartedAt": self.turn_started_at.isoformat() if self.turn_started_at else None,
            "pendingPermissions": len(self.pending),
            "attached": len(self.clients),
        }

    def broadcast(self, msg: Message, but: Attachment | None = None) -> None:
        for client in self.clients:
            if client.ready and client is not but:
                client.put(msg)

    def broadcast_state(self) -> None:
        self.broadcast(notification("_handler/session_state", **self.state()))

    # ── idle stop (F.6.3) ───────────────────────────────────────────────

    def touch(self) -> None:
        self.record.last_activity_at = now()
        self.store.save(self.record)

    def schedule_idle(self) -> None:
        self.cancel_idle()
        if not self.clients and not self.busy and not self.pending:
            loop = asyncio.get_running_loop()
            self.idle = loop.call_later(
                self.store.settings.session_idle_timeout,
                lambda: self.store.spawn(self.stop("idle timeout", "idle")),
            )

    def cancel_idle(self) -> None:
        if self.idle is not None:
            self.idle.cancel()
            self.idle = None


def title_of(prompt: str) -> str:
    line = next((x.strip() for x in prompt.splitlines() if x.strip()), "")
    return line if len(line) <= TITLE_LENGTH else line[: TITLE_LENGTH - 1].rstrip() + "…"


def notification(method: str, **params: Any) -> Message:
    return {"jsonrpc": "2.0", "method": method, "params": params}


@dataclass
class Forwarded:
    """A client's request, forwarded to the agent under our own id."""

    client: Attachment
    id: Any  # the client's id, restored on the response
    method: str
    params: Message


class SessionStore:
    def __init__(self, settings: Settings, registry: AgentRegistry) -> None:
        self.settings = settings
        self.registry = registry
        self.dir = settings.state_dir / "sessions"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.records: dict[str, SessionRecord] = {}
        self.live: dict[str, LiveSession] = {}
        self.starting: dict[str, asyncio.Task[LiveSession]] = {}
        self.background: set[asyncio.Task[Any]] = set()
        self.listeners: list[Callable[[], None]] = []  # told when sessions stop or are shared
        # told with its id when a session's `lifecycle stopped` event is written (automations)
        self.stop_listeners: list[Callable[[str], None]] = []
        self._load()

    # ── persistence ─────────────────────────────────────────────────────

    def folder(self, session_id: str) -> Path:
        return self.dir / session_id

    def event_log(self, session_id: str) -> EventLog:
        def stopped() -> None:
            for listener in self.stop_listeners:
                listener(session_id)

        return EventLog(self.folder(session_id) / "events.ndjson", stopped)

    def _load(self) -> None:
        """F.6.5: sessions that were live when the daemon stopped are `stopped` now."""
        for path in self.dir.glob("*/session.json"):
            try:
                rec = SessionRecord.from_json(json.loads(path.read_text()))
            except (ValueError, TypeError, KeyError) as e:
                log.warning("ignoring %s: %s", path, e)
                continue
            self.records[rec.id] = rec
            if rec.state in ("starting", "running"):
                events = self.event_log(rec.id)
                if events.open_turn:
                    events.append("turn", phase="end", stopReason="daemon_restarted")
                events.append(
                    "lifecycle", event="stopped", detail="daemon restarted", how="daemon_restarted"
                )
                rec.state = "stopped" if rec.acp_session_id else "failed"
                self.save(rec)

    def save(self, rec: SessionRecord) -> None:
        folder = self.folder(rec.id)
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = folder / "session.json.tmp"
        tmp.write_text(json.dumps(rec.to_json(), indent=2))
        tmp.replace(folder / "session.json")

    def redactor(self, agent: AgentRecord, runs: RunsAs) -> Any:
        """Invariant 4: its account's or provider's and bindings' secret values never land in the
        event log."""
        return redactor(launcher.secret_values(self.settings, agent, runs))

    def spawn(self, coro: Any) -> None:
        task = asyncio.ensure_future(coro)
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    # ── API ─────────────────────────────────────────────────────────────

    def to_contract(self, rec: SessionRecord) -> Session:
        live = self.live.get(rec.id)
        agent = self.registry.get(rec.agent_id)
        return Session(
            id=rec.id,
            agent_id=rec.agent_id,
            project_id=agent.project_id if agent else None,
            harness=rec.harness,
            account=rec.account,
            provider=rec.provider,
            model=rec.model,
            scope=rec.scope,
            acp_session_id=rec.acp_session_id,
            title=rec.title,
            state=rec.state,
            busy=bool(live and live.busy),
            pending_permissions=len(live.pending) if live else 0,
            attached=len(live.clients) if live else 0,
            remote=bool(live and live.remote),
            can_resume=rec.can_resume,
            error=rec.error,
            harness_version=rec.harness_version,
            origin=rec.origin,
            last_stop_reason=rec.last_stop_reason,
            answer=rec.answer,
            input=SessionInput.model_validate(rec.input) if rec.input else None,
            output=SessionOutput.model_validate(rec.output) if rec.output else None,
            created_at=rec.created_at,
            last_activity_at=rec.last_activity_at,
            acp_url=self.settings.base_url.replace("http://", "ws://") + session_acp_path(rec.id),
        )

    def list(self, agent_id: str | None = None) -> list[SessionRecord]:
        # a copy: sync routes read it in a worker thread, the event loop changes it
        records = list(self.records.values())
        records = [r for r in records if agent_id is None or r.agent_id == agent_id]
        return sorted(records, key=lambda r: r.last_activity_at, reverse=True)

    def mounts(self, session_id: str) -> Path:
        """What its sandbox saw of the host at its last start (F.8)."""
        return self.folder(session_id) / "mounts.json"

    def baseline(self, session_id: str) -> Path:
        """Its folder as it started (F.8)."""
        return self.folder(session_id) / "baseline.json"

    def work_folder(self, session_id: str) -> Path:
        """A folderless agent's session's own folder (D.18)."""
        return self.folder(session_id) / "work"

    def create(
        self,
        agent: AgentRecord,
        runs: RunsAs,
        acp_session_id: str | None = None,
        prompt: str | None = None,
        *,
        origin: SessionOrigin = "ui",
        run: SessionInput | None = None,
        from_skill: str | None = None,
    ) -> SessionRecord:
        """A new session, started in the background (F.3). With a `prompt` (the request), the
        daemon sends it once the agent runs, after the agent's instructions if it has any (a
        blank line between them, in one text block); without, the instructions go the same way
        with the first prompt a client sends. The
        request's first line is the title until the agent gives one. `runs`: the agent's model it
        runs with (one of its own).

        `run`: an agent with an interface's checked input (D.18): an unattended run. A
        folderless agent's session works in its own folder, a copy of `from_skill` if given."""
        sid = "s_" + pysecrets.token_hex(8)
        scope = agent.scope
        if scope is None:
            work = self.work_folder(sid)
            work.mkdir(parents=True)
            work.parent.chmod(0o700)
            if from_skill is not None:
                skills.copy(self.settings.skills_dir / from_skill, work)
            scope = str(work)
        interface = agent.interface if run is not None else None
        title = title_of(prompt) if prompt else None
        timeout = None
        if interface is not None and run is not None:
            timeout = interface.timeout_sec
            subject = run.subject.skill if run.subject else None
            title = f"{agent.name or runs.harness}: {subject}" if subject else agent.name
        rec = SessionRecord(
            id=sid,
            agent_id=agent.id,
            harness=runs.harness,
            account=runs.account,
            provider=runs.provider,
            model=runs.model,
            scope=scope,
            created_at=now(),
            last_activity_at=now(),
            acp_session_id=acp_session_id,
            title=title,
            origin=origin,
            interface=interface.model_dump(mode="json", by_alias=True) if interface else None,
            input=run.model_dump(mode="json", by_alias=True) if run is not None else None,
            # with no request to go with, they go with the first prompt (a resumed one has had
            # its first turn)
            instructions=None if prompt or run or acp_session_id else agent.instructions,
        )
        self.records[rec.id] = rec
        self.save(rec)
        text = None
        if interface is not None and run is not None:
            notes = self.subject_notes(run)
            text = interfaces.request(agent.instructions, interface, run, notes)
        elif prompt:
            text = f"{agent.instructions}\n\n{prompt}" if agent.instructions else prompt
        # one block: every adapter reads it (some would drop a second one)
        blocks = [{"type": "text", "text": text}] if text else []
        self.spawn(self._start_quietly(rec.id, blocks, timeout))
        return rec

    def subject_notes(self, run: SessionInput) -> str | None:
        """What handlerd tells a run about its subject besides where it is: a skill's scan
        (D.17)."""
        if run.subject is None:
            return None
        return skill_scan.notes(skill_scan.scan(self.settings.skills_dir / run.subject.skill))

    async def _start_quietly(
        self, session_id: str, prompt: Sequence[Message] = (), timeout: float | None = None
    ) -> None:
        with contextlib.suppress(SessionError):
            live = await self.ensure_running(session_id)
            if prompt:
                await live.first_prompt(list(prompt), timeout)
            if live.record.interface is not None:  # a run: its result, then no one to talk to
                await self.read_output(live, timeout)
                self.keep_answer(live.record)
                await self.stop(session_id, "run ended", "run_ended")

    async def read_output(self, live: LiveSession, timeout: float | None) -> None:
        """A run's result, from its final message (D.18); asked once more when it is missing or
        invalid. None when its turn did not end (timed out, cancelled, failed)."""
        rec = live.record
        assert rec.interface is not None
        schema = AgentInterface.model_validate(rec.interface).result
        output: SessionOutput | None = None
        for attempt in range(2):
            if rec.last_stop_reason != "end_turn":
                break
            output = interfaces.parse(self.event_log(rec.id).answer(), schema)
            if output.valid or attempt == 1 or live.record.state != "running":
                break
            await live.first_prompt([{"type": "text", "text": interfaces.repair(output)}], timeout)
        rec.output = output.model_dump(mode="json", by_alias=True) if output else None
        self.save(rec)

    def keep_answer(self, rec: SessionRecord) -> None:
        rec.answer = self.event_log(rec.id).answer()
        self.save(rec)

    async def cancel(self, session_id: str) -> None:
        if (live := self.live.get(session_id)) is not None:
            await live.cancel_turn()

    async def ensure_running(self, session_id: str) -> LiveSession:
        """The live session, started if needed — at most one start at a time (F.6.1)."""
        if (live := self.live.get(session_id)) is not None and live.record.state == "running":
            return live
        task = self.starting.get(session_id)
        if task is None:
            task = asyncio.create_task(self._start(self.records[session_id]))
            self.starting[session_id] = task
            task.add_done_callback(lambda _: self.starting.pop(session_id, None))
        return await asyncio.shield(task)

    async def _start(self, rec: SessionRecord) -> LiveSession:
        if rec.state == "failed":
            raise SessionError(rec.error or "session failed")
        agent = self.registry.get(rec.agent_id)
        if agent is None:
            raise SessionError("its agent was deleted")
        # its history belongs to the harness, login and folder it was started with
        # (its project's context is checked when it starts, launcher.prepare)
        runs = agent.resumes_as(rec.harness, rec.account, rec.provider, rec.model)
        if (scope := agent.scope or str(self.work_folder(rec.id))) != rec.scope:
            raise SessionError(
                f"the agent now works in {scope}; this conversation was in {rec.scope}: "
                "start a new session"
            )
        self.registry.touch(agent)
        first = rec.state == "starting"
        rec.state = "starting"
        self.save(rec)
        if first:  # what its folder holds before the agent runs (F.8)
            try:
                await asyncio.to_thread(
                    session_files.record_baseline, Path(rec.scope), self.baseline(rec.id)
                )
            except OSError as e:
                log.warning("session %s: its folder not recorded: %s", rec.id, e)
        live = LiveSession(self, rec, agent, runs)
        self.live[rec.id] = live
        try:
            await live.start()
        except (SessionError, launcher.AgentStartError, OSError) as e:
            log.warning("session %s: start failed: %s", rec.id, e)
            rec.state, rec.error = ("failed" if first else "stopped"), str(e)
            live.stop_reason = str(e)
            self.save(rec)
            await live.stop(str(e), "error")
            self.live.pop(rec.id, None)
            raise SessionError(str(e)) from None
        return live

    def changed(self) -> None:
        for listener in self.listeners:
            listener()

    def set_remote(self, session_id: str, enabled: bool) -> None:
        """Share a running session with paired devices, or stop sharing it
        (docs/dev/design/remote.md §5). Off closes the remote attachments at once (4004)."""
        live = self.live.get(session_id)
        if live is None or live.record.state != "running":
            raise SessionError("the session is not running")
        live.remote = enabled
        if not enabled:
            for client in list(live.clients):
                if client.kind == "remote":
                    client.close(AcpCloseCode.REMOTE_DISABLED, "remote access disabled")
        self.changed()

    async def stop(self, session_id: str, reason: str, how: StopHow) -> None:
        if (task := self.starting.get(session_id)) is not None:
            with contextlib.suppress(SessionError):
                await asyncio.shield(task)
        if (live := self.live.get(session_id)) is not None:
            await live.stop(reason, how)
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*live.tasks, return_exceptions=True)

    async def delete(self, session_id: str) -> None:
        await self.stop(session_id, "deleted", "deleted")
        self.records.pop(session_id, None)
        shutil.rmtree(self.folder(session_id), ignore_errors=True)

    async def stop_agent(self, agent_id: str) -> None:
        for rec in self.list(agent_id):
            await self.stop(rec.id, "workspace deleted", "deleted")
