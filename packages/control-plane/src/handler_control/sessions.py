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

A session may be started with a request (sent by the daemon as its first turn), or, for an agent
with an interface (D.18), with an input (its form filled): a brief's session then goes on as a
chat; a job's run is unattended: its
permission requests are answered by its interface's policy, its turn is cancelled after its
timeout, no client may prompt it, and its result is read from its final message (one more turn
when it is missing or invalid); then it stops, its answer (the agent's last message) kept. Runs
of one agent take turns (D.18): a run waits, in order, while another run of its agent goes on, at
most `run_wait_timeout` (30 min); runs of other agents go on meanwhile.

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
from typing import Any, Literal, Protocol

from starlette.websockets import WebSocket

from handler_contracts import (
    RUN_TIMEOUT_SEC,
    AcpCloseCode,
    AgentInterface,
    LlmUsage,
    Mount,
    NoNetwork,
    SandboxExit,
    Session,
    SessionAppDraft,
    SessionErrorCode,
    SessionInput,
    SessionLifecycle,
    SessionOrigin,
    SessionOutput,
    SessionSubject,
    session_acp_path,
)

from . import __version__, interfaces, launcher, llm, session_files, skill_scan, skills
from .agents import AgentRecord, AgentRegistry, LiveConnection, RunsAs
from .model_agent import ModelAgent
from .policy import AcpPolicy, ToAgent, ToClient, instructed, is_request, is_response, parse
from .sandbox_process import read_stderr, stop
from .secrets import redactor
from .settings import Settings

log = logging.getLogger("handler.sessions")

Message = dict[str, Any]
STDERR_DRAIN = 2.0  # seconds for the rest of a sandbox's stderr once it exited
SANDBOX_EXITS = {int(code) for code in SandboxExit}  # its launcher refused or failed to start it
START_TIMEOUT = 300.0  # initialize + session/new|load, image start included
TITLE_LENGTH = 80  # a title taken from the first request
CANCEL_GRACE = 30.0  # after a timeout's session/cancel, for the agent to end its turn
QUEUE_SIZE = 10_000  # messages waiting for one client; more: it is closed as too slow (F.7)
RUN_POLL = 0.2
RESULT_POLL = 0.5  # a run read again until it ended (result_of)

# how a session stopped (F.5), on its `lifecycle stopped` event: read by automations (I.2)
StopHow = Literal["explicit", "idle", "exited", "error", "run_ended", "daemon_restarted", "deleted"]


class AgentLink(Protocol):
    """What a session talks ACP through: an agent program's sandbox (SandboxLink) or, for an
    agent on the model alone, handlerd's own model agent (model_agent.ModelAgent, D.18)."""

    async def send(self, msg: Message) -> None: ...

    async def receive(self) -> Message | None:
        """Its next message; None when it is gone."""
        ...

    async def wait(self) -> int | None:
        """Once gone: its exit code."""
        ...

    async def stop(self) -> None: ...


class AgentMessageTooBigError(Exception):
    """A line of the agent's past the message limit (DEFAULT_MAX_MESSAGE_BYTES)."""


class SandboxLink:
    """An agent program in its sandbox: ACP as JSON lines on the sandbox process's stdio."""

    def __init__(self, proc: asyncio.subprocess.Process, label: str) -> None:
        assert proc.stdin is not None and proc.stdout is not None
        self.proc, self.label = proc, label
        self.stdin, self.stdout = proc.stdin, proc.stdout

    async def send(self, msg: Message) -> None:
        with contextlib.suppress(ConnectionError):
            self.stdin.write(json.dumps(msg).encode() + b"\n")
            await self.stdin.drain()

    async def receive(self) -> Message | None:
        while True:
            try:
                line = await self.stdout.readline()
            except (ValueError, asyncio.LimitOverrunError):
                raise AgentMessageTooBigError from None
            if not line:
                return None
            if (msg := parse(line.decode(errors="replace"))) is not None:
                return msg
            log.warning("[%s] dropped a non-object agent message", self.label)

    async def wait(self) -> int | None:
        return await self.proc.wait()

    async def stop(self) -> None:
        await stop(self.proc)


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
    harness: str | None  # the model it was started with (its agent's or one picked for it): the
    # harness (None: the model alone, D.18), on the account or provider below, with `model`
    scope: str
    created_at: datetime
    last_activity_at: datetime
    # started with its agent's model, not one picked for it alone (D.19): when the agent's
    # changes, it resumes with the agent's new one on the same harness and access
    agents_model: bool
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
    missing_image: str | None = None  # its last start refused: the build making what it needs
    harness_version: str | None = None
    origin: SessionOrigin = "ui"
    app: str | None = None  # origin "app": the app that started it (H.11)
    waiting_for: str | None = None  # a run waiting: the run of its agent it waits for (D.18)
    last_stop_reason: str | None = None
    answer: str | None = None  # a run's: the agent's last message, kept when it ended
    interface: dict[str, Any] | None = None  # a run (D.18): its job's interface when it started
    input: dict[str, Any] | None = None  # a run, a brief's session: SessionInput
    subject: dict[str, Any] | None = None  # a run: SessionSubject, the skill it works on
    output: dict[str, Any] | None = None  # a run: SessionOutput, once its turn ended
    # its folder is a draft of an app's code (H.15), not used yet: SessionAppDraft
    app_draft: dict[str, Any] | None = None
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
        self.link: AgentLink | None = None
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
        self.stderr: asyncio.Task[None] | None = None  # its sandbox's logs, read
        self.launcher_said: str | None = None  # the last line of its sandbox's launcher's own

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
        if rec.subject is not None:
            try:
                subject = interfaces.subject_mount(
                    settings.skills_dir, SessionSubject.model_validate(rec.subject)
                )
            except skills.SkillError as e:
                raise SessionError(str(e)) from None
        if self.agent.model_alone:
            self.start_model_agent(state_dir)
        else:
            await self.start_sandbox(state_dir, subject)
        self.tasks.append(asyncio.create_task(self.agent_pump()))
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
        rec.state, rec.error, rec.missing_image = "running", None, None
        self.log.append("lifecycle", event="started")
        self.store.save(rec)
        self.schedule_idle()

    async def start_sandbox(self, state_dir: Path, subject: Mount | None) -> None:
        """An agent program in its sandbox (A, B)."""
        rec, settings = self.record, self.store.settings
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
        assert rec.harness is not None  # an agent program's
        rec.harness_version = await launcher.harness_version(rec.harness)
        process = started.process
        self.link = SandboxLink(process, rec.id)  # ty: ignore[invalid-argument-type]
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
            process=process,
            egress_base=started.egress_base,
        )
        registry = self.store.registry
        on_egress = lambda e: registry.add_event(self.agent, rec.id, e)  # noqa: E731
        said = lambda line: setattr(self, "launcher_said", line)  # noqa: E731
        self.stderr = asyncio.create_task(read_stderr(process, rec.id, on_egress, said))  # ty: ignore[invalid-argument-type]
        self.tasks = [self.stderr]

    def start_model_agent(self, state_dir: Path) -> None:
        """An agent on the model alone (D.18): handlerd's model agent, no sandbox, no tools."""
        rec = self.record
        assert self.runs.provider is not None  # the model alone runs on a provider

        def on_call(usage: LlmUsage, ms: int) -> None:
            tokens = {"inTokens": usage.in_tokens, "outTokens": usage.out_tokens}
            self.log.append("lifecycle", event="model call", model=self.runs.model, ms=ms, **tokens)

        self.link = ModelAgent(
            self.store.settings,
            provider=self.runs.provider,
            model=self.runs.model,
            knowledge_folders=self.agent.knowledge,
            folder=state_dir,
            on_call=on_call,
        )
        self.policy = AcpPolicy(
            scope=rec.scope,
            network=NoNetwork(mode="none"),
            on_event=lambda text: log.info("[%s] policy: %s", rec.id, text),
        )

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
        assert self.link is not None
        if self.translate and self.record.agent_session_id is not None:
            msg = with_session_id(msg, self.record.acp_session_id, self.record.agent_session_id)
        async with self.agent_lock:
            await self.link.send(msg)

    async def agent_pump(self) -> None:
        assert self.link is not None and self.policy is not None
        try:
            while True:
                try:
                    msg = await self.link.receive()
                except AgentMessageTooBigError:
                    log.warning("[%s] agent message too big: stopping", self.record.id)
                    self.stop_reason, self.stop_how = "agent message too big", "error"
                    await self.link.stop()
                    break
                if msg is None:
                    break
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
        code = await self.link.wait() if self.link else None
        exited = f"agent exited ({code})"
        if code in SANDBOX_EXITS and self.stderr is not None:  # its sandbox did not start
            await asyncio.wait([self.stderr], timeout=STDERR_DRAIN)  # its launcher's last words
            exited = self.launcher_said or exited
        for task in self.tasks:
            if task is not asyncio.current_task():
                task.cancel()
        self.cancel_idle()
        for future in self.own.values():
            if not future.done():
                future.set_exception(SessionError(exited))
        reason = self.stop_reason or exited
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
        if self.link is not None:
            await self.link.stop()

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
            "lastStopReason": self.record.last_stop_reason,
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


