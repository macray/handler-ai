"""The gateway's HTTP API (remote design §6) — two mailboxes per paired device, nothing
more.

    host   (Authorization: Bearer <hostId>.<secret>)
      GET    /v1/host/poll?after=<cursor>&wait=<s>   down envelopes of all its devices; marks them
                                                     fetched; records "host last seen"
      POST   /v1/host/up        {envelopes: [{dev, id, nonce, ct}]}
      GET    /v1/host/queue     → {envelopes: [{dev, id, nonce, ct}]}  what devices queued
      DELETE /v1/host/queue/{id}                     processed: forget it
      GET    /v1/host/devices   → {devices: [ids]}
      PUT    /v1/host/devices/{dev}  {tokenHash}     register (or re-key) a device
      DELETE /v1/host/devices/{dev}                  revoke it
    device (Authorization: Bearer <deviceId>.<token>)
      POST   /v1/device/down    {id, nonce, ct}      → 202 {id}
      POST   /v1/device/queue   {id, nonce, ct}      → 202 {id}: kept (on disk, 7 days) until the
                                                     host takes it, for when the host is off
      GET    /v1/device/poll?after=<cursor>&wait=<s> up envelopes, ids of its down envelopes the
                                                     host fetched since the last poll, hostSeen,
                                                     ids of its queued envelopes still waiting
    GET /v1/health; everything else: the remote client's static files (if configured).

Cursors are opaque (`<epoch>-<n>`): after a gateway restart, a reader starts over.
"""

import json
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .store import ConflictError, Mailbox, MailboxFullError, Queue, Registry

ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")  # envelope id (random, base64url)
NONCE = re.compile(r"^[A-Za-z0-9_-]{16}$")  # 96-bit AES-GCM nonce, base64url
B64URL = re.compile(r"^[A-Za-z0-9_-]+$")
DEVICE_ID = re.compile(r"^d_[0-9a-f]{16}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

MAX_WAIT = 25.0
DOWN_BODY = 256 * 1024  # one command envelope
UP_BODY = 8 * 1024 * 1024  # a batch of agent output
POLL_BYTES = 4 * 1024 * 1024  # per poll answer
FETCHED_KEPT = 1000  # ids the host fetched, per device, until it polls: the newest


@dataclass
class Limits:
    ttl: float = 600.0  # seconds an envelope waits for its reader
    down_count: int = 500  # per host
    down_bytes: int = 8 * 1024 * 1024
    up_count: int = 5000  # per device
    up_bytes: int = 32 * 1024 * 1024
    rate: float = 20.0  # requests per second per caller (burst: 3x)


class Bucket:
    def __init__(self, rate: float) -> None:
        self.rate, self.tokens, self.at = rate, rate * 3, time.monotonic()

    def take(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.rate * 3, self.tokens + (now - self.at) * self.rate)
        self.at = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


@dataclass
class State:
    registry: Registry
    limits: Limits
    epoch: str = field(default_factory=lambda: secrets.token_hex(4))
    down: dict[str, Mailbox] = field(default_factory=dict)  # host id → envelopes from devices
    up: dict[str, Mailbox] = field(default_factory=dict)  # device id → envelopes from its host
    fetched: dict[str, list[str]] = field(default_factory=dict)  # device id → ids, unreported
    host_seen: dict[str, float] = field(default_factory=dict)  # host id → unix time
    polling: dict[str, int] = field(default_factory=dict)  # host id → its open long polls
    buckets: dict[str, Bucket] = field(default_factory=dict)
    queue: Queue = field(default_factory=lambda: Queue(None))

    def down_box(self, host: str) -> Mailbox:
        lim = self.limits
        return self.down.setdefault(host, Mailbox(lim.down_count, lim.down_bytes, lim.ttl))

    def up_box(self, dev: str) -> Mailbox:
        lim = self.limits
        return self.up.setdefault(dev, Mailbox(lim.up_count, lim.up_bytes, lim.ttl))

    def cursor(self, raw: str | None) -> int:
        epoch, _, n = (raw or "").partition("-")
        return int(n) if epoch == self.epoch and n.isdigit() else 0

    def allow(self, caller: str) -> bool:
        return self.buckets.setdefault(caller, Bucket(self.limits.rate)).take()


def problem(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"title": detail, "status": status}, status_code=status)


