"""Remote control in real browsers: the handler web UI pairs a phone and shares a session; the
remote client (served by a real gateway) drives it — WebCrypto envelopes, end to end.

The "phone" is a second browser context with a phone's viewport and touch screen, on
http://127.0.0.1 (a secure context, like the HTTPS a real gateway needs). Skipped when podman, the
image or the built apps are missing.
"""

import re
import socket
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, expect

from handler_control.settings import WEB_UI

from ..support.daemon import REPO, Daemon, start_daemon
from ..support.remote import Gateway, start_gateway
from .browser import PW_IMAGE, image_present
from .web_ui.ui import open_run
from .web_ui.ui import say as say_on_desk

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


def test_the_phone_knows_the_computer_by_its_name(
    desk: Page, phone: Page, daemon: Daemon, gateway: Gateway
) -> None:
    """Settings → Your phone names the computer (the hostname until then); the pair offer and
    the phone's Settings say that name, the host id kept in the Details."""
    set_up_remote(desk, daemon, gateway, "before")  # the gateway set, the name shown
    card = desk.get_by_test_id("computer-name")
    expect(card.get_by_test_id("computer-name-value")).to_have_text(
        socket.gethostname().split(".")[0]
    )
    card.get_by_test_id("computer-name-change").click()
    card.get_by_test_id("computer-name-input").fill("desk")
    card.get_by_test_id("computer-name-save").click()
    expect(card.get_by_test_id("computer-name-value")).to_have_text("desk")
    link = set_up_remote(desk, daemon, gateway, "named phone")

    phone.goto(link)
    expect(phone.get_by_role("heading", name="Pair this phone with desk?")).to_be_visible()
    expect(phone.get_by_test_id("pair-details")).to_contain_text("h_")
    phone.get_by_test_id("pair").click()
    phone.get_by_test_id("tab-settings").click()
    expect(phone.get_by_test_id("paired-with")).to_have_text("desk")


