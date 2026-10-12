"""Mini apps in real browsers (docs/dev/design/miniapps.md): the Apps page registers, deploys and
shares the test app; the desk opens it at its own origin; a family member's phone (paired for apps
only) uses the same instance through the gateway, in the sandboxed frame.

Needs podman (the app runs in it), the built web apps, and Playwright's image (or
HANDLER_TEST_CHROMIUM).
"""

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, expect

from ..apps.conftest import copy_fixture
from ..sandbox.conftest import podman_usable
from ..support import dev_env
from ..support.daemon import Daemon, start_daemon
from ..support.remote import Gateway, start_gateway
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


@pytest.fixture(scope="module")
def daemon(data_root: Path) -> Iterator[Daemon]:
    yield from start_daemon(extra_env={"HANDLER_DATA_DIR": str(data_root)})


def test_desk_and_family_phone_share_one_app(
    browser: Browser, daemon: Daemon, gateway: Gateway, data_root: Path
) -> None:
    source = copy_fixture("miniapp", data_root)
    desk = browser.new_context().new_page()
    desk.goto(f"{daemon.base_url}/#token={daemon.token}")

    # the gateway, then a phone paired for alice (apps only)
    desk.goto(f"{daemon.base_url}/#/settings/remote")
    desk.get_by_label("Gateway URL").fill(gateway.url)
    desk.get_by_label("Host token").fill(gateway.host_token)
    desk.get_by_role("button", name="Save").first.click()
    desk.get_by_test_id("device-for-family").check()
    desk.get_by_test_id("device-person-input").fill("alice")
    desk.get_by_test_id("device-name").fill("alice-phone")
    desk.get_by_test_id("pair-device").click()
    pairing_url = desk.get_by_test_id("pairing-url").text_content() or ""
    desk.get_by_role("button", name="Done").click()
    expect(desk.get_by_test_id("device-person")).to_have_text("alice · apps only")

    # Apps: register, deploy, share with alice, open at the desk
    desk.goto(f"{daemon.base_url}/#/apps")
    desk.fill("#app-source", str(source))
    desk.get_by_role("button", name="Add").click()
    desk.get_by_role("button", name="Deploy 1.0.0").click()
    expect(desk.get_by_role("button", name="Open")).to_be_enabled(timeout=300_000)
    persons = desk.get_by_test_id("app-persons")
    persons.get_by_label("you").check()
    expect(persons.get_by_label("you")).to_be_checked()
    persons.get_by_label("alice").check()
    expect(persons.get_by_label("alice")).to_be_checked()
    with desk.context.expect_page() as opened:
        desk.get_by_role("button", name="Open").click()
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

    # the app's page sends its frame elsewhere: that document gets nothing more
    app_frame = next(f for f in phone.frames if f.url.endswith("/appframe.html"))
    app_frame.evaluate("location.href = '/manifest.webmanifest'")
    expect(phone.get_by_test_id("app-left")).to_be_visible(timeout=20_000)
