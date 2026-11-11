"""Apps from paired devices (H.8, apps design §5.2): the `app:<name>` channel
of the remote connector. The phone never talks to the app's origin: it gets the app's UI as one
self-contained HTML page, shows it in a sandboxed frame with no network, and carries its backend
calls here, sealed like everything else.

    _handler/app/ui  {have?}                          → {version, html} | {version, unchanged}
    _handler/app/http  {method, path, headers, body}  → {status, headers, body}  (base64 bodies)

The device's person must be one the app is shared with; the backend gets `X-HANDLER-Person:
<person>` exactly as for local use.
"""

import base64
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from handler_contracts import (
    API_PREFIX,
    PERSON_HEADER,
    START_HEADER,
    AppHttpAnswer,
    AppHttpParams,
    AppUi,
    AppUiParams,
    is_within,
)

from .apps import AppError, AppStore
from .files import describe

UI_BYTES = 2 * 1024 * 1024  # an assembled UI: it travels in one up envelope
REQUEST_BYTES = 128 * 1024  # a request body: a down envelope is 256 KiB at the gateway
RESPONSE_BYTES = 4 * 1024 * 1024
# headers carried each way (the rest is the browser's or handler's business)
REQUEST_HEADERS = frozenset(
    {"accept", "accept-language", "content-type", "if-match", "if-none-match", "idempotency-key"}
)
RESPONSE_HEADERS = frozenset(
    {"cache-control", "content-type", "etag", "last-modified", "location", "retry-after"}
)
METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})

NOT_SHARED = -32020
INVALID = -32602


class RemoteAppError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


# ── the UI as one page ──────────────────────────────────────────────────

_SCRIPT = re.compile(r"<script\b([^>]*?)\bsrc=[\"']([^\"']+)[\"']([^>]*)>\s*</script>", re.I)
_LINK = re.compile(r"<link\b[^>]*>", re.I)
_ATTR = re.compile(r"""\b([a-z-]+)\s*=\s*["']([^"']*)["']""", re.I)
_SRC = re.compile(r"""\b(src|href)=(["'])(/[^"']*|\./[^"']*)\2""", re.I)
_CSS_URL = re.compile(r"""url\((["']?)(/[^)"']+|\./[^)"']+)\1\)""")


def _file(root: str, ref: str) -> Path | None:
    """The UI file a reference names, if it is one (not a URL, inside the UI directory)."""
    if "://" in ref or ref.startswith(("data:", "//", "#")):
        return None
    rel = re.split(r"[?#]", ref, maxsplit=1)[0].lstrip("./")
    path = os.path.realpath(os.path.join(root, rel))
    return Path(path) if is_within(path, root) and os.path.isfile(path) else None


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _css(root: str, text: str) -> str:
    def inline(m: re.Match[str]) -> str:
        path = _file(root, m[2])
        return f"url({_data_uri(path)})" if path else m[0]

    return _CSS_URL.sub(inline, text).replace("</style", "<\\/style")


def assemble_ui(ui_dir: Path) -> str:
    """index.html with its scripts and stylesheets inlined and its other files as data: URIs.
    Made for the template's build (one script, one stylesheet, assets inlined): a page that loads
    more at run time (dynamic imports) does not work remotely."""
    root = os.path.realpath(ui_dir)
    html = (ui_dir / "index.html").read_text()

    def script(m: re.Match[str]) -> str:
        path = _file(root, m[2])
        if path is None:
            return ""  # an outside script could not load in the frame anyway
        attrs = dict((k.lower(), v) for k, v in _ATTR.findall(m[1] + m[3]))
        kind = ' type="module"' if attrs.get("type") == "module" else ""
        code = path.read_text().replace("</script", "<\\/script").replace("<!--", "<\\!--")
        return f"<script{kind}>{code}</script>"

    def link(m: re.Match[str]) -> str:
        attrs = dict((k.lower(), v) for k, v in _ATTR.findall(m[0]))
        path = _file(root, attrs.get("href", ""))
        rel = attrs.get("rel", "").lower()
        if path is None:
            return ""
        if rel == "stylesheet":
            return f"<style>{_css(root, path.read_text())}</style>"
        if "icon" in rel:
            return f'<link rel="icon" href="{_data_uri(path)}">'
        return ""  # modulepreload, manifest…: nothing to fetch in the frame

    html = _SCRIPT.sub(script, html)
    html = _LINK.sub(link, html)

    def attr(m: re.Match[str]) -> str:
        path = _file(root, m[3])
        return f"{m[1]}={m[2]}{_data_uri(path)}{m[2]}" if path else m[0]

    return _SRC.sub(attr, html)


