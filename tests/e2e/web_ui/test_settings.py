"""The Projects page, Under the hood, the toolbox, connections and knowledge given to agents.

Skipped when podman, the image or the built UI is missing."""

import json
import re
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from handler_control import runtime
from handler_harness import images

from ...support import dev_env
from ...support.daemon import Daemon, start_daemon
from ..browser import PW_IMAGE, image_present
from .ui import UI_BUILT, create_project, set_knowledge_root, under_the_hood

pytestmark = [
    pytest.mark.skipif(not UI_BUILT, reason="web UI not built (scripts/build-web-ui.sh)"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


@pytest.fixture(scope="module")
def configurable(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Daemon]:
    """A daemon whose notes root you change (no HANDLER_NOTES_DIR), in a home of its own."""
    home = tmp_path_factory.mktemp("home")
    yield from start_daemon(extra_env={"HANDLER_NOTES_DIR": "", "HOME": str(home)})


@pytest.fixture
def notes_page(browser: Browser, configurable: Daemon) -> Iterator[Page]:
    context = browser.new_context()
    page = context.new_page()
    page.goto(configurable.ui_url())
    yield page
    context.close()


def test_projects_filter_pin_open_start_and_edit(page: Page, daemon: Daemon) -> None:
    """Projects: every project by name; type to filter; a pin puts one in the menu's Pinned and
    takes it off (Undo puts it back); open, start; rename the agent and the project (same ids)."""
    create_project(daemon, daemon.make_scope(), name="first")  # pinned by itself, as the first
    alpha = create_project(daemon, daemon.make_scope(), name="lst-alpha")
    create_project(daemon, daemon.make_scope(), name="lst-beta")
    page.goto(f"{daemon.base_url}/#/projects")
    page.reload()  # created after the page loaded
    menu = page.get_by_test_id("sidebar-project").filter(has_text="lst-alpha")
    expect(menu).to_have_count(0)  # not the first project: not pinned by itself
    page.get_by_test_id("project-search").fill("lst-")
    names = page.get_by_test_id("project-row").get_by_test_id("project-name")
    expect(names).to_have_text(["lst-alpha", "lst-beta"])  # by name
    first = page.get_by_test_id("project-row").first
    first.get_by_test_id("project-pin").click()
    expect(menu).to_have_count(1)
    first.get_by_test_id("project-pin").click()
    expect(menu).to_have_count(0)
    page.get_by_test_id("unpinned-undo").click()
    expect(menu).to_have_count(1)
    with daemon.http() as c:
        pinned = c.get("/v1/pins").json()["items"]
        assert {"kind": "project", "id": alpha["id"]} in pinned
    first.get_by_test_id("project-pin").click()
    expect(menu).to_have_count(0)
    page.get_by_test_id("project-search").fill("lst-alpha")
    expect(page.get_by_test_id("project-row")).to_have_count(1)
    first.get_by_test_id("project-name").click()
    page.get_by_test_id("project-start-button").click()
    expect(page.get_by_test_id("mode-select")).to_have_value("yolo")
    page.get_by_test_id("projects-link").click()
    page.get_by_test_id("project-search").fill("lst-alpha")
    page.get_by_test_id("project-row").first.get_by_test_id("project-name").click()
    page.get_by_test_id("agent-edit").click()
    page.get_by_test_id("agent-name-input").fill("coder")
    page.get_by_test_id("agent-save").click()
    expect(page.get_by_test_id("agent-row")).to_contain_text("coder")
    page.get_by_test_id("project-edit").click()
    expect(page.get_by_test_id("project-savebar")).to_have_count(0)  # shown once something changed
    page.get_by_test_id("project-name").fill("alpha-renamed")
    expect(page.get_by_test_id("project-savebar")).to_contain_text("1 change")
    page.get_by_test_id("project-save").click()
    expect(page.get_by_role("heading", name="alpha-renamed")).to_be_visible()
    with daemon.http() as c:
        saved = c.get(f"/v1/projects/{alpha['id']}").json()
    assert (saved["name"], saved["agents"][0]["name"]) == ("alpha-renamed", "coder")


def test_harness_images_and_a_failed_rebuild(page: Page, daemon: Daemon) -> None:
    """D.4 in the UI: installed versions are listed; a failed rebuild shows its error and log
    (its panel brought into view: the Build buttons are below it), and the page follows it again
    after a reload. The fake harness has no Containerfile, so its rebuild fails fast and offline."""
    missing = daemon.config_dir.parent / "fake-ran" / "harness-image-missing"
    missing.touch()  # the fake harness's image, not built
    try:
        page.goto(f"{daemon.base_url}/#/settings/sandboxes")
        under_the_hood(page)
        rows = page.get_by_test_id("harness-image-row")
        if runtime.exists(images.ref("localhost/handler-ai-vibe", images.LATEST)):
            vibe = rows.filter(has_text="localhost/handler-ai-vibe")
            expect(vibe.get_by_test_id("harness-version")).to_contain_text("Mistral Vibe")
        fake = rows.filter(has_text="localhost/handler-ai-test-fake")
        # removed "by hand": handlerd may show it as found for runtime.IMAGE_TTL (an earlier
        # test of the file started it); a reload past that says it is gone
        deadline = time.monotonic() + runtime.IMAGE_TTL + 20
        while fake.get_by_test_id("harness-version").inner_text() != "not built yet":
            assert time.monotonic() < deadline, "the image removed by hand still shown as built"
            page.wait_for_timeout(1000)
            page.reload()
            under_the_hood(page)
        expect(fake.get_by_test_id("harness-version")).to_have_text("not built yet")
    finally:
        missing.unlink()
    fake.get_by_role("button", name="Build").click()
    panel = page.get_by_test_id("build-panel")
    expect(panel).to_be_in_viewport()
    expect(panel).to_be_focused()
    expect(page.get_by_test_id("build-state")).to_contain_text("failed", timeout=60_000)
    expect(page.get_by_test_id("build-error")).to_be_visible()
    expect(page.get_by_test_id("build-log")).to_contain_text("failed:")
    page.reload()
    expect(page.get_by_test_id("build-error")).to_be_visible()


def test_the_toolbox_made_of_system_packages_and_your_lines(page: Page, daemon: Daemon) -> None:
    """B.7 in the UI: the system packages, each saying what it gives and who needs it, turned on
    (after saying it runs as root for every agent) and off; your lines saved; the generated
    Containerfile shown folded. Nothing is built: the test daemon has no toolbox."""
    folder = daemon.config_dir / "toolbox"
    before = (folder / "toolbox.toml").read_text()
    try:
        page.goto(f"{daemon.base_url}/#/settings/sandboxes")
        under_the_hood(page)
        section = page.get_by_test_id("toolbox")
        rows = section.get_by_test_id("system-package")
        expect(rows.get_by_test_id("system-package-name")).to_have_text(
            ["chromium", "docker", "gcc", "podman", "wl-clipboard"]
        )
        daemons = rows.filter(has_text="docker").get_by_test_id("system-package-daemon")
        expect(daemons).to_have_text(
            "starts handler-dockerd in the sandboxes of agents that run containers or are "
            "privileged"
        )
        gcc = rows.filter(has_text="gcc")
        expect(gcc).to_contain_text("gives cc, gcc")
        gcc.get_by_test_id("system-package-toggle").click()
        page.get_by_test_id("ask-yes").click()
        expect(gcc).to_contain_text("nothing needs it now")
        assert "[systemPackages.gcc]" in (folder / "toolbox.toml").read_text()
        gcc.get_by_test_id("system-package-toggle").click()
        expect(gcc).not_to_contain_text("nothing needs it now")
        assert "gcc" not in (folder / "toolbox.toml").read_text()
        section.get_by_test_id("toolbox-needs").locator("summary").click()
        expect(section.get_by_test_id("toolbox-needs")).to_contain_text("Handler's base")
        section.get_by_test_id("toolbox-edit").click()
        section.get_by_test_id("toolbox-content").fill("RUN dnf -y install htop\n")
        section.get_by_test_id("toolbox-save").click()
        section.get_by_test_id("toolbox-containerfile").locator("summary").click()
        expect(section.get_by_test_id("toolbox-containerfile")).to_contain_text(
            "# your lines (custom.containerfile)"
        )
        assert (folder / "custom.containerfile").read_text() == "RUN dnf -y install htop\n"
    finally:
        (folder / "toolbox.toml").write_text(before)
        (folder / "custom.containerfile").unlink(missing_ok=True)


def test_bindings_listed_and_selected_for_a_project(page: Page, daemon: Daemon) -> None:
    """G in the UI: bindings are listed under their tool (what each holds, who it is given to; a
    new one from the tool's Connect), one whose tool is gone apart, with Get and Delete; an agent's picker offers
    the addons without settings by their name and every valid binding of the others, saying which
    other projects use it; the official source's fake-shop addon backs the valid one."""
    root = daemon.config_dir / "connections"
    root.mkdir(exist_ok=True)
    (root / "shop.toml").write_text(
        'apiVersion = "handler.connection/v1"\ntool = "fake-shop"\n'
        'settings = { store = "dev.shop.example.com" }\n'
    )
    (root / "broken.toml").write_text('apiVersion = "handler.connection/v1"\ntool = "nope"\n')
    (root / "old.toml").write_text('apiVersion = "handler.connection/v1"\ntool = "gone"\n')
    page.goto(f"{daemon.base_url}/#/library/tools")
    tool = page.get_by_test_id("addon-card").filter(has_text="fake-shop")
    shop_row = tool.get_by_test_id("tool-connection").filter(has_text="shop")
    expect(shop_row).to_contain_text("dev.shop.example.com")
    expect(shop_row.get_by_test_id("connection-given")).to_have_text("not given to any agent yet")
    apart = page.get_by_test_id("connections-without-tool").get_by_test_id("binding-row")
    broken = apart.filter(has_text="broken")
    expect(broken).to_contain_text('Its tool "nope" isn\'t installed any more')
    broken.get_by_test_id("connection-get").click()  # no source offers it: Community
    expect(page).to_have_url(re.compile(r"#/library/tools/more$"))
    page.go_back()
    old = apart.filter(has_text="old")
    old.get_by_test_id("binding-delete").click()
    page.get_by_test_id("ask-yes").click()
    expect(old).to_have_count(0)
    assert not (root / "old.toml").exists()
    tool.get_by_test_id("tool-connect").click()  # Connect another: the tool's page, its form open
    expect(page.get_by_test_id("binding-form")).to_be_visible()
    page.keyboard.press("Escape")
    page.goto(f"{daemon.base_url}/#/settings/sandboxes")
    under_the_hood(page)
    expect(page.get_by_test_id("addon-image-row").filter(has_text="fake-shop")).to_be_visible()

    shop = {"addon": "fake-shop", "binding": "shop"}
    dev = {"model": {"account": "fake"}, "name": "dev", "addons": [shop]}
    create_project(
        daemon, daemon.make_scope(), name="storefront", agents=[dev | {"confirmRisks": True}]
    )
    other = create_project(daemon, daemon.make_scope())
    page.goto(f"{daemon.base_url}/#/projects/{other['id']}/agents/{other['agents'][0]['id']}")
    page.get_by_test_id("addon-picker-add").click()  # the Tools row's + Add
    picker = page.get_by_test_id("addon-picker-list")
    expect(page.get_by_test_id("agent-editor")).to_contain_text(
        "broken tool(s) or connection(s)"
    )  # listed by now
    expect(picker.locator("label").filter(has_text="app-builder")).to_be_visible()  # no setting
    row = picker.locator("label").filter(has_text="fake-shop: shop")
    expect(row.get_by_test_id("pick-note")).to_have_text("used in storefront")
    row.click()
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("addon-picker-chip")).to_contain_text("fake-shop")
    page.get_by_test_id("agent-save").click()
    expect(page.get_by_test_id("agent-editor")).to_have_count(0)
    with daemon.http() as c:
        assert c.get(f"/v1/agents/{other['agents'][0]['id']}").json()["addons"] == [shop]


@pytest.mark.rule("notes.read-only-at-its-name")
def test_knowledge_selected_for_an_agent(
    notes_page: Page, configurable: Daemon, tmp_path: Path
) -> None:
    """D.5 in the UI: the knowledge root's folders are offered; selecting a folder covers its
    sub-folders; the agent gets the checked ones, read-only unless switched to Can write, which
    is confirmed as a risk on save."""
    page, daemon = notes_page, configurable
    for folder in ("me", "projects/blog"):
        (tmp_path / "knowledge" / folder).mkdir(parents=True)
    set_knowledge_root(daemon, tmp_path / "knowledge")
    project = create_project(daemon, daemon.make_scope())
    agent = project["agents"][0]
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}/agents/{agent['id']}")
    page.get_by_test_id("knowledge-picker-add").click()  # the Notes row's + Add
    picker = page.get_by_test_id("knowledge-picker-list")
    expect(picker.get_by_test_id("knowledge-option")).to_have_count(3)  # me, projects, blog
    picker.get_by_label("projects", exact=True).click()
    expect(picker.get_by_label("blog with its parent", exact=True)).to_be_disabled()
    picker.get_by_label("me", exact=True).click()
    page.keyboard.press("Escape")
    page.get_by_label("Can write in me").click()  # read-write: amber, confirmed on save
    page.get_by_test_id("agent-save").click()
    expect(page.get_by_test_id("agent-risks")).to_contain_text("notes me read-write")
    page.get_by_test_id("agent-confirm-risks").click()
    expect(page.get_by_test_id("agent-editor")).to_have_count(0)
    with daemon.http() as c:
        assert c.get(f"/v1/agents/{agent['id']}").json()["knowledge"] == [
            {"folder": "me", "access": "write"},
            {"folder": "projects", "access": "read"},
        ]


