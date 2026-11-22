"""The harnesses (D.2): `GET /v1/harnesses` is what their descriptors say, with no call to the
runtime (every screen naming a harness asks it, a new session's mode chip among them);
`GET /v1/harness-images` asks the runtime for each one's image. These tests mount the catalog
routes alone and replace the runtime's `image` verbs by a recorder."""

import asyncio
import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI

from handler_contracts import ImageInfo
from handler_control import runtime
from handler_control.api.catalog import add_catalog_routes
from handler_control.api.common import Context
from handler_harness import catalog, images


class Runtime:
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
        if verb == "read" and ref in self.by_ref.values():
            return subprocess.CompletedProcess(args, 0, "Mistral Vibe 2.0.0\n", "")
        return subprocess.CompletedProcess(args, 1, "", f"no image {ref}")


@pytest.fixture
def fake_runtime(monkeypatch: pytest.MonkeyPatch) -> Runtime:
    found = Runtime()
    monkeypatch.setattr(runtime, "_image", found)
    monkeypatch.setattr(runtime, "_found", {})
    monkeypatch.setattr(runtime, "_versions", {})
    return found


def get(path: str) -> Any:
    """`path`'s answer from the catalog routes alone (no authentication)."""
    app = FastAPI()
    add_catalog_routes(app, cast(Context, SimpleNamespace(require_auth=lambda: None)))

    async def ask() -> Any:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://handlerd") as c:
            r = await c.get(path)
            r.raise_for_status()
            return r.json()

    return asyncio.run(ask())


@pytest.mark.rule("harness.listed-without-asking-the-runtime")
def test_listing_the_harnesses_asks_nothing_of_the_runtime(fake_runtime: Runtime) -> None:
    """If this fails: a new session's mode chip, and every screen naming a harness, waits on
    the runtime for each harness image (seconds when it is busy)."""
    listed = get("/v1/harnesses")
    assert fake_runtime.asked == []
    vibe = next(h for h in listed if h["name"] == "vibe")
    assert vibe["product"] == "Mistral Vibe"
    assert vibe["sessionModes"]  # what the mode chip needs, from the descriptor
    assert not {"imagePresent", "version", "builtAt"} & vibe.keys()


@pytest.mark.rule("image.records-what-it-installed")
def test_harness_images_give_each_image_s_state(fake_runtime: Runtime) -> None:
    """If this fails: Settings → Sandboxes and `handler image list` show a built harness as not
    built, or without its version."""
    vibe = catalog.get("vibe")
    fake_runtime.by_ref[images.ref(vibe.descriptor.image, images.LATEST)] = "a" * 64
    found: dict[str, Any] = {i["name"]: i for i in get("/v1/harness-images")}
    assert found.keys() == {h.name for h in catalog.all_harnesses()}
    assert found["vibe"] == {
        "name": "vibe",
        "image": vibe.descriptor.image,
        "imagePresent": True,
        "version": "Mistral Vibe 2.0.0",
        "builtAt": "2026-11-13T00:00:00Z",
    }
    assert found["codex"]["imagePresent"] is False
    assert "version" not in found["codex"] or found["codex"]["version"] is None
