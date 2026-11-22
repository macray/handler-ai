"""What the web UI's tests share: the steps a person takes in the UI, and the API calls that set a
scene up."""

import re
import struct
import zlib
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from handler_control.settings import TEMPLATES, WEB_UI

from ...support.daemon import Daemon

UI_BUILT = (WEB_UI / "index.html").is_file()
APP_CREATOR = {"kind": "handler-need", "name": "app-creator", "version": 1}  # the App creators'


def set_knowledge_root(daemon: Daemon, root: Path) -> None:
    with daemon.http() as c:
        c.put("/v1/knowledge/root", json={"root": str(root), "create": True}).raise_for_status()


def pick_account(page: Page, account: str, within: Locator | None = None) -> None:
    """Who works (E2) on a set-up page, the page's first or the one in `within`: that account."""
    pick_access(page, account, (within or page).get_by_test_id("model-choice").first)


def choose_account(page: Page, account: str) -> None:
    """The agent form's Who works: its account menu, then that account."""
    page.get_by_test_id("agent-model").get_by_test_id("model-choice-access").click()
    row = page.get_by_test_id("model-choice-access-row")
    row.filter(has=page.get_by_text(account, exact=True)).click()
    page.keyboard.press("Escape")


def choose_helper_account(page: Page, account: str, card: Locator | None = None) -> None:
    """A helper's set-up card (the page's only one, or `card`): Who works, its account menu,
    then that account."""
    chip = (card or page.get_by_test_id("helper-card")).get_by_test_id("model-choice-access")
    row = page.get_by_test_id("model-choice-access-row").filter(
        has=page.get_by_text(account, exact=True)
    )
    for _ in range(3):  # the menu may close while the page loads around it: open it again
        if not row.is_visible():
            chip.click()
        try:
            row.click(timeout=5_000)
            break
        except PlaywrightTimeoutError:
            continue
    page.keyboard.press("Escape")
    expect(chip).to_contain_text(account)


def new_project_page(page: Page, daemon: Daemon, folder: Path) -> None:
    """New project, on another folder than the recent ones."""
    page.goto(f"{daemon.base_url}/#/projects/new")
    page.get_by_test_id("project-folder-other").click()
    page.get_by_label("folder path").fill(str(folder))


def new_project(page: Page, daemon: Daemon, account: str, folder: Path) -> None:
    """A new project on that folder (made alone), then its first agent set up from its page, on
    that account."""
    new_project_page(page, daemon, folder)
    page.get_by_test_id("project-save").click()
    page.get_by_test_id("no-agent-set-up").click()
    choose_account(page, account)
    page.get_by_test_id("agent-save").click()
    expect(page.get_by_test_id("project-agents")).to_contain_text("Assistant")


def create_project(daemon: Daemon, folder: Path, **body: Any) -> dict[str, Any]:
    with daemon.http() as c:
        body = {
            "folder": str(folder),
            "agents": [{"model": {"account": "fake"}, "name": "dev"}],
        } | body
        r = c.post("/v1/projects", json=body)
        assert r.status_code == 201, r.text
        return r.json()


def open_run(page: Page, daemon: Daemon, folder: Path | None = None) -> None:
    """A new project (the fake agent on a new folder), then an empty chat session on it."""
    new_project(page, daemon, "fake", folder or daemon.make_scope())
    page.get_by_test_id("project-start-button").click()
    expect(page.get_by_test_id("mode-select")).to_have_value("yolo")  # P7, seen in the UI


def bell_items(page: Page, folder: Path, kind: str = "bell-waiting") -> Locator:
    """The bell's list opened, its items in `folder` (other tests' sessions are listed too)."""
    if not page.get_by_test_id("bell-list").is_visible():
        page.get_by_test_id("bell").click()
    titled = f'[title$="{folder}"]'
    return (
        page.get_by_test_id(kind)
        .filter(has=page.locator(titled))
        .or_(page.locator(f'[data-testid="{kind}"]{titled}'))
    )


def pin(daemon: Daemon, project_id: str) -> None:
    """The project in the menu's Pinned, last (only the first project is pinned by itself: on a
    fresh daemon, it is already there, and a list naming it twice is refused)."""
    mine = {"kind": "project", "id": project_id}
    with daemon.http() as c:
        items = [i for i in c.get("/v1/pins").json()["items"] if i != mine] + [mine]
        assert c.put("/v1/pins", json={"items": items}).status_code == 200


def project_of(daemon: Daemon, folder: Path) -> dict:
    with daemon.http() as c:
        return next(p for p in c.get("/v1/projects").json() if p["folder"] == str(folder))


def open_new_skill(page: Page, daemon: Daemon) -> None:
    """Library → Skills → Community: its ways to make or import a skill."""
    page.goto(f"{daemon.base_url}/#/library/skills/more")
    expect(page.get_by_test_id("skill-new")).to_be_visible()


def say(page: Page, text: str) -> None:
    page.get_by_label("prompt").fill(text)
    page.get_by_label("prompt").press("Enter")


