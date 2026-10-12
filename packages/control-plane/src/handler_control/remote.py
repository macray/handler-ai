"""Remote connector (docs/dev/design/remote.md §5): paired devices reach shared sessions through a
gateway that handlerd polls — handlerd never listens to anything but loopback.

    config     <config>/remote.json          gateway URL + host token (0600)
    devices    <config>/remote-devices.json  paired devices and their keys (0600)
    replay     <state>/remote-replay.json    ids of the envelopes accepted in the last 10 min
    queued     <state>/remote-queue-replay.json  ids of the queued envelopes taken (8 days)
    push key   <config>/vapid.json           Web Push signing key (0600), made when first asked

    Connector  one loop for every device: long-polls the gateway while a gateway is set and
               at least one session is shared; opens each envelope (remote_crypto), refuses
               replays and envelopes older than 5 min, and hands the frames to the sessions.
    Link       one device: its attachments (one per session it has open), its outbox (frames
               batched ~250 ms per envelope), its lease (no envelope for 90 s: detached).

A device reaches only running sessions whose `remote` switch is on, and only with the methods of
ALLOWED (plus answers to permission requests). Everything goes through the session like any
client's traffic: the policy (C.4) applies.

A device belongs to a person (`owner`, or a family member) and has a scope: `all`, or `apps` for
mini apps only (no session, ever). Frames `s: "app:<name>"` reach a mini app shared with the
device's person (app_remote.py, H.8). handlerd polls while a session or an app is shared, or while
an agent may be started from a device (`remoteStart`: the owner's devices start sessions of it).

A5 (docs/dev/design/miniapps.md §5.3, §7): what a device queued at the gateway while the host was
off is taken when handlerd is back (only app calls to routes the app declares "queued", up to 7 days
old); what handler tells a person (its inbox: apps' notifications, automations' results) is pushed,
content-free, to the devices of that person (Web Push).
"""

import asyncio
import contextlib
import json
import logging
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from handler_contracts import (
    AcpCloseCode,
    AgentList,
    AppHttpParams,
    AppList,
    ClosedNotice,
    DetachParams,
    DeviceScope,
    InboxList,
    InboxMessage,
    PushKey,
    PushSubscribeParams,
    PushSubscription,
    RemoteDevice,
    RemoteLight,
    RemotePairing,
    RemoteStatus,
    SessionList,
    SharedApps,
    SharedSession,
    StartedSession,
    StartSessionParams,
)

from . import files, webpush
from . import remote_crypto as rc
from .app_remote import AppChannel, RemoteAppError
from .apps import AppError, AppStore
from .policy import is_request, is_response
from .projects import ProjectRegistry
from .sessions import (
    Attachment,
    LiveSession,
    SessionError,
    SessionStore,
    error,
    notification,
    now,
)
from .settings import Settings

log = logging.getLogger("handler.remote")

Message = dict[str, Any]

MAX_AGE = 300.0  # seconds: an older command is refused (the gateway held it back)
REPLAY_KEEP = 2 * MAX_AGE
QUEUE_MAX_AGE = 7 * 24 * 3600.0  # a queued call older than this is refused
QUEUE_KEEP = QUEUE_MAX_AGE + 24 * 3600.0
QUEUE_EVERY = 30.0  # seconds between two looks at the gateway's queue
PUSH_CONTACT = os.environ.get("HANDLER_PUSH_CONTACT", "mailto:handler@example.invalid")
LEASE = 90.0  # seconds without an envelope from a device: its attachments are closed
POLL_WAIT = 25
FLUSH_DELAY = 0.25
ENVELOPE_BYTES = 512 * 1024  # plaintext per up envelope (a single bigger frame goes alone)
OUTBOX_BYTES = 16 * 1024 * 1024  # a device's unsent output; beyond, it is detached (re-syncs)

ALLOWED = frozenset(
    {
        "initialize",
        "session/load",
        "session/prompt",
        "session/cancel",
        "session/set_mode",
        "session/set_config_option",
    }
)
APP_CHANNEL = "app:"
IDLE_CLOSE = 1001  # "going away": the lease ran out
NOT_SHARED = -32020
NOT_ATTACHED = -32021
NOT_ALLOWED = -32022


