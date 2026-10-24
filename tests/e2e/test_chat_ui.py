"""Chat in the web UI, in a real browser against a real handlerd: Handler's own app for talking
about anything with no folder of yours. Who you talk to are the agents of no project and no app,
with no folder, used as a chat; the others of no project are in Other folders. On the model
alone, on a stub provider in the test process (no harness image needed)."""

import re
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, expect

from handler_control.settings import WEB_UI

from ..support import dev_env
from ..support.daemon import Daemon, start_daemon
from ..support.stub_llm import StubLlm
from .browser import PW_IMAGE, image_present

pytestmark = [
    pytest.mark.skipif(not (WEB_UI / "index.html").is_file(), reason="web UI not built"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


@pytest.fixture(scope="module")
def stub() -> Iterator[StubLlm]:
    s = StubLlm("Happy to help.")
    yield s
    s.close()


@pytest.fixture(scope="module")
def daemon(stub: StubLlm) -> Iterator[Daemon]:
    yield from start_daemon(
        extra_env={"HANDLER_TEST_STUB_KEY": "sk-stub"}, extra_providers={"stub": stub.provider()}
    )


@pytest.fixture
def page(browser: Browser, daemon: Daemon) -> Iterator[Page]:
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{daemon.base_url}/#token={daemon.token}")
    yield page
    context.close()


def test_someone_new_to_talk_to_then_a_conversation(
    page: Page, daemon: Daemon, stub: StubLlm
) -> None:
    """From the menu: Chat, with no one yet; someone new (a name, how they behave, the model
    alone) is an agent of no project with no folder; what you type starts a conversation."""
    page.get_by_test_id("sidebar-chat").click()
    expect(page.get_by_test_id("chat-empty")).to_be_visible()
    page.get_by_test_id("chat-new").click()
    dialog = page.get_by_test_id("chat-new-dialog")
    dialog.get_by_test_id("chat-name").fill("Writing partner")
    dialog.get_by_test_id("chat-instructions").fill("Ask before rewriting; keep my voice.")
    dialog.get_by_test_id("chat-model-alone").click()
    dialog.get_by_test_id("access-provider").filter(has_text="stub").click()
    dialog.get_by_test_id("chat-add").click()
    expect(page.get_by_test_id("chat-pick")).to_contain_text("Writing partner")
    with daemon.http() as c:
        made = next(a for a in c.get("/v1/agents").json() if a.get("name") == "Writing partner")
    assert made.get("scope") is None and made.get("projectId") is None and made["modelAlone"]
    assert made["instructions"] == "Ask before rewriting; keep my voice."

    page.get_by_test_id("project-request").fill("Shorten this mail to the school")
    page.get_by_test_id("project-start-button").click()
    expect(page).to_have_url(re.compile(r"#/sessions/"))
    expect(page.get_by_text("Happy to help.").first).to_be_visible(timeout=30_000)
    said = [m for r in stub.requests for m in r.get("messages", [])]
    assert any("Shorten this mail" in str(m.get("content")) for m in said)


def test_chat_and_other_folders_split_the_agents_of_no_project(page: Page, daemon: Daemon) -> None:
    """An agent of no project is in Other folders, not in Chat; one whose home is Chat is in Chat
    only. Ask's Start a chat about it types what was said in the box."""
    with daemon.http() as c:
        body = {"name": "Claude", "modelAlone": True, "model": {"provider": "stub"}, "chat": True}
        r = c.post("/v1/agents", json=body)
        assert r.status_code == 201, r.text
        chat = r.json()
    daemon.create_ad_hoc("fake", daemon.make_scope(), name="Notes keeper")

    page.goto(f"{daemon.base_url}/#/agents")
    expect(page.get_by_role("heading", name="Other folders")).to_be_visible()
    expect(page.get_by_test_id("outside-yours")).to_contain_text("Notes keeper")
    expect(page.get_by_test_id("outside-yours")).not_to_contain_text("Claude")

    page.goto(f"{daemon.base_url}/#/chat?say=Train%20or%20plane%20to%20Lyon%3F")
    expect(page.get_by_test_id("chat-who")).to_contain_text("Claude")
    expect(page.get_by_test_id("chat-who")).not_to_contain_text("Notes keeper")
    expect(page.get_by_test_id("project-request")).to_have_value("Train or plane to Lyon?")

    page.goto(f"{daemon.base_url}/#/agents/{chat['id']}")  # its address opens its place: Chat
    expect(page).to_have_url(re.compile(r"#/chat\?agent="))
    page.goto(f"{daemon.base_url}/#/apps")
    expect(page.get_by_test_id("chat-card")).to_contain_text("from Handler")
