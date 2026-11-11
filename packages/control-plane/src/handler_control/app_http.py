"""Serving apps (H.4): each at its own origin, http://<name>.localhost:<port>/.

An app's code is written by an agent, so it never shares an origin with handler's web UI (which
holds the token) nor with another app. Browsers resolve *.localhost to the loopback address and
treat it as a secure context. Requests whose Host is not `<app>.localhost:<port>` go to handler (a
rebinding attack names another host, so it never reaches an app).

An app's draft opened (H.16) is served the same way at http://<name>--draft.localhost:<port>/,
from its own copies, each of its pages with a banner saying it is the draft.

On an app's origin:
    /_handler/login?code=…  redeems a one-time link (POST /v1/apps/{name}/open): sets the
                            app's cookie
    /api/…                  the backend, started if needed; `X-HANDLER-Person: owner`
    anything else           the built UI (index.html for unknown paths, so client-side routes work)
Everything except the login needs the app's cookie. Requests that change something must come from
the app's own pages: apps are same-site with each other (*.localhost), so SameSite alone does not
stop one app from posting to another.
"""

import html
import mimetypes
import os
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from handler_contracts import API_PREFIX, PERSON_HEADER, START_HEADER, is_within

from .apps import COOKIE_NAME, DRAFT, AppError, AppStore, Backend, read_manifest

HOST_RE = re.compile(
    r"^(?P<app>[a-z][a-z0-9-]{0,29}?)(?P<draft>--draft)?\.localhost:(?P<port>\d+)$"
)
LOGIN_PATH = "/_handler/login"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# RFC 9110 §7.6.1 and friends: never forwarded by a proxy.
HOP_BY_HOP = frozenset(
    {
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
        "trailer", "transfer-encoding", "upgrade", "host",
    }
)  # fmt: skip
COOKIE_MAX_AGE = 365 * 24 * 3600
# taken out of a request before the backend gets it: handlerd sets the person and the start
# token (H.4, H.11), and puts the cookies back without its own
HANDLER_HEADERS = ("cookie", PERSON_HEADER.lower(), START_HEADER.lower())

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",  # the UI talks to its own backend only: nothing leaves the machine
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "form-action 'self'",
    ]
)


def page(title: str, text: str, status: int, headers: dict[str, str] | None = None) -> Response:
    body = (
        f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
        f"<body style='font-family:sans-serif;margin:3em'><h1>{html.escape(title)}</h1>"
        f"<p>{html.escape(text)}</p>"
    )
    return HTMLResponse(body, status_code=status, headers=headers)


