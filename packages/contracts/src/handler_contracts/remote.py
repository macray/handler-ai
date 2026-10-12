"""Contract D.7 — what a paired device and handler say inside the envelopes
(docs/dev/design/remote.md §4): on the control channel (`s: null`) and on an app's channel
(`app:<name>`, H.8). Sessions' own channels carry plain ACP (F.4) and are not modelled here.

Requests are JSON-RPC: each `…Params` model is a method's params, the model named next to it its
result. Notifications from handler carry the model named with them.
"""

from typing import Annotated

from pydantic import Field

from .common import Document
from .control import MAX_REQUEST, DeviceScope, InboxMessage, SessionOrigin

REMOTE_API_VERSION = "handler.remote/v1"

# ── what a device is shown ──────────────────────────────────────────────


class SharedSession(Document):
    """A running session shared with devices (F, D.7)."""

    id: str
    title: str | None = None
    label: str | None = None  # "project · agent" for an agent of a project
    project_id: str | None = None
    project: str | None = None
    agent: str | None = None  # the agent's name, for an agent of a project
    origin: SessionOrigin
    harness: str
    scope: str
    acp_session_id: str | None = None
    busy: bool
    pending_permissions: int


class RemoteAgent(Document):
    """An agent a device may start sessions with (its `remoteStart` is on, D.8)."""

    id: str
    name: str
    description: str | None = None
    default: bool  # its project's default agent


class RemoteProject(Document):
    project_id: str
    project: str
    agents: list[RemoteAgent]


class SharedApp(Document):
    """A deployed mini app shared with the device's person (H.8)."""

    name: str
    description: str | None = None
    version: str
    queued: list[str] = []  # "POST /api/checkin": routes taken later while handler is off (H.10)


# ── control channel (`s: null`) ─────────────────────────────────────────


class SessionList(Document):
    """`_handler/remote/list_sessions` → this; also the params of the notification
    `_handler/remote/sessions_changed` (the new list)."""

    sessions: list[SharedSession]


class AgentList(Document):
    """`_handler/remote/list_agents` → this (owner's devices only; empty otherwise)."""

    projects: list[RemoteProject]


class StartSessionParams(Document):
    """`_handler/remote/start_session` → StartedSession: a new session of a `remoteStart` agent,
    `prompt` sent as its first turn, shared with the devices once it runs."""

    agent_id: str
    prompt: Annotated[str, Field(max_length=MAX_REQUEST)] | None = None


class StartedSession(Document):
    session: str  # its id: the device attaches once it is listed


class SharedApps(Document):
    """The params of the notification `_handler/remote/apps_changed` (the device's person's)."""

    apps: list[SharedApp]


class AppList(SharedApps):
    """`_handler/remote/list_apps` → this: who the device is for, and the apps shared with them."""

    person: str
    scope: DeviceScope


class InboxList(Document):
    """`_handler/remote/inbox` → this: the inbox of the device's person (H.9, I.3)."""

    messages: list[InboxMessage]


class PushKey(Document):
    """`_handler/remote/push_key` → this: handler's VAPID public key (H.10)."""

    public_key: str


class PushSubscribeParams(Document):
    """`_handler/remote/push_subscribe` → PushSubscription. No endpoint: push off."""

    endpoint: str | None = None  # https


class PushSubscription(Document):
    subscribed: bool


class DetachParams(Document):
    """The notification `_handler/remote/detach`: the device leaves a session it is attached to."""

    s: str


class ClosedNotice(Document):
    """The params of the notification `_handler/remote/closed`: one of the device's attachments was
    closed, with a WebSocket-like close code (F.4)."""

    s: str
    code: int
    reason: str


# ── an app's channel (`app:<name>`, H.8) ────────────────────────────────


class AppUiParams(Document):
    """`_handler/app/ui` → AppUi. `have`: the version the device keeps, to get nothing new back."""

    have: str | None = None


class AppUi(Document):
    version: str  # "<version>#<deploy>"
    html: str | None = None  # the app's UI as one page; absent when `unchanged`
    unchanged: bool | None = None  # the device's copy is this version


class AppHttpParams(Document):
    """`_handler/app/http` → AppHttpAnswer: one call to the app's backend (/api/… only)."""

    method: str = "GET"
    path: str
    headers: dict[str, str] = {}
    body: str = ""  # base64


class AppHttpAnswer(Document):
    status: int
    headers: dict[str, str]
    body: str  # base64
