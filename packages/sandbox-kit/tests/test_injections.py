"""The proxy addon's injection helpers: the phantom swapped for its value inside `Authorization:
Basic` credentials, and a value echoed in a streamed response turned back into its phantom.

Spec: contract A.3 "Network semantics" (Injections). The whole path, a request
through a real proxy, is tested in tests/sandbox/conformance/test_injection.py."""

import base64

import pytest

from handler_sandbox_kit.egress.proxy import addon


def basic(credentials: str, scheme: str = "Basic") -> str:
    return f"{scheme} " + base64.b64encode(credentials.encode()).decode()


# --- Basic credentials --------------------------------------------------------------------------


@pytest.mark.rule("secrets.the-sandbox-never-holds-a-secret")
@pytest.mark.parametrize(
    ("header", "swapped"),
    [
        pytest.param(basic("user:PHANTOM1"), basic("user:realval1"), id="as-password"),
        pytest.param(basic("PHANTOM1:x"), basic("realval1:x"), id="as-user"),
        pytest.param(
            basic("user:PHANTOM1", "basic"), basic("user:realval1", "basic"), id="scheme-case"
        ),
    ],
)
def test_the_phantom_is_swapped_inside_basic_credentials(header: str, swapped: str) -> None:
    """The phantom is replaced inside the base64 credentials, wherever it is in them.
    If this fails: a harness using Basic auth sends the phantom, and its host refuses it."""
    assert addon.swap_basic(header, "PHANTOM1", "realval1") == swapped


@pytest.mark.rule("secrets.the-sandbox-never-holds-a-secret")
@pytest.mark.parametrize(
    "header",
    [
        pytest.param(basic("user:other"), id="no-phantom-inside"),
        pytest.param("Bearer PHANTOM1", id="other-scheme"),
        pytest.param("Basic not-base64!", id="not-base64"),
    ],
)
def test_a_header_without_basic_credentials_holding_the_phantom_is_left_as_it_is(
    header: str,
) -> None:
    """Only Basic credentials holding the phantom are rewritten (other headers have their phantom
    replaced as text, elsewhere in the addon).
    If this fails: unrelated Authorization headers are altered or the proxy errors on them."""
    assert addon.swap_basic(header, "PHANTOM1", "realval1") == header


# --- Responses: values back into phantoms -------------------------------------------------------


def masked(chunks: list[bytes], pairs: list[tuple[bytes, bytes]] | None = None) -> list[bytes]:
    """What the process receives for each chunk, then for the end (b"")."""
    masker = addon.Masker(pairs or [(b"VALUE-123", b"PHANT-999")])
    return [masker(c) for c in [*chunks, b""]]


@pytest.mark.rule("secrets.responses-carry-the-phantom")
def test_a_value_in_a_response_becomes_its_phantom() -> None:
    """A server echoing the secret back gives the process the phantom, never the value.
    If this fails: the secret reaches the sandboxed process."""
    assert b"".join(masked([b"a VALUE-123 b"])) == b"a PHANT-999 b"


@pytest.mark.rule("secrets.responses-carry-the-phantom")
def test_a_value_split_across_chunks_becomes_its_phantom() -> None:
    """Streamed bodies cut anywhere, inside a value too.
    If this fails: the secret reaches the process whenever a chunk boundary falls in it."""
    out = masked([b"data: VAL", b"UE-1", b"23 end"])
    assert b"".join(out) == b"data: PHANT-999 end"
    assert out[0] == b"data: "  # only what could begin the value waits


@pytest.mark.rule("secrets.responses-carry-the-phantom")
def test_a_value_cut_just_before_its_last_byte_becomes_its_phantom() -> None:
    """The longest start of a value a chunk can end with is all of it but its last byte.
    If this fails: the secret reaches the process when a chunk ends one byte short of it."""
    assert b"".join(masked([b"VALUE-12", b"3"])) == b"PHANT-999"


@pytest.mark.rule("secrets.responses-carry-the-phantom")
def test_every_secret_s_value_is_masked() -> None:
    """A sandbox may have several injections: each value becomes its own phantom.
    If this fails: the second secret reaches the process."""
    pairs = [(b"VALUE-123", b"PHANT-999"), (b"OTHER-456", b"PHANT-888")]
    assert b"".join(masked([b"VALUE-123 OTHER-456"], pairs)) == b"PHANT-999 PHANT-888"


@pytest.mark.rule("secrets.responses-carry-the-phantom")
def test_a_chunk_is_passed_on_at_once_when_nothing_in_it_could_begin_a_value() -> None:
    """Streaming is not delayed: a chunk goes out whole unless its end could begin a value.
    If this fails: server-sent events (a model's answer) reach the harness one chunk late."""
    out = masked([b"event: one\n\n", b"event: two\n\n"])
    assert out == [b"event: one\n\n", b"event: two\n\n", b""]


@pytest.mark.rule("secrets.responses-carry-the-phantom")
def test_what_was_held_back_and_is_not_a_value_comes_out_unchanged() -> None:
    """A chunk ending like the start of a value waits; the next one shows it is not, and it goes
    out as it was.
    If this fails: responses are altered or lose bytes where a chunk ends like a secret."""
    out = masked([b"ends with VAL", b"LEY"])
    assert b"".join(out) == b"ends with VALLEY"


@pytest.mark.rule("secrets.responses-carry-the-phantom")
def test_the_end_of_the_response_releases_what_was_held_back() -> None:
    """At the end, a held start of a value that never completed is sent as it is.
    If this fails: responses lose their last bytes."""
    out = masked([b"ends with VALUE-1"])
    assert out == [b"ends with ", b"VALUE-1"]
