"""Envelopes of the remote connector (docs/dev/design/remote.md §4): what a device and the host
exchange through the gateway, sealed with a key the gateway never has.

    K        32 random bytes per device, made at pairing, given to the device by QR code
    keys     HKDF-SHA256(K, salt "handler-remote/v1", info "down" | "up" | "gateway-auth")
             down: device → host, up: host → device (so an envelope cannot be sent back to its
             sender); gateway-auth: the device's gateway token (the gateway stores its hash)
    seal     AES-256-GCM, random 96-bit nonce,
             AAD "handler-remote/v1|<hostId>|<deviceId>|<down|up>|<envelope id>"
    wire     {id, nonce, ct}, base64url without padding; plaintext: JSON
             {expires: unix ms, frames: [{s: session id | null, m: JSON-RPC message}], acks?,
             rejected?}; `expires`: until when it may be taken (its reader takes it once, before)

The remote client implements the same in WebCrypto (packages/remote-client/src/lib/crypto.ts).
"""

import base64
import hashlib
import json
import os
import secrets
from typing import Any, Literal

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = "handler-remote/v1"
Direction = Literal["down", "up"]


class EnvelopeError(ValueError):
    """Not a valid envelope for this device and direction (forged, altered, or mis-routed)."""


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def derive(key: bytes, info: str) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=VERSION.encode(), info=info.encode())
    return hkdf.derive(key)


def new_device_key() -> bytes:
    return os.urandom(32)


def gateway_token(key: bytes) -> str:
    """The device's secret towards the gateway (it sends `<deviceId>.<token>`)."""
    return b64(derive(key, "gateway-auth"))


def gateway_token_hash(key: bytes) -> str:
    """What the gateway stores to check that token."""
    return hashlib.sha256(gateway_token(key).encode()).hexdigest()


def aad(host_id: str, device_id: str, direction: Direction, envelope_id: str) -> bytes:
    return f"{VERSION}|{host_id}|{device_id}|{direction}|{envelope_id}".encode()


def seal(
    key: bytes, host_id: str, device_id: str, direction: Direction, plaintext: dict[str, Any]
) -> dict[str, str]:
    envelope_id = b64(secrets.token_bytes(16))
    nonce = os.urandom(12)
    data = json.dumps(plaintext, separators=(",", ":")).encode()
    ct = AESGCM(derive(key, direction)).encrypt(
        nonce, data, aad(host_id, device_id, direction, envelope_id)
    )
    return {"id": envelope_id, "nonce": b64(nonce), "ct": b64(ct)}


def open_envelope(
    key: bytes, host_id: str, device_id: str, direction: Direction, envelope: dict[str, Any]
) -> dict[str, Any]:
    try:
        envelope_id, nonce, ct = envelope["id"], unb64(envelope["nonce"]), unb64(envelope["ct"])
        data = AESGCM(derive(key, direction)).decrypt(
            nonce, ct, aad(host_id, device_id, direction, envelope_id)
        )
        plaintext = json.loads(data)
    except Exception as e:  # InvalidTag, bad base64, bad JSON, missing field: all the same
        raise EnvelopeError(type(e).__name__) from None
    if not isinstance(plaintext, dict) or not isinstance(plaintext.get("expires"), int):
        raise EnvelopeError("no expiry")
    return plaintext


def pairing_fragment(gateway_url: str, host_id: str, device_id: str, key: bytes, name: str) -> str:
    """`pair=<base64url JSON>`, put after `#` so it never reaches a server."""
    payload = {"v": 1, "g": gateway_url, "h": host_id, "d": device_id, "k": b64(key), "n": name}
    return "pair=" + b64(json.dumps(payload, separators=(",", ":")).encode())
