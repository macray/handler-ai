"""What agents are given, in the web UI: caches, folders, connections, tools, skills, accounts, providers.

Skipped when podman, the image or the built UI is missing."""

import re
import zipfile
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from ...support import dev_env
from ...support.daemon import Daemon
from ...support.models_server import ModelsServer
from ..browser import PW_IMAGE, image_present
from .ui import UI_BUILT, create_project, open_new_skill

pytestmark = [
    pytest.mark.skipif(not UI_BUILT, reason="web UI not built (scripts/build-web-ui.sh)"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


def test_caches_listed_measured_emptied_and_added(page: Page, daemon: Daemon) -> None:
    """D.8 in the UI: the total and each cache's, by one name; a folder opened by a click anywhere
    on its row, a cache emptied after an in-app confirmation; what a removed cache left freed
    apart; a project's choice changed from its chip; one added is saved at once (in the test
    daemon's own folders)."""
    toolbox = daemon.config_dir / "toolbox" / "toolbox.toml"
    before = toolbox.read_text()
    npm, left = daemon.cache_dir / "npm", daemon.cache_dir / "old-cache"
    for folder in (npm, left):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "pkg.tgz").write_bytes(b"x" * 2_000_000)
    project = create_project(daemon, daemon.make_scope(), name="cached", caches="off")
    try:
        page.goto(f"{daemon.base_url}/#/settings/caches")
        section = page.get_by_test_id("caches")
        expect(section.get_by_test_id("caches-total")).to_be_visible()
        expect(section.get_by_test_id("caches-legend")).to_contain_text("npm packages")
        npm_row = section.get_by_test_id("cache").filter(has_text="~/.npm")
        expect(npm_row.get_by_test_id("cache-declared-by")).to_have_text("Handler")
        # what a removed cache left: freed alone
        leftover = section.get_by_test_id("caches-leftover").filter(has_text="old-cache")
        leftover.get_by_test_id("caches-free").click()
        page.get_by_test_id("cache-confirm-button").click()
        expect(leftover).to_have_count(0)
        assert not left.exists() and npm.is_dir()
        # the global folder opened from its size, not only its name
        shared = section.get_by_test_id("cache-folders").filter(has_text="Global")
        shared.get_by_test_id("cache-folders-size").click()
        expect(shared.get_by_test_id("cache-folders-path")).to_have_text(str(daemon.cache_dir))
        row = shared.get_by_test_id("cache-folder").filter(has_text="~/.npm")
        expect(row.get_by_test_id("cache-size")).to_have_text("2.0 MB")
        row.get_by_test_id("cache-empty").click()
        page.get_by_test_id("cache-confirm-button").click()
        expect(row.get_by_test_id("cache-size")).to_have_text("empty")
        assert list(npm.iterdir()) == []
        # a project without caches moved to the global ones from its chip
        section.get_by_test_id("caches-off").filter(has_text="cached").get_by_test_id(
            "cache-mode"
        ).click()
        page.get_by_test_id("cache-mode-global").click()
        expect(shared.get_by_test_id("cache-mode").filter(has_text="cached")).to_be_visible()
        with daemon.http() as c:
            assert c.get(f"/v1/projects/{project['id']}").json()["caches"] == "global"
        section.get_by_test_id("cache-new").click()
        section.get_by_test_id("cache-about-input").fill("Gradle's packages")
        section.get_by_test_id("cache-target-input").fill("~/.gradle")
        section.get_by_test_id("cache-add").click()
        expect(
            section.get_by_test_id("caches-kept").get_by_test_id("cache-name").last
        ).to_have_text("Gradle's packages")
        assert '[[caches]]\ntarget = "~/.gradle"' in toolbox.read_text()
    finally:
        toolbox.write_text(before)
        with daemon.http() as c:
            c.delete(f"/v1/projects/{project['id']}")


def test_work_folders_edited(page: Page, daemon: Daemon) -> None:
    """D.13 in the UI: each change saved at once; handler's own folders refused; a folder says
    whether it holds projects, or does not exist."""
    extra = daemon.make_scope()
    try:
        page.goto(f"{daemon.base_url}/#/settings/folders")
        form = page.get_by_test_id("folders")
        expect(form.get_by_test_id("work-folder")).to_have_text([str(daemon.scope_root)])
        form.get_by_test_id("work-folder-new").click()
        form.get_by_test_id("work-folder-input").fill(str(daemon.config_dir))
        form.get_by_test_id("work-folder-add").click()
        expect(form.get_by_test_id("work-folder-error")).to_contain_text("the daemon's own files")
        form.get_by_test_id("work-folder-input").fill(str(extra))
        form.get_by_test_id("work-folder-add").click()
        expect(form.get_by_test_id("work-folder")).to_have_text(
            [str(daemon.scope_root), str(extra)]
        )
        expect(form.get_by_test_id("work-folder-state").last).to_have_text("no project in it yet")
        with daemon.http() as c:
            listed = [f["root"] for f in c.get("/v1/folders").json()["folders"]]
            assert listed == [str(daemon.scope_root), str(extra)]
        form.get_by_test_id("work-folder-new").click()
        form.get_by_test_id("work-folder-input").fill(f"{extra}-missing")
        form.get_by_test_id("work-folder-add").click()
        expect(form.get_by_test_id("work-folder-state").last).to_have_text(
            "does not exist on this computer"
        )
        form.get_by_role("button", name=f"Remove {extra}-missing").click()
        expect(form.get_by_test_id("work-folder")).to_have_count(2)
    finally:
        with daemon.http() as c:
            c.put("/v1/folders", json={"roots": [str(daemon.scope_root)]}).raise_for_status()


def test_binding_created_edited_and_deleted(page: Page, daemon: Daemon) -> None:
    """G.2, D.15 in the UI: a connection of a tool from its slots, on the tool's page; its secret
    goes to the store and is shown sealed."""
    page.goto(f"{daemon.base_url}/#/library/tools")
    tool = page.get_by_test_id("addon-card").filter(has_text="fake-shop")
    expect(tool.get_by_test_id("addon-state")).to_have_text("Not set up")
    tool.get_by_test_id("tool-set-up").click()
    page.get_by_test_id("new-binding").click()
    form = page.get_by_test_id("binding-form")
    expect(form.get_by_test_id("binding-name")).to_have_value("fake-shop")
    expect(form.get_by_test_id("binding-save")).to_be_disabled()  # its store is required
    form.get_by_test_id("binding-setting-store").fill("dev.shop.example.com")
    form.get_by_test_id("binding-secret-theme_token").fill("shptka_not_real")
    form.get_by_test_id("binding-save").click()
    row = page.get_by_test_id("binding-row").filter(has_text="fake-shop")
    expect(row).to_contain_text("store=dev.shop.example.com")
    expect(row).to_contain_text("sealed")
    path = daemon.config_dir / "connections" / "fake-shop.toml"
    text = path.read_text()
    assert "shptka_not_real" not in text and "connections/fake-shop/theme_token" in text

    # D.14: Settings → Secrets lists it by its connection, sealed, and links to its tool's page
    page.goto(f"{daemon.base_url}/#/settings/secrets")
    used = page.get_by_test_id("secrets-used")
    secret = used.get_by_test_id("secret").filter(has_text="fake-shop")
    expect(secret.get_by_test_id("secret-hidden")).to_be_visible()
    secret.get_by_test_id("secret-open").click()
    secret.get_by_test_id("secret-change").click()
    expect(page).to_have_url(re.compile(r"#/library/tools/fake-shop$"))

    row.get_by_test_id("binding-edit").click()
    form = page.get_by_test_id("binding-form")
    form.get_by_test_id("binding-name").fill("dev-shop")
    form.get_by_test_id("binding-save").click()
    row = page.get_by_test_id("binding-row").filter(has_text="dev-shop")
    expect(row).to_contain_text("not used yet")
    row.get_by_test_id("binding-edit").click()
    page.get_by_test_id("binding-delete").click()
    page.get_by_test_id("ask-yes").click()
    expect(row).to_have_count(0)
    assert not (daemon.config_dir / "connections" / "dev-shop.toml").exists()


def test_addon_installed_then_its_first_tool(page: Page, daemon: Daemon, tmp_path: Path) -> None:
    """G.5 in the UI: from a folder (Library → Tools → Community), its preview first; once
    installed, its page opens on its first connection's form (G.2): it has a setting."""
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "tool.toml").write_text(
        'apiVersion = "handler.tool/v1"\nname = "notes"\negress = ["notes.example.com:443"]\n'
        '[settings.book]\nenv = "NOTES_BOOK"\n'
    )
    page.goto(f"{daemon.base_url}/#/library/tools/more")
    page.get_by_test_id("addon-elsewhere").click()
    page.get_by_test_id("addon-source").fill(str(folder))
    page.get_by_test_id("addon-source-look").click()
    preview = page.get_by_test_id("addon-preview")
    expect(preview).to_contain_text("notes.example.com:443")
    preview.get_by_test_id("addon-install").click()
    expect(page.get_by_test_id("tool-page")).to_contain_text("reaches 1 site")
    form = page.get_by_test_id("binding-form")
    expect(form.get_by_test_id("binding-name")).to_have_value("notes")
    form.get_by_test_id("binding-save").click()
    row = page.get_by_test_id("binding-row").filter(has_text="notes")
    expect(row.get_by_test_id("binding-use")).to_contain_text("not used yet")
    row.get_by_test_id("binding-edit").click()
    page.get_by_test_id("binding-delete").click()
    page.get_by_test_id("ask-yes").click()
    expect(row).to_have_count(0)
    page.get_by_test_id("tool-more").click()
    page.get_by_test_id("addon-remove").click()
    page.get_by_test_id("ask-yes").click()
    expect(page.get_by_test_id("addons-page")).to_be_visible()
    expect(page.get_by_test_id("addon-card").filter(has_text="notes")).to_have_count(0)


