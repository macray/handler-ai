"""Authentication of clients (invariant 5): a per-install token, and an Origin allow-list.

HTTP (contract D):      `Authorization: Bearer <token>`
WebSocket (contract C): subprotocol `bearer.<token>` next to `acp.v1` (browsers cannot set headers)
The web UI:             a cookie derived from the token (`UI_COOKIE`), set by a one-time link
                        (`handler ui`), accepted only from the UI's own pages
Browsers always send `Origin` on a WebSocket and on a cross-origin request; it must be allowed.
Non-browser clients send none.

The cookie follows the host name, not the port: a page of another port of 127.0.0.1 (a dev
server an agent runs) is "same site" for the browser and gets it sent; what refuses it is that
the request does not come from the UI's own origin (`from_own_pages`). A page whose name is made
to point at 127.0.0.1 (DNS rebinding) never gets it: its host name is another.
"""

import hashlib
import hmac
import os
import secrets
import time
from collections.abc import Mapping
from pathlib import Path

from handler_contracts import BEARER_SUBPROTOCOL_PREFIX


def load_or_create_token(path: Path) -> str:
    """Read the token, creating it (mode 0600) on first start."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        path.chmod(0o600)
        return path.read_text().strip()
    token = secrets.token_urlsafe(32)  # [A-Za-z0-9_-]: valid in a WebSocket subprotocol
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    return token


def token_matches(presented: str | None, token: str) -> bool:
    return presented is not None and hmac.compare_digest(presented.encode(), token.encode())


def bearer_from_header(value: str | None) -> str | None:
    if value and value.lower().startswith("bearer "):
        return value[7:].strip()
    return None


def bearer_from_subprotocols(protocols: list[str]) -> str | None:
    for p in protocols:
        if p.startswith(BEARER_SUBPROTOCOL_PREFIX):
            return p[len(BEARER_SUBPROTOCOL_PREFIX) :]
    return None


def origin_allowed(origin: str | None, allowed: frozenset[str]) -> bool:
    return origin is None or origin in allowed


UI_COOKIE = "handler-ui"
UI_COOKIE_MAX_AGE = 365 * 24 * 3600
UI_LINK_TTL = 120.0  # seconds a link of `handler ui` opens the web UI, once


def ui_cookie(token: str) -> str:
    """The web UI's cookie: derived from the token, so changing the token signs it out."""
    return hmac.new(token.encode(), b"handler-ui", hashlib.sha256).hexdigest()


def ui_cookie_matches(presented: str | None, token: str) -> bool:
    return presented is not None and hmac.compare_digest(
        presented.encode(), ui_cookie(token).encode()
    )


def from_own_pages(headers: Mapping[str, str], allowed: frozenset[str]) -> bool:
    """A browser request from the web UI's own pages: sent to one of handlerd's own addresses
    (the hosts of the allowed origins: not a rebinding page's name), and the browser says it
    comes from that origin (Sec-Fetch-Site) or names an allowed one (a WebSocket, a cross-origin
    request). Without both, a cookie is not taken: another page of the same site may have sent
    it."""
    if f"http://{headers.get('host', '')}" not in allowed:
        return False
    if headers.get("sec-fetch-site") == "same-origin":
        return True
    origin = headers.get("origin")
    return origin is not None and origin in allowed


class UiLinks:
    """One-time links opening the web UI: each sets its cookie once, within UI_LINK_TTL."""

    def __init__(self) -> None:
        self.codes: dict[str, float] = {}

    def new(self) -> str:
        now = time.monotonic()
        self.codes = {c: t for c, t in self.codes.items() if t > now}
        code = secrets.token_urlsafe(24)
        self.codes[code] = now + UI_LINK_TTL
        return code

    def redeem(self, code: str) -> bool:
        expires = self.codes.pop(code, None)
        return expires is not None and expires > time.monotonic()
