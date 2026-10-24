"""Unit tests: content-free Web Push with VAPID (docs/dev/design/apps.md §7)."""

import asyncio
import base64
import json
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from handler_control import webpush


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def test_key_is_kept_private(tmp_path: Path) -> None:
    v = webpush.Vapid(tmp_path / "vapid.json")
    assert (tmp_path / "vapid.json").stat().st_mode & 0o777 == 0o600
    assert webpush.Vapid(tmp_path / "vapid.json").public_key == v.public_key
    assert len(unb64(v.public_key)) == 65


def test_signature_verifies(tmp_path: Path) -> None:
    v = webpush.Vapid(tmp_path / "vapid.json")
    header = v.authorization("https://push.example.org/p/abc", "mailto:me@example.org", now=1000)
    token = header.split("t=")[1].split(",")[0]
    assert header.endswith(f"k={v.public_key}")
    head, claims, sig = token.split(".")
    assert json.loads(unb64(claims)) == {
        "aud": "https://push.example.org",
        "exp": 1000 + webpush.JWT_LIFETIME,
        "sub": "mailto:me@example.org",
    }
    raw = unb64(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32]), int.from_bytes(raw[32:]))
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(v.public_key))
    public.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if not


def test_push_sends_nothing_but_the_signal(tmp_path: Path) -> None:
    v = webpush.Vapid(tmp_path / "vapid.json")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    async def run() -> int:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await webpush.push(http, v, "https://push.example.org/p/abc", "mailto:x@y.z")

    assert asyncio.run(run()) == 201
    (request,) = seen
    assert request.content == b""
    assert request.headers["TTL"] == str(webpush.TTL)
    assert request.headers["Authorization"].startswith("vapid t=")


def test_endpoints() -> None:
    """The browsers' push services only: handlerd posts to it, on a paired device's word."""
    assert webpush.valid_endpoint("https://updates.push.services.mozilla.com/wpush/v2/x")
    assert webpush.valid_endpoint("https://fcm.googleapis.com/fcm/send/x")
    assert webpush.valid_endpoint("https://web.push.apple.com/x")
    assert webpush.valid_endpoint("https://wns2-par02p.notify.windows.com/w/?token=x")
    for elsewhere in (
        "https://push.example.org/x",
        "https://192.168.1.1/x",
        "https://localhost/x",
        "https://fcm.googleapis.com.example.org/x",
        "https://fcm.googleapis.com:8443/x",
        "https://me@fcm.googleapis.com/x",
        "https://notify.windows.com.example.org/x",
    ):
        assert not webpush.valid_endpoint(elsewhere), elsewhere
    assert not webpush.valid_endpoint("http://fcm.googleapis.com/x")
    assert not webpush.valid_endpoint("https://" + "a" * 3000)
    assert not webpush.valid_endpoint(None)