def test_addon_updated_keeps_its_configurations(page: Page, daemon: Daemon, tmp_path: Path) -> None:
    """G.5 in the UI: an update installs over the tool without opening a new connection; one it
    made invalid (a setting gone, a required one added) says Broken, and is fixed in its Edit
    (G.2)."""
    folder = tmp_path / "notes"
    folder.mkdir()
    manifest = (
        'apiVersion = "handler.tool/v1"\nname = "notes"\negress = ["notes.example.com:443"]\n'
    )
    (folder / "tool.toml").write_text(manifest + '[settings.book]\nenv = "NOTES_BOOK"\n')
    page.goto(f"{daemon.base_url}/#/library/tools/more")
    page.get_by_test_id("addon-elsewhere").click()
    page.get_by_test_id("addon-source").fill(str(folder))
    page.get_by_test_id("addon-source-look").click()
    page.get_by_test_id("addon-preview").get_by_test_id("addon-install").click()
    form = page.get_by_test_id("binding-form")
    form.get_by_test_id("binding-setting-book").fill("work")
    form.get_by_test_id("binding-save").click()
    row = page.get_by_test_id("binding-row").filter(has_text="notes")
    expect(row).to_contain_text("book=work")

    shelf = '[settings.shelf]\nenv = "NOTES_SHELF"\nrequired = true\n'  # book gone, shelf required
    (folder / "tool.toml").write_text(manifest + shelf)
    page.get_by_test_id("tool-more").click()
    page.get_by_test_id("addon-update").click()
    preview = page.get_by_test_id("addon-preview")
    expect(preview).to_contain_text("an update")
    preview.get_by_test_id("addon-install").click()
    expect(preview).to_have_count(0)
    expect(form).to_have_count(0)
    expect(row).to_contain_text("Broken")
    expect(page.get_by_test_id("tool-state")).to_have_text("Broken")

    row.get_by_test_id("binding-edit").click()
    expect(form.get_by_test_id("binding-invalid")).to_be_visible()
    form.get_by_test_id("binding-setting-shelf").fill("top")
    form.get_by_test_id("binding-save").click()
    expect(form).to_have_count(0)


