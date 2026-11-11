"""Remote control in real browsers: the handler web UI pairs a phone and shares a session; the
remote client (served by a real gateway) drives it — WebCrypto envelopes, end to end.

The "phone" is a second browser context with a phone's viewport and touch screen, on
http://127.0.0.1 (a secure context, like the HTTPS a real gateway needs). Skipped when podman, the
image or the built apps are missing.
"""

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, expect

from handler_control.settings import WEB_UI

from ..support.daemon import REPO, Daemon, start_daemon
from ..support.remote import Gateway, start_gateway
from .browser import PW_IMAGE, image_present
from .test_web_ui import open_run

CLIENT = REPO / "packages" / "remote-client" / "dist"
BUILT = (CLIENT / "index.html").is_file() and (WEB_UI / "index.html").is_file()

pytestmark = [
    pytest.mark.skipif(not BUILT, reason="web apps not built (scripts/build-web-ui.sh)"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
]


@pytest.fixture(scope="module")
def gateway() -> Iterator[Gateway]:
    yield from start_gateway(CLIENT)


@pytest.fixture(scope="module")
def daemon() -> Iterator[Daemon]:
    yield from start_daemon()


@pytest.fixture
def desk(browser: Browser, daemon: Daemon) -> Iterator[Page]:
    context = browser.new_context()
    page = context.new_page()
    page.goto(daemon.ui_url())
    yield page
    context.close()


@pytest.fixture
def phone(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(
        viewport={"width": 390, "height": 800}, is_mobile=True, has_touch=True
    )
    page = context.new_page()
    yield page
    context.close()


def say(phone: Page, text: str) -> None:
    """On a touch screen Return starts a new line (no Shift+Enter there): Send sends."""
    prompt = phone.get_by_label("prompt")
    prompt.fill(text)
    prompt.press("Enter")
    expect(prompt).to_have_value(f"{text}\n")
    phone.get_by_test_id("send").click()


def set_up_remote(desk: Page, daemon: Daemon, gateway: Gateway, name: str) -> str:
    """Settings → Your phone: the gateway, then a new device; returns its pairing link."""
    desk.goto(f"{daemon.base_url}/#/settings/phone")
    settings = desk.get_by_test_id("phone-settings")
    if settings.get_by_test_id("gateway-url").is_visible():
        settings.get_by_test_id("gateway-url").fill(gateway.url)
        settings.get_by_test_id("host-token").fill(gateway.host_token)
        settings.get_by_test_id("save-gateway").click()
    settings.get_by_test_id("pair-open").click()
    settings.get_by_test_id("device-name").fill(name)
    settings.get_by_test_id("pair-device").click()
    expect(settings.get_by_test_id("qr")).to_be_visible()
    link = settings.get_by_test_id("pairing-url").text_content() or ""
    assert link.startswith(f"{gateway.url}/#pair=")
    settings.get_by_role("button", name="Done").click()
    expect(settings.get_by_test_id("device-row").filter(has_text=name)).to_have_count(1)
    return link


@pytest.mark.rule(
    "device.paired-from-this-computer-only",
    "share.off-closes-the-devices-at-once",
    "phone.an-ordinary-attachment",
)
def test_phone_drives_a_shared_session(
    desk: Page, phone: Page, daemon: Daemon, gateway: Gateway
) -> None:
    link = set_up_remote(desk, daemon, gateway, "my phone")

    # a session on the desk, shared
    open_run(desk, daemon)
    toggle = desk.get_by_test_id("remote-toggle")
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")

    # the phone pairs (the key leaves the address bar) and lists it
    phone.goto(link)
    phone.get_by_test_id("pair").click()
    assert "#pair=" not in phone.url
    shared = phone.get_by_test_id("shared-session")
    expect(shared).to_have_count(1, timeout=20_000)
    expect(phone.get_by_test_id("lights")).to_be_visible()
    shared.click()

    # a prompt from the phone: answered there, and shown on the desk (F.7)
    say(phone, "hello from the phone")
    expect(phone.get_by_test_id("agent-message").last).to_have_text("ok", timeout=20_000)
    expect(phone.get_by_test_id("send-state")).to_have_count(0)  # delivered: nothing said
    # the session's first prompt: what its filtered network means, then the person's words
    expect(desk.get_by_test_id("user-message").last).to_contain_text("hello from the phone")

    # a permission request: asked on both, answered on the phone, withdrawn on the desk
    say(phone, "permission")
    ask = phone.get_by_role("alertdialog", name="permission request")
    expect(ask).to_be_visible(timeout=20_000)
    expect(desk.get_by_role("alertdialog", name="permission request")).to_be_visible()
    ask.get_by_role("button", name="Allow").click()
    expect(phone.get_by_test_id("agent-message").last).to_contain_text('"optionId": "yes"')
    expect(desk.get_by_role("alertdialog", name="permission request")).to_have_count(0)

    # Interrupt takes a second tap on a touch screen; the timeline then says so, on both
    say(phone, "sleep")  # the agent works until it is interrupted
    interrupt = phone.get_by_test_id("interrupt")
    interrupt.click()
    expect(interrupt).to_have_text("Tap again to interrupt")
    # the first tap only asks: the status line says so instead of "working", nothing stops
    expect(phone.get_by_text("Tap ■ again to interrupt")).to_be_visible()
    expect(phone.get_by_test_id("turn-stopped")).to_have_count(0)
    interrupt.click()
    expect(phone.get_by_test_id("turn-stopped")).to_contain_text("Interrupted", timeout=20_000)
    expect(desk.get_by_test_id("turn-stopped")).to_contain_text("Interrupted")

    # unshared from the desk: the phone is told
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "false")
    expect(phone.get_by_text("The session is no longer shared.")).to_be_visible(timeout=20_000)
    phone.get_by_role("button", name="Back", exact=True).click()
    expect(phone.get_by_test_id("shared-session")).to_have_count(0, timeout=20_000)


@pytest.mark.rule("device.revoked-is-refused")
def test_revoked_phone_is_locked_out(
    desk: Page, phone: Page, daemon: Daemon, gateway: Gateway
) -> None:
    link = set_up_remote(desk, daemon, gateway, "lost phone")
    phone.goto(link)
    phone.get_by_test_id("pair").click()
    expect(phone.get_by_role("heading", name="Handler remote")).to_be_visible()
    desk.once("dialog", lambda d: d.accept())
    row = desk.get_by_test_id("device-row").filter(has_text="lost phone")
    row.get_by_role("button", name="Revoke").click()
    phone.reload()
    expect(phone.get_by_text("The gateway does not know this device")).to_be_visible(timeout=40_000)


@pytest.mark.rule("phone.starts-only-the-agents-you-marked")
def test_phone_starts_a_session(desk: Page, phone: Page, daemon: Daemon, gateway: Gateway) -> None:
    """An agent marked "Can be started from your phone": the phone starts a session with a
    request, opens it once the host shares it, and the desk lists it under its project."""
    link = set_up_remote(desk, daemon, gateway, "starter phone")
    folder = daemon.make_scope()
    with daemon.http() as c:
        body = {
            "folder": str(folder),
            "name": "shop",
            "agents": [{"model": {"account": "fake"}, "name": "coder"}],
        }
        project = c.post("/v1/projects", json=body).json()
    desk.goto(f"{daemon.base_url}/#/projects/{project['id']}/agents/{project['agents'][0]['id']}")
    desk.get_by_test_id("agent-remote-start").click()
    desk.get_by_test_id("agent-save").click()
    expect(desk.get_by_test_id("agent-editor")).to_have_count(0)

    phone.goto(link)
    phone.get_by_test_id("pair").click()
    phone.get_by_test_id("new-session-open").click(timeout=20_000)
    expect(phone.get_by_test_id("new-session-agent")).to_have_value(project["agents"][0]["id"])
    phone.get_by_test_id("new-session-request").fill("report")
    phone.get_by_test_id("new-session-start").click()
    expect(phone.get_by_test_id("agent-message").last).to_contain_text(
        '"mode": "yolo"', timeout=30_000
    )
    phone.get_by_label("back to the list").click()
    expect(phone.get_by_test_id("session-group").filter(has_text="shop")).to_be_visible()

    desk.goto(f"{daemon.base_url}/#/projects/{project['id']}")
    item = desk.get_by_test_id("agent-session").filter(has_text="report")
    expect(item).to_be_visible(timeout=15_000)  # listed with its agent's sessions
