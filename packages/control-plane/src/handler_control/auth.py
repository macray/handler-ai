"""Authentication of clients (invariant 5): a per-install token, and an Origin allow-list.

HTTP (contract D):      `Authorization: Bearer <token>`
WebSocket (contract C): subprotocol `bearer.<token>` next to `acp.v1` (browsers cannot set headers)
Browsers always send `Origin`; it must be allowed. Non-browser clients send none.
"""

import hmac
import os
import secrets
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