def test_skill_written_on_its_page(page: Page, daemon: Daemon) -> None:
    """D.17 in the UI: a new skill's form (name, when to use it, instructions), then its page:
    a script, unsaved changes kept from a click away, the list's card, delete."""
    open_new_skill(page, daemon)
    page.get_by_test_id("skill-write").click()
    page.get_by_test_id("skill-name").fill("ui-review")
    page.get_by_test_id("skill-description").fill("Review: a diff, before committing")
    page.get_by_test_id("skill-content").fill("# Review\n\nRead the diff.\n")
    page.get_by_test_id("skill-save").click()
    expect(page).to_have_url(f"{daemon.base_url}/#/skills/ui-review")
    text = (daemon.config_dir / "skills" / "ui-review" / "SKILL.md").read_text()
    assert 'description: "Review: a diff, before committing"' in text and "Read the diff." in text

    page.get_by_test_id("skill-new-file").click()
    page.get_by_test_id("skill-new-path").fill("scripts/check.sh")
    page.get_by_test_id("skill-add-file").click()
    page.get_by_test_id("skill-file-content").fill("echo ok\n")
    page.get_by_test_id("skill-file-save").click()
    expect(page.get_by_test_id("skill-file").filter(has_text="scripts/check.sh")).to_contain_text(
        "runs"
    )

    page.get_by_text("SKILL.md", exact=True).click()
    edited = "Review a diff before committing."
    page.get_by_test_id("skill-description").fill(edited)
    page.get_by_role("link", name="Skills").first.click()
    page.get_by_test_id("ask-no").click()  # "Leave without saving?": stay
    expect(page.get_by_test_id("skill-description")).to_have_value(edited)
    page.get_by_test_id("skill-save").click()
    expect(page.get_by_test_id("skill-saved")).to_be_visible()  # nothing changed since: no Save
    page.get_by_test_id("skill-description").fill("dropped")
    page.get_by_test_id("skill-discard").click()
    expect(page.get_by_test_id("skill-description")).to_have_value(edited)

    page.get_by_role("link", name="Skills").first.click()
    card = page.get_by_test_id("skill-card").filter(has_text="ui-review")
    expect(card).to_contain_text("Review a diff before committing.")
    expect(card.get_by_test_id("skill-use")).to_contain_text("+ 1 file, 1 script")
    card.click()
    page.get_by_test_id("skill-delete").click()
    page.get_by_test_id("ask-yes").click()
    expect(page).to_have_url(f"{daemon.base_url}/#/library/skills")
    expect(page.get_by_test_id("skill-card").filter(has_text="ui-review")).to_have_count(0)


