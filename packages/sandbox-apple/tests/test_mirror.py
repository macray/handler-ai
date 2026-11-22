"""The images mirror (mirror.py) with a registry of the test's: what it keeps and serves."""

import hashlib
import http.client
import io
import socket
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from handler_sandbox_apple import mirror
from handler_sandbox_apple.container import short_dir

LAYER = b"layer bytes"
GOOD = hashlib.sha256(LAYER).hexdigest()


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(body)
        self.status = 200
        self.headers = headers or {}

    def getheader(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)


class FakeUpstream(mirror.Upstream):
    """A registry answering every blob with LAYER, every manifest with the same document."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []

    def fetch(self, registry: str, name: str, kind: str, ref: str, accept: str) -> Any:
        self.asked.append((kind, ref))
        body = LAYER if kind == "blobs" else b'{"schemaVersion": 2}'
        headers = {"content-type": "application/vnd.oci.image.manifest.v1+json"}
        return FakeResponse(body, headers), FakeResponse(b"")


def get(path: Path, url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes, Any]:
    class Conn(http.client.HTTPConnection):
        def connect(self) -> None:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(str(path))

    conn = Conn("mirror")
    conn.request("GET", url, headers=headers or {})
    resp = conn.getresponse()
    return resp.status, resp.read(), resp


def serve(cache: Path, upstream: FakeUpstream, only: str = "") -> mirror.Served:
    m = mirror.Mirror(cache, upstream, only)
    return m.serve(short_dir() / f"test-mirror-{uuid.uuid4().hex[:8]}.sock")


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[mirror.Served, FakeUpstream, Path]]:
    upstream = FakeUpstream()
    s = serve(tmp_path / "cache", upstream)
    yield s, upstream, tmp_path / "cache"
    s.stop()


@pytest.mark.rule("cache.the-mirror-reaches-only-what-the-sandbox-may")
def test_a_blob_is_kept_once_checked_then_served_from_the_cache(served: Any) -> None:
    """If this fails: every sandbox downloads the same layer again."""
    s, upstream, cache = served
    for _ in range(2):
        status, body, _ = get(s.path, f"/v2/docker.io/library/alpine/blobs/sha256:{GOOD}")
        assert (status, body) == (200, LAYER)
    assert upstream.asked == [("blobs", f"sha256:{GOOD}")]  # once
    assert (cache / "blobs" / "sha256" / GOOD).read_bytes() == LAYER


@pytest.mark.rule("cache.the-mirror-reaches-only-what-the-sandbox-may")
def test_a_blob_not_matching_its_digest_is_not_kept(served: Any) -> None:
    """If this fails: a forged or broken layer is served to every agent of the project."""
    s, _, cache = served
    other = "0" * 64
    status, _, _ = get(s.path, f"/v2/quay.io/x/y/blobs/sha256:{other}")
    assert status != 200
    assert not (cache / "blobs" / "sha256" / other).exists()
    assert not [p for p in (cache / "blobs" / "sha256").iterdir() if p.name.startswith(".")]


@pytest.mark.rule("cache.the-mirror-reaches-only-what-the-sandbox-may")
def test_a_tag_is_always_asked_of_the_registry_a_digest_only_once(served: Any) -> None:
    """If this fails: an agent gets an old image for a tag that moved."""
    s, upstream, _ = served
    for _ in range(2):
        status, _, resp = get(s.path, "/v2/ghcr.io/o/i/manifests/latest")
        assert status == 200
    digest = resp.getheader("Docker-Content-Digest")
    assert get(s.path, f"/v2/ghcr.io/o/i/manifests/{digest}")[0] == 200
    assert upstream.asked == [("manifests", "latest")] * 2


@pytest.mark.rule("cache.the-mirror-reaches-only-what-the-sandbox-may")
def test_what_needs_credentials_or_is_not_mirrored_is_refused(served: Any) -> None:
    """A private image's pull (credentials) is the engine's own, to the registry; another
    registry is not mirrored."""
    s, upstream, _ = served
    auth = {"Authorization": "Bearer x"}
    assert get(s.path, "/v2/docker.io/me/secret/manifests/1", auth)[0] == 401
    assert get(s.path, "/v2/registry.example.com/x/manifests/1")[0] == 404
    assert upstream.asked == []


def test_docker_s_mirror_is_docker_hub_s(tmp_path: Path) -> None:
    """Docker's paths say no registry (its mirror is Docker Hub's alone)."""
    upstream = FakeUpstream()
    s = serve(tmp_path, upstream, only="docker.io")
    try:
        assert get(s.path, f"/v2/library/alpine/blobs/sha256:{GOOD}")[1] == LAYER
    finally:
        s.stop()