@pytest.mark.rule(
    "device.paired-from-this-computer-only",
    "phone-session.off-closes-the-devices-at-once",
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

    # a permission request: asked on both, answered on the phone, withdrawn on the desk; of no
    # kind, it is risky: a slide (pressed twice, as a keyboard does) allows it
    say(phone, "permission")
    ask = phone.get_by_role("alertdialog", name="permission request")
    expect(ask).to_be_visible(timeout=20_000)
    expect(desk.get_by_role("alertdialog", name="permission request")).to_be_visible()
    ask.get_by_test_id("permission-slide").click()
    ask.get_by_test_id("permission-slide").click()
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
    expect(phone.get_by_test_id("lights")).to_be_visible()  # a tab's header: paired
    row = desk.get_by_test_id("device-row").filter(has_text="lost phone")
    row.get_by_role("button", name="Revoke").click()
    desk.get_by_test_id("ask-yes").click()
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
    expect(phone.get_by_test_id("shared-session").filter(has_text="shop")).to_be_visible()

    desk.goto(f"{daemon.base_url}/#/projects/{project['id']}")
    item = desk.get_by_test_id("agent-session").filter(has_text="report")
    expect(item).to_be_visible()  # listed with its agent's sessions


@pytest.mark.rule("phone.starts-only-the-agents-you-marked")
def test_phone_starts_a_brief_from_its_form(
    desk: Page, phone: Page, daemon: Daemon, gateway: Gateway
) -> None:
    """An agent with a form (a brief, D.18) marked for the phone: the phone shows its form, not a
    request, and the session starts with it filled in."""
    link = set_up_remote(desk, daemon, gateway, "brief phone")
    form = {"type": "object", "properties": {"ask": {"type": "string", "title": "Ask"}}}
    agent = {"model": {"account": "fake"}, "name": "briefed", "remoteStart": True}
    with daemon.http() as c:
        body = {"folder": str(daemon.make_scope()), "name": "briefs", "agents": []}
        project = c.post("/v1/projects", json=body).json()
        made = c.post(
            "/v1/agents",
            json=agent | {"projectId": project["id"], "interface": {"fields": form}},
        )
        assert made.status_code == 201, made.text

    phone.goto(link)
    phone.get_by_test_id("pair").click()
    phone.get_by_test_id("new-session-open").click(timeout=20_000)
    phone.get_by_test_id("new-session-project").select_option(label="briefs")
    expect(phone.get_by_test_id("new-session-request")).to_have_count(0)  # its form instead
    phone.get_by_test_id("new-session-field-ask").fill("Write the notes")
    phone.get_by_test_id("new-session-start").click()
    expect(phone.get_by_test_id("agent-message").last).to_have_text("ok", timeout=30_000)
    with daemon.http() as c:
        listed = c.get("/v1/sessions").json()
    started = [s for s in listed if s.get("projectId") == project["id"]]
    assert [s["input"] for s in started] == [{"fields": {"ask": "Write the notes"}}]


@pytest.mark.rule("phone.starts-only-the-agents-you-marked")
def test_phone_is_told_when_its_session_does_not_start(
    desk: Page, phone: Page, daemon: Daemon, gateway: Gateway
) -> None:
    """A session started from the phone whose program is not prepared (F.1) does not start: the
    phone says so on New session, the request typed again."""
    link = set_up_remote(desk, daemon, gateway, "waiting phone")
    agent = {"model": {"account": "fake"}, "name": "coder", "remoteStart": True}
    with daemon.http() as c:
        body = {"folder": str(daemon.make_scope()), "name": "unbuilt", "agents": [agent]}
        assert c.post("/v1/projects", json=body).status_code == 201
    missing = daemon.config_dir.parent / "fake-ran" / "harness-image-missing"
    missing.touch()
    try:
        phone.goto(link)
        phone.get_by_test_id("pair").click()
        phone.get_by_test_id("new-session-open").click(timeout=20_000)
        phone.get_by_test_id("new-session-project").select_option(label="unbuilt")
        phone.get_by_test_id("new-session-request").fill("hi")
        phone.get_by_test_id("new-session-start").click()
        expect(phone.get_by_text("its program is not prepared yet")).to_be_visible(timeout=30_000)
        expect(phone.get_by_test_id("new-session-request")).to_have_value("hi")
    finally:
        missing.unlink()


# Everything this browser keeps for the client's origin, as text: IndexedDB's values (bytes
# read as text), localStorage, the service worker's caches; and whether a kept key could be read.
KEPT = """async () => {
  const text = [];
  const walk = (v) => {
    if (v instanceof CryptoKey) text.push(`key:${v.extractable}`);
    else if (v instanceof ArrayBuffer || ArrayBuffer.isView(v)) {
      const bytes = new Uint8Array(v instanceof ArrayBuffer ? v : v.buffer);
      text.push(Array.from(bytes, (b) => String.fromCharCode(b)).join(""));
    } else if (v && typeof v === "object") Object.values(v).forEach(walk);
    else text.push(String(v));
  };
  for (const { name } of await indexedDB.databases()) {
    const db = await new Promise((ok) => (indexedDB.open(name).onsuccess = (e) => ok(e.target.result)));
    for (const store of db.objectStoreNames) {
      const all = db.transaction(store).objectStore(store).getAll();
      walk(await new Promise((ok) => (all.onsuccess = () => ok(all.result))));
    }
    db.close();
  }
  for (let i = 0; i < localStorage.length; i++) text.push(localStorage.key(i), localStorage.getItem(localStorage.key(i)));
  for (const name of await caches.keys()) {
    const cache = await caches.open(name);
    for (const request of await cache.keys()) text.push(await (await cache.match(request)).text());
  }
  return text.join("\\n");
}"""


def phone_with_a_shared_session(
    desk: Page, phone: Page, daemon: Daemon, gateway: Gateway, name: str
) -> str:
    """A session shared from the desk, listed on a phone just paired whose service worker keeps
    the client; returns its project's name (its folder's: unique), which its row shows."""
    link = set_up_remote(desk, daemon, gateway, name)
    folder = daemon.make_scope()
    open_run(desk, daemon, folder)
    toggle = desk.get_by_test_id("remote-toggle")
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    phone.goto(link)
    phone.get_by_test_id("pair").click()
    row = phone.get_by_test_id("shared-session").filter(has_text=folder.name)
    expect(row).to_be_visible(timeout=20_000)
    phone.wait_for_function("() => navigator.serviceWorker.controller !== null", timeout=20_000)
    return folder.name


@pytest.mark.rule("phone.a-card-answers-only-the-ask-it-shows")
def test_a_safe_ask_is_answered_on_its_card(
    desk: Page, phone: Page, daemon: Daemon, gateway: Gateway
) -> None:
    """A session's card says since when it waits and what it asks; a safe ask is allowed there,
    once, without opening the session; a risky one has no answers on its card: it opens the
    session, whose sheet takes a slide."""
    project = phone_with_a_shared_session(desk, phone, daemon, gateway, "card phone")
    row = phone.get_by_test_id("shared-session").filter(has_text=project)

    say_on_desk(desk, "permission read")
    expect(row.get_by_test_id("card-ask")).to_have_text("Read notes.md", timeout=20_000)
    expect(row.get_by_test_id("card-age")).to_have_text("now")
    row.get_by_test_id("card-allow").click()
    expect(desk.get_by_test_id("agent-message").last).to_contain_text(
        '"optionId": "once"', timeout=20_000
    )
    expect(row.get_by_test_id("card-ask")).to_have_count(0, timeout=20_000)
    expect(phone.get_by_label("back to the list")).to_have_count(0)  # never opened

    say_on_desk(desk, "permission execute")
    expect(row.get_by_test_id("card-ask")).to_have_text("Run npm test", timeout=20_000)
    expect(row.get_by_test_id("card-allow")).to_have_count(0)
    row.get_by_role("button").first.click()
    ask = phone.get_by_role("alertdialog", name="permission request")
    expect(ask).to_be_visible(timeout=20_000)
    expect(ask.get_by_test_id("permission-slide")).to_be_visible()
    ask.get_by_test_id("permission-answer").filter(has_text="Reject").click()
    expect(desk.get_by_test_id("agent-message").last).to_contain_text(
        '"optionId": "no"', timeout=20_000
    )


@pytest.mark.rule("phone.offline-says-so")
def test_phone_opens_offline_on_its_last_home(
    desk: Page, phone: Page, daemon: Daemon, gateway: Gateway
) -> None:
    """Opened without a network, the phone shows its last Home, dated and saying to answer when
    it is back; a session opened says it is offline; back online, the live Home replaces it."""
    project = phone_with_a_shared_session(desk, phone, daemon, gateway, "offline phone")
    phone.context.set_offline(True)
    phone.reload()
    said = phone.get_by_test_id("home-offline")
    expect(said).to_contain_text("no connection", timeout=20_000)
    expect(said).to_contain_text("can't reach your gateway")
    expect(said).to_contain_text("As it was at")
    expect(said).to_contain_text("Answer when it is back")
    row = phone.get_by_test_id("shared-session").filter(has_text=project)
    expect(row).to_be_visible()
    row.click()
    expect(phone.get_by_test_id("error")).to_contain_text("Offline")
    phone.get_by_label("back to the list").click()

    phone.context.set_offline(False)
    expect(said).to_have_count(0, timeout=30_000)
    expect(phone.get_by_test_id("shared-session").filter(has_text=project)).to_be_visible()


@pytest.mark.rule("phone.its-last-home-sealed-at-rest")
def test_phone_keeps_its_last_home_sealed(
    desk: Page, phone: Page, daemon: Daemon, gateway: Gateway
) -> None:
    """What the phone keeps of its Home holds none of it in plain text (its project's name), under keys the page cannot
    read; Forget this phone erases it."""
    project = phone_with_a_shared_session(desk, phone, daemon, gateway, "sealed phone")
    phone.wait_for_function(
        """async () => {
          const db = await new Promise((ok) => (indexedDB.open("handler-remote").onsuccess = (e) => ok(e.target.result)));
          const got = db.transaction("device").objectStore("device").get("snapshot");
          return await new Promise((ok) => (got.onsuccess = () => ok(got.result !== undefined)));
        }""",
        timeout=20_000,
    )
    # the agent's last line on its card: kept sealed too
    say_on_desk(desk, "steps")
    row = phone.get_by_test_id("shared-session").filter(has_text=project)
    expect(row.get_by_test_id("card-last")).to_have_text("All 42 tests pass", timeout=20_000)
    phone.wait_for_timeout(1000)  # the snapshot written again
    kept = phone.evaluate(KEPT)
    assert "key:false" in kept and "key:true" not in kept
    assert project not in kept
    assert "All 42 tests pass" not in kept

    phone.get_by_test_id("tab-settings").click()
    phone.get_by_test_id("forget").click()
    slide = phone.get_by_test_id("forget-sheet").get_by_test_id("forget-slide")
    slide.click()  # a press (a keyboard's, a screen reader's) asks again
    expect(slide).to_have_accessible_name("Forget this phone? Press again to confirm.")
    slide.click()
    phone.wait_for_function(
        """async () => {
          const db = await new Promise((ok) => (indexedDB.open("handler-remote").onsuccess = (e) => ok(e.target.result)));
          const keys = db.transaction("device").objectStore("device").getAllKeys();
          return await new Promise((ok) => (keys.onsuccess = () => ok(keys.result.length === 0)));
        }"""
    )


def test_gateway_setup_guides_and_says_what_failed(
    desk: Page, daemon: Daemon, gateway: Gateway
) -> None:
    """Settings → Your phone without a gateway (or on Change): the guided setup, its ways as tabs
    with the commands of each, and a Connect refused says what was wrong in words (E5); Connect
    tries the gateway once, and says beside it at once what failed (D.7)."""
    desk.goto(f"{daemon.base_url}/#/settings/phone")
    settings = desk.get_by_test_id("phone-settings")
    change = settings.get_by_test_id("gateway-change")
    expect(change.or_(settings.get_by_test_id("gateway-setup"))).to_be_visible()
    if change.is_visible():  # another test of this daemon set one
        change.click()
    setup = settings.get_by_test_id("gateway-setup")
    commands = setup.get_by_test_id("command-line")
    expect(commands).to_have_count(3)
    expect(commands.nth(2)).to_contain_text("podman exec handler-gateway handler-gateway add-host")
    setup.get_by_test_id("gateway-way-direct").click()
    expect(commands.nth(0)).to_contain_text("uv tool install ./remote-gateway")
    expect(commands.nth(2)).to_have_text(re.compile(r"^\$\s*handler-gateway add-host laptop"))
    expect(setup.get_by_test_id("gateway-way-community")).to_be_disabled()

    setup.get_by_test_id("gateway-url").fill("http://gateway.example")
    setup.get_by_test_id("host-token").fill("not-a-token")
    setup.get_by_test_id("save-gateway").click()
    error = setup.get_by_test_id("remote-error")
    expect(error).to_contain_text("This address can't be used: it starts with https://")
    expect(error).to_contain_text("This isn't a host token: it is the line starting with h_")

    # saved, then tried: a token the gateway does not know, said at once, the form kept open
    setup.get_by_test_id("gateway-url").fill(gateway.url)
    setup.get_by_test_id("host-token").fill("h_0123456789abcdef." + "x" * 43)
    setup.get_by_test_id("save-gateway").click()
    expect(error).to_have_text(
        "Reached the gateway, but it doesn't know this token: run step 3 again on the gateway's "
        "machine, then paste its new token here."
    )
    # nothing answering at the address
    setup.get_by_test_id("gateway-url").fill(f"http://127.0.0.1:{free_port()}")
    setup.get_by_test_id("save-gateway").click()
    expect(error).to_contain_text("The gateway didn't answer at this address")
    # the right ones: the form closes, the light green, with nothing shared
    setup.get_by_test_id("gateway-url").fill(gateway.url)
    setup.get_by_test_id("host-token").fill(gateway.host_token)
    setup.get_by_test_id("save-gateway").click()
    expect(setup).to_have_count(0)
    expect(settings.get_by_test_id("remote-light")).to_have_text("gateway reachable")
    expect(settings.get_by_test_id("gateway-untried")).to_have_count(0)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
