"""handlerd remembers an image it found, briefly (runtime.inspect): the pages listing images ask
for the same few within seconds, and podman answers slowly while it creates or removes
containers. These tests replace the runtime's `image` verbs by a dictionary of images."""

import subprocess
from datetime import UTC, datetime

import pytest

from handler_contracts import ImageInfo
from handler_control import runtime

REF = "localhost/handler-ai-vibe:latest"


class Images:
    """The runtime's images by reference, and the verbs asked of it."""

    def __init__(self) -> None:
        self.by_ref: dict[str, str] = {}  # reference → image id
        self.asked: list[str] = []

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.asked.append(" ".join(args))
        verb, ref = args[0], args[1]
        if verb == "inspect" and ref in self.by_ref:
            info = ImageInfo(id=self.by_ref[ref], created=datetime(2026, 11, 13, tzinfo=UTC))
            return subprocess.CompletedProcess(args, 0, info.model_dump_json(by_alias=True), "")
        if verb in ("tag", "remove"):
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 1, "", f"no image {ref}")

    def inspections(self) -> int:
        return sum(a.startswith("inspect") for a in self.asked)


def found_id() -> str | None:
    info = runtime.inspect(REF)
    return info.id if info else None


@pytest.fixture
def images(monkeypatch: pytest.MonkeyPatch) -> Images:
    found = Images()
    monkeypatch.setattr(runtime, "_image", found)
    monkeypatch.setattr(runtime, "_found", {})
    return found


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [1000.0]
    monkeypatch.setattr(runtime.time, "monotonic", lambda: now[0])
    return now


@pytest.mark.rule("runtime.an-image-found-is-remembered-briefly")
def test_an_image_found_is_not_asked_again_for_ten_seconds(
    images: Images, clock: list[float]
) -> None:
    """If this fails: every page listing images waits on podman again for each of them."""
    images.by_ref[REF] = "a" * 64
    assert found_id() == "a" * 64
    clock[0] += runtime.IMAGE_TTL - 0.1
    assert runtime.exists(REF)
    assert images.inspections() == 1


@pytest.mark.rule("runtime.an-image-found-is-remembered-briefly")
def test_an_image_replaced_outside_handler_is_seen_after_ten_seconds(
    images: Images, clock: list[float]
) -> None:
    """If this fails: a page shows an image removed or replaced by hand for as long as handlerd
    runs."""
    images.by_ref[REF] = "a" * 64
    runtime.inspect(REF)
    images.by_ref[REF] = "b" * 64  # `podman build -t` by hand
    clock[0] += runtime.IMAGE_TTL
    assert found_id() == "b" * 64
    del images.by_ref[REF]  # `podman rmi` by hand
    clock[0] += runtime.IMAGE_TTL
    assert runtime.inspect(REF) is None


@pytest.mark.rule("runtime.an-image-found-is-remembered-briefly")
def test_an_image_missing_is_not_remembered(images: Images, clock: list[float]) -> None:
    """One just built or pulled, outside Handler or by it, is seen at once.

    If this fails: an image built shows as missing for a while, and a deploy pulls again."""
    assert not runtime.exists(REF)
    images.by_ref[REF] = "a" * 64
    assert runtime.exists(REF)


@pytest.mark.rule("runtime.an-image-found-is-remembered-briefly")
@pytest.mark.parametrize("change", ["tag", "remove"])
def test_handlers_own_change_to_an_image_is_seen_at_once(
    images: Images, clock: list[float], change: str
) -> None:
    """A build switches `latest` by a tag, and removes the image it replaced.

    If this fails: after a rebuild, the page shows the old image for up to ten seconds."""
    images.by_ref[REF] = "a" * 64
    runtime.inspect(REF)
    images.by_ref[REF] = "b" * 64
    if change == "tag":
        runtime.tag("b" * 64, REF)
    else:
        assert runtime.remove("a" * 64) is None
    assert found_id() == "b" * 64


@pytest.mark.rule("runtime.an-image-found-is-remembered-briefly")
def test_a_launch_asks_the_runtime_now(images: Images, clock: list[float]) -> None:
    """If this fails: a session starts on an image removed by hand a moment ago and fails in the
    runtime's words, instead of Handler's "not built: prepare it"."""
    images.by_ref[REF] = "a" * 64
    runtime.inspect(REF)
    del images.by_ref[REF]
    assert runtime.inspect(REF) is not None  # remembered
    assert runtime.inspect_now(REF) is None
    assert not runtime.exists(REF)  # and forgotten
