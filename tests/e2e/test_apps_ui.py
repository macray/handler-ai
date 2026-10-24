"""Apps in real browsers (docs/dev/design/apps.md): the Apps page registers, deploys and
shares the test app; the desk opens it at its own origin; a family member's phone (paired for apps
only) uses the same instance through the gateway, in the sandboxed frame.

Needs podman (the app runs in it), the built web apps, and Playwright's image (or
HANDLER_TEST_CHROMIUM).
"""

import json
import re
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, FilePayload, expect

from ..apps.conftest import app_file, copy_fixture
from ..sandbox.conftest import podman_usable
from ..support import dev_env
from ..support.daemon import Daemon, start_daemon
from ..support.remote import Gateway, start_gateway
from ..support.stub_llm import StubLlm
from .browser import PW_IMAGE, image_present
from .test_remote_ui import BUILT, CLIENT

pytestmark = [
    pytest.mark.skipif(not BUILT, reason="web apps not built (scripts/build-web-ui.sh)"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.skipif(not podman_usable(), reason="podman not usable"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


@pytest.fixture(scope="module")
def data_root() -> Iterator[Path]:
    path = dev_env.scope_root() / f"apps-ui-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="module")
def gateway() -> Iterator[Gateway]:
    yield from start_gateway(CLIENT)


def route(body: dict[str, Any]) -> str:
    """The Ask router's answer (D.24): the counter's action, whatever was said."""
    result: dict[str, Any] = {"status": "ok", "summary": "the counter counts", "kind": "pick"}
    result |= {"app": "counter"}
    result |= {"action": "count", "fields": {}, "why": "it counts"}
    return f"```json handler-result\n{json.dumps(result)}\n```"


@pytest.fixture(scope="module")
def stub() -> Iterator[StubLlm]:
    s = StubLlm(route, heard="count one more")
    yield s
    s.close()


@pytest.fixture(scope="module")
def daemon(data_root: Path, stub: StubLlm) -> Iterator[Daemon]:
    env = {"HANDLER_DATA_DIR": str(data_root), "HANDLER_TEST_STUB_KEY": "sk-stub"}
    yield from start_daemon(extra_env=env, extra_providers={"stub": stub.provider()})


def test_desk_and_family_phone_share_one_app(
    browser: Browser, daemon: Daemon, gateway: Gateway, data_root: Path
) -> None:
    source = copy_fixture("app", data_root)
    desk = browser.new_context().new_page()
    desk.goto(f"{daemon.base_url}/#token={daemon.token}")

    # the gateway, then a phone paired for alice (apps only)
    desk.goto(f"{daemon.base_url}/#/settings/remote")
    desk.get_by_label("Gateway URL").fill(gateway.url)
    desk.get_by_label("Host token").fill(gateway.host_token)
    desk.get_by_test_id("save-gateway").click()
    desk.get_by_test_id("pair-open").click()
    desk.get_by_test_id("device-for-family").check()
    desk.get_by_test_id("device-person-input").fill("alice")
    desk.get_by_test_id("device-name").fill("alice-phone")
    desk.get_by_test_id("pair-device").click()
    pairing_url = desk.get_by_test_id("pairing-url").text_content() or ""
    desk.get_by_role("button", name="Done").click()
    expect(desk.get_by_test_id("device-person")).to_have_text("alice · apps only")

    # Apps: register, deploy, share with alice, open at the desk
    desk.goto(f"{daemon.base_url}/#/apps")
    file: FilePayload = {
        "name": "counter.zip",
        "mimeType": "application/zip",
        "buffer": app_file(source),
    }
    desk.get_by_test_id("app-file").set_input_files(file)  # its install page: who opens, Install
    desk.get_by_label("you, on your phone").check()
    desk.get_by_label("alice").check()
    desk.get_by_test_id("install-go").click()
    persons = desk.get_by_test_id("app-persons")  # installed: its page
    expect(persons.get_by_label("you")).to_be_checked(timeout=300_000)
    expect(persons.get_by_label("alice")).to_be_checked()
    with desk.context.expect_page() as opened:
        desk.get_by_test_id("app-open").click()
    local = opened.value
    expect(local.locator("#n")).to_have_text("0", timeout=60_000)
    local.click("#add")
    expect(local.locator("#n")).to_have_text("1")

    # alice's phone: the same app, the same data
    phone = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True).new_page()
    phone.goto(pairing_url)
    phone.get_by_test_id("pair").click()
    phone.get_by_test_id("shared-app").click(timeout=60_000)
    frame = phone.frame_locator("[data-testid=app-frame]")
    expect(frame.locator("#n")).to_have_text("1", timeout=60_000)
    frame.locator("#add").click()
    expect(frame.locator("#n")).to_have_text("2", timeout=60_000)
    local.reload()
    expect(local.locator("#n")).to_have_text("2")

    # the app's page sends its frame to another site, data in the address: the client's policy
    # (frame-src 'self') stops it before anything is sent, and the app is closed (its frame
    # loaded a second page, the browser's error)
    left: list[str] = []
    phone.on("request", lambda r: left.append(r.url) if "example.com" in r.url else None)
    app_frame = next(f for f in phone.frames if f.url.endswith("/appframe.html"))
    app_frame.evaluate("location.href = 'https://example.com/?n=2'")
    expect(phone.get_by_test_id("app-left")).to_be_visible(timeout=20_000)
    assert left == []


def test_an_action_is_tried_from_the_app_s_page(browser: Browser, daemon: Daemon) -> None:
    """H.12 in the UI: the deployed counter's page lists what you can ask it; Try runs it once
    and shows its answer."""
    desk = browser.new_page()
    desk.goto(f"{daemon.base_url}/#token={daemon.token}")
    desk.goto(f"{daemon.base_url}/#/apps/counter")
    action = desk.get_by_test_id("app-action").filter(has_text="Count one more")
    expect(action).to_contain_text("instant")
    action.get_by_test_id("app-action-try").click()
    desk.get_by_test_id("action-run").click()
    expect(desk.get_by_test_id("action-answer")).to_contain_text(
        re.compile(r"Counted: \d+\."), timeout=60_000
    )


ROUTER = Path(__file__).parents[2] / (
    "packages/control-plane/src/handler_control/data/handler-needs/ask-router"
)


def test_ask_picks_the_app_and_answers(browser: Browser, daemon: Daemon, stub: StubLlm) -> None:
    """D.24 in the UI: with no router, Ask says it needs one; with one (the model alone, a stub
    provider), what you type is routed to the counter's action, which answers on the page. D.25:
    Settings → Voice chooses the stub's speech model, then what is said is heard and asked."""
    desk = browser.new_page()
    desk.goto(f"{daemon.base_url}/#token={daemon.token}")
    desk.goto(f"{daemon.base_url}/#/ask")
    expect(desk.get_by_test_id("ask-no-router")).to_be_visible()
    router = {
        "name": "Ask router",
        "modelAlone": True,
        "model": {"provider": "stub"},
        "instructions": (ROUTER / "instructions.md").read_text(),
        "interface": json.loads((ROUTER / "interface.json").read_text()),
    }
    with daemon.http() as c:
        agent = c.post("/v1/agents", json=router).json()
        assert c.put("/v1/handler-needs/ask-router", json={"agentId": agent["id"]}).is_success
    desk.reload()
    desk.get_by_test_id("ask-input").fill("count one more")
    desk.get_by_test_id("ask-send").click()
    entry = desk.get_by_test_id("ask-entry").first
    expect(entry.get_by_test_id("ask-pick")).to_contain_text("counter · Count one more")
    expect(entry.get_by_test_id("ask-answer")).to_contain_text(
        re.compile(r"Counted: \d+\."), timeout=60_000
    )
    expect(desk.get_by_test_id("ask-can")).to_contain_text("counter")

    # D.25: off, the microphone leads to Settings → Voice; there, the stub's speech model chosen
    desk.get_by_test_id("ask-mic-setup").click()
    expect(desk.get_by_test_id("voice")).to_be_visible()
    desk.get_by_test_id("voice-model").filter(has_text="ears").click()
    expect(desk.get_by_test_id("voice-model").filter(has_text="ears")).to_contain_text(
        "on this computer"
    )
    with daemon.http() as c:
        assert c.get("/v1/voice").json()["model"] == "stub/ears"
    # a microphone the browser makes up (a tone), then spoken: written down, sent, marked heard
    desk.add_init_script(MICROPHONE)
    desk.goto(f"{daemon.base_url}/#/ask")
    desk.reload()  # a new document: the script runs in it
    desk.get_by_test_id("ask-mic").click()
    expect(desk.get_by_test_id("ask-listening")).to_be_visible()
    desk.wait_for_timeout(800)
    desk.get_by_test_id("ask-mic").click()
    heard = desk.get_by_test_id("ask-entry").first
    expect(heard).to_contain_text("count one more")
    expect(heard.get_by_label("heard")).to_be_visible()
    expect(heard.get_by_test_id("ask-answer")).to_contain_text(
        re.compile(r"Counted: \d+\."), timeout=60_000
    )
    assert any(r["path"].endswith("/audio/transcriptions") for r in stub.requests)


# getUserMedia answered with a tone (no microphone in the test browser)
MICROPHONE = """
navigator.mediaDevices.getUserMedia = async () => {
  const ctx = new AudioContext();
  const tone = ctx.createOscillator();
  const out = ctx.createMediaStreamDestination();
  tone.connect(out);
  tone.start();
  return out.stream;
};
"""


def test_a_draft_is_opened_from_the_app_s_page(browser: Browser, daemon: Daemon) -> None:
    """H.16 in the UI: while a change of the counter waits, Open the draft opens it in a new tab
    at its own address, its banner first, and the bar says what it works on (copies)."""
    with daemon.http() as c:
        agent = c.post("/v1/agents", json={"name": "Drafter", "model": {"account": "fake"}}).json()
        body = {"agentId": agent["id"], "appDraft": {"app": "counter"}}
        session = c.post("/v1/sessions", json=body).json()
    desk = browser.new_page()
    desk.goto(f"{daemon.base_url}/#token={daemon.token}")
    desk.goto(f"{daemon.base_url}/#/apps/counter")
    bar = desk.get_by_test_id("app-draft")
    with desk.context.expect_page() as opened:
        bar.get_by_test_id("draft-open").click()
    tab = opened.value
    expect(tab.locator("[data-handler-draft]")).to_contain_text("Draft of counter", timeout=60_000)
    expect(tab.locator("#n")).not_to_have_text("?", timeout=30_000)  # its backend answers
    expect(bar.get_by_test_id("draft-copies")).to_contain_text("its data: a copy")
    with daemon.http() as c:
        assert c.delete(f"/v1/sessions/{session['id']}").status_code == 204
