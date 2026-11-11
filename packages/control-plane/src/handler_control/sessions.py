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
when it is missing or invalid); then it stops, its answer (the agent's last message) kept.

Handler says things in the conversation itself (`LiveSession.say`, F.5): a line logged among the
updates, sent live as `_handler/line` and replayed in its place. A host the network filter
refuses is one (F.9): a card per host per turn, answered *Allow* or *Keep blocked* by a client's
`_handler/decide_host`, saved to the agent and applied to its running sandboxes. While a client
that can answer is attached, the filter is told so (`set-watched`): it holds the first request to
an undecided host a few seconds for the answer, and the card counts them down. An answer after
the agent was refused is told to it as a turn of Handler's own (`tell`): at once, or queued until
its turn ends. Runs
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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from starlette.websockets import WebSocket

from handler_contracts import (
    CONTAINER_HOST,
    RUN_TIMEOUT_SEC,
    AcpCloseCode,
    AgentInterface,
    HostFolder,
    LlmUsage,
    NoNetwork,
    RefusedHost,
    SandboxExit,
    Session,
    SessionAppDraft,
    SessionErrorCode,
    SessionInput,
    SessionLifecycle,
    SessionOrigin,
    SessionOutput,
    SessionPlan,
    SessionPlanDraft,
    SessionSubject,
    session_acp_path,
)
from handler_harness import starting_instructions

from . import (
    __version__,
    addon_folders,
    compose,
    folders,
    interfaces,
    launcher,
    llm,
    session_files,
    skill_scan,
    skills,
)
from .agents import AgentRecord, AgentRegistry, LiveConnection, RunsAs, apply_network
from .model_agent import ModelAgent
from .policy import AcpPolicy, ToAgent, ToClient, instructed, is_request, is_response, parse
from .sandbox_process import read_stderr, set_watched, stop
from .secrets import redactor
from .settings import Settings

log = logging.getLogger("handler.sessions")

Message = dict[str, Any]
STDERR_DRAIN = 2.0  # seconds for the rest of a sandbox's stderr once it exited
SANDBOX_EXITS = {int(code) for code in SandboxExit}  # its launcher refused, failed or ended it
START_TIMEOUT = 300.0  # initialize + session/new|load, image start included
TITLE_LENGTH = 80  # a title taken from the first request
CANCEL_GRACE = 30.0  # after a timeout's session/cancel, for the agent to end its turn
QUEUE_SIZE = 10_000  # messages waiting for one client; more: it is closed as too slow (F.7)
RUN_POLL = 0.2
RESULT_POLL = 0.5  # a run read again until it ended (result_of)
EGRESS_LAG = 1.0  # seconds after a turn's end for its filter's last decisions (they come apart)
# the model's host failing to connect (A.3 `unreached`): said in the session after so many
# failures in a turn, or so many seconds after the first one with no connection reached since
MODEL_FAILURES = 3
MODEL_SILENCE = 15.0

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
    plan: dict[str, Any] | None = None  # origin "plan": SessionPlan, the step it is (D.27)
    waiting_for: str | None = None  # a run waiting: the run of its agent it waits for (D.18)
    last_stop_reason: str | None = None
    answer: str | None = None  # a run's: the agent's last message, kept when it ended
    interface: dict[str, Any] | None = None  # a run (D.18): its job's interface when it started
    input: dict[str, Any] | None = None  # a run, a brief's session: SessionInput
    subject: dict[str, Any] | None = None  # a run: SessionSubject, the skill it works on
    output: dict[str, Any] | None = None  # a run: SessionOutput, once its turn ended
    # its folder is a draft of an app's code (H.15), not used yet: SessionAppDraft
    app_draft: dict[str, Any] | None = None
    # a plan builder's: its folder is this plan draft, its project seen read-only (D.27):
    # SessionPlanDraft
    plan_draft: dict[str, Any] | None = None
    # its agent's instructions, until they go with the first prompt a client sends (F.3), or
    # with its `request`
    instructions: str | None = None
    # the request it was created with, until it is sent: kept while its start waits for an
    # image not built (F.1), sent once it starts
    request: str | None = None

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
            with contextlib.suppress(ValueError):
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

    def replay(self, after: int = 0) -> list[dict[str, Any]]:
        """What a client that attaches is sent, in order (F.5): the updates, and Handler's own
        lines (`lifecycle` events marked `shown`)."""
        if not self.path.exists():
            return []
        return [
            e
            for e in self._read()
            if e["seq"] > after and (e.get("kind") == "update" or e.get("shown"))
        ]

    def refused(self, host: str, at_least: int = 0) -> bool:
        """Whether `host` had a card in this session; with `at_least` 1, one whose request was
        refused (not only held, F.9)."""
        return any(
            e.get("event") == "host blocked" and e.get("host") == host and e["count"] >= at_least
            for e in self.replay()
        )

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
        self.remote = False  # reachable through the remote connector (remote design)
        self.agent_lock = asyncio.Lock()
        self.ids = itertools.count(1)
        self.own: dict[str, asyncio.Future[Message]] = {}  # the daemon's own requests
        self.forwarded: dict[str, Forwarded] = {}  # our id → the client's request
        self.pending: dict[Any, Message] = {}  # agent→client requests awaiting an answer
        self.prompt_id: str | None = None  # the turn in progress (our id of its session/prompt)
        self.turn_started_at: datetime | None = None
        self.stop_reason: str | None = None  # why the daemon stopped it, if it did
        self.turn_error: str | None = None  # why the daemon's last turn failed, if it did
        self.stop_how: StopHow = "exited"  # how, for the log (F.5)
        self.replaying = False  # updates are the agent's replay of history we have: not relayed
        self.translate = False  # the agent's session id is not the clients': translated (F.6)
        self.idle: asyncio.TimerHandle | None = None
        self.tasks: list[asyncio.Task[None]] = []
        self.stderr: asyncio.Task[None] | None = None  # its sandbox's logs, read
        self.launcher_said: str | None = None  # the last line of its sandbox's launcher's own
        self.cards: dict[str, tuple[int, int]] = {}  # this turn's refused hosts: (card, count)
        self.turn = "0"  # the word for the turn in progress or last (its `turn start` seq)
        self.watched: str | None = None  # what its filter is to be told (`watch`)
        self.told_filter: str | None = None  # what it was told last
        # what Handler put before the person's words in its first turn (its agent's
        # instructions, a run's or a step's whole request): no title of the agent's is made of it
        self.handlers_words: str | None = None
        self.watch_lock = asyncio.Lock()
        self.to_tell: list[str] = []  # Handler's messages for the agent's next turn (`tell`)
        # refused while nobody could answer (`unwatched`): host → count, told when a turn ends;
        # the hosts the inbox was told of already, never told again
        self.unseen: dict[str, int] = {}
        self.told_inbox: set[str] = set()
        # on a provider: its endpoint's host, and this turn's failures to connect to it, the last
        # one's error, whether Handler said so, and the wait before it does (`model_outcome`)
        self.model_host: str | None = None
        self.model_failures = 0
        self.model_error = ""
        self.model_said = False
        self.model_wait: asyncio.TimerHandle | None = None

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
                subject = interfaces.subject_folder(
                    settings.skills_dir, SessionSubject.model_validate(rec.subject)
                )
            except skills.SkillError as e:
                raise SessionError(str(e)) from None
        if (
            rec.plan_draft is not None
        ):  # its project, read-only (plan.builder-reads-the-project-only)
            folder = SessionPlanDraft.model_validate(rec.plan_draft).folder
            try:
                folder = compose.check_scope(folders.roots(settings), folder)
            except compose.ScopeError as e:
                raise SessionError(f"its project's folder: {e}") from None
            subject = HostFolder(source=folder, target=folder, writable=False)
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
        self.watch()

    async def start_sandbox(self, state_dir: Path, subject: HostFolder | None) -> None:
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
        session_files.record_mounts(self.store.mounts(rec.id), started.seen, now())
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
        self.model_host = started.model_host
        said = lambda line: setattr(self, "launcher_said", line)  # noqa: E731
        self.stderr = asyncio.create_task(read_stderr(process, rec.id, self.egress, said))  # ty: ignore[invalid-argument-type]
        self.tasks = [self.stderr]

    # ── blocked hosts (F.9) ─────────────────────────────────────────────

    def egress(self, event: dict[str, Any]) -> None:
        """A decision of its network filter (A.3): kept for the network panel; a host refused
        or held that the person neither allowed nor keeps blocked is asked about in the
        session."""
        self.store.registry.add_event(self.agent, self.record.id, event)
        host, decision = event.get("host"), event.get("decision")
        if host == self.model_host and decision in ("reached", "unreached"):
            self.model_outcome(decision == "reached", str(event.get("error") or ""))
        if decision not in ("denied", "held") or not isinstance(host, str):
            return
        if host in self.agent.allow or host in self.agent.blocked:
            return
        if decision == "held":
            self.host_held(host, int(event.get("wait") or 0))
        else:
            self.host_refused(host)

    def model_outcome(self, reached: bool, error: str) -> None:
        """A connection to the model's host reached it, or failed: once MODEL_FAILURES failed in
        a turn, or MODEL_SILENCE seconds after the first with none reached since, Handler says
        so in the session (rule session.an-unreachable-model-is-said)."""
        if reached:
            self.model_failures = 0
            self.cancel_model_wait()
            return
        if self.model_said:
            return
        self.model_failures += 1
        self.model_error = error or "connection failed"
        if self.model_failures >= MODEL_FAILURES:
            self.model_unreached()
        elif self.model_wait is None:
            loop = asyncio.get_running_loop()
            self.model_wait = loop.call_later(MODEL_SILENCE, self.model_unreached)

    def model_unreached(self) -> None:
        """`model unreached {host, error, provider, local}`: its line (F.9), once per turn; a
        model on this computer (`local`) may be listening on its loopback only."""
        self.cancel_model_wait()
        if self.model_said or self.model_host is None:
            return
        self.model_said = True
        local = self.model_host.startswith(f"{CONTAINER_HOST}:")
        host, provider = self.model_host, self.runs.provider
        self.say(
            "model unreached", host=host, error=self.model_error, provider=provider, local=local
        )

    def cancel_model_wait(self) -> None:
        if self.model_wait is not None:
            self.model_wait.cancel()
            self.model_wait = None

    def host_held(self, host: str, wait: int) -> None:
        """Its request waits for the answer (`held`): the card says until when (`until`), so a
        client counts it down; the request's decision follows (rule
        session.a-held-request-is-counted-down)."""
        card, count = self.cards.get(host, (self.log.seq + 1, 0))
        self.cards[host] = (card, count)
        until = (now() + timedelta(seconds=wait)).isoformat()
        self.say("host blocked", host=host, count=count, card=card, until=until)

    def host_refused(self, host: str) -> None:
        """One card per host per turn (`host blocked`, its `card` the seq of its first line):
        each repeat raises its count (rule session.a-refused-host-is-asked-once-per-turn)."""
        card, count = self.cards.get(host, (self.log.seq + 1, 0))
        self.cards[host] = (card, count + 1)
        self.say("host blocked", host=host, count=count + 1, card=card)
        if self.unwatched and host not in self.told_inbox:
            self.unseen[host] = self.unseen.get(host, 0) + 1

    @property
    def unwatched(self) -> bool:
        """A session (not a run: its own result says, D.27, I.3) nobody who can answer a card
        watches: no client but the phone's attached."""
        return self.record.interface is None and not any(c.kind != "remote" for c in self.clients)

    async def tell_inbox(self) -> None:
        """After its turn ended (and its filter's last decisions came): the hosts refused while
        nobody could answer, still neither allowed nor kept blocked, in one inbox message
        (`refusal_listeners`), each host once per session (rule
        session.hosts-refused-while-away-go-to-the-inbox)."""
        await asyncio.sleep(EGRESS_LAG)
        unseen, self.unseen = self.unseen, {}
        hosts = [
            RefusedHost(host=h, count=n)
            for h, n in unseen.items()
            if h not in self.agent.allow and h not in self.agent.blocked
        ]
        if hosts:
            self.told_inbox |= {h.host for h in hosts}
            for listener in self.store.refusal_listeners:
                listener(self.record, self.agent, hosts)

    async def decide_host(self, client: Attachment, m: Message, params: Message) -> None:
        """`_handler/decide_host {host, decision}`: a card's answer, saved to the agent and
        applied to its running sandboxes (rule session.a-card-s-answer-is-saved-and-applied)."""
        host, decision = params.get("host"), params.get("decision")
        if decision not in ("allowed", "kept blocked") or not isinstance(host, str):
            client.put(error(m["id"], -32602, "decision: allowed or kept blocked"))
            return
        if not self.log.refused(host):
            code = SessionErrorCode.NOT_REFUSED_HERE
            client.put(error(m["id"], code, f"{host} was not blocked in this session"))
            return
        refused = self.refused(host)  # before this answer: the agent got a refusal
        self.store.registry.decide_host(self.agent, host, keep_blocked=decision == "kept blocked")
        failures = await apply_network(self.agent)
        self.decided(host, decision, tell=refused and not failures)
        if failures:
            code = SessionErrorCode.NOT_APPLIED
            client.put(error(m["id"], code, f"saved, but not applied: {'; '.join(failures)}"))
            return
        client.put({"jsonrpc": "2.0", "id": m["id"], "result": {}})

    def decided(self, host: str, decision: str, *, tell: bool) -> None:
        """An answer saved and applied: `host decided` to every client, and, with `tell` (the
        agent got a refusal), told to the agent (not a run: it takes no prompt)."""
        queued = False
        if tell and self.record.interface is None:
            queued = self.tell(
                f"Handler: {host} is now allowed. Go on."
                if decision == "allowed"
                else f"Handler: the user keeps {host} blocked. Go on without it."
            )
        self.say(
            "host decided", host=host, decision=decision, **({"queued": True} if queued else {})
        )

    def refused(self, host: str) -> bool:
        """Whether the filter refused a request for `host` (not only held it): this turn's card
        counts, an earlier turn's card was one."""
        if host in self.cards:
            return self.cards[host][1] > 0
        return self.log.refused(host, at_least=1)

    def tell(self, text: str) -> bool:
        """Handler's message for the agent, sent as its next prompt, a turn of Handler's own
        (`send_told`): at once when no turn runs, else when it ends (`end_turn`). Whether it was
        queued (rule session.a-later-answer-is-told-to-the-agent)."""
        self.to_tell.append(text)
        if self.busy:
            return True
        self.store.spawn(self.send_told())
        return False

    async def send_told(self) -> None:
        """What Handler has to tell the agent, in one prompt, unless a turn began meanwhile (it
        waits for its end)."""
        if self.busy or not self.to_tell or self.record.state != "running":
            return
        text, self.to_tell = "\n".join(self.to_tell), []
        await self.first_prompt([{"type": "text", "text": text}], from_handler=True)

    def watch(self) -> None:
        """Tell its filter whether someone who can answer a card watches, and in which turn
        (A.4 `set-watched`): a client attached but the phone's (it cannot answer one yet). The
        latest is sent, one call at a time (rule network.a-watched-request-waits-for-the-answer)."""
        conn = self.agent.connections.get(self.record.id)
        if conn is None or conn.egress_base is None:  # no filter, or one for its secrets only
            return
        watched = self.turn if any(c.kind != "remote" for c in self.clients) else None
        if watched != self.watched:
            self.watched = watched
            self.store.spawn(self.tell_filter(conn.sandbox))

    async def tell_filter(self, sandbox: str) -> None:
        async with self.watch_lock:
            watched = self.watched
            if watched == self.told_filter:
                return
            if error := await set_watched(sandbox, watched):
                log.warning("[%s] its filter not told who watches: %s", self.record.id, error)
                return
            self.told_filter = watched

    def say(self, event: str, **fields: Any) -> None:
        """A line of Handler's own in the conversation (F.5): logged as a `lifecycle` event
        marked `shown`, sent to the attached clients as `_handler/line`, replayed to those that
        attach later in its place among the updates."""
        self.log.append("lifecycle", event=event, shown=True, **fields)
        line = {"seq": self.log.seq, "event": event} | fields
        self.broadcast(notification("_handler/line", **line))

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
            if not self.observe_update(update):
                return
            # user messages are logged from the prompts themselves (the agent may echo them)
            if not (self.busy and update.get("sessionUpdate") == "user_message_chunk"):
                self.log.append("update", update=update)
                m = with_seq(m, self.log.seq)  # where a client is, to attach again after it
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

    def observe_update(self, update: Message) -> bool:
        """Kept from the agent's update what later answers need; False when it is not passed on:
        a title the agent made of Handler's words, not the person's (Codex titles a session
        with the start of its first prompt), Handler's own title stays."""
        kind = update.get("sessionUpdate")
        if kind == "session_info_update" and "title" in update:
            if drawn_from(update["title"], self.handlers_words):
                return False
            self.record.title = update["title"]
        elif kind == "current_mode_update" and isinstance(self.modes, dict):
            self.modes = self.modes | {"currentModeId": update.get("currentModeId")}
        elif kind == "config_option_update":
            self.config_options = update.get("configOptions")
        return True

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
        if self.to_tell:
            self.store.spawn(self.send_told())
        if self.unseen:
            self.store.spawn(self.tell_inbox())

    async def ended(self) -> None:
        """The agent is gone (exit, stop, idle timeout): the session becomes `stopped`."""
        rec = self.record
        code = await self.link.wait() if self.link else None
        exited = f"agent exited ({code})"
        if self.stderr is not None:  # its filter's last decisions, its launcher's last words
            await asyncio.wait([self.stderr], timeout=STDERR_DRAIN)
        if code in SANDBOX_EXITS and self.stderr is not None:  # did not start, or was ended
            exited = self.launcher_said or exited
        for task in self.tasks:
            if task is not asyncio.current_task():
                task.cancel()
        self.cancel_idle()
        self.cancel_model_wait()
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
        addon_folders.sweep_soon(self.store.settings)  # a folder it mounted may be free
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
        self.watch()
        return client

    def remove(self, client: Attachment) -> None:
        """The client has gone (or was closed): the agent and its turn go on."""
        if client in self.clients:
            self.clients.remove(client)
            client.discard()
            self.broadcast_state()
            self.watch()
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
        if request and method in ("initialize", "session/load", "_handler/decide_host"):
            await self.answer(client, m, params)
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
                self.handlers_words = self.record.instructions
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

    async def answer(self, client: Attachment, m: Message, params: Message) -> None:
        """A request handlerd answers itself, never the agent: `initialize` (cached),
        `session/load` (the attach proper, F.4), `_handler/decide_host` (F.9)."""
        if m["method"] == "initialize":
            client.put({"jsonrpc": "2.0", "id": m["id"], "result": self.init_result})
        elif m["method"] == "session/load":
            self.load(client, m, params)
        else:
            await self.decide_host(client, m, params)

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

    async def first_prompt(
        self, blocks: list[Message], timeout: float | None = None, *, from_handler: bool = False
    ) -> None:
        """The request a session was created with, sent by the daemon itself as its first turn:
        the attached clients see it like another client's prompt (F.7). After `timeout` seconds
        the turn is cancelled (and ends as `timed_out`). `from_handler`: a message of Handler's
        own (`tell`), shown as Handler's line, not as the person's."""
        rid = f"handler-d-{next(self.ids)}"
        future: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
        self.own[rid] = future
        self.begin_turn(blocks, None, from_handler=from_handler)
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
        error = response.get("error")
        self.turn_error = str(error.get("message") or error) if isinstance(error, dict) else None
        self.end_turn(stop)
        self.broadcast(notification("_handler/turn_ended", stopReason=stop))
        self.broadcast_state()

    async def cancel_turn(self) -> None:
        """session/cancel for the turn in progress, whoever started it."""
        if self.busy:
            params = {"sessionId": self.record.acp_session_id}
            await self.execute({"jsonrpc": "2.0", "method": "session/cancel", "params": params})

    def begin_turn(
        self, prompt: list[Any], by: Attachment | None, *, from_handler: bool = False
    ) -> None:
        self.cancel_idle()
        self.cards = {}
        self.model_failures, self.model_said = 0, False
        self.cancel_model_wait()
        if from_handler:  # Handler's own message: its line (F.5), not the person's
            self.say("told agent", text="\n".join(b.get("text", "") for b in prompt))
            prompt = []
        for block in prompt:
            update = {"sessionUpdate": "user_message_chunk", "content": block}
            self.log.append("update", update=update)
            params = {"sessionId": self.record.acp_session_id, "update": update}
            self.broadcast(
                notification("session/update", **params, _meta={"handler.dev/seq": self.log.seq}),
                by,
            )
        self.log.append("turn", phase="start")
        self.turn = str(self.log.seq)
        self.touch()
        self.prompt_id = "starting"  # busy from now on; set to the forwarded id right after
        self.turn_started_at = now()
        self.broadcast_state()
        self.watch()

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
        for event in self.log.replay(after if isinstance(after, int) else 0):
            client.put(replayed(self.record.acp_session_id, event))
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


def drawn_from(title: Any, words: str | None) -> bool:
    """Whether an agent's title is the start of `words` (cut, an ellipsis after it)."""
    if not words or not isinstance(title, str):
        return False
    start = " ".join(title.rstrip(".… \n").split())
    return bool(start) and " ".join(words.split()).startswith(start)


def title_of(prompt: str) -> str:
    line = next((x.strip() for x in prompt.splitlines() if x.strip()), "")
    return line if len(line) <= TITLE_LENGTH else line[: TITLE_LENGTH - 1].rstrip() + "…"


def notification(method: str, **params: Any) -> Message:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def replayed(session_id: str | None, event: dict[str, Any]) -> Message:
    """A logged event as a client that attaches gets it (F.5): an update as `session/update`
    with its seq, a line of Handler's own as `_handler/line`."""
    seq = event["seq"]
    if event["kind"] == "update":
        params = {"sessionId": session_id, "update": event["update"]}
        return notification("session/update", **params, _meta={"handler.dev/seq": seq})
    fields = {k: v for k, v in event.items() if k not in ("seq", "t", "kind", "shown")}
    return notification("_handler/line", seq=seq, **fields)


def with_seq(m: Message, seq: int) -> Message:
    """A logged update as clients get it: its `seq` in the log (F.5), the agent's own `_meta`
    kept."""
    params = m.get("params") or {}
    meta = params.get("_meta")
    meta = meta if isinstance(meta, dict) else {}
    return m | {"params": params | {"_meta": meta | {"handler.dev/seq": seq}}}


@dataclass(frozen=True)
class PlanTurn:
    """A plan's step, as a session starts it (D.27): which step of which plan, its title, its own
    interface (the step's result, its time limit)."""

    plan: SessionPlan
    title: str
    interface: AgentInterface


@dataclass(frozen=True)
class DraftWork:
    """A plan builder's session, as it starts (D.27): the draft it writes, its folder (the
    session's), and its brief (after its agent's instructions: the project, the draft, the
    runners)."""

    draft: SessionPlanDraft
    folder: Path
    brief: str


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
        # told of the hosts refused in a session's turn while nobody could answer (the inbox)
        self.refusal_listeners: list[
            Callable[[SessionRecord, AgentRecord, list[RefusedHost]], None]
        ] = []
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
            request=rec.request,
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
            plan=SessionPlan.model_validate(rec.plan) if rec.plan else None,
            plan_draft=SessionPlanDraft.model_validate(rec.plan_draft) if rec.plan_draft else None,
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

    def own_folder(self, rec: SessionRecord) -> Path:
        """Where a folderless agent's session works: its plan draft's (a plan builder's, D.27),
        else its own."""
        if rec.plan_draft is not None:
            draft = SessionPlanDraft.model_validate(rec.plan_draft)
            return launcher.plan_drafts_root(self.settings) / draft.id / "draft"
        return self.work_folder(rec.id)

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
        prompt: str | None = None,
        *,
        origin: SessionOrigin = "ui",
        run: SessionInput | None = None,
        subject: SessionSubject | None = None,
        from_skill: str | None = None,
        app_draft: tuple[SessionAppDraft, Path | None] | None = None,
        app: str | None = None,
        instructions: str | None = None,
        step: PlanTurn | None = None,
        plan_draft: DraftWork | None = None,
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
        agent's: the agent is not changed.
        `step`: a plan's step (origin "plan", D.27), its `prompt` composed by the plan: run
        unattended with the step's own interface (its result, its time limit), as a job's run;
        the agent is not changed.
        `plan_draft`: a plan builder's session (D.27): it works in the draft's folder, its
        project mounted read-only when it starts, told its brief after the agent's
        instructions."""
        sid = "s_" + pysecrets.token_hex(8)
        scope = agent.scope
        if plan_draft is not None:
            assert scope is None and app_draft is None and from_skill is None
            scope = str(plan_draft.folder)
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
        assert step is None or (origin == "plan" and prompt and run is None)
        told = agent.instructions if instructions is None else instructions
        if plan_draft is not None:
            told = "\n\n".join(t for t in (agent.instructions, plan_draft.brief) if t)
        # what its network means for it: the model alone has none (A.3, D.18)
        told = starting_instructions(told, "none" if agent.model_alone else agent.network)
        form = agent.interface if run is not None else None
        interface = form if form is not None and form.result is not None else None  # a job's run
        if step is not None:
            interface = step.interface
        title = step.title if step else title_of(prompt) if prompt else None
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
            title=title,
            origin=origin,
            app=app,
            plan=step.plan.model_dump(mode="json", by_alias=True) if step else None,
            interface=interface.model_dump(mode="json", by_alias=True) if interface else None,
            input=run.model_dump(mode="json", by_alias=True) if run is not None else None,
            subject=subject.model_dump(mode="json", by_alias=True) if subject else None,
            app_draft=app_draft[0].model_dump(mode="json", by_alias=True) if app_draft else None,
            plan_draft=plan_draft.draft.model_dump(mode="json", by_alias=True)
            if plan_draft
            else None,
            # they go with its request when it is sent, else with the first prompt
            instructions=None if run or step else told,
            # a request of the person's: sent when it starts, whenever that is (F.1)
            request=prompt if run is None and step is None else None,
        )
        self.records[rec.id] = rec
        self.save(rec)
        text = None
        if form is not None and run is not None:
            notes = self.subject_notes(subject)
            text = interfaces.request(told, form, run, subject, notes)
        elif step is not None:
            text = f"{told}\n\n{prompt}" if told else prompt
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
        self, session_id: str, prompt: Sequence[Message], timeout: float | None
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

    async def _go(self, session_id: str, prompt: Sequence[Message], timeout: float | None) -> None:
        with contextlib.suppress(SessionError):
            live = await self.ensure_running(session_id)
            if prompt:
                if live.record.input is not None or live.record.plan is not None:
                    live.handlers_words = prompt[0].get("text")  # a run's, a step's: all Handler's
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
                if live.turn_error:  # the agent's own words (a model it could not reach, say)
                    output = SessionOutput(valid=False, error=live.turn_error)
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

    async def answered(self, session_id: str, host: str, decision: str) -> None:
        """An answer given elsewhere (the inbox) about a host refused in that session, already
        saved and applied: the session says it, and its agent is told, the session started
        again if it stopped (rule session.a-later-answer-is-told-to-the-agent)."""
        try:
            live = await self.ensure_running(session_id)
        except SessionError as e:
            log.info("[%s] not told the answer about %s: %s", session_id, host, e)
            return
        live.decided(host, decision, tell=True)

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
        if (scope := agent.scope or str(self.own_folder(rec))) != rec.scope:
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
        if rec.request is not None:  # its first turn, now that it runs (F.1, F.3)
            text = f"{rec.instructions}\n\n{rec.request}" if rec.instructions else rec.request
            live.handlers_words = rec.instructions
            rec.request = rec.instructions = None
            self.save(rec)
            self.spawn(live.first_prompt([{"type": "text", "text": text}]))
        return live

    def changed(self) -> None:
        for listener in self.listeners:
            listener()

    def set_remote(self, session_id: str, enabled: bool) -> None:
        """Share a running session with paired devices, or stop sharing it
        (remote design §5). Off closes the remote attachments at once (4004)."""
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
