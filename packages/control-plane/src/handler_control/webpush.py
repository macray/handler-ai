"""Web Push without content (RFC 8030, VAPID RFC 8292) — apps design §7.

handlerd signs with its own key (`<config>/vapid.json`, 0600): no account with any push service.
The push carries nothing; the phone's service worker shows "something new" and the text is
fetched through the E2E channel when it is opened, so the push service (Mozilla, Apple, Google:
the browser picks it) learns only "now".

Nothing is still sent encrypted (RFC 8291, aes128gcm: an empty plaintext to the subscription's
keys, the same size every time): Firefox for Android drops a push without a body, its decryption
requires one.
"""

import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from handler_contracts import WebPush

from .remote_crypto import b64, unb64

TTL = 24 * 3600  # how long the push service keeps it for a phone that is off
JWT_LIFETIME = 12 * 3600


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
        return b64(raw)

    def authorization(self, endpoint: str, contact: str, now: float | None = None) -> str:
        parts = urlsplit(endpoint)
        claims = {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int((now or time.time()) + JWT_LIFETIME),
            "sub": contact,
        }
        header = {"typ": "JWT", "alg": "ES256"}
        signing = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims).encode())}"
        der = self.key.sign(signing.encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        token = f"{signing}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
        return f"vapid t={token}, k={self.public_key}"


# The push services browsers subscribe with (Chrome, Android: Google; Firefox: Mozilla; Safari:
# Apple; Edge: Windows). handlerd POSTs to a device's endpoint whenever its person gets a message:
# any other address would let a paired device (a family member's too) have handlerd call one of
# your network's.
PUSH_HOSTS = frozenset(
    {"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"}
)
PUSH_DOMAINS = (".notify.windows.com",)


def valid_endpoint(endpoint: object) -> bool:
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        return False
    parts = urlsplit(endpoint)
    try:
        port = parts.port
    except ValueError:
        return False
    host = parts.hostname or ""
    return (
        parts.scheme == "https"
        and port is None
        and parts.username is None
        and (host in PUSH_HOSTS or host.endswith(PUSH_DOMAINS))
    )


def valid_keys(p256dh: str, auth: str) -> bool:
    """A subscription's keys: a P-256 point (uncompressed) and a 16-byte secret."""
    try:
        point, secret = unb64(p256dh), unb64(auth)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except ValueError:
        return False
    return len(point) == 65 and len(secret) == 16


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(hashes.SHA256(), length, salt, info).derive(ikm)


def encrypt(
    plaintext: bytes,
    p256dh: str,
    auth: str,
    sender: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
) -> bytes:
    """RFC 8291 (aes128gcm, one record) to the subscription's keys; `sender` and `salt` are
    fresh per push (given only by the RFC's test vector)."""
    ua_public = unb64(p256dh)
    sender = sender or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = sender.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = sender.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    )
    ikm = _hkdf(unb64(auth), shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    record = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)  # 0x02: the last record
    rs = 4096
    return salt + rs.to_bytes(4, "big") + bytes([len(as_public)]) + as_public + record


async def push(http: httpx.AsyncClient, vapid: Vapid, to: WebPush, contact: str) -> int:
    """One content-free push; the push service's status (201: accepted, 404/410: gone)."""
    r = await http.post(
        to.endpoint,
        headers={
            "TTL": str(TTL),
            "Urgency": "normal",
            "Authorization": vapid.authorization(to.endpoint, contact),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
        },
        content=encrypt(b"", to.keys.p256dh, to.keys.auth),
    )
    return r.status_code