class RemoteError(RuntimeError):
    """A request the connector cannot do now (e.g. pairing without a gateway)."""


def write_private(path: Path, data: Any) -> None:
    files.write_private(path, json.dumps(data, indent=2))


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


@dataclass
class Device:
    id: str
    name: str
    key: bytes
    created_at: datetime
    last_seen_at: datetime | None = None
    person: str = "owner"
    scope: DeviceScope = "all"
    push_endpoint: str | None = None  # its Web Push subscription (A5)

    def to_json(self) -> Message:
        return {
            "id": self.id,
            "name": self.name,
            "person": self.person,
            "scope": self.scope,
            "pushEndpoint": self.push_endpoint,
            "key": rc.b64(self.key),
            "createdAt": self.created_at.isoformat(),
            "lastSeenAt": self.last_seen_at.isoformat() if self.last_seen_at else None,
        }

    @classmethod
    def from_json(cls, d: Message) -> "Device":
        seen = d.get("lastSeenAt")
        return cls(
            d["id"],
            d["name"],
            rc.unb64(d["key"]),
            datetime.fromisoformat(d["createdAt"]),
            datetime.fromisoformat(seen) if seen else None,
            d.get("person", "owner"),
            "apps" if d.get("scope") == "apps" else "all",
            d.get("pushEndpoint"),
        )


@dataclass
class Link:
    """One device's traffic."""

    device: Device
    attachments: dict[str, tuple[LiveSession, Attachment]] = field(default_factory=dict)
    frames: list[Message] = field(default_factory=list)
    size: int = 0
    acks: list[str] = field(default_factory=list)
    rejected: list[Message] = field(default_factory=list)
    last_seen: float = 0.0  # monotonic
    flushing: asyncio.Task[None] | None = None
    app_calls: set[asyncio.Task[None]] = field(default_factory=set)


