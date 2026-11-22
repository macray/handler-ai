"""Sessions in the web UI: chatting, several at once, what goes with a prompt.

Skipped when podman, the image or the built UI is missing."""

import json
import re

import pytest
from playwright.sync_api import FilePayload, Page, expect

from handler_harness.render import FILTERED_NETWORK

from ...support import dev_env
from ...support.daemon import Daemon
from ..browser import PW_IMAGE, image_present
from .ui import UI_BUILT, bell_items, create_project, open_run, pin, png, project_of, say

pytestmark = [
    pytest.mark.skipif(not UI_BUILT, reason="web UI not built (scripts/build-web-ui.sh)"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


def test_token_leaves_the_address_bar(page: Page) -> None:
    home = re.compile("^(Projects|Your first project)$")  # the latter before any project
    expect(page.get_by_role("heading", name=home)).to_be_visible()
    assert "token" not in page.url


@pytest.mark.rule("policy.never-the-client-s-files-or-terminal")
def test_chat_through_the_ui(page: Page, daemon: Daemon) -> None:
    open_run(page, daemon)
    say(page, "report")
    message = page.get_by_test_id("agent-message").last
    expect(message).to_contain_text('"mode": "yolo"')
    # its text, not its inner_text: a timeline item not laid out yet (content-visibility: auto)
    # has an empty one
    report = json.loads(message.text_content() or "")
    assert report["capabilities"] == {
        "fs": {"readTextFile": False, "writeTextFile": False},
        "terminal": False,
    }


def test_an_edit_shows_its_diff(page: Page, daemon: Daemon) -> None:
    """An edit as the Claude adapter reports it shows what it changed under its step, while the
    turn runs and once the session is read again."""
    open_run(page, daemon)
    say(page, "edit")
    expect(page.get_by_test_id("agent-message").last).to_contain_text("edited")
    for _ in range(2):
        step = page.locator(".tool").last
        expect(step.get_by_test_id("tool-summary")).to_contain_text("Updated notes.md")
        diff = step.get_by_test_id("diff")
        expect(diff).to_be_visible()
        expect(diff.locator(".row.del")).to_contain_text("first")
        expect(diff.locator(".row.add")).to_contain_text("second")
        page.reload()


def test_hostile_agent_output_stays_inert(page: Page, daemon: Daemon) -> None:
    open_run(page, daemon)
    say(page, "xss")
    message = page.get_by_test_id("agent-message").last
    expect(message).to_contain_text("hello")
    page.wait_for_timeout(500)
    assert page.evaluate("window.__pwned") is None
    assert message.locator("img, script, iframe, a[href^='javascript']").count() == 0


def test_supervise_several_sessions(page: Page, daemon: Daemon) -> None:
    folder = daemon.make_scope()
    open_run(page, daemon, folder)
    say(page, "permission")  # the first agent now waits for an answer
    expect(page.get_by_role("alertdialog")).to_be_visible()
    page.goto(f"{daemon.base_url}/#/projects/{project_of(daemon, folder)['id']}")
    page.get_by_test_id("project-start-button").click()  # another session, the default agent
    expect(page.get_by_test_id("mode-select")).to_have_value("yolo")
    expect(page.get_by_test_id("bell")).to_have_attribute("data-state", "waiting")
    expect(page).to_have_title(re.compile(r"^\(\d+\) Handler$"))  # other tests' sessions too
    waiting = bell_items(page, folder)  # the bell's list: the one asking, waiting for you
    expect(waiting).to_have_count(1)
    expect(waiting).to_contain_text("asks:")
    link = waiting.locator("a").first.get_attribute("href")
    waiting.get_by_test_id("bell-allow").click()  # answered in place
    expect(waiting).to_have_count(0)
    page.goto(f"{daemon.base_url}/{link}")
    expect(page.get_by_test_id("agent-message").last).to_contain_text('"optionId": "yes"')


def test_projects_row_waiting_opens_its_session(page: Page, daemon: Daemon) -> None:
    """Projects: a project waiting for you says so on its row, and two ways in: its Open
    session goes to the waiting session, the rest of the row to the project."""
    folder = daemon.make_scope()
    open_run(page, daemon, folder)
    say(page, "permission")  # the agent now waits for an answer
    expect(page.get_by_role("alertdialog")).to_be_visible()
    session = page.url
    project = project_of(daemon, folder)
    page.goto(f"{daemon.base_url}/#/projects")
    page.get_by_test_id("project-search").fill(project["name"])
    row = page.get_by_test_id("project-row")
    expect(row).to_have_count(1)
    expect(row.get_by_test_id("project-state")).to_have_text("needs you")
    row.get_by_test_id("open-session").click()
    expect(page).to_have_url(session)
    expect(page.get_by_role("alertdialog")).to_be_visible()
    page.go_back()
    page.get_by_test_id("project-search").fill(project["name"])
    page.get_by_test_id("project-row").get_by_test_id("project-name").click()
    expect(page.get_by_role("heading", name=project["name"])).to_be_visible()
    page.goto(f"{daemon.base_url}/#/projects")  # the agents of no project: one row, counted
    expect(page.get_by_test_id("outside-row")).to_contain_text("Agents outside projects")


@pytest.mark.rule("session.outlives-its-clients")
def test_reload_keeps_the_turn_in_progress(page: Page, daemon: Daemon) -> None:
    """The agent lives in the daemon (F): a reload re-attaches, the pending question is back."""
    folder = daemon.make_scope()
    open_run(page, daemon, folder)
    say(page, "permission")  # the agent now waits for an answer
    expect(page.get_by_role("alertdialog")).to_be_visible()
    pin(daemon, project_of(daemon, folder)["id"])
    page.reload()
    # its project in the menu's Pinned says it, by the most urgent of its sessions; the bell too
    dot = page.locator(f'[data-testid="sidebar-project"][title="{folder}"]').get_by_test_id(
        "place-dot"
    )
    expect(dot).to_have_attribute("data-status", "needs-you")
    expect(page.get_by_test_id("bell")).to_have_attribute("data-state", "waiting")
    expect(page.get_by_test_id("user-message").last).to_contain_text("permission")  # replayed
    page.get_by_role("alertdialog").get_by_role("button", name="Allow").click()
    expect(page.get_by_test_id("agent-message").last).to_contain_text('"optionId": "yes"')
    expect(dot).to_have_attribute("data-status", "idle")


def test_a_pinned_project_s_area_is_its_colour(page: Page, daemon: Daemon) -> None:
    """Pinned is one list in the person's order: a project's area is its folder's colour, no
    group and no tag."""
    with daemon.http() as c:
        assert c.post("/v1/areas", json={"name": "Menu-e2e", "color": "cyan"}).status_code == 201
        info = next(a for a in c.get("/v1/accounts").json() if a["name"] == "fake")
        body = {"name": "fake", "harness": info["harness"], "areas": ["Menu-e2e"]}
        assert c.put("/v1/accounts/fake", json=body).status_code == 200
    folder = daemon.make_scope()
    project = create_project(daemon, folder, name="menu-area-e2e", area="Menu-e2e")
    try:
        pin(daemon, project["id"])
        page.goto(f"{daemon.base_url}/#/projects")
        page.reload()  # areas are loaded at start (Settings reloads them after a change)
        row = page.get_by_test_id("sidebar-project").filter(has_text="menu-area-e2e")
        expect(row).to_have_text("menu-area-e2e")
        expect(row.locator("svg.area-icon")).to_have_count(1)
        expect(row.get_by_test_id("area-tag")).to_have_count(0)
    finally:
        with daemon.http() as c:
            assert c.delete(f"/v1/projects/{project['id']}").status_code == 204
            body["areas"] = []
            assert c.put("/v1/accounts/fake", json=body).status_code == 200
            assert c.delete("/v1/areas/Menu-e2e").status_code == 204


def test_settings_keep_the_menu(page: Page, daemon: Daemon) -> None:
    """Settings list their sections in the page: the menu stays, Settings lit at its foot. Five
    everyday ones, then Expert, folded until opened once (this browser)."""
    page.goto(f"{daemon.base_url}/#/")
    page.evaluate("localStorage.removeItem('handler.settings.expert')")
    page.get_by_test_id("settings-link").click()
    expect(page.get_by_test_id("settings-models")).to_be_visible()
    expect(page.get_by_test_id("projects-link")).to_be_visible()  # the menu is still there
    expect(page.get_by_test_id("settings-link")).to_have_attribute("data-active", "true")
    nav = page.get_by_test_id("settings-nav")
    expect(nav.locator("a")).to_have_text(
        ["Model access", "Helpers", "Folders", "Your phone", "Appearance"]
    )
    nav.get_by_test_id("settings-expert").click()
    nav.get_by_test_id("settings-nav-areas").click()
    expect(page.get_by_test_id("settings-areas")).to_be_visible()
    expect(page.get_by_test_id("settings-nav-areas")).to_have_attribute("aria-current", "page")
    page.reload()  # opened once: stays open
    expect(nav.get_by_test_id("settings-nav-sandboxes")).to_be_visible()


def test_a_broken_gateway_is_said_only_while_a_session_is_shared(
    page: Page, daemon: Daemon
) -> None:
    """No Remote row in the menu: a red line only when the gateway is broken and a session is
    shared (what it costs you then); nothing when nothing is shared."""
    status = {
        "gatewayUrl": "https://gw.example",
        "hostId": "h1",
        "light": "unreachable",
        "detail": "connection refused",
        "devices": [],
        "sharedSessions": ["s1"],
    }
    page.route("**/v1/remote", lambda route: route.fulfill(json=status))
    page.goto(f"{daemon.base_url}/#/")
    page.reload()
    problem = page.get_by_test_id("remote-problem")
    expect(problem).to_contain_text("Your phone can't reach Handler")
    expect(problem).to_have_attribute("href", "#/settings/phone")
    status["sharedSessions"] = []  # set up but not in use: the menu says nothing
    with page.expect_response("**/v1/remote"):
        page.reload()
    page.wait_for_timeout(200)  # the answer rendered
    expect(problem).to_have_count(0)


def test_a_message_typed_while_the_agent_works_is_queued(page: Page, daemon: Daemon) -> None:
    """Enter queues it while the turn goes on; "Send now" interrupts the turn, then sends it."""
    open_run(page, daemon)
    say(page, "sleep")  # the agent works until it is interrupted
    expect(page.get_by_test_id("elapsed")).to_be_visible()
    say(page, "forgotten")
    expect(page.get_by_test_id("queued")).to_contain_text("forgotten")
    page.get_by_test_id("queued-delete").click()
    expect(page.get_by_test_id("queued")).to_have_count(0)
    say(page, "hello")
    page.get_by_test_id("queued-send-now").click()
    expect(page.get_by_test_id("queued")).to_have_count(0)
    expect(page.get_by_test_id("user-message").last).to_contain_text("hello")
    expect(page.get_by_test_id("agent-message").last).to_contain_text("ok")
    expect(page.get_by_test_id("working")).to_have_count(0)


def test_an_image_goes_with_the_prompt(page: Page, daemon: Daemon) -> None:
    """Attached (scaled down: 2000 px), sent before the text, shown, and replayed after a reload."""
    open_run(page, daemon)
    shot: FilePayload = {"name": "shot.png", "mimeType": "image/png", "buffer": png(2000, 1000)}
    page.get_by_test_id("image-input").set_input_files(shot)
    expect(page.get_by_test_id("attached-images").locator("img")).to_have_count(1)
    say(page, "report")
    report = page.get_by_test_id("agent-message").last
    told = json.dumps([FILTERED_NETWORK, "(image image/png)", "report"])  # a filtered network's
    expect(report).to_contain_text(f'"prompt": {told}')
    expect(page.get_by_test_id("attached-images")).to_have_count(0)
    expect(page.get_by_test_id("user-image")).to_have_count(1)
    page.reload()
    expect(page.get_by_test_id("user-image")).to_have_count(1)  # from the session's log


def test_at_names_a_file_of_the_folder(page: Page, daemon: Daemon) -> None:
    """`@` lists the folder's files, narrowed as one types; Enter puts the path in the text."""
    folder = daemon.make_scope()
    (folder / "src").mkdir()
    (folder / "src" / "app.py").write_text("print('hi')\n")
    (folder / "README.md").write_text("# hi\n")
    open_run(page, daemon, folder)
    prompt = page.get_by_label("prompt")
    prompt.press_sequentially("look at @")
    expect(page.get_by_test_id("file-suggestions")).to_contain_text("README.md")
    prompt.press_sequentially("ap")
    expect(page.get_by_test_id("file-suggestions").get_by_role("option")).to_have_count(1)
    prompt.press("Enter")  # picks, does not send
    expect(prompt).to_have_value("look at @src/app.py ")
    prompt.press("Shift+Enter")
    prompt.press_sequentially("report")
    prompt.press("Enter")
    report = page.get_by_test_id("agent-message").last
    told = json.dumps([f"{FILTERED_NETWORK}\n\nlook at @src/app.py \nreport"])  # filtered
    expect(report).to_contain_text(f'"prompt": {told}')