class AppOrigins:
    """ASGI middleware, outermost: app origins are served here, the rest goes to handler."""

    def __init__(self, app: ASGIApp, store: AppStore, port: int) -> None:
        self.app = app
        self.store = store
        self.port = port

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            host = dict(scope["headers"]).get(b"host", b"").decode("latin-1").lower()
            m = HOST_RE.match(host)
            if m and int(m["port"]) == self.port:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                request = Request(scope, receive)
                if m["draft"]:
                    response = await self.handle_draft(request, m["app"])
                else:
                    response = await self.handle(request, m["app"])
                response.headers["Content-Security-Policy"] = CSP  # the backend's too
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["Referrer-Policy"] = "no-referrer"
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

    async def handle(self, request: Request, name: str) -> Response:
        record = self.store.records.get(name)
        if record is None or record.current is None:
            return page("No such app", f"There is no deployed app named {name}.", 404)
        if request.url.path == LOGIN_PATH:
            return self.login(request, name)
        api = request.url.path == API_PREFIX.rstrip("/") or request.url.path.startswith(API_PREFIX)
        if denial := self.denial(request, name, api=api):
            return denial
        if api:
            return await self.proxy(request, name)
        if request.method not in ("GET", "HEAD"):
            return Response(status_code=405, headers={"Allow": "GET, HEAD"})
        return self.static(name, request.url.path)

    async def handle_draft(self, request: Request, name: str) -> Response:
        """An app's draft opened (H.16): its own origin, cookie and copies."""
        draft = name + DRAFT
        preview = self.store.previews.get(name)
        if preview is None:
            text = "It was used, thrown away or left idle: open it again from Handler."
            return page(f"The draft of {name} is closed", text, 404)
        if request.url.path == LOGIN_PATH:
            return self.login(request, draft)
        api = request.url.path == API_PREFIX.rstrip("/") or request.url.path.startswith(API_PREFIX)
        if denial := self.denial(request, draft, api=api):
            return denial
        if api:
            preview.backend.last_used = time.monotonic()
            return await self.forward(request, name, preview.backend, start=False)
        if request.method not in ("GET", "HEAD"):
            return Response(status_code=405, headers={"Allow": "GET, HEAD"})
        return self.draft_static(name, request.url.path)

    def draft_static(self, name: str, path: str) -> Response:
        root = self.store.app_dir(name + DRAFT) / "code"
        try:
            manifest = read_manifest(root)
        except AppError as e:
            return page("Draft unavailable", str(e), 500)
        return self.serve(root / manifest.ui.dir, path, banner=name)

    def denial(self, request: Request, name: str, *, api: bool) -> Response | None:
        if not self.store.cookie_matches(name, request.cookies.get(COOKIE_NAME)):
            text = f"Open it from handler: the Apps page, or `handler app open {name}`."
            return page(f"{name}: not signed in", text, 401)
        if api and not same_origin(request, self.store.origin(name)):
            return page("Refused", "This request does not come from the app itself.", 403)
        return None

    def login(self, request: Request, name: str) -> Response:
        if not self.store.redeem(name, request.query_params.get("code", "")):
            text = "This link was already used or has expired. Open the app from handler again."
            return page("Link expired", text, 403)
        # A page, not a redirect: when the link comes from another site (handler's web UI), a
        # redirect would still count as cross-site and the new SameSite=Strict cookie would
        # not be sent. The refresh is a navigation from the app's own origin.
        response = HTMLResponse(
            "<!doctype html><meta charset=utf-8><meta http-equiv=refresh content='0;url=/'>"
            f"<title>{html.escape(name)}</title>",
            headers={"Cache-Control": "no-store"},
        )
        response.set_cookie(
            COOKIE_NAME,
            self.store.cookie(name),
            max_age=COOKIE_MAX_AGE,
            path="/",
            httponly=True,
            samesite="strict",
        )
        return response

    def static(self, name: str, path: str) -> Response:
        record = self.store.records[name]
        assert record.current is not None
        try:
            manifest = self.store.manifest(name, record.current.seq)
        except AppError as e:
            return page("App unavailable", str(e), 500)
        return self.serve(self.store.version_dir(name, record.current.seq) / manifest.ui.dir, path)

    def serve(self, ui: Path, path: str, banner: str | None = None) -> Response:
        """A file of a built UI (index.html for a client-side route); `banner`: an opened
        draft's, each of its pages saying so first."""
        root = os.path.realpath(ui)
        wanted = os.path.realpath(os.path.join(root, path.lstrip("/")))
        if not is_within(wanted, root):
            return page("Not found", path, 404)
        if os.path.isdir(wanted):
            wanted = os.path.join(wanted, "index.html")
        if not os.path.isfile(wanted):
            if Path(path).suffix:  # a missing asset, not a client-side route
                return page("Not found", path, 404)
            wanted = os.path.join(root, "index.html")
        media_type = mimetypes.guess_type(wanted)[0] or "application/octet-stream"
        cache = "no-cache" if wanted.endswith(".html") else "max-age=300"
        if banner is not None and wanted.endswith(".html"):
            text = Path(wanted).read_text(errors="replace")
            return HTMLResponse(with_banner(text, banner), headers={"Cache-Control": "no-store"})
        return FileResponse(wanted, media_type=media_type, headers={"Cache-Control": cache})

    async def answered(self, r: httpx.Response, start: str | None) -> None:
        await r.aclose()
        self.store.end_start(start)

    async def proxy(self, request: Request, name: str) -> Response:
        try:
            backend = await self.store.ensure_running(name)
        except AppError as e:
            return page(f"{name} did not start", str(e), 503)
        return await self.forward(request, name, backend, start=True)

    async def forward(
        self, request: Request, name: str, backend: Backend, *, start: bool
    ) -> Response:
        """The request to the backend, as the owner (H.4); `start`: with a start token (H.11),
        never for an opened draft, which starts nothing."""
        headers = [
            (k, v)
            for k, v in request.headers.items()
            if k not in HOP_BY_HOP and k not in HANDLER_HEADERS
        ]
        if cookies := without_handler_cookie(request.headers.get("cookie", "")):
            headers.append(("cookie", cookies))
        # H.4: only the owner is local (apps design)
        headers.append((PERSON_HEADER, "owner"))
        token = self.store.issue_start(name, "owner") if start else None  # H.11: until answered
        if token is not None:
            headers.append((START_HEADER, token))
        upstream = backend.client.build_request(
            request.method,
            request.url.path,
            params=request.url.query,
            headers=headers,
            content=request.stream(),
        )
        try:
            r = await backend.client.send(upstream, stream=True)
        except httpx.HTTPError as e:
            self.store.end_start(token)
            return page(f"{name} did not answer", str(e) or type(e).__name__, 502)

        async def body() -> AsyncIterator[bytes]:
            async for chunk in r.aiter_raw():
                self.store.touch(name)  # a long answer (e.g. a stream) keeps the backend up
                yield chunk

        return StreamingResponse(
            body(),
            status_code=r.status_code,
            headers={k: v for k, v in r.headers.items() if k.lower() not in HOP_BY_HOP},
            background=BackgroundTask(self.answered, r, token),
        )


def same_origin(request: Request, origin: str) -> bool:
    """A request that may change something must come from the app's own pages. Reads too, when
    the browser says where they come from (Sec-Fetch-Site): another app's page gets nothing."""
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in ("same-origin", "none"):
        return False
    if request.method in SAFE_METHODS:
        return True
    return request.headers.get("origin") == origin


def without_handler_cookie(header: str) -> str:
    """The Cookie header minus handler's own cookie: the backend has no use for it."""
    parts = [p.strip() for p in header.split(";") if p.strip()]
    return "; ".join(p for p in parts if p.split("=", 1)[0].strip() != COOKIE_NAME)


BANNER = (
    '<div style="position:sticky;top:0;z-index:2147483647;padding:8px 14px;font:14px/1.4 '
    "system-ui,sans-serif;color:#5b3c00;background:repeating-linear-gradient(-45deg,#fdf4e3,"
    '#fdf4e3 12px,#fbecd0 12px,#fbecd0 24px);border-bottom:1px solid #f0d9a8" '
    "data-handler-draft><b>Draft of {name}, not the one you use.</b> What you do here changes "
    "copies: {name}'s data and your folders are untouched. Use it or throw it away in Handler, "
    "on {name}'s page.</div>"
)


def with_banner(page_html: str, name: str) -> str:
    """An opened draft's page, its banner first in its body (H.16)."""
    banner = BANNER.format(name=html.escape(name))
    m = re.search(r"<body[^>]*>", page_html, re.IGNORECASE)
    return page_html[: m.end()] + banner + page_html[m.end() :] if m else banner + page_html