def test_skill_imported_says_it_is_in_the_library(
    page: Page, daemon: Daemon, tmp_path: Path
) -> None:
    """D.17 in the UI: an import is already in the library; its page says so, with the next
    steps (what handler found, who gets it), and no Save. Again: it replaced the skill."""
    archive = tmp_path / "ui-imported.skill"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("ui-imported/SKILL.md", "---\nname: ui-imported\ndescription: d\n---\nHi.\n")
        z.writestr("ui-imported/scripts/run.sh", "curl https://api.example.com\n")
    open_new_skill(page, daemon)
    page.get_by_test_id("import-skill-file").set_input_files(archive)
    expect(page).to_have_url(f"{daemon.base_url}/#/skills/ui-imported?imported=new")
    panel = page.get_by_test_id("skill-imported")
    expect(panel).to_contain_text("ui-imported is in your library")
    expect(panel).to_contain_text("1 host it names")
    expect(panel.get_by_test_id("skill-who")).to_contain_text("No agent uses it yet")
    expect(page.get_by_test_id("skill-saved")).to_be_visible()
    expect(page.get_by_test_id("skill-save")).to_have_count(0)
    panel.get_by_test_id("skill-imported-close").click()
    expect(page).to_have_url(f"{daemon.base_url}/#/skills/ui-imported")
    expect(page.get_by_test_id("skill-placement")).to_contain_text("No agent uses it yet")

    open_new_skill(page, daemon)
    page.get_by_test_id("import-skill-file").set_input_files(archive)
    page.get_by_test_id("ask-yes").click()  # "The skill ui-imported exists: replace?"
    expect(page).to_have_url(f"{daemon.base_url}/#/skills/ui-imported?imported=replaced")
    expect(page.get_by_test_id("skill-imported")).to_contain_text("replaced by the imported ones")
    page.get_by_test_id("skill-delete").click()
    page.get_by_test_id("ask-yes").click()
    expect(page).to_have_url(f"{daemon.base_url}/#/library/skills")