class Connector:
    def __init__(
        self, settings: Settings, sessions: SessionStore, apps: AppStore | None = None
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.apps = apps
        self.projects: ProjectRegistry | None = None  # set by the app: names, remote agents
        self.app_channel = AppChannel(apps) if apps else None
        self.config_file = settings.config_dir / "remote.json"
        self.devices_file = settings.config_dir / "remote-devices.json"
        self.replay_file = settings.state_dir / "remote-replay.json"
        self.config: Message | None = read_json(self.config_file, None)
        self.devices = {
            d["id"]: Device.from_json(d)
            for d in read_json(self.devices_file, {}).get("devices", [])
        }
        cutoff = time.time() * 1000 - REPLAY_KEEP * 1000
        self.replay: dict[str, int] = {
            k: v for k, v in read_json(self.replay_file, {}).items() if v > cutoff
        }
        self.links: dict[str, Link] = {}
        self.light: RemoteLight = "off" if self.config is None else "idle"
        self.detail: str | None = None
        self.since = now()
        self.cursor = ""
        self.synced = False
        self.wake = asyncio.Event()
        self.tasks: list[asyncio.Task[None]] = []
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=POLL_WAIT + 15.0))
        sessions.listeners.append(self.sessions_changed)
        if apps is not None:
            apps.listeners.append(self.apps_changed)
            apps.inbox.listeners.append(self.on_message)
        self.queue_file = settings.state_dir / "remote-queue-replay.json"
        cutoff = time.time() * 1000 - QUEUE_KEEP * 1000
        self.queue_replay: dict[str, int] = {
            k: v for k, v in read_json(self.queue_file, {}).items() if v > cutoff
        }
        self.queue_checked = 0.0  # monotonic
        self._vapid: webpush.Vapid | None = None
        self.pushes: set[asyncio.Task[None]] = set()

    # ── lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        self.tasks = [asyncio.create_task(self.run()), asyncio.create_task(self.leases())]

    async def close(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.http.aclose()

    def restart(self) -> None:
        """The gateway changed: start polling over."""
        self.cursor, self.synced = "", False
        if self.tasks:
            self.tasks[0].cancel()
            self.tasks[0] = asyncio.create_task(self.run())

    @property
    def host_id(self) -> str | None:
        return self.config["hostToken"].split(".")[0] if self.config else None

    @property
    def base(self) -> str:
        assert self.config is not None
        return self.config["gatewayUrl"].rstrip("/")

    def headers(self) -> dict[str, str]:
        assert self.config is not None
        return {"Authorization": f"Bearer {self.config['hostToken']}"}

    def shared(self) -> list[LiveSession]:
        return [
            live
            for live in self.sessions.live.values()
            if live.remote and live.record.state == "running"
        ]

    def active(self) -> bool:
        """Something is shared, or an agent may be started from a device: handlerd polls."""
        agents = bool(self.projects and self.projects.remote_agents())
        return bool(self.shared()) or bool(self.apps and self.apps.remote_apps()) or agents

    def agents_changed(self) -> None:
        """An agent's `remoteStart` may have changed: poll (or stop polling)."""
        self.wake.set()

    def set_light(self, light: RemoteLight, detail: str | None = None) -> None:
        if light != self.light:
            self.since = now()
            log.info("remote: %s%s", light, f" ({detail})" if detail else "")
        self.light, self.detail = light, detail

    async def sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.wake.wait(), seconds)

    async def run(self) -> None:
        backoff = 1.0
        while True:
            self.wake.clear()
            if self.config is None:
                self.set_light("off")
                await self.wake.wait()
                continue
            if not self.active():
                self.set_light("idle")
                await self.wake.wait()
                continue
            try:
                if not self.synced:
                    await self.sync_devices()
                r = await self.poll()
                if r is None:
                    continue  # nothing shared any more
                if r.status_code == 401:
                    self.set_light("unauthorized", "the gateway refused the host token")
                    await self.sleep(60)
                    continue
                r.raise_for_status()
                data = r.json()
                self.set_light("ok")
                for envelope in data["envelopes"]:
                    await self.receive(envelope)
                self.cursor = data["cursor"]
                if data.get("queued") or time.monotonic() - self.queue_checked > QUEUE_EVERY:
                    await self.drain_queue()
                backoff = 1.0
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
                self.set_light("unreachable", describe(e))
                await self.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def poll(self) -> httpx.Response | None:
        """One long poll, given up when the last session stops being shared (the gateway keeps
        the envelopes: the cursor has not moved, the next poll gets them again)."""
        # not known to be reachable: a quick poll first, so the light turns green at once
        wait = POLL_WAIT if self.light == "ok" else 0
        poll = asyncio.create_task(
            self.http.get(
                f"{self.base}/v1/host/poll",
                params={"after": self.cursor, "wait": wait},
                headers=self.headers(),
            )
        )
        while True:
            woken = asyncio.create_task(self.wake.wait())
            done, _ = await asyncio.wait({poll, woken}, return_when=asyncio.FIRST_COMPLETED)
            woken.cancel()
            if poll in done:
                return poll.result()
            self.wake.clear()
            if not self.active():
                poll.cancel()
                with contextlib.suppress(asyncio.CancelledError, httpx.HTTPError):
                    await poll
                return None

    async def leases(self) -> None:
        while True:
            await asyncio.sleep(LEASE / 6)
            for link in self.links.values():
                if link.attachments and time.monotonic() - link.last_seen > LEASE:
                    log.info("remote: device %s went quiet: detached", link.device.id)
                    for s in list(link.attachments):
                        self.detach(link, s)
                        # it re-attaches when it wakes up (the notice waits at the gateway)
                        self.send(link, None, closed_notice(s, IDLE_CLOSE, "device idle"))

    def sessions_changed(self) -> None:
        """A session was shared, unshared or stopped: poll (or stop polling), and tell the
        devices that are around, with the new list (with nothing shared, handlerd stops polling: a
        device could not ask)."""
        self.wake.set()
        shared = wire(SessionList(sessions=[self.describe(live) for live in self.shared()]))
        for link in self.links.values():
            if time.monotonic() - link.last_seen < LEASE and link.device.scope == "all":
                self.send(link, None, notification("_handler/remote/sessions_changed", **shared))

    def apps_changed(self) -> None:
        """An app was shared, unshared, deployed or removed: each device around gets its list."""
        self.wake.set()
        for link in self.links.values():
            if time.monotonic() - link.last_seen < LEASE and self.apps is not None:
                apps = wire(SharedApps(apps=self.apps.remote_apps(link.device.person)))
                self.send(link, None, notification("_handler/remote/apps_changed", **apps))

    # ── gateway configuration and devices (D.7) ────────────────────────

    def set_gateway(self, url: str, host_token: str) -> None:
        self.config = {"gatewayUrl": url.rstrip("/"), "hostToken": host_token}
        write_private(self.config_file, self.config)
        self.set_light("idle")
        self.restart()

    def clear_gateway(self) -> None:
        self.config = None
        self.config_file.unlink(missing_ok=True)
        self.set_light("off")
        self.restart()

    def save_devices(self) -> None:
        write_private(self.devices_file, {"devices": [d.to_json() for d in self.devices.values()]})

    async def sync_devices(self) -> None:
        """The gateway knows exactly our devices (registered while it was unreachable, or
        revoked)."""
        r = await self.http.get(f"{self.base}/v1/host/devices", headers=self.headers())
        if r.status_code == 401:
            return  # the poll reports it
        r.raise_for_status()
        known = set(r.json()["devices"])
        for device in self.devices.values():
            if device.id not in known:
                await self.register(device)
        for device_id in known - set(self.devices):
            await self.http.delete(
                f"{self.base}/v1/host/devices/{device_id}", headers=self.headers()
            )
        self.synced = True

    async def register(self, device: Device) -> None:
        r = await self.http.put(
            f"{self.base}/v1/host/devices/{device.id}",
            json={"tokenHash": rc.gateway_token_hash(device.key)},
            headers=self.headers(),
        )
        r.raise_for_status()

    async def pair(
        self, name: str, person: str = "owner", scope: DeviceScope = "all"
    ) -> RemotePairing:
        if self.config is None:
            raise RemoteError("set the gateway first")
        if person != "owner" and scope == "all":
            raise RemoteError("only the owner's devices reach sessions: pair it for apps only")
        device = Device(
            "d_" + secrets.token_hex(8), name, rc.new_device_key(), now(), None, person, scope
        )
        self.devices[device.id] = device
        self.save_devices()
        try:
            await self.register(device)
        except httpx.HTTPError as e:  # registered on the next successful poll
            log.warning("remote: registering %s: %s", device.id, describe(e))
            self.synced = False
        assert self.host_id is not None
        fragment = rc.pairing_fragment(self.base, self.host_id, device.id, device.key, name)
        return RemotePairing(device=self.to_device(device), pairing_url=f"{self.base}/#{fragment}")

    async def revoke(self, device_id: str) -> bool:
        device = self.devices.pop(device_id, None)
        if device is None:
            return False
        self.save_devices()
        if (link := self.links.pop(device_id, None)) is not None:
            for s in list(link.attachments):
                self.detach(link, s)
            if link.flushing:
                link.flushing.cancel()
        if self.config is not None:
            try:
                r = await self.http.delete(
                    f"{self.base}/v1/host/devices/{device_id}", headers=self.headers()
                )
                r.raise_for_status()
            except httpx.HTTPError:
                self.synced = False  # removed on the next sync; we refuse it anyway
        return True

    def to_device(self, device: Device) -> RemoteDevice:
        link = self.links.get(device.id)
        return RemoteDevice(
            id=device.id,
            name=device.name,
            created_at=device.created_at,
            last_seen_at=device.last_seen_at,
            person=device.person,
            scope=device.scope,
            attached=sorted(link.attachments) if link else [],
        )

    def status(self) -> RemoteStatus:
        return RemoteStatus(
            gateway_url=self.config["gatewayUrl"] if self.config else None,
            host_id=self.host_id,
            light=self.light,
            detail=self.detail,
            since=self.since,
            shared_sessions=sorted(live.record.id for live in self.shared()),
            devices=[self.to_device(d) for d in self.devices.values()],
        )

    # ── down: device → sessions ────────────────────────────────────────

    def link(self, device: Device) -> Link:
        if (link := self.links.get(device.id)) is None:
            link = self.links[device.id] = Link(device)
        return link

    async def receive(self, envelope: Message) -> None:
        device = self.devices.get(str(envelope.get("dev")))
        if device is None or self.host_id is None:
            return  # revoked (or never ours)
        try:
            plain = rc.open_envelope(device.key, self.host_id, device.id, "down", envelope)
        except rc.EnvelopeError as e:
            log.warning("remote: dropped an envelope from %s: %s", device.id, e)
            return
        envelope_id = envelope["id"]
        if envelope_id in self.replay or envelope_id in self.queue_replay:
            log.warning("remote: dropped a replayed envelope from %s", device.id)
            return
        link = self.link(device)
        self.remember(envelope_id)
        if abs(time.time() * 1000 - plain["ts"]) > MAX_AGE * 1000:
            link.rejected.append({"id": envelope_id, "reason": "expired"})
            self.schedule_flush(link)
            return
        link.last_seen = time.monotonic()
        if device.last_seen_at is None or (now() - device.last_seen_at).total_seconds() > 60:
            device.last_seen_at = now()
            self.save_devices()
        link.acks.append(envelope_id)
        for frame in plain.get("frames") or []:
            if isinstance(frame, dict):
                await self.frame(link, frame)
        self.schedule_flush(link)

    def remember(self, envelope_id: str) -> None:
        cutoff = time.time() * 1000 - REPLAY_KEEP * 1000
        self.replay = {k: v for k, v in self.replay.items() if v > cutoff}
        self.replay[envelope_id] = int(time.time() * 1000)
        write_private(self.replay_file, self.replay)

    async def frame(self, link: Link, frame: Message) -> None:
        s, m = frame.get("s"), frame.get("m")
        if not isinstance(m, dict):
            return
        if s is None:
            self.control(link, m)
            return
        if not isinstance(s, str):
            return
        if s.startswith(APP_CHANNEL):
            if is_request(m):  # answered when the backend is done: the poll loop goes on
                task = asyncio.create_task(self.app_call(link, s, m))
                link.app_calls.add(task)
                task.add_done_callback(link.app_calls.discard)
        elif link.device.scope != "all":
            if is_request(m):
                self.send(link, s, error(m["id"], NOT_ALLOWED, "this device reaches apps only"))
        else:
            await self.session_frame(link, s, m)

    async def session_frame(self, link: Link, s: str, m: Message) -> None:
        live = self.sessions.live.get(s)
        held = link.attachments.get(s)
        if live is None or not live.remote or live.record.state != "running":
            if held is not None:
                self.detach(link, s)
            if is_request(m):
                self.send(link, s, error(m["id"], NOT_SHARED, "this session is not shared"))
            return
        method = m.get("method")
        if method == "initialize" and is_request(m):
            if held is not None:
                self.detach(link, s)
            held = self.attach(link, s, live)
        elif held is None or held[1].closed:
            if is_request(m):
                self.send(link, s, error(m["id"], NOT_ATTACHED, "not attached: initialize"))
            return
        elif not (is_response(m) or method in ALLOWED):
            if is_request(m):
                self.send(link, s, error(m["id"], NOT_ALLOWED, "not allowed remotely"))
            return
        await live.from_client(held[1], m)

    async def app_call(self, link: Link, s: str, m: Message) -> None:
        params = m.get("params") if isinstance(m.get("params"), dict) else {}
        try:
            if self.app_channel is None:
                raise RemoteAppError(NOT_SHARED, "no apps here")
            name = s[len(APP_CHANNEL) :]
            result = await self.app_channel.handle(
                name, link.device.person, str(m.get("method")), params or {}
            )
            self.send(link, s, {"jsonrpc": "2.0", "id": m["id"], "result": wire(result)})
        except RemoteAppError as e:
            self.send(link, s, error(m["id"], e.code, str(e)))
        except Exception as e:  # the device must get an answer
            log.exception("remote: app call on %s", s)
            self.send(link, s, error(m["id"], -32603, f"{type(e).__name__}: {e}"))

    def control(self, link: Link, m: Message) -> None:
        """The control channel (D.7): a request is answered with its handler's result, refused
        when the method is not one of them or its params do not fit its model."""
        method = str(m.get("method"))
        params = m.get("params") if isinstance(m.get("params"), dict) else {}
        if method == "_handler/remote/detach":
            with contextlib.suppress(ValidationError):
                s = DetachParams.model_validate(params).s
                if s in link.attachments:
                    self.detach(link, s)
            return
        if not is_request(m):  # _handler/remote/ping is a notification: the lease is renewed
            return
        handlers: dict[str, tuple[type[BaseModel] | None, Callable[..., BaseModel]]] = {
            "_handler/remote/list_sessions": (None, self.list_sessions),
            "_handler/remote/list_agents": (None, self.list_agents),
            "_handler/remote/start_session": (StartSessionParams, self.start_session),
            "_handler/remote/list_apps": (None, self.list_apps),
            "_handler/remote/inbox": (None, self.device_inbox),
            "_handler/remote/push_key": (None, self.push_key),
            "_handler/remote/push_subscribe": (PushSubscribeParams, self.push_subscribe),
        }
        if method not in handlers:
            self.send(link, None, error(m["id"], NOT_ALLOWED, "not allowed remotely"))
            return
        model, handler = handlers[method]
        try:
            args = [model.model_validate(params or {})] if model else []
            result = handler(link.device, *args)
        except ValidationError as e:
            self.send(link, None, error(m["id"], -32602, files.describe(e)))
            return
        except RemoteError as e:
            self.send(link, None, error(m["id"], -32602, str(e)))
            return
        self.send(link, None, {"jsonrpc": "2.0", "id": m["id"], "result": wire(result)})

    def list_sessions(self, device: Device) -> SessionList:
        shared = self.shared() if device.scope == "all" else []
        return SessionList(sessions=[self.describe(live) for live in shared])

    def list_agents(self, device: Device) -> AgentList:
        """The agents a device may start sessions with: those marked `remoteStart` (D.7)."""
        if device.scope != "all" or self.projects is None:
            return AgentList(projects=[])
        return AgentList(projects=self.projects.remote_agents())

    def start_session(self, device: Device, params: StartSessionParams) -> StartedSession:
        """A new session of a `remoteStart` agent, its request sent first, shared with the
        devices once it runs (so this one can attach)."""
        allowed = {a.id for p in self.list_agents(device).projects for a in p.agents}
        if params.agent_id not in allowed:
            raise RemoteError("agentId: not an agent you may start from a device")
        agent = self.sessions.registry.get(params.agent_id)
        assert agent is not None  # listed just above
        rec = self.sessions.create(
            agent, agent.runs_as(), prompt=params.prompt or None, origin="phone"
        )
        task = asyncio.get_running_loop().create_task(self.share_when_running(rec.id))
        self.pushes.add(task)
        task.add_done_callback(self.pushes.discard)
        log.info("remote: %s started session %s", device.id, rec.id)
        return StartedSession(session=rec.id)

    async def share_when_running(self, session_id: str) -> None:
        with contextlib.suppress(SessionError):
            await self.sessions.ensure_running(session_id)
            self.sessions.set_remote(session_id, True)

    def list_apps(self, device: Device) -> AppList:
        apps = self.apps.remote_apps(device.person) if self.apps else []
        return AppList(person=device.person, scope=device.scope, apps=apps)

    def device_inbox(self, device: Device) -> InboxList:
        found = self.apps.inbox.list(device.person) if self.apps else []
        return InboxList(messages=found)

    # ── Web Push (A5) ───────────────────────────────────────────────────

    @property
    def vapid(self) -> webpush.Vapid:
        if self._vapid is None:
            self._vapid = webpush.Vapid(self.settings.config_dir / "vapid.json")
        return self._vapid

    def push_key(self, _device: Device) -> PushKey:
        return PushKey(public_key=self.vapid.public_key)

    def push_subscribe(self, device: Device, params: PushSubscribeParams) -> PushSubscription:
        endpoint = params.endpoint
        if endpoint is not None and not webpush.valid_endpoint(endpoint):
            raise RemoteError("endpoint: an https URL")
        device.push_endpoint = endpoint  # None: unsubscribe
        self.save_devices()
        return PushSubscription(subscribed=endpoint is not None)

    def on_message(self, message: InboxMessage) -> None:
        for device in self.devices.values():
            if device.person == message.person and device.push_endpoint:
                self.push_to(device)

    def push_to(self, device: Device) -> None:
        task = asyncio.get_running_loop().create_task(self.push(device))
        self.pushes.add(task)
        task.add_done_callback(self.pushes.discard)

    async def push(self, device: Device) -> None:
        endpoint = device.push_endpoint
        if endpoint is None:
            return
        try:
            status = await webpush.push(self.http, self.vapid, endpoint, PUSH_CONTACT)
        except httpx.HTTPError as e:
            log.info("remote: push to %s: %s", device.id, describe(e))
            return
        if status in (404, 410):  # the subscription is gone (the phone unsubscribed)
            device.push_endpoint = None
            self.save_devices()
        elif status >= 400:
            log.info("remote: push to %s: HTTP %s", device.id, status)

    # ── queued calls (A5) ───────────────────────────────────────────────

    async def drain_queue(self) -> None:
        """Take what devices queued at the gateway while handlerd was off; each is deleted there
        once processed (or refused): taken at most once, even if handlerd stops halfway (ids are
        kept)."""
        self.queue_checked = time.monotonic()
        r = await self.http.get(f"{self.base}/v1/host/queue", headers=self.headers())
        if r.status_code == 404:
            return  # a gateway without a queue
        r.raise_for_status()
        for envelope in r.json().get("envelopes", []):
            await self.take_queued(envelope)
            await self.http.delete(
                f"{self.base}/v1/host/queue/{envelope.get('id')}", headers=self.headers()
            )

    async def take_queued(self, envelope: Message) -> None:
        device = self.devices.get(str(envelope.get("dev")))
        if device is None or self.host_id is None:
            return
        try:
            plain = rc.open_envelope(device.key, self.host_id, device.id, "down", envelope)
        except rc.EnvelopeError as e:
            log.warning("remote: dropped a queued envelope from %s: %s", device.id, e)
            return
        envelope_id = envelope["id"]
        if envelope_id in self.queue_replay or envelope_id in self.replay:
            return
        self.queue_replay[envelope_id] = int(time.time() * 1000)
        cutoff = time.time() * 1000 - QUEUE_KEEP * 1000
        self.queue_replay = {k: v for k, v in self.queue_replay.items() if v > cutoff}
        write_private(self.queue_file, self.queue_replay)
        link = self.link(device)
        if abs(time.time() * 1000 - plain["ts"]) > QUEUE_MAX_AGE * 1000:
            link.rejected.append({"id": envelope_id, "reason": "expired"})
            self.schedule_flush(link)
            return
        link.acks.append(envelope_id)
        for frame in plain.get("frames") or []:
            s, m = (frame.get("s"), frame.get("m")) if isinstance(frame, dict) else (None, None)
            if not (isinstance(s, str) and s.startswith(APP_CHANNEL) and isinstance(m, dict)):
                continue
            if not is_request(m):
                continue
            if not self.queueable(s[len(APP_CHANNEL) :], m):
                self.send(link, s, error(m["id"], NOT_ALLOWED, "not a queued route of this app"))
                continue
            await self.app_call(link, s, m)
        self.schedule_flush(link)
        if device.push_endpoint:
            self.push_to(device)

    def queueable(self, name: str, m: Message) -> bool:
        """Only `_handler/app/http` calls to a route the installed version declares queued."""
        if m.get("method") != "_handler/app/http" or self.apps is None:
            return False
        try:
            params = AppHttpParams.model_validate(m.get("params"))
        except ValidationError:
            return False
        record = self.apps.records.get(name)
        if record is None or record.current is None:
            return False
        try:
            manifest = self.apps.manifest(name, record.current.seq)
        except AppError:
            return False
        path = httpx.URL(params.path).path
        return f"{params.method.upper()} {path}" in manifest.queued_routes

    def describe(self, live: LiveSession) -> SharedSession:
        rec, agent = live.record, live.agent
        project = self.projects.get(agent.project_id or "") if self.projects else None
        return SharedSession(
            id=rec.id,
            title=rec.title,
            label=self.projects.label(agent) if self.projects else agent.name,
            project_id=project.id if project else None,
            project=project.name if project else None,
            agent=(agent.name or live.runs.harness) if project else None,
            origin=rec.origin,
            harness=rec.harness,
            scope=rec.scope,
            acp_session_id=rec.acp_session_id,
            busy=live.busy,
            pending_permissions=len(live.pending),
        )

    def attach(self, link: Link, s: str, live: LiveSession) -> tuple[LiveSession, Attachment]:
        async def send(text: str) -> None:
            self.send(link, s, json.loads(text))

        async def close(code: int, reason: str) -> None:
            self.send(link, None, closed_notice(s, code, reason))
            if link.attachments.get(s, (None, None))[1] is attachment:
                del link.attachments[s]
            live.remove(attachment)

        attachment = Attachment(send, close, kind="remote")
        live.add(attachment)
        link.attachments[s] = (live, attachment)
        return live, attachment

    def detach(self, link: Link, s: str) -> None:
        held = link.attachments.pop(s, None)
        if held is not None:
            held[0].remove(held[1])

    # ── up: sessions → device ──────────────────────────────────────────

    def send(self, link: Link, s: str | None, m: Message) -> None:
        frame = {"s": s, "m": m}
        link.frames.append(frame)
        link.size += len(json.dumps(frame))
        if link.size > OUTBOX_BYTES:  # the gateway is not taking it: drop, the device re-syncs
            log.warning("remote: device %s is too far behind: detached", link.device.id)
            closed = [
                {"s": None, "m": closed_notice(s_, AcpCloseCode.TOO_SLOW, "too slow")}
                for s_ in link.attachments
            ]
            for s_ in list(link.attachments):
                held = link.attachments.pop(s_)
                held[0].remove(held[1])
            link.frames, link.size = closed, 0
        self.schedule_flush(link)

    def schedule_flush(self, link: Link) -> None:
        if link.flushing is None or link.flushing.done():
            link.flushing = asyncio.create_task(self.flush(link))

    async def flush(self, link: Link) -> None:
        await asyncio.sleep(FLUSH_DELAY)
        while (link.frames or link.acks or link.rejected) and self.config is not None:
            frames, size = [], 0
            while link.frames and (not frames or size < ENVELOPE_BYTES):
                frame = link.frames.pop(0)
                frames.append(frame)
                size += len(json.dumps(frame))
            link.size = max(0, link.size - size)
            plain: Message = {"ts": int(time.time() * 1000), "frames": frames}
            if link.acks:
                plain["acks"], link.acks = link.acks, []
            if link.rejected:
                plain["rejected"], link.rejected = link.rejected, []
            assert self.host_id is not None
            envelope = rc.seal(link.device.key, self.host_id, link.device.id, "up", plain)
            try:
                r = await self.http.post(
                    f"{self.base}/v1/host/up",
                    json={"envelopes": [envelope | {"dev": link.device.id}]},
                    headers=self.headers(),
                )
                if r.status_code == 404:  # the gateway does not know the device (yet)
                    self.synced = False
                r.raise_for_status()
            except httpx.HTTPError as e:
                log.info("remote: sending to %s: %s", link.device.id, describe(e))
                link.frames[:0] = frames  # retried, re-sealed (new id and time)
                link.size += size
                link.acks[:0] = plain.get("acks", [])
                link.rejected[:0] = plain.get("rejected", [])
                await asyncio.sleep(2.0)


def closed_notice(s: str, code: int, reason: str) -> Message:
    """One of the device's attachments was closed (with a WebSocket-like close code, F.4)."""
    return notification(
        "_handler/remote/closed", **wire(ClosedNotice(s=s, code=code, reason=reason))
    )


def wire(model: BaseModel) -> Message:
    """A D.7 document as it travels in an envelope (as the Control API's: absent, not null)."""
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


def describe(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    return str(e) or type(e).__name__