@pytest.mark.rule("knowledge.one-schema-per-id")
def test_a_schema_added_to_the_library_and_given_to_an_agent(
    page: Page, daemon: Daemon, tmp_path: Path
) -> None:
    """D.29 in the UI: Library → Schemas adds a file under its `$id`, asks before replacing a
    different one; the agent form's Schemas row picks it, Writes on."""
    item = {"fields": {"email": {"type": "string"}}}
    first = tmp_path / "contacts.schema.json"
    first.write_text(json.dumps({"$id": "ui-contacts@1", "title": "Contacts", "item": item}))
    page.goto(f"{daemon.base_url}/#/library/schemas")
    page.get_by_test_id("add-schema-file").set_input_files(str(first))
    card = page.get_by_test_id("schema-card").filter(has_text="ui-contacts@1")
    expect(card).to_contain_text("Contacts")
    expect(page.get_by_test_id("schema-content")).to_contain_text('"ui-contacts@1"')
    other = tmp_path / "people.schema.json"
    other.write_text(json.dumps({"$id": "ui-contacts@1", "title": "People", "item": item}))
    page.get_by_test_id("add-schema-file").set_input_files(str(other))
    expect(page.get_by_test_id("ask")).to_contain_text("Replace it with people.schema.json?")
    page.get_by_test_id("ask-no").click()  # keep yours
    expect(card).to_contain_text("Contacts")
    page.get_by_test_id("add-schema-file").set_input_files(str(other))
    page.get_by_test_id("ask-yes").click()  # then replace it
    expect(card).to_contain_text("People")

    project = create_project(daemon, daemon.make_scope())
    agent = project["agents"][0]
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}/agents/{agent['id']}")
    page.get_by_test_id("schema-picker-add").click()
    page.get_by_test_id("schema-picker-list").get_by_label("ui-contacts@1").click()
    page.keyboard.press("Escape")
    page.get_by_label("Writes ui-contacts@1").click()
    page.get_by_test_id("agent-save").click()
    expect(page.get_by_test_id("agent-editor")).to_have_count(0)
    with daemon.http() as c:
        assert c.get(f"/v1/agents/{agent['id']}").json()["schemas"] == [
            {"schemaId": "ui-contacts@1", "access": "write"}
        ]


