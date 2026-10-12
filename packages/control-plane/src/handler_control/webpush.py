"""Web Push without content (RFC 8030, VAPID RFC 8292) — docs/dev/design/miniapps.md §7.

handlerd signs with its own key (`<config>/vapid.json`, 0600): no account with any push service.
The push carries nothing; the phone's service worker shows "something new" and the text is
fetched through the E2E channel when it is opened, so the push service (Mozilla, Apple, Google:
the browser picks it) learns only "now".
"""

import base64
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

TTL = 24 * 3600  # how long the push service keeps it for a phone that is off
JWT_LIFETIME = 12 * 3600


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Vapid:
    def __init__(self, path: Path) -> None:
        try:
            pem = json.loads(path.read_text())["privateKey"].encode()
            key = serialization.load_pem_private_key(pem, password=None)
            assert isinstance(key, ec.EllipticCurvePrivateKey)
        except FileNotFoundError:
            key = ec.generate_private_key(ec.SECP256R1())
            pem = key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"privateKey": pem.decode()}, f)
        self.key = key

    @property
    def public_key(self) -> str:
        """The application server key a browser subscribes with (uncompressed point)."""
        raw = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return b64url(raw)

    def authorization(self, endpoint: str, contact: str, now: float | None = None) -> str:
        parts = urlsplit(endpoint)
        claims = {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int((now or time.time()) + JWT_LIFETIME),
            "sub": contact,
        }
        header = {"typ": "JWT", "alg": "ES256"}
        signing = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(claims).encode())}"
        der = self.key.sign(signing.encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        token = f"{signing}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
        return f"vapid t={token}, k={self.public_key}"


def valid_endpoint(endpoint: object) -> bool:
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        return False
    parts = urlsplit(endpoint)
    return parts.scheme == "https" and bool(parts.netloc)


async def push(http: httpx.AsyncClient, vapid: Vapid, endpoint: str, contact: str) -> int:
    """One content-free push; the push service's status (201: accepted, 404/410: gone)."""
    r = await http.post(
        endpoint,
        headers={
            "TTL": str(TTL),
            "Urgency": "normal",
            "Authorization": vapid.authorization(endpoint, contact),
            "Content-Length": "0",
        },
        content=b"",
    )
    return r.status_code
