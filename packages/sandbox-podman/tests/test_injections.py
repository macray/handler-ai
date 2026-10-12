"""The proxy addon's injection helpers (A.3): `Basic` credentials, and the mask that turns a
secret value echoed in a streamed response back into its phantom."""

import base64

from handler_sandbox_podman.proxy import addon


def _basic(credentials: str) -> str:
    return "Basic " + base64.b64encode(credentials.encode()).decode()


def test_swap_basic() -> None:
    swapped = addon.swap_basic(_basic("user:PHANTOM1"), "PHANTOM1", "realval1")
    assert swapped == _basic("user:realval1")
    assert addon.swap_basic(_basic("user:other"), "PHANTOM1", "realval1") == _basic("user:other")
    assert addon.swap_basic("Bearer PHANTOM1", "PHANTOM1", "x") == "Bearer PHANTOM1"
    assert addon.swap_basic("Basic not-base64!", "PHANTOM1", "x") == "Basic not-base64!"


def _masked(chunks: list[bytes]) -> list[bytes]:
    masker = addon.Masker([(b"VALUE-123", b"PHANT-999")])
    return [masker(c) for c in [*chunks, b""]]


def test_masker_replaces_whole_values() -> None:
    assert b"".join(_masked([b"a VALUE-123 b"])) == b"a PHANT-999 b"


def test_masker_replaces_a_value_split_across_chunks() -> None:
    out = _masked([b"data: VAL", b"UE-1", b"23 end"])
    assert b"".join(out) == b"data: PHANT-999 end"
    assert out[0] == b"data: "  # only what could begin the value waits


def test_masker_holds_nothing_back_when_nothing_could_begin_a_value() -> None:
    out = _masked([b"event: one\n\n", b"event: two\n\n"])
    assert out == [b"event: one\n\n", b"event: two\n\n", b""]


def test_masker_flushes_a_partial_at_the_end() -> None:
    out = _masked([b"ends with VALUE-1"])
    assert out == [b"ends with ", b"VALUE-1"]