def test_skills_given_in_the_project_settings(page: Page, daemon: Daemon) -> None:
    """D.17 from the project's side: its settings add a skill from the library (saying what the
    scan found in its files) and take one back, saved with the rest."""
    md = "---\nname: {0}\ndescription: Does {0}. Use when asked.\n---\n\nSteps.\n"
    with daemon.http() as c:
        for name in ("ps-plain", "ps-scripted"):
            assert c.post("/v1/skills", json={"content": md.format(name)}).status_code == 201
        script = {"text": "#!/bin/sh\necho hi\n", "executable": True}
        assert c.put("/v1/skills/ps-scripted/files/run.sh", json=script).status_code == 200
    project = create_project(daemon, daemon.make_scope(), name="ps-project", skills=["ps-plain"])
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}/settings")
    row = page.get_by_test_id("project-skills")
    expect(row.get_by_test_id("project-skill")).to_have_text(["ps-plain"])
    row.get_by_test_id("project-skill-add").click()
    page.get_by_test_id("project-skill-pick-ps-scripted").click()
    page.get_by_test_id("project-skill-done").click()
    expect(row.get_by_test_id("project-skill")).to_have_text(["ps-plain", "ps-scripted"])
    expect(row.get_by_test_id("project-skill-findings")).to_contain_text("1 script that runs")
    row.get_by_test_id("project-skill").filter(has_text="ps-plain").get_by_test_id(
        "project-skill-remove"
    ).click()
    expect(page.get_by_test_id("project-savebar")).to_contain_text("1 change")
    page.get_by_test_id("project-save").click()
    expect(page.get_by_test_id("project-savebar")).to_have_count(0)  # saved, on its tab
    with daemon.http() as c:
        assert c.get(f"/v1/projects/{project['id']}").json()["skills"] == ["ps-scripted"]


def test_addons_given_in_the_project_settings(page: Page, daemon: Daemon) -> None:
    """G.3 from the project's side: its settings give an addon to all its agents, picked in a
    dialog (one without settings by its name), saved with the rest; its agents then have it."""
    project = create_project(daemon, daemon.make_scope(), name="pa-project")
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}/settings")
    row = page.get_by_test_id("project-addons")
    expect(row.get_by_test_id("project-addon")).to_have_count(0)
    row.get_by_test_id("project-addon-add").click()
    dialog = page.get_by_test_id("project-addon-dialog")
    dialog.locator("label").filter(has_text="app-builder").click()
    page.get_by_test_id("project-addon-done").click()
    expect(row.get_by_test_id("project-addon")).to_have_text(["app-builder"])
    page.get_by_test_id("project-save").click()
    expect(page.get_by_test_id("project-savebar")).to_have_count(0)  # saved, on its tab
    with daemon.http() as c:
        assert c.get(f"/v1/projects/{project['id']}").json()["addons"] == [{"addon": "app-builder"}]
        agent = c.get(f"/v1/agents/{project['agents'][0]['id']}").json()
        assert agent["projectAddons"] == [{"addon": "app-builder"}]