def test_knowledge_page_change_browse(
    notes_page: Page, configurable: Daemon, tmp_path: Path
) -> None:
    """D.5 in the UI: the notes folder is there from the start (nothing to set up); change it
    (the button says what it does), create a folder, read a folder's summary and a note (links
    between notes stay in the page)."""
    page, daemon = notes_page, configurable
    vault = tmp_path / "vault"
    (vault / "me").mkdir(parents=True)
    (vault / "me" / "_index.md").write_text(
        "---\nversion: 1\nsummary: My preferences.\n---\n\n# me\n\nOverview text.\n\n"
        "## Contents\n\n- [tools.md](tools.md) — Editors I use.\n"
    )
    (vault / "me" / "tools.md").write_text("# Tools\n\nZed, mostly.\n")

    page.goto(f"{daemon.base_url}/#/library")
    page.get_by_test_id("shelf-notes").click()
    expect(page.get_by_test_id("knowledge-root")).to_be_visible()  # the default, made by handlerd
    page.get_by_test_id("change-root").click()
    field = page.get_by_role("textbox", name="Folder")
    save = page.get_by_test_id("knowledge-save-root")
    field.fill("vault")
    expect(page.get_by_test_id("knowledge-error")).to_contain_text("full path")
    expect(save).to_be_disabled()
    field.fill(str(tmp_path / "fresh"))
    expect(save).to_have_text("Create this folder")
    field.fill(str(vault))
    expect(save).to_have_text("Use this folder")
    save.click()
    expect(page.get_by_test_id("knowledge-root")).to_have_text(str(vault))

    page.get_by_test_id("knowledge-new-folder").click()
    page.get_by_placeholder("name").fill("projects")
    page.get_by_role("button", name="create folder").click()
    expect(page.get_by_test_id("knowledge-folder")).to_have_count(2)  # me, projects
    expect(page.get_by_test_id("knowledge-no-index")).to_be_visible()
    assert (vault / "projects").is_dir()

    page.get_by_test_id("knowledge-folder").filter(has_text="me").click()
    expect(page.get_by_test_id("knowledge-summary")).to_have_text("My preferences.")
    content = page.get_by_test_id("knowledge-content")
    expect(content).to_contain_text("Overview text.")
    content.get_by_role("link", name="tools.md").click()
    expect(content).to_contain_text("Zed, mostly.")
    assert "note=me%2Ftools.md" in page.url