def png(width: int, height: int) -> bytes:
    """A plain grey PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)  # 8-bit greyscale
    rows = b"".join(b"\0" + b"\x80" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + (chunk(b"IEND", b""))
    )


def pick_program(page: Page, product: str) -> None:
    """The box's program chip: its menu, then a program by its product name."""
    page.get_by_test_id("model-choice-harness").click()
    page.get_by_test_id("model-choice-program").filter(has_text=product).click()


def pick_access(page: Page, name: str, within: Locator) -> None:
    """Who works (E2) in `within`: its account part's menu, then that account or provider."""
    within.get_by_test_id("model-choice-access").click()
    row = page.get_by_test_id("model-choice-access-row")
    row.filter(has=page.get_by_text(name, exact=True)).click()
    expect(within.get_by_test_id("model-choice-access")).to_contain_text(name)


def local_provider(daemon: Daemon, *models: str) -> None:
    """A provider `llamacpp` from its template (which has no model: picked from what the server
    serves), serving `models`."""
    template = (TEMPLATES / "providers" / "llamacpp.toml").read_text()
    served = "".join(f'\n[[models]]\nid = "{m}"\n' for m in models)
    (daemon.providers_dir / "llamacpp.toml").write_text(template + served)


def under_the_hood(page: Page) -> None:
    """Settings → Sandboxes: Under the hood unfolded (open by itself when an image is not built)."""
    hood = page.get_by_test_id("under-the-hood")
    expect(hood.get_by_test_id("toolbox")).to_have_count(1, timeout=30_000)  # listing images: slow
    if hood.get_attribute("open") is None:
        hood.locator("> summary").click()


def library_skill(daemon: Daemon, name: str) -> None:
    md = f"---\nname: {name}\ndescription: Does {name} things.\n---\n\nRun the script.\n"
    with daemon.http() as c:
        if c.get(f"/v1/skills/{name}").status_code == 404:
            c.post("/v1/skills", json={"content": md}).raise_for_status()
        script = {"text": "echo hi\nrm -rf ~/.ssh\n", "executable": True}
        c.put(f"/v1/skills/{name}/files/scripts/run.sh", json=script).raise_for_status()


def given_everything(page: Page, daemon: Daemon, tasks: Path) -> None:
    """The app given its folder and who works on its job: its suggested automation left on made
    at Install (on), its optional one made from its page (off, running its job), turned on and
    off there; both go when it is uninstalled (H.14)."""
    card = page.get_by_test_id("app-card").filter(has_text="needs-e2e")
    expect(card.get_by_test_id("app-needs-missing")).to_have_count(0)  # given everything
    card.hover()  # its ⋯ → Manage in Library: its page's Settings, its suggested automation made off
    card.get_by_test_id("app-more").click()
    page.get_by_test_id("app-menu").get_by_test_id("app-manage").click()
    first = page.get_by_test_id("app-suggest").filter(has_text="What to do next, every 5 hours")
    expect(first.get_by_test_id("app-suggest-on")).to_have_attribute("aria-checked", "true")
    suggested = page.get_by_test_id("app-suggest").filter(has_text="Weekly review")
    suggested.get_by_test_id("app-suggest-make").click()
    expect(suggested.get_by_test_id("app-suggest-on")).to_have_attribute("aria-checked", "false")
    page.keyboard.press("Escape")
    weekly, every = "needs-e2e-weekly-review", "needs-e2e-what-to-do-next-every-5-hours"
    with daemon.http() as c:
        made = c.get(f"/v1/automations/{weekly}").json()
    run = made["definition"]["run"]
    assert (run["app"], run["job"], made["enabled"]) == ("needs-e2e", "plan", False)

    suggested.get_by_test_id("app-suggest-on").click()  # on, then off again, from its page
    expect(suggested.get_by_test_id("app-suggest-on")).to_have_attribute("aria-checked", "true")
    with daemon.http() as c:
        assert c.get(f"/v1/automations/{weekly}").json()["enabled"]
    suggested.get_by_test_id("app-suggest-on").click()
    expect(suggested.get_by_test_id("app-suggest-on")).to_have_attribute("aria-checked", "false")

    # Uninstall (H.6): it says that its own data goes and your folder stays, then takes its parts
    page.goto(f"{daemon.base_url}/#/apps/needs-e2e")
    page.get_by_test_id("app-page-more").click()  # its ⋯
    page.get_by_test_id("app-uninstall").click()
    confirm = page.get_by_test_id("app-confirm")
    expect(confirm.get_by_test_id("app-uninstall-data")).to_contain_text("cannot be brought back")
    expect(confirm).to_contain_text(f"your folders, as they are ({tasks})")
    confirm.get_by_test_id("app-confirm-go").click()
    expect(page).to_have_url(re.compile(r"#/apps$"))
    with daemon.http() as c:
        assert c.get("/v1/apps/needs-e2e").status_code == 404
        names = {a["name"] for a in c.get("/v1/automations").json()}
        assert not names & {weekly, every}  # the automations running its job went with it
    assert tasks.is_dir()
