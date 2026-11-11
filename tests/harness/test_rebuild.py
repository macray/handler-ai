"""D.4 end to end: rebuild a real harness image through handlerd, check it, switch.

Needs the default runtime (Podman; Apple container on a Mac), the toolbox and vibe images (`handler image rebuild toolbox`) and the internet (the
rebuild fetches Vibe's latest release). Vibe is used because its image is the quickest to rebuild.
"""

import os
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from handler_control import runtime
from handler_harness import images

from ..support import dev_env
from ..support.daemon import Daemon, start_daemon
from ..support.runtimes import real_sandbox_env
from .conftest import image_present

REPO = "localhost/handler-ai-vibe"
LATEST = images.ref(REPO, images.LATEST)

pytestmark = [
    pytest.mark.skipif(
        not (image_present(LATEST) and image_present("localhost/handler-ai-toolbox:latest")),
        reason="toolbox and vibe images not built (run: handler image rebuild toolbox)",
    ),
    pytest.mark.skipif(
        bool(os.environ.get("HANDLER_TEST_OFFLINE")), reason="HANDLER_TEST_OFFLINE set"
    ),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


@pytest.fixture(scope="module")
def daemon() -> Iterator[Daemon]:
    # the image check's scope lives in the state dir: the sandbox uid must reach it (dev_env)
    state = dev_env.make_scope()
    try:
        yield from start_daemon(extra_env={"HANDLER_STATE_DIR": str(state)} | real_sandbox_env())
    finally:
        dev_env.remove_scope(state)


def image_id(ref: str) -> str | None:
    info = runtime.inspect(ref)
    return info.id if info else None


def wait_for_end(c: httpx.Client, build_id: str, timeout: float = 900) -> tuple[Any, str]:
    """Poll like the web UI does: the build and its log from the last offset."""
    deadline, offset, log = time.monotonic() + timeout, 0, ""
    while time.monotonic() < deadline:
        chunk = c.get(f"/v1/builds/{build_id}/log", params={"offset": offset}).json()
        log, offset = log + chunk["text"], chunk["nextOffset"]
        if chunk["complete"]:
            return c.get(f"/v1/builds/{build_id}").json(), log
        time.sleep(1)
    raise TimeoutError(f"build {build_id} still running:\n{log[-2000:]}")


@pytest.mark.rule("image.latest-is-the-last-that-passed", "image.built-only-from-what-is-on-disk")
def test_cancelled_rebuild_leaves_latest_alone(daemon: Daemon) -> None:
    before = image_id(LATEST)
    with daemon.http() as c:
        build = c.post("/v1/harnesses/vibe/rebuild").json()
        r = c.post("/v1/toolbox/rebuild")
        assert r.status_code == 409, r.text  # one build at a time
        r = c.post(f"/v1/builds/{build['id']}/cancel")
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "cancelled"
    assert image_id(LATEST) == before


@pytest.mark.rule(
    "image.latest-is-the-last-that-passed",
    "image.checked-against-its-descriptor",
    "image.records-what-it-installed",
)
def test_rebuild_checks_then_switches(daemon: Daemon) -> None:
    before = image_id(LATEST)
    with daemon.http() as c:
        r = c.post("/v1/harnesses/vibe/rebuild")
        assert r.status_code == 202, r.text
        build, log = wait_for_end(c, r.json()["id"])
        assert build["state"] == "succeeded", f"{build.get('error')}\n{log[-3000:]}"
        assert build["versions"].get("vibe", "").startswith("Mistral Vibe "), log[-3000:]
        assert "STEP 1/" in log and "check: session/new ok" in log

        assert image_id(LATEST) != before
        # the replaced image is removed, or kept and said why: in use (the parallel suite's other
        # tests may run vibe containers on it)
        assert before is None or image_id(before) is None or f"{before[:12]} kept: " in log
        info = next(h for h in c.get("/v1/harnesses").json() if h["name"] == "vibe")
        assert info["version"] == build["versions"]["vibe"]


@pytest.mark.rule("image.built-only-from-what-is-on-disk")
def test_unknown_target_and_build(daemon: Daemon) -> None:
    with daemon.http() as c:
        assert c.post("/v1/harnesses/nope/rebuild").status_code == 404
        assert c.get("/v1/builds/nope").status_code == 404
