"""Envelopes (docs/dev/design/remote.md §4): sealed per direction, bound to host, device and
envelope id."""

import json
from pathlib import Path
from typing import Any

import pytest

from handler_control import remote_crypto as rc

VECTORS = json.loads(
    (Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "remote-vectors.json").read_text()
)
KEY = rc.unb64(VECTORS["key"])
HOST, DEV = VECTORS["hostId"], VECTORS["deviceId"]
PLAIN: dict[str, Any] = {"ts": 1, "frames": [{"s": "s_1", "m": {"jsonrpc": "2.0", "id": 1}}]}


def test_vectors() -> None:
    """The remote client (WebCrypto) is checked against the same file."""
    assert rc.derive(KEY, "down").hex() == VECTORS["derived"]["down"]
    assert rc.derive(KEY, "up").hex() == VECTORS["derived"]["up"]
    assert rc.gateway_token(KEY) == VECTORS["derived"]["gatewayToken"]
    for direction in ("down", "up"):
        case = VECTORS[direction]
        assert rc.open_envelope(KEY, HOST, DEV, direction, case["envelope"]) == case["plaintext"]


def test_round_trip() -> None:
    envelope = rc.seal(KEY, HOST, DEV, "up", PLAIN)
    assert set(envelope) == {"id", "nonce", "ct"}
    assert rc.open_envelope(KEY, HOST, DEV, "up", envelope) == PLAIN
    assert rc.seal(KEY, HOST, DEV, "up", PLAIN)["nonce"] != envelope["nonce"]


@pytest.mark.parametrize(
    ("key", "host", "dev", "direction", "change"),
    [
        (bytes(32), HOST, DEV, "down", None),  # another key
        (KEY, "h_ffffffffffffffff", DEV, "down", None),  # another host
        (KEY, HOST, "d_0000000000000000", "down", None),  # another device
        (KEY, HOST, DEV, "up", None),  # sent back to its sender
        (KEY, HOST, DEV, "down", "id"),  # the gateway relabels it
        (KEY, HOST, DEV, "down", "ct"),  # the gateway alters it
    ],
)
def test_anything_else_is_refused(
    key: bytes, host: str, dev: str, direction: rc.Direction, change: str | None
) -> None:
    envelope = rc.seal(KEY, HOST, DEV, "down", PLAIN)
    if change == "id":
        envelope["id"] = rc.b64(b"x" * 16)
    elif change == "ct":
        raw = bytearray(rc.unb64(envelope["ct"]))
        raw[0] ^= 1
        envelope["ct"] = rc.b64(bytes(raw))
    with pytest.raises(rc.EnvelopeError):
        rc.open_envelope(key, host, dev, direction, envelope)


def test_pairing_fragment_carries_what_the_device_needs() -> None:
    fragment = rc.pairing_fragment("https://gw.example", HOST, DEV, KEY, "phone")
    payload = json.loads(rc.unb64(fragment.removeprefix("pair=")))
    assert payload == {
        "v": 1,
        "g": "https://gw.example",
        "h": HOST,
        "d": DEV,
        "k": VECTORS["key"],
        "n": "phone",
    }
    # the gateway only ever gets the hash of a token derived from the key, never the key
    assert rc.gateway_token_hash(KEY) != rc.b64(KEY)