def bearer(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    return value[7:].strip() if value.lower().startswith("bearer ") else None


async def body(request: Request, limit: int) -> Any:
    if int(request.headers.get("content-length") or 0) > limit:
        raise TooBigError()
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > limit:
            raise TooBigError()
    return json.loads(raw or b"null")


class TooBigError(ValueError):
    pass


def valid_envelope(env: Any) -> bool:
    return (
        isinstance(env, dict)
        and isinstance(env.get("id"), str)
        and bool(ID.match(env["id"]))
        and isinstance(env.get("nonce"), str)
        and bool(NONCE.match(env["nonce"]))
        and isinstance(env.get("ct"), str)
        and bool(B64URL.match(env["ct"]))
    )


def wait_param(request: Request) -> float:
    try:
        return max(0.0, min(MAX_WAIT, float(request.query_params.get("wait", MAX_WAIT))))
    except ValueError:
        return MAX_WAIT


def create_app(state: State, client_dir: Path | None = None) -> Starlette:
    def host_of(request: Request) -> str | Response:
        host = state.registry.host_for(bearer(request))
        if host is None:
            return problem(401, "unknown host token")
        if not state.allow(host):
            return problem(429, "slow down")
        return host

    def device_of(request: Request) -> tuple[str, str] | Response:
        found = state.registry.device_for(bearer(request))
        if found is None:
            return problem(401, "unknown device token")
        if not state.allow(found[0]):
            return problem(429, "slow down")
        return found

    async def health(_: Request) -> Response:
        return JSONResponse({"ok": True})

    async def host_poll(request: Request) -> Response:
        host = host_of(request)
        if isinstance(host, Response):
            return host
        state.host_seen[host] = time.time()
        box = state.down_box(host)
        state.polling[host] = state.polling.get(host, 0) + 1
        try:
            found = await box.wait_after(
                state.cursor(request.query_params.get("after")),
                wait_param(request),
                POLL_BYTES,
                done=lambda: bool(state.queue.waiting_any(host)),
            )
        finally:
            state.polling[host] -= 1
        state.host_seen[host] = time.time()
        for env in found:
            ids = state.fetched.setdefault(env.dev, [])
            ids.append(env.id)
            del ids[:-FETCHED_KEPT]  # a device that never polls: a hint only, the newest kept
        for dev in {env.dev for env in found}:
            state.up_box(dev).poke()  # its long poll answers with the fetched ids
        cursor = found[-1].cursor if found else state.cursor(request.query_params.get("after"))
        return JSONResponse(
            {
                "cursor": f"{state.epoch}-{cursor}",
                "envelopes": [e.to_json() for e in found],
                "queued": state.queue.waiting_any(host),
            }
        )

    async def host_up(request: Request) -> Response:
        host = host_of(request)
        if isinstance(host, Response):
            return host
        state.host_seen[host] = time.time()
        try:
            data = await body(request, UP_BODY)
        except (TooBigError, ValueError):
            return problem(413, "body too big or not JSON")
        envelopes = data.get("envelopes") if isinstance(data, dict) else None
        if not isinstance(envelopes, list) or not all(valid_envelope(e) for e in envelopes):
            return problem(400, "invalid envelopes")
        owned = set(state.registry.devices_of(host))
        if any(e.get("dev") not in owned for e in envelopes):
            return problem(404, "unknown device")
        for e in envelopes:
            state.up_box(e["dev"]).put(e["id"], e["nonce"], e["ct"], e["dev"], drop_oldest=True)
        return Response(status_code=204)

    async def host_devices(request: Request) -> Response:
        host = host_of(request)
        if isinstance(host, Response):
            return host
        return JSONResponse({"devices": state.registry.devices_of(host)})

    async def host_device(request: Request) -> Response:
        host = host_of(request)
        if isinstance(host, Response):
            return host
        dev = request.path_params["dev"]
        if not DEVICE_ID.match(dev):
            return problem(400, "invalid device id")
        if request.method == "DELETE":
            state.registry.delete_device(host, dev)
            state.up.pop(dev, None)
            state.fetched.pop(dev, None)
            return Response(status_code=204)
        try:
            data = await body(request, 4096)
        except (TooBigError, ValueError):
            return problem(400, "invalid body")
        token_hash = data.get("tokenHash") if isinstance(data, dict) else None
        if not isinstance(token_hash, str) or not HEX64.match(token_hash):
            return problem(400, "tokenHash: 64 hex characters")
        try:
            state.registry.put_device(host, dev, token_hash)
        except ConflictError:
            return problem(409, "device id taken")
        return Response(status_code=204)

    async def device_down(request: Request) -> Response:
        found = device_of(request)
        if isinstance(found, Response):
            return found
        dev, host = found
        try:
            env = await body(request, DOWN_BODY)
        except (TooBigError, ValueError):
            return problem(413, "body too big or not JSON")
        if not valid_envelope(env):
            return problem(400, "invalid envelope")
        try:
            state.down_box(host).put(env["id"], env["nonce"], env["ct"], dev, drop_oldest=False)
        except MailboxFullError:
            return problem(503, "the host is not fetching: try later")
        return JSONResponse({"id": env["id"]}, status_code=202)

    async def device_queue(request: Request) -> Response:
        found = device_of(request)
        if isinstance(found, Response):
            return found
        dev, host = found
        try:
            env = await body(request, DOWN_BODY)
        except (TooBigError, ValueError):
            return problem(413, "body too big or not JSON")
        if not valid_envelope(env):
            return problem(400, "invalid envelope")
        try:
            state.queue.put(host, dev, env["id"], env["nonce"], env["ct"])
        except MailboxFullError:
            return problem(503, "the queue is full")
        state.down_box(host).poke()  # a host waiting in a long poll takes it now
        return JSONResponse({"id": env["id"]}, status_code=202)

    async def host_queue(request: Request) -> Response:
        host = host_of(request)
        if isinstance(host, Response):
            return host
        return JSONResponse({"envelopes": state.queue.pending(host, POLL_BYTES)})

    async def host_queue_done(request: Request) -> Response:
        host = host_of(request)
        if isinstance(host, Response):
            return host
        if not state.queue.remove(host, request.path_params["id"]):
            return problem(404, "not queued")
        return Response(status_code=204)

    async def device_poll(request: Request) -> Response:
        found = device_of(request)
        if isinstance(found, Response):
            return found
        dev, host = found
        after = state.cursor(request.query_params.get("after"))
        envelopes = await state.up_box(dev).wait_after(
            after, wait_param(request), POLL_BYTES, done=lambda: bool(state.fetched.get(dev))
        )
        cursor = envelopes[-1].cursor if envelopes else after
        # a host waiting in a long poll is listening now
        seen = time.time() if state.polling.get(host) else state.host_seen.get(host)
        return JSONResponse(
            {
                "cursor": f"{state.epoch}-{cursor}",
                "envelopes": [e.to_json() for e in envelopes],
                "fetched": state.fetched.pop(dev, []),
                "hostSeen": int(seen * 1000) if seen else None,
                "queued": state.queue.waiting(host, dev),
            }
        )

    routes: list[Route | Mount] = [
        Route("/v1/health", health),
        Route("/v1/host/poll", host_poll),
        Route("/v1/host/up", host_up, methods=["POST"]),
        Route("/v1/host/queue", host_queue),
        Route("/v1/host/queue/{id}", host_queue_done, methods=["DELETE"]),
        Route("/v1/host/devices", host_devices),
        Route("/v1/host/devices/{dev}", host_device, methods=["PUT", "DELETE"]),
        Route("/v1/device/down", device_down, methods=["POST"]),
        Route("/v1/device/queue", device_queue, methods=["POST"]),
        Route("/v1/device/poll", device_poll),
    ]
    if client_dir is not None and (client_dir / "index.html").is_file():
        routes.append(Mount("/", StaticFiles(directory=client_dir, html=True)))
    return Starlette(routes=routes, middleware=[Middleware(SecurityHeaders)])


# frame-src 'self': an app's frame cannot be navigated out of the gateway (the client's policy
# governs it), so an app's page cannot carry data away in an address.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'none'"
)
# The frame an app runs in, on the phone (handler's apps design §5.2): loaded
# sandboxed (an opaque origin) by the client, it runs the app's inlined page and reaches nothing:
# no connection, no fetch, only postMessage to the client, which carries the app's calls. Its own
# `sandbox` makes it an opaque origin however it is opened (alone in a tab too): never the
# client's, which holds the device's keys.
APP_FRAME = "/appframe.html"
APP_FRAME_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; "
    "frame-ancestors 'self'; base-uri 'none'; form-action 'none'; "
    "sandbox allow-scripts allow-forms allow-modals"
)


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        frame = request.url.path == APP_FRAME
        response.headers["Content-Security-Policy"] = APP_FRAME_CSP if frame else CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response
