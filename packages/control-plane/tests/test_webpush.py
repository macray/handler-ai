"""Unit tests: content-free Web Push with VAPID (apps design §7), encrypted (RFC 8291)."""

import asyncio
import base64
import json
import os
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from handler_contracts import PushKeys, WebPush
from handler_control import webpush


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@pytest.mark.rule("push.content-free")
def test_key_is_kept_private(tmp_path: Path) -> None:
    v = webpush.Vapid(tmp_path / "vapid.json")
    assert (tmp_path / "vapid.json").stat().st_mode & 0o777 == 0o600
    assert webpush.Vapid(tmp_path / "vapid.json").public_key == v.public_key
    assert len(unb64(v.public_key)) == 65


@pytest.mark.rule("push.content-free")
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


def a_browser() -> tuple[ec.EllipticCurvePrivateKey, PushKeys]:
    """A browser's subscription keys, and its private key to read what it receives."""
    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return key, PushKeys(p256dh=b64(point), auth=b64(os.urandom(16)))


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def decrypt(body: bytes, key: ec.EllipticCurvePrivateKey, auth: str) -> bytes:
    """What the browser does with a push (RFC 8291 §3.4), written apart from webpush.encrypt."""
    salt, rs, idlen = body[:16], int.from_bytes(body[16:20]), body[20]
    sender, record = body[21 : 21 + idlen], body[21 + idlen :]
    assert rs == 4096 and len(record) <= rs
    ua_public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = key.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender)
    )

    def hkdf(salt: bytes, ikm: bytes, info: bytes, n: int) -> bytes:
        return HKDF(hashes.SHA256(), n, salt, info).derive(ikm)

    ikm = hkdf(unb64(auth), shared, b"WebPush: info\x00" + ua_public + sender, 32)
    cek = hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    padded = AESGCM(cek).decrypt(nonce, record, None)
    assert padded.endswith(b"\x02")  # the last (and only) record
    return padded[:-1]


def test_encryption_matches_the_rfc_test_vector() -> None:
    """RFC 8291 Appendix A: the same keys and salt give the same bytes as the RFC."""
    sender = ec.derive_private_key(
        int.from_bytes(unb64("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw")), ec.SECP256R1()
    )
    body = webpush.encrypt(
        b"When I grow up, I want to be a watermelon",
        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
        "BTBZMqHH6r4Tts7J_aSIgg",
        sender=sender,
        salt=unb64("DGv6ra1nlYgDCS1FRnbzlw"),
    )
    assert b64(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWA"
        "mS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxs"
        "j_Qulcy4a-fN"
    )


@pytest.mark.rule("push.content-free")
def test_push_sends_nothing_but_the_signal(tmp_path: Path) -> None:
    """If this fails: a push service reads what a push says, or Firefox for Android drops it
    (it needs a body to decrypt)."""
    v = webpush.Vapid(tmp_path / "vapid.json")
    key, keys = a_browser()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    async def run() -> int:
        to = WebPush(endpoint="https://push.example.org/p/abc", keys=keys)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await webpush.push(http, v, to, "mailto:x@y.z")

    assert asyncio.run(run()) == 201
    (request,) = seen
    assert request.headers["Content-Encoding"] == "aes128gcm"
    assert request.headers["TTL"] == str(webpush.TTL)
    assert request.headers["Authorization"].startswith("vapid t=")
    assert decrypt(request.content, key, keys.auth) == b""  # the browser reads nothing
    assert len(request.content) == 16 + 4 + 1 + 65 + 1 + 16  # always the same size


def test_keys() -> None:
    _, keys = a_browser()
    assert webpush.valid_keys(keys.p256dh, keys.auth)
    assert not webpush.valid_keys(keys.p256dh, b64(b"short"))
    assert not webpush.valid_keys(b64(b"\x04" + b"\x01" * 64), keys.auth)  # not on the curve
    assert not webpush.valid_keys("not base64 !", keys.auth)
    assert not webpush.valid_keys("é", keys.auth)


@pytest.mark.rule("push.only-to-a-browser-push-service")
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
