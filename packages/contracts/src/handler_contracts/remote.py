"""Contract D.7 — what a paired device and handler say inside the envelopes
(remote design §4): on the control channel (`s: null`) and on an app's channel
(`app:<name>`, H.8). Sessions' own channels carry plain ACP (F.4) and are not modelled here.

Requests are JSON-RPC: each `…Params` model is a method's params, the model named next to it its
result. Notifications from handler carry the model named with them.
"""

from typing import Annotated

from pydantic import Field

from .common import Document
from .control import (
    MAX_REQUEST,
    ActionOption,
    ActionRun,
    AssistantAnswer,
    AssistantRequest,
    DeviceScope,
    InboxMessage,
    SessionOrigin,
    SpeechRequest,
    Transcription,
)

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
    harness: str | None  # None: the model alone (D.18)
    scope: str
    acp_session_id: str | None = None
    busy: bool
    pending_permissions: int


class RemoteAgent(Document):
    """An agent a device may start sessions with (its `remoteStart` is on, D.8; or one you talk to
    in Chat)."""

    id: str
    name: str
    description: str | None = None
    default: bool  # its project's default agent; in Chat, the one you talked to last


class RemoteProject(Document):
    project_id: str
    project: str
    agents: list[RemoteAgent]


class SharedApp(Document):
    """A deployed app shared with the device's person (H.8)."""

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
    # who you talk to in Chat (D.1 `chat`), the one used last first (its `default`): no folder,
    # so started from the owner's devices without a `remoteStart` of their own, as Ask (D.24)
    chats: list[RemoteAgent] = []


class StartSessionParams(Document):
    """`_handler/remote/start_session` → StartedSession: a new session of a `remoteStart` agent or
    of one you talk to in Chat, `prompt` sent as its first turn, shared with the devices once it
    runs."""

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


class AskParams(AssistantRequest):
    """`_handler/remote/ask` → AskAnswer: Ask (D.24) from one of the owner's devices: the
    exchange so far, the person's words last, the device's time zone."""


class AskAnswer(AssistantAnswer):
    """What Ask did (D.24), as the web UI gets it."""


class AskOptions(Document):
    """`_handler/remote/ask_options` → this: the actions Ask can pick now (the owner's devices),
    and whether it can be said (D.25: a speech model chosen) and the answers read aloud."""

    actions: list[ActionOption]
    listens: bool = False  # `_handler/remote/transcribe` writes down a recording
    read_aloud_spoken: bool = True
    read_aloud_typed: bool = False


class TranscribeParams(SpeechRequest):
    """`_handler/remote/transcribe` → Transcription: a recording from one of the owner's devices,
    written down with the chosen speech model (D.25), never kept."""


class RemoteTranscription(Transcription):
    """What was heard in a device's recording (D.25)."""


class ActionRunParams(Document):
    """`_handler/remote/action_run` → RemoteActionRun: an agent's action read again (H.12)."""

    app: str
    action: str
    run_id: str


class RemoteActionRun(ActionRun):
    """An action, done or under way (H.12)."""


class PushKey(Document):
    """`_handler/remote/push_key` → this: handler's VAPID public key (H.10)."""

    public_key: str


class PushKeys(Document):
    """A browser's push subscription keys (RFC 8291), base64url as `PushSubscription.toJSON()`."""

    p256dh: str = Field(alias="p256dh")  # the browser's P-256 public key, uncompressed
    auth: str  # its 16-byte secret


class WebPush(Document):
    """A device's Web Push subscription: where handlerd posts, and the keys it encrypts to."""

    endpoint: str  # https, a browser push service's
    keys: PushKeys


class PushSubscribeParams(Document):
    """`_handler/remote/push_subscribe` → PushSubscription. No subscription: push off."""

    subscription: WebPush | None = None


class PushSubscription(Document):
    subscribed: bool


class PushTest(Document):
    """`_handler/remote/push_test` → this: one push sent now to the asking device (H.10), the
    same as a message's; `problem` says why its push service did not take it."""

    sent: bool
    problem: str | None = None


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