def test_skill_given_by_projects_and_saved_as_a_new_one(page: Page, daemon: Daemon) -> None:
    """D.17 in the UI: several projects give a skill to all their agents; an edit says whom it
    changes the skill for, and "Save as a new skill" keeps the change to a copy, with its files."""
    shop = create_project(daemon, daemon.make_scope(), name="ui-shop")
    create_project(daemon, daemon.make_scope(), name="ui-blog")
    with daemon.http() as c:
        md = "---\nname: ui-shared\ndescription: d\n---\nHi.\n"
        assert c.post("/v1/skills", json={"content": md}).status_code == 201
        script = {"text": "echo\n", "executable": True}
        assert c.put("/v1/skills/ui-shared/files/scripts/run.sh", json=script).status_code == 200
    page.goto(f"{daemon.base_url}/#/skills/ui-shared")
    page.get_by_test_id("skill-change-who").click()
    givers = page.get_by_test_id("skill-projects")
    givers.get_by_label("All agents of ui-shop", exact=True).click()
    givers.get_by_label("All agents of ui-blog", exact=True).click()
    page.get_by_test_id("skill-place").click()
    expect(page.get_by_test_id("skill-who")).to_contain_text("all agents of ui-shop, ui-blog")
    with daemon.http() as c:
        agent = c.get(f"/v1/agents/{shop['agents'][0]['id']}").json()
        assert agent["projectSkills"] == ["ui-shared"]

    page.get_by_test_id("skill-description").fill("Only for the shop.")
    expect(page.get_by_test_id("skill-affects")).to_contain_text("all agents of ui-shop, ui-blog")
    page.once("dialog", lambda dialog: dialog.accept("ui-shared-shop"))  # its new name
    page.get_by_test_id("skill-save-new").click()
    expect(page).to_have_url(f"{daemon.base_url}/#/skills/ui-shared-shop")
    expect(page.get_by_test_id("skill-description")).to_have_value("Only for the shop.")
    expect(page.get_by_test_id("skill-file").filter(has_text="scripts/run.sh")).to_be_visible()
    expect(page.get_by_test_id("skill-who")).to_contain_text("No agent uses it yet")
    original = (daemon.config_dir / "skills" / "ui-shared" / "SKILL.md").read_text()
    assert "description: d" in original


def test_account_created_and_logged_in_in_a_terminal_window(page: Page, daemon: Daemon) -> None:
    """D.9 in the UI: started from Model access's subscriptions, its name suggested, the
    person's to change; a file login: handlerd opens a terminal window for it (here a stand-in
    that types the code; on the host, as the harness has a login there), and the card follows the
    account until it is logged in."""
    page.goto(f"{daemon.base_url}/#/settings/models")
    page.get_by_test_id("add-account").click()
    page.get_by_test_id("connect-subscription").filter(has_text="Login box").click()
    form = page.get_by_test_id("account-form")
    expect(form.get_by_test_id("account-name")).to_have_value("login")  # suggested
    form.get_by_test_id("account-name").fill("box2")
    form.get_by_test_id("account-create").click()
    card = page.get_by_test_id("account-card").filter(has_text="box2")
    expect(page.get_by_test_id("account-login-window")).to_contain_text("fake-terminal")
    expect(card.get_by_test_id("account-status")).to_have_text("● Logged in", timeout=180_000)
    expect(page.get_by_test_id("account-login")).to_have_count(
        0
    )  # its dialog closed once it changed
    kept = daemon.data_dir / "accounts" / "box2" / "login" / "credential"
    assert kept.read_text().strip() == "typed-in-the-window"
    card.get_by_test_id("account-edit").click()
    page.get_by_test_id("account-delete").click()
    page.get_by_test_id("ask-yes").click()
    expect(card).to_have_count(0)