# ── the channel ─────────────────────────────────────────────────────────


class AppChannel:
    def __init__(self, store: AppStore) -> None:
        self.store = store

    def check(self, name: str, person: str) -> None:
        record = self.store.records.get(name)
        if record is None or record.current is None or person not in record.persons:
            raise RemoteAppError(NOT_SHARED, f"{name} is not shared with you")

    async def handle(
        self, name: str, person: str, method: str, params: dict[str, Any]
    ) -> AppUi | AppHttpAnswer:
        self.check(name, person)
        try:
            if method == "_handler/app/ui":
                return self.ui(name, AppUiParams.model_validate(params).have)
            if method == "_handler/app/http":
                return await self.http(name, person, AppHttpParams.model_validate(params))
        except ValidationError as e:
            raise RemoteAppError(INVALID, describe(e)) from None
        raise RemoteAppError(-32601, f"unknown method {method}")

    def ui(self, name: str, have: str | None) -> AppUi:
        record = self.store.records[name]
        assert record.current is not None
        version = f"{record.current.version}#{record.current.seq}"
        if have == version:
            return AppUi(version=version, unchanged=True)
        try:
            manifest = self.store.manifest(name, record.current.seq)
            html = assemble_ui(self.store.version_dir(name, record.current.seq) / manifest.ui.dir)
        except (AppError, OSError, UnicodeDecodeError) as e:
            raise RemoteAppError(-32000, f"cannot read the app's UI: {e}") from None
        if len(html.encode()) > UI_BYTES:
            raise RemoteAppError(-32000, f"the UI is more than {UI_BYTES // 2**20} MiB")
        return AppUi(version=version, html=html)

    async def http(self, name: str, person: str, params: AppHttpParams) -> AppHttpAnswer:
        method = params.method.upper()
        if method not in METHODS:
            raise RemoteAppError(INVALID, f"method: one of {', '.join(sorted(METHODS))}")
        target = httpx.URL(params.path)
        if target.host or not (
            target.path == API_PREFIX.rstrip("/") or target.path.startswith(API_PREFIX)
        ):
            raise RemoteAppError(INVALID, f"only {API_PREFIX}… is reachable")
        try:
            body = base64.b64decode(params.body, validate=True)
        except ValueError:
            raise RemoteAppError(INVALID, "body: base64") from None
        if len(body) > REQUEST_BYTES:
            raise RemoteAppError(INVALID, f"body over {REQUEST_BYTES // 1024} KiB")
        headers = {k.lower(): v for k, v in params.headers.items() if k.lower() in REQUEST_HEADERS}
        headers[PERSON_HEADER] = person
        try:
            backend = await self.store.ensure_running(name)
        except AppError as e:
            return answer(503, {"content-type": "text/plain"}, f"{name} did not start: {e}")
        start = self.store.issue_start(name, person)  # H.11: the owner's, until it is answered
        if start is not None:
            headers[START_HEADER] = start
        try:
            async with backend.client.stream(
                method, target.path, params=target.query, headers=headers, content=body
            ) as r:
                data = b""
                async for chunk in r.aiter_bytes():
                    self.store.touch(name)
                    data += chunk
                    if len(data) > RESPONSE_BYTES:
                        return answer(502, {}, f"the answer is over {RESPONSE_BYTES // 2**20} MiB")
        except httpx.HTTPError as e:
            return answer(502, {"content-type": "text/plain"}, f"{name} did not answer: {e}")
        finally:
            self.store.end_start(start)
        kept = {k: v for k, v in r.headers.items() if k.lower() in RESPONSE_HEADERS}
        return answer(r.status_code, kept, data)


def answer(status: int, headers: dict[str, str], body: bytes | str) -> AppHttpAnswer:
    raw = body.encode() if isinstance(body, str) else body
    return AppHttpAnswer(status=status, headers=headers, body=base64.b64encode(raw).decode())