def wait_label(seconds: float) -> str:
    """ "30 min", "45 s"."""
    return f"{seconds / 60:.0f} min" if seconds >= 60 else f"{seconds:.0f} s"


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
        # runs take turns per agent (D.18): agent id → the run going on, the runs waiting
        self.running_runs: dict[str, str] = {}
        self.run_queues: dict[str, list[str]] = {}
        self.waits: dict[str, asyncio.Task[Any]] = {}  # a waiting run's id → its task
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
                rec.waiting_for = None
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
        if agent.model_alone:
            assert runs.provider is not None  # the model alone runs on a provider
            return redactor(llm.secret_values(self.settings, runs.provider))
        return redactor(launcher.secret_values(self.settings, agent, runs))

    def spawn(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self.background.add(task)
        task.add_done_callback(self.background.discard)
        return task

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
            missing_image=rec.missing_image,
            harness_version=rec.harness_version,
            origin=rec.origin,
            app=rec.app,
            waiting_for=rec.waiting_for,
            last_stop_reason=rec.last_stop_reason,
            answer=rec.answer,
            input=SessionInput.model_validate(rec.input) if rec.input else None,
            unattended=rec.interface is not None,
            subject=SessionSubject.model_validate(rec.subject) if rec.subject else None,
            output=SessionOutput.model_validate(rec.output) if rec.output else None,
            app_draft=SessionAppDraft.model_validate(rec.app_draft) if rec.app_draft else None,
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

    async def result_of(self, session_id: str) -> tuple[dict[str, Any] | None, str | None]:
        """A run's valid result (D.18) once it ended, else why it has none."""
        while True:
            rec = self.records.get(session_id)
            if rec is None:
                return None, "its run was deleted"
            ended = session_id not in self.live and session_id not in self.starting
            if ended and rec.state in ("stopped", "failed") and rec.waiting_for is None:
                break
            await asyncio.sleep(RESULT_POLL)
        output = SessionOutput.model_validate(rec.output) if rec.output else None
        if output is None or not output.valid or not isinstance(output.value, dict):
            return None, (output.error if output else None) or rec.error or "no valid result"
        return output.value, None

    def create(
        self,
        agent: AgentRecord,
        runs: RunsAs,
        acp_session_id: str | None = None,
        prompt: str | None = None,
        *,
        origin: SessionOrigin = "ui",
        run: SessionInput | None = None,
        subject: SessionSubject | None = None,
        from_skill: str | None = None,
        app_draft: tuple[SessionAppDraft, Path | None] | None = None,
        app: str | None = None,
        instructions: str | None = None,
    ) -> SessionRecord:
        """A new session, started in the background (F.3). With a `prompt` (the request), the
        daemon sends it once the agent runs, after the agent's instructions if it has any (a
        blank line between them, in one text block); without, the instructions go the same way
        with the first prompt a client sends. The
        request's first line is the title until the agent gives one. `runs`: the agent's model it
        runs with (one of its own).

        `run`: an agent with an interface's checked input (D.18), working on `subject` (the skill
        its skill field names) when given: a job's unattended run, or a brief's session. A
        folderless agent's session works in its own folder, a copy of `from_skill` if given, or a
        draft of an app's code (`app_draft`: the draft, and the code it starts as a copy of; none
        for a new app, H.15).
        `app`: the app that started it (origin "app", H.11).
        `instructions`: for a check's run only (D.20, an improvement's attempt), instead of the
        agent's: the agent is not changed."""
        sid = "s_" + pysecrets.token_hex(8)
        scope = agent.scope
        if scope is None:
            work = self.work_folder(sid)
            work.mkdir(parents=True)
            work.parent.chmod(0o700)
            if from_skill is not None:
                skills.copy(self.settings.skills_dir / from_skill, work)
            if app_draft is not None and app_draft[1] is not None:
                shutil.copytree(app_draft[1], work, symlinks=True, dirs_exist_ok=True)
            scope = str(work)
        assert instructions is None or origin == "check"
        told = agent.instructions if instructions is None else instructions
        form = agent.interface if run is not None else None
        interface = form if form is not None and form.result is not None else None  # a job's run
        title = title_of(prompt) if prompt else None
        if form is not None and run is not None:
            title = f"{agent.name or runs.harness}: {subject.skill}" if subject else agent.name
            asked = [v for v in run.fields.values() if isinstance(v, str) and v.strip()]
            if interface is None and not subject and asked:  # a brief's: its first text
                title = title_of(asked[0])
        timeout = (interface.timeout_sec or RUN_TIMEOUT_SEC) if interface is not None else None
        rec = SessionRecord(
            id=sid,
            agent_id=agent.id,
            harness=runs.harness,
            account=runs.account,
            provider=runs.provider,
            model=runs.model,
            agents_model=runs == agent.model,
            scope=scope,
            created_at=now(),
            last_activity_at=now(),
            acp_session_id=acp_session_id,
            title=title,
            origin=origin,
            app=app,
            interface=interface.model_dump(mode="json", by_alias=True) if interface else None,
            input=run.model_dump(mode="json", by_alias=True) if run is not None else None,
            subject=subject.model_dump(mode="json", by_alias=True) if subject else None,
            app_draft=app_draft[0].model_dump(mode="json", by_alias=True) if app_draft else None,
            # with no request to go with, they go with the first prompt (a resumed one has had
            # its first turn)
            instructions=None if prompt or run or acp_session_id else agent.instructions,
        )
        self.records[rec.id] = rec
        self.save(rec)
        text = None
        if form is not None and run is not None:
            notes = self.subject_notes(subject)
            text = interfaces.request(told, form, run, subject, notes)
        elif prompt:
            text = f"{agent.instructions}\n\n{prompt}" if agent.instructions else prompt
        # one block: every adapter reads it (some would drop a second one)
        blocks = [{"type": "text", "text": text}] if text else []
        self.spawn(self._start_quietly(rec.id, blocks, timeout))
        return rec

    def subject_notes(self, subject: SessionSubject | None) -> str | None:
        """What handlerd tells a run about its subject besides where it is: a skill's scan
        (D.17)."""
        if subject is None:
            return None
        return skill_scan.notes(skill_scan.scan(self.settings.skills_dir / subject.skill))

    async def _start_quietly(
        self, session_id: str, prompt: Sequence[Message] = (), timeout: float | None = None
    ) -> None:
        rec = self.records[session_id]
        if rec.interface is None:
            await self._go(session_id, prompt, timeout)
            return
        if not await self._take_turn(rec):
            return
        try:
            await self._go(session_id, prompt, timeout)
        finally:
            self.running_runs.pop(rec.agent_id, None)

    async def _take_turn(self, rec: SessionRecord) -> bool:
        """A run's turn among its agent's runs (D.18): False when it did not come (it waited
        too long, or was stopped meanwhile)."""
        agent_id, loop = rec.agent_id, asyncio.get_running_loop()
        queue = self.run_queues.setdefault(agent_id, [])
        queue.append(rec.id)
        task = asyncio.current_task()
        assert task is not None
        self.waits[rec.id] = task
        limit = self.settings.run_wait_timeout
        deadline = loop.time() + limit
        try:
            while (ahead := self.running_runs.get(agent_id)) is not None or queue[0] != rec.id:
                ahead = ahead or queue[0]
                if rec.waiting_for != ahead:
                    rec.waiting_for = ahead
                    self.save(rec)
                    self.changed()
                if loop.time() > deadline:
                    behind = self.records.get(ahead)
                    what = behind.title if behind and behind.title else ahead
                    self.not_started(
                        rec, f"waited {wait_label(limit)}: its agent was still running {what}"
                    )
                    return False
                await asyncio.sleep(RUN_POLL)
            self.running_runs[agent_id] = rec.id
        except asyncio.CancelledError:  # stopped while waiting (stop): not_started is done
            return False
        finally:
            queue.remove(rec.id)
            self.waits.pop(rec.id, None)
        if rec.waiting_for is not None:
            rec.waiting_for = None
            self.save(rec)
            self.changed()
        return True

    def not_started(self, rec: SessionRecord, reason: str) -> None:
        """A run that never started: failed, with why (its `lifecycle stopped` event told)."""
        rec.waiting_for, rec.state, rec.error = None, "failed", reason
        self.save(rec)
        self.event_log(rec.id).append("lifecycle", event="stopped", detail=reason, how="error")
        self.changed()

    async def _go(
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
        assert schema is not None
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
        """Its turn cancelled; a run waiting for its turn (D.18) does not start."""
        if session_id in self.waits:
            await self.stop(session_id, "cancelled before its turn", "explicit")
        elif (live := self.live.get(session_id)) is not None:
            await live.cancel_turn()

    async def ensure_running(self, session_id: str) -> LiveSession:
        """The live session, started if needed — at most one start at a time (F.6.1). A run
        waiting for its turn (D.18) is not started before it comes."""
        if session_id in self.waits:
            raise SessionError("this run waits for its agent's run in progress")
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
        # (its project's area is checked when it starts, launcher.prepare)
        runs = agent.resumes_as(
            rec.harness, rec.account, rec.provider, rec.model, agents_model=rec.agents_model
        )
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
            # an image not built: nothing was launched, it starts once the image is (F.1)
            missing = e.target if isinstance(e, launcher.ImageMissingError) else None
            rec.state = "failed" if first and missing is None else "stopped"
            rec.error, rec.missing_image = str(e), missing
            if missing is not None:  # when, for a build of it to be known as later (F.1)
                rec.last_activity_at = now()
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
        if (wait := self.waits.pop(session_id, None)) is not None:  # a run waiting for its turn
            wait.cancel()
            self.not_started(self.records[session_id], reason)
            return
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