def test_account_with_a_token_the_person_gives(page: Page, daemon: Daemon) -> None:
    """D.9 in the UI: a token login is the person's to run (handler shows its command, opens no
    terminal); its token is given in the dialog that makes the account, pasted, or, behind "Keep
    it elsewhere", where they keep it; a logged-in account logs in again from its Edit."""
    page.goto(f"{daemon.base_url}/#/settings/models")
    page.get_by_test_id("add-account").click()
    page.get_by_test_id("connect-subscription").filter(has_text="Echo").click()
    form = page.get_by_test_id("account-form")
    expect(form.get_by_test_id("account-token-steps")).to_contain_text("echo-box setup-token")
    form.get_by_test_id("account-name").fill("echo-perso")
    expect(form.get_by_test_id("account-create")).to_be_disabled()  # its token first
    form.get_by_test_id("secret-source-text").fill("tok-pasted")
    form.get_by_test_id("account-create").click()
    card = page.get_by_test_id("account-card").filter(has_text="echo-perso")
    expect(card.get_by_test_id("account-status")).to_have_text(
        "● Logged in · token kept by Handler"
    )
    expect(page.get_by_test_id("account-login-window")).to_have_count(0)
    expect(card.get_by_test_id("account-log-in")).to_have_count(0)  # nothing to do on its line
    card.get_by_test_id("account-edit").click()
    page.get_by_test_id("account-log-in-again").click()  # New token: from a command this time
    token = page.get_by_test_id("account-token-form")
    expect(token.get_by_test_id("secret-source-kind")).to_have_count(0)  # folded
    token.get_by_test_id("secret-source-elsewhere").click()
    token.get_by_test_id("secret-source-kind").select_option("command")
    token.get_by_test_id("secret-source-text").fill("pass show echo")
    token.get_by_test_id("account-token-save").click()
    expect(card.get_by_test_id("account-status")).to_have_text("● Logged in · token from a command")
    assert (
        'command = ["pass", "show", "echo"]'
        in (daemon.accounts_dir / "echo-perso.toml").read_text()
    )
    card.get_by_test_id("account-edit").click()
    page.get_by_test_id("account-delete").click()
    page.get_by_test_id("ask-yes").click()
    expect(card).to_have_count(0)


def test_provider_from_a_template_edited_and_deleted(page: Page, daemon: Daemon) -> None:
    """D.12 in the UI: started from Model access's APIs, the form starts from a template; the
    key goes to the secret store."""
    page.goto(f"{daemon.base_url}/#/settings/models")
    page.get_by_test_id("add-provider").click()
    page.get_by_test_id("connect-api").filter(has_text="OpenRouter").click()
    form = page.get_by_test_id("provider-form")
    expect(form.get_by_test_id("provider-name")).to_have_value("openrouter")
    form.get_by_test_id("provider-key").fill("sk-or-not-real")
    form.get_by_test_id("provider-save").click()
    card = page.get_by_test_id("provider-card").filter(has_text="openrouter")
    expect(card.get_by_test_id("provider-status")).to_have_text("● Ready")
    text = (daemon.providers_dir / "openrouter.toml").read_text()
    assert "sk-or-not-real" not in text and 'secret = "providers/openrouter/apiKey"' in text

    card.get_by_test_id("provider-edit").click()
    form = page.get_by_test_id("provider-form")
    form.get_by_test_id("provider-name").fill("router")
    models = form.get_by_test_id("provider-model")
    count = models.count()
    form.get_by_role("button", name="Add a model").click()
    expect(models).to_have_count(count + 1)
    models.last.get_by_placeholder("id").fill("extra/model")
    form.get_by_test_id("provider-save").click()
    card = page.get_by_test_id("provider-card").filter(has_text="router")
    expect(card.get_by_test_id("provider-status")).to_have_text("● Ready")  # its key followed
    renamed = page.get_by_test_id("provider-card").filter(
        has=page.get_by_text("router", exact=True)
    )
    expect(renamed).to_have_count(1)
    assert "extra/model" in (daemon.providers_dir / "router.toml").read_text()
    card.get_by_test_id("provider-edit").click()
    page.get_by_test_id("provider-delete").click()
    page.get_by_test_id("ask-yes").click()
    expect(card).to_have_count(0)


@pytest.mark.rule("provider.tested-from-where-agents-reach-it")
def test_a_provider_that_redirects_to_https_is_told_in_its_form(page: Page, daemon: Daemon) -> None:
    """D.12 in the UI: an endpoint whose server answers `http://` with a 308 to `https://` is not
    reached; the form says where it redirects, why agents are not, and offers the `https://`
    endpoint, which *Use* puts in place of the typed one (then tested again)."""
    server = ModelsServer([{"id": "m"}], redirect=True)
    https = "https://127.0.0.1/v1"
    try:
        page.goto(f"{daemon.base_url}/#/settings/models")
        page.get_by_test_id("add-provider").click()
        page.get_by_test_id("connect-api").filter(has_text="llama.cpp").click()
        form = page.get_by_test_id("provider-form")
        for protocol in ("openai-chat", "responses"):
            form.get_by_test_id(f"provider-endpoint-{protocol}").fill(server.endpoint())
        form.get_by_test_id("provider-test").click()
        reach = form.get_by_test_id("provider-reach")
        expect(reach).to_have_attribute("data-state", "not reached")
        expect(reach).to_contain_text(
            f"Not reached: host.containers.internal:{server.port} redirects to https://"
        )
        redirect = form.get_by_test_id("provider-redirect")
        expect(redirect).to_contain_text(f"Use {https} as its endpoint: agents are not redirected")
        use = form.get_by_test_id("provider-use-redirect")
        expect(use).to_have_text(f"Use {https}")
        use.click()
        for protocol in ("openai-chat", "responses"):
            expect(form.get_by_test_id(f"provider-endpoint-{protocol}")).to_have_value(https)
        expect(reach).to_have_attribute("data-state", "not reached")  # nothing on its 443
        expect(redirect).to_have_count(0)
    finally:
        server.close()


@pytest.mark.rule("provider.tested-from-where-agents-reach-it")
def test_a_local_provider_is_tested_in_its_form(page: Page, daemon: Daemon) -> None:
    """D.12 in the UI: llama.cpp's form says where its server must listen; Test says not reached
    while it listens nowhere a sandbox reaches, then fills the model and its context from what it
    serves; saved, it is ready (a server on this computer never tested is not)."""
    loopback = ModelsServer([{"id": "qwen-coder"}], listen="127.0.0.1")
    server = ModelsServer([{"id": "qwen-coder", "max_model_len": 32768}])
    try:
        page.goto(f"{daemon.base_url}/#/settings/models")
        page.get_by_test_id("add-provider").click()
        page.get_by_test_id("connect-api").filter(has_text="llama.cpp").click()
        form = page.get_by_test_id("provider-form")
        expect(form.get_by_test_id("provider-listen")).to_contain_text("--host 0.0.0.0 --jinja")
        expect(form.get_by_test_id("provider-model")).to_have_count(0)
        expect(form.get_by_test_id("provider-no-model")).to_be_visible()
        expect(form.get_by_test_id("provider-save")).to_be_disabled()
        reach = form.get_by_test_id("provider-reach")
        expect(reach).to_have_attribute("data-state", "untested")

        for protocol in ("openai-chat", "responses"):
            form.get_by_test_id(f"provider-endpoint-{protocol}").fill(loopback.endpoint())
        form.get_by_test_id("provider-test").click()
        expect(reach).to_have_attribute("data-state", "not reached")
        expect(reach).to_contain_text(
            f"Not reached: nothing answered at host.containers.internal:{loopback.port}"
        )

        for protocol in ("openai-chat", "responses"):
            form.get_by_test_id(f"provider-endpoint-{protocol}").fill(server.endpoint())
        expect(reach).to_have_attribute("data-state", "untested")  # of other endpoints
        form.get_by_test_id("provider-test").click()
        expect(reach).to_have_attribute("data-state", "ready")
        expect(reach).to_have_text(
            f"Ready: host.containers.internal:{server.port} answered, 1 model"
        )
        model = form.get_by_test_id("provider-model")
        expect(model).to_have_count(1)
        expect(model.get_by_placeholder("id")).to_have_value("qwen-coder")
        expect(model.get_by_placeholder("tokens")).to_have_value("32768")
        form.get_by_test_id("provider-name").fill("tested-here")
        form.get_by_test_id("provider-save").click()
        card = page.get_by_test_id("provider-card").filter(has_text="tested-here")
        expect(card.get_by_test_id("provider-status")).to_have_text("● Ready")
    finally:
        loopback.close()
        server.close()
    card.get_by_test_id("provider-card-test").click()  # its server stopped
    expect(card.get_by_test_id("provider-status")).to_have_text("● Not reached")
    expect(card.get_by_test_id("provider-not-reached")).to_contain_text("nothing answered")
    with daemon.http() as c:
        assert c.delete("/v1/providers/tested-here").status_code == 204
