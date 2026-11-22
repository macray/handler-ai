"""Apps given what they need, areas, Handler's helpers, sources and Discover.

Skipped when podman, the image or the built UI is missing."""

import re
from pathlib import Path

import pytest
from playwright.sync_api import FilePayload, Page, expect

from ...apps.conftest import app_file
from ...support import dev_env
from ...support.daemon import Daemon
from ..browser import PW_IMAGE, image_present
from .ui import (
    APP_CREATOR,
    UI_BUILT,
    choose_helper_account,
    create_project,
    given_everything,
    pick_access,
)

pytestmark = [
    pytest.mark.skipif(not UI_BUILT, reason="web UI not built (scripts/build-web-ui.sh)"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


@pytest.mark.rule("inbox.told-by-handlerd-alone")
def test_an_agent_run_s_results_open_an_app(page: Page, daemon: Daemon) -> None:
    """I.1, I.9: an automation names the app its agent's results open; its form shows it; the
    run's message in the inbox has "Open <app>"."""
    source = daemon.make_scope() / "planner-e2e-app"
    source.mkdir()
    (source / "app.toml").write_text(
        'apiVersion = "handler.app/v1"\nname = "planner-e2e"\nversion = "1.0.0"\n'
    )
    result = {
        "type": "object",
        "required": ["status", "summary"],
        "properties": {
            "status": {"enum": ["ok", "attention", "failed"]},
            "summary": {"type": "string"},
        },
    }
    fields = {"type": "object", "properties": {"fake": {"type": "string"}, "answer": {}}}
    body = {
        "model": {"account": "fake"},
        "name": "web-planner",
        "permissions": "bypass",
        "interface": {"fields": fields, "result": result},
    }
    answer = {"status": "attention", "summary": "Call the bank before 10."}
    definition = {
        "apiVersion": "handler.automation/v1",
        "when": {"every": "5h"},
        "app": "planner-e2e",
        "run": {"agent": "web-planner", "input": {"fields": {"fake": "valid", "answer": answer}}},
    }
    with daemon.http() as c:
        assert c.post("/v1/apps", content=app_file(source)).status_code == 201
        assert c.post("/v1/agents", json=body).status_code == 201
        r = c.post("/v1/automations", json={"name": "web-plan", "definition": definition})
        assert r.status_code == 201, r.text
        assert "which opens the app planner-e2e" in r.json()["permissions"][-1]

    page.goto(f"{daemon.base_url}/#/automations/web-plan/edit")
    expect(page.get_by_test_id("new-automation-opens")).to_have_value("planner-e2e")
    page.get_by_test_id("new-automation-opens").select_option("")
    page.get_by_test_id("automation-save").click()
    expect(page.get_by_test_id("automation-permissions")).not_to_contain_text("opens the app")
    toml = daemon.config_dir / "automations" / "web-plan" / "automation.toml"
    assert "planner-e2e" not in toml.read_text()
    page.get_by_test_id("automation-edit").click()
    page.get_by_test_id("new-automation-opens").select_option("planner-e2e")
    page.get_by_test_id("automation-save").click()
    expect(page.get_by_test_id("automation-permissions")).to_contain_text("opens the app")
    assert 'app = "planner-e2e"' in toml.read_text()

    with daemon.http() as c:
        assert c.post("/v1/automations/web-plan/try", json={}).status_code == 202
    page.goto(f"{daemon.base_url}/#/inbox")
    message = page.get_by_test_id("inbox-message").filter(has_text="Call the bank before 10.")
    expect(message).to_be_visible(timeout=60_000)
    expect(message.get_by_test_id("inbox-open-app")).to_have_text("Open planner-e2e")
    expect(message.get_by_test_id("inbox-open")).to_contain_text("See the result")
    # unread: counted at the foot of the bell's list (other tests' messages too: shared daemon)
    page.get_by_test_id("bell").click()
    expect(page.get_by_test_id("bell-inbox")).to_contain_text(re.compile(r"[1-9]\d* unread"))


@pytest.mark.rule(
    "app.uninstalled-leaves-nothing-of-it",
    "app-part.removed-with-its-app",
    "app.its-automations-shown-before-install",
    "app.optional-automation-opt-in",
    "automation.off-until-you-turn-it-on",
)
def test_an_app_is_given_what_it_needs(page: Page, daemon: Daemon) -> None:
    """H.2: an app added opens its install page: the person gives it a folder (one of no
    project), chooses who works on its jobs, sees its suggested automations running its job with
    their switches (on, an optional one off; off and disabled, saying why, while who works is an
    account whose terms refuse runs nobody follows); Install gives it both, makes and turns on the
    one left on, then deploys (here it fails: no runtime image needed for the rest), what was
    done kept."""
    source = daemon.make_scope() / "needs-e2e-app"
    (source / "jobs").mkdir(parents=True)
    (source / "app.toml").write_text(
        'apiVersion = "handler.app/v1"\nname = "needs-e2e"\nversion = "1.0.0"\n'
        '[needs.files.tasks]\ndescription = "Where your tasks are kept"\nmode = "rw"\n'
        '[jobs.plan]\ndescription = "Tells you what to do next"\nfiles = { tasks = "write" }\n'
        'worksIn = ["tasks"]\n'
        'result = { type = "object", required = ["status", "summary"], properties = '
        '{ status = { enum = ["ok", "attention", "failed"] }, summary = { type = "string" } } }\n'
        '[[automations]]\ndescription = "What to do next, every 5 hours"\n'
        'when = { every = "5h" }\nrun = { job = "plan" }\n'
        '[[automations]]\ndescription = "Weekly review"\noptional = true\n'
        'when = { at = "09:00", days = ["mon"] }\nrun = { job = "plan" }\n'
    )
    (source / "jobs" / "plan.md").write_text("Say what to do next.\n")
    tasks = daemon.make_scope() / "needs-e2e-tasks"
    tasks.mkdir()

    page.goto(f"{daemon.base_url}/#/library/apps/more")  # Install from a file
    file: FilePayload = {
        "name": "needs-e2e.zip",
        "mimeType": "application/zip",
        "buffer": app_file(source),
    }
    page.get_by_test_id("app-file").set_input_files(file)
    expect(page.get_by_test_id("install-where")).to_contain_text("Where your tasks are kept")
    suggests = page.get_by_test_id("install-suggests")
    expect(suggests).to_contain_text("every 5 hours")
    expect(suggests).to_contain_text("who you choose works")
    switches = page.get_by_test_id("install-suggest")
    expect(switches.nth(0)).to_have_attribute("aria-checked", "true")  # on: made at Install
    expect(switches.nth(1)).to_have_attribute("aria-checked", "false")  # optional: off
    # who works on an account whose terms refuse runs nobody follows (I.7), chosen before: its
    # suggestion off and disabled, saying why; on fake, on again
    with daemon.http() as c:
        own = {"program": "login-box", "account": "login-box"}
        assert c.put("/v1/apps/needs-e2e/who-works", json=own).status_code == 200
    page.reload()
    who = page.get_by_test_id("install-who-works")
    expect(switches.nth(0)).to_have_attribute("aria-checked", "false")
    expect(switches.nth(0)).to_be_disabled()
    refused = page.get_by_test_id("install-suggest-refused")  # both: the same job
    expect(refused).to_have_count(2)
    expect(refused.first).to_contain_text("login-box's terms don't allow runs nobody follows")
    expect(refused.first.get_by_test_id("disabled-fix")).to_have_text(
        "Choose an API key in Who works"
    )
    page.get_by_test_id("install-folder-other").click()  # not a folder suggested: this one
    page.get_by_label("folder path").fill(str(tasks))
    pick_access(page, "fake", who.get_by_test_id("model-choice"))
    expect(switches.nth(0)).to_have_attribute("aria-checked", "true")
    expect(refused).to_have_count(0)
    expect(page.get_by_test_id("install-may")).to_contain_text(f"Reads and writes {tasks}")
    expect(page.get_by_test_id("install-todo")).to_have_count(0)
    page.get_by_test_id("install-go").click()
    stopped = page.get_by_test_id("install-error")  # its deploy failed: what was done is kept
    installed = page.get_by_test_id("app-page")  # or it is installed: its page
    expect(stopped.or_(installed)).to_be_visible(timeout=120_000)
    with daemon.http() as c:
        app = c.get("/v1/apps/needs-e2e").json()
        assert [f["path"] for f in app["files"]] == [str(tasks)]
        assert app["whoWorks"] == {"program": "fake", "account": "fake"}
        made = {a["name"]: a["enabled"] for a in c.get("/v1/automations").json()}
        assert made.get("needs-e2e-what-to-do-next-every-5-hours") is True
        assert "needs-e2e-weekly-review" not in made
    page.goto(f"{daemon.base_url}/#/apps")
    given_everything(page, daemon, tasks)


def test_a_project_s_agent_with_an_interface_is_run_from_its_page(
    page: Page, daemon: Daemon
) -> None:
    """D.18: in a project, an agent with an interface is run with its form (on the project page,
    once chosen), never started as a chat; the automation that runs it shows there (I.1)."""
    result = {
        "type": "object",
        "properties": {
            "status": {"enum": ["ok", "attention", "failed"]},
            "summary": {"type": "string"},
        },
        "required": ["status", "summary"],
    }
    fields = {"type": "object", "properties": {"focus": {"type": "string"}}}
    reviewer = {
        "model": {"account": "fake"},
        "name": "reviewer",
        "permissions": "bypass",
        "interface": {"fields": fields, "result": result},
    }
    folder = daemon.make_scope()
    dev = {"model": {"account": "fake"}, "name": "dev"}
    project = create_project(daemon, folder, agents=[dev, reviewer])
    definition = {
        "apiVersion": "handler.automation/v1",
        "when": {"every": "2h"},
        "run": {"agent": "reviewer", "project": project["name"]},
    }
    with daemon.http() as c:
        r = c.post("/v1/automations", json={"name": "review", "definition": definition})
        assert r.status_code == 201 and r.json()["problems"] == [], r.text
        assert c.post("/v1/automations/review/enable").status_code == 200
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}")
    page.get_by_test_id("agent-row").filter(has_text="reviewer").click()
    panel = page.get_by_test_id("agent-panel")
    expect(panel.get_by_test_id("run-form")).to_be_visible()  # its form, on the project page
    page.get_by_test_id("project-tab-automations").click()  # what runs it, on its own tab
    expect(page.get_by_test_id("project-tab-automations")).to_contain_text("1")
    row = page.get_by_test_id("project-automation")
    expect(row).to_contain_text("Every 2h")
    expect(row.get_by_test_id("automation-runs")).to_have_text("reviewer")
    page.get_by_test_id("project-tab-sessions").click()
    page.get_by_test_id("agent-row").filter(has_text="reviewer").click()
    page.get_by_test_id("run-field-focus").fill("security")
    page.get_by_test_id("run-start").click()
    expect(page).to_have_url(re.compile(r"#/runs/"))


def test_areas_started_coloured_and_deleted(page: Page, daemon: Daemon) -> None:
    """D.19 in the UI: none yet, Work and Personal in one click; another made in its dialog; a
    colour changed; one in use cannot be deleted, a free one can."""
    page.goto(f"{daemon.base_url}/#/settings/areas")
    page.get_by_test_id("area-starters").click()
    rows = page.get_by_test_id("area-row")
    expect(rows).to_have_count(2)
    expect(rows.first).to_contain_text("nothing in it yet")

    page.get_by_test_id("area-new").click()
    page.get_by_test_id("area-name").fill("Client")
    page.get_by_test_id("area-color-cyan").click()
    page.get_by_test_id("area-add").click()
    expect(rows).to_have_count(3)

    rows.filter(has_text="Work").get_by_test_id("area-edit").click()
    page.get_by_test_id("area-color-pink").click()
    page.get_by_test_id("area-add").click()
    with daemon.http() as c:
        work = next(a for a in c.get("/v1/areas").json() if a["name"] == "Work")
    assert work["color"] == "pink"

    rows.filter(has_text="Client").get_by_test_id("area-edit").click()
    page.get_by_test_id("area-delete").click()
    page.get_by_test_id("ask-yes").click()
    expect(rows).to_have_count(2)


@pytest.mark.rule("uses.seen-from-both-ends")
def test_uses_and_used_by_link_both_ways(page: Page, daemon: Daemon) -> None:
    """D.22 in the UI: the skill's page says who uses it, linking to that agent; a project's
    Sessions tab lists none of it (the box's chips say what the agent uses)."""
    skill = "---\nname: linked-skill\ndescription: Does linked things.\n---\n\nDo it.\n"
    with daemon.http() as c:
        c.post("/v1/skills", json={"content": skill}).raise_for_status()
    agents = [{"model": {"account": "fake"}, "name": "linker", "skills": ["linked-skill"]}]
    create_project(daemon, daemon.make_scope(), name="linking", agents=agents)
    page.goto(f"{daemon.base_url}/#/skills/linked-skill")
    used_by = page.get_by_test_id("used-by-list")
    expect(used_by).to_contain_text("linking · linker, picks it")
    used_by.get_by_role("link", name="linking · linker").click()
    chosen = page.get_by_test_id("agent-row").filter(has_text="linker")
    expect(chosen).to_have_attribute("aria-selected", "true")
    expect(page.get_by_test_id("uses-panel")).to_have_count(0)


def test_a_project_lists_the_apps_given_its_folder(
    page: Page, daemon: Daemon, tmp_path: Path
) -> None:
    """H.14 in the UI: an app given a project's folder is listed on that project's page (it lives
    in Apps), its page says whose folder it is."""
    source = tmp_path / "shelf"
    source.mkdir()
    (source / "app.toml").write_text(
        'apiVersion = "handler.app/v1"\nname = "shelf"\nversion = "1.0.0"\n'
        '[needs.files.data]\ndescription = "Where your books are"\nmode = "rw"\n'
    )
    folder = daemon.make_scope()
    project = create_project(daemon, folder, name="library")
    with daemon.http() as c:
        assert c.post("/v1/apps", content=app_file(source)).is_success
        elsewhere = daemon.make_scope()
        c.put("/v1/apps/shelf/files/data", json={"path": str(elsewhere)}).raise_for_status()
    page.goto(f"{daemon.base_url}/#/apps/shelf/settings")  # what it uses: its value, Change…
    expect(page.get_by_test_id("app-need-folder")).to_contain_text(str(elsewhere))
    expect(page.get_by_test_id("app-needs-set")).to_be_visible()
    with daemon.http() as c:
        c.put("/v1/apps/shelf/files/data", json={"path": str(folder)}).raise_for_status()
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}")
    apps = page.get_by_test_id("project-apps")
    expect(apps.get_by_test_id("project-app")).to_have_text("shelf")
    apps.get_by_test_id("project-app").click()
    expect(page.get_by_test_id("app-need-folder")).to_contain_text(
        "the folder of the project library"
    )


def test_one_of_handlers_apps_is_installed_from_the_apps_page(page: Page, daemon: Daemon) -> None:
    """D.26: what Handler's source offers is on the Library's Apps shelf, Community; Install takes
    its code and opens its install page; the app is then in the menu once pinned, its page says
    it is from Handler."""
    page.goto(f"{daemon.base_url}/#/apps")
    page.get_by_test_id("apps-get").click()  # no app yet: Get an app
    expect(page).to_have_url(re.compile(r"#/library/apps/more$"))
    page.get_by_test_id("discover-item").filter(
        has_text="A journal kept in a folder of yours"
    ).get_by_test_id("discover-item-take").click()
    expect(page).to_have_url(re.compile(r"#/apps/journal/install$"))
    expect(page.get_by_test_id("install-where")).to_contain_text("Where the journal is kept")
    expect(page.get_by_test_id("install-where")).to_contain_text("Journal's folder")  # its title
    expect(page.get_by_test_id("install-actions")).to_contain_text("Write in my journal")
    page.goto(f"{daemon.base_url}/#/apps/journal")
    expect(page.get_by_test_id("page-header")).to_contain_text("from Handler")
    page.get_by_test_id("app-page-more").click()  # its ⋯: Change it with the App creator
    expect(page.get_by_test_id("app-improve")).to_be_visible()  # once used, a draft makes it yours
    page.keyboard.press("Escape")
    in_menu = page.get_by_test_id("sidebar-app").filter(has_text=re.compile(r"^Journal$"))
    expect(in_menu).to_have_count(0)  # an app is pinned when you choose
    page.get_by_test_id("app-pin").click()  # from its page
    expect(in_menu).to_be_visible()
    page.goto(f"{daemon.base_url}/#/apps")  # Apps, a launcher: its ⋯ unpins it
    tile = page.get_by_test_id("app-card").filter(has_text="Journal")
    tile.hover()
    tile.get_by_test_id("app-more").click()
    menu = page.get_by_test_id("app-menu")
    expect(menu.get_by_test_id("app-menu-open")).to_have_text("Install")  # not installed yet
    menu.get_by_test_id("app-pin").click()
    expect(in_menu).to_have_count(0)
    with daemon.http() as c:
        assert c.delete("/v1/apps/journal").status_code == 204
        assert {"kind": "app", "id": "journal"} not in c.get("/v1/pins").json()["items"]


def test_handlers_helpers_are_in_settings(page: Page, daemon: Daemon) -> None:
    """D.18: Settings → Helpers lists the agents behind Handler's features, by the feature each
    serves; one not set up yet is set up the first time it is used, or from its page (its card).
    Set up, its page shows who works, what its feature fixes locked, and its instructions."""
    page.goto(f"{daemon.base_url}/#/settings/helpers")
    plans = page.get_by_test_id("helper").filter(has_text="Plans")
    expect(plans).to_contain_text("plan builder · in each project")
    expect(plans.get_by_test_id("helper-not-set-up")).to_be_visible()
    plans.click()
    expect(page).to_have_url(re.compile(r"#/settings/helpers/plan-builder$"))
    expect(page.get_by_test_id("page-header")).to_contain_text("Plan builder")
    choose_helper_account(page, "fake")
    page.get_by_test_id("helper-turn-on").click()
    locked = page.get_by_test_id("helper-can-do").get_by_test_id("helper-locked")
    expect(locked).to_have_count(4)  # set by Plans: Handler holds the plan builder to them
    expect(locked.first).to_have_text("set by Plans")
    instructions = page.get_by_test_id("helper-instructions")
    expect(instructions).to_have_value(re.compile("You write a Handler plan"))
    instructions.fill("Be brief.")
    expect(page.get_by_test_id("helper-back-to-handlers")).to_be_visible()
    page.get_by_test_id("helper-save").click()
    expect(page.get_by_test_id("helper-save")).to_have_count(0)
    page.get_by_test_id("helper-back-to-handlers").click()  # Handler's, to save again
    page.get_by_test_id("helper-save").click()
    expect(page.get_by_test_id("helper-back-to-handlers")).to_have_count(0)


def test_a_helper_whose_tool_asks_nothing_is_turned_on(page: Page, daemon: Daemon) -> None:
    """D.18, G.3: the App creator needs the app-builder tool, built in and without settings: its
    card asks only who works, never a connection to the tool."""
    page.goto(f"{daemon.base_url}/#/settings/helpers/app-creator")
    turn_on = page.get_by_test_id("helper-turn-on")
    expect(turn_on).to_be_disabled()  # who works: not chosen yet
    choose_helper_account(page, "fake")
    expect(turn_on).to_be_enabled()


def test_an_app_is_written_and_changed_on_drafts(page: Page, daemon: Daemon) -> None:
    """H.15 in the UI: New app starts a session of the App creator on an empty draft kept by
    Handler; Install it, on the session's page, makes it a new app (its install page), or says
    why not, handed to the App creator in one click. Change
    it, on the app's page, starts one on a copy of its code; while it waits the app's page says
    so, and Use it makes it the app's next version."""
    with daemon.http() as c:
        body = {"name": "App creator", "model": {"account": "fake"}, "origin": APP_CREATOR}
        creator = c.post("/v1/agents", json=body).json()
        assert c.put("/v1/handler-needs/app-creator", json={"agentId": creator["id"]}).is_success
    page.goto(f"{daemon.base_url}/#/library/apps/more")
    page.get_by_test_id("app-create").click()
    expect(page).to_have_url(re.compile(r"#/sessions/"))
    with daemon.http() as c:
        (session,) = [s for s in c.get("/v1/sessions").json() if s.get("appDraft") == {}]
    draft = Path(session["scope"])
    (draft / "app.toml").write_text(
        'apiVersion = "handler.app/v1"\nname = "drafted_e2e"\nversion = "0.1.0"\n'
    )
    page.get_by_test_id("draft-use").click()  # refused: its error whole, for the App creator
    expect(page.get_by_test_id("draft-error")).to_contain_text("app.toml is invalid: name:")
    page.get_by_test_id("draft-fix").click()
    expect(page.get_by_label("prompt")).to_have_value(
        re.compile(r"^Install it failed: .*app.toml is invalid")
    )
    expect(page.get_by_test_id("draft-error")).to_have_count(0)
    (draft / "app.toml").write_text(
        'apiVersion = "handler.app/v1"\nname = "drafted-e2e"\nversion = "0.1.0"\n'
    )
    page.get_by_test_id("draft-use").click()
    expect(page).to_have_url(re.compile(r"#/apps/drafted-e2e/install$"))

    page.goto(f"{daemon.base_url}/#/apps/drafted-e2e")
    page.get_by_test_id("app-page-more").click()  # its ⋯
    page.get_by_test_id("app-improve").click()
    expect(page).to_have_url(re.compile(r"#/sessions/"))
    with daemon.http() as c:
        drafts = [s for s in c.get("/v1/sessions").json() if s.get("appDraft")]
    (change,) = [s for s in drafts if s["appDraft"] == {"app": "drafted-e2e"}]
    manifest = Path(change["scope"]) / "app.toml"
    assert "0.1.0" in manifest.read_text()  # a copy of its code
    manifest.write_text(manifest.read_text().replace("0.1.0", "0.2.0"))
    page.goto(f"{daemon.base_url}/#/apps/drafted-e2e/settings")
    bar = page.get_by_test_id("app-draft")
    expect(bar).to_contain_text("Your change, waiting")
    page.get_by_test_id("app-page-more").click()
    expect(page.get_by_test_id("app-export")).to_be_visible()
    expect(page.get_by_test_id("app-improve")).to_have_count(0)  # one draft at a time
    page.keyboard.press("Escape")
    bar.get_by_test_id("draft-use").click()
    expect(page.get_by_test_id("app-draft")).to_have_count(0)
    with daemon.http() as c:
        assert c.get("/v1/apps/drafted-e2e").json()["source"]["version"] == "0.2.0"


@pytest.mark.rule("source.adding-one-is-confirmed")
def test_a_source_is_added_only_once_trusted(page: Page, daemon: Daemon) -> None:
    """D.26: Settings → Sources lists Handler's; adding one asks to trust it first, and one that
    cannot be read is not added."""
    page.goto(f"{daemon.base_url}/#/settings/sources")
    expect(page.get_by_test_id("source")).to_have_count(1)
    expect(page.get_by_test_id("source-name")).to_have_text("Handler")
    page.get_by_test_id("source-new").click()
    page.get_by_test_id("source-url").fill("https://127.0.0.1:9/someone/source")  # refused
    expect(page.get_by_test_id("source-add")).to_be_disabled()
    page.get_by_test_id("source-trust").click()
    page.get_by_test_id("source-add").click()
    expect(page.get_by_test_id("source-dialog").get_by_test_id("source-error")).to_contain_text(
        "cannot read"
    )
    expect(page.get_by_test_id("source")).to_have_count(1)


def test_discover_shows_what_the_sources_offer_and_installs_it(page: Page, daemon: Daemon) -> None:
    """D.26: each Library shelf's Community lists what the sources offer of its kind (Handler's
    own included), named with Yours at the head of its list, a line saying which one you see
    (E6; not on Notes and Schemas); an item's page says where it comes from and what it may do;
    its button goes to its kind's install page (an app's install page; a tool's preview, opened
    by Library → Tools → Community's `install`)."""
    page.goto(f"{daemon.base_url}/#/library/apps")
    lists = page.get_by_test_id("shelf-lists")
    expect(lists.get_by_test_id("shelf-yours")).to_have_attribute("aria-current", "page")
    expect(lists.get_by_test_id("shelf-yours")).to_have_text(re.compile(r"Yours\s·\s\d+"))
    expect(lists.get_by_test_id("shelf-more")).to_have_text(re.compile(r"Community\s·\s\d+"))
    expect(page.get_by_test_id("shelf-line")).to_have_text(
        "You are looking at the apps you have. More are shared by Handler and the community:"
        " Community."
    )
    page.get_by_test_id("shelf-line-link").click()  # the line's link: the other list
    expect(page).to_have_url(re.compile(r"#/library/apps/more$"))
    expect(page.get_by_test_id("shelf-line")).to_contain_text("shared by Handler and the community")
    expect(lists.get_by_test_id("shelf-more")).to_have_attribute("aria-current", "page")
    expect(  # Handler's own items are in Community, marked so
        page.get_by_test_id("discover-item").filter(has_text="journal")
    ).to_contain_text("from Handler")
    page.goto(f"{daemon.base_url}/#/library/notes")  # Notes and Schemas: no lists
    expect(page.get_by_test_id("shelf-lists")).to_have_count(0)
    page.goto(f"{daemon.base_url}/#/library/apps")
    page.get_by_test_id("shelf-more").click()
    page.get_by_test_id("discover-item").filter(has_text="journal").get_by_test_id(
        "discover-item-open"
    ).click()
    expect(page).to_have_url(re.compile(r"#/discover/official/apps/journal$"))
    expect(page.get_by_test_id("discover-item-trust")).to_contain_text("Reviewed by Handler")
    expect(page.get_by_test_id("discover-item-may-do")).to_contain_text("notify you")
    expect(page.get_by_test_id("discover-item-readme")).to_contain_text("journal")
    # one h1, its display name: its README's own title, not repeated in the README shown (E8)
    expect(page.get_by_role("heading", level=1)).to_have_text(["Journal"])
    page.get_by_test_id("discover-item-page-take").click()
    expect(page).to_have_url(re.compile(r"#/apps/journal/install$"))
    with daemon.http() as c:
        assert c.delete("/v1/apps/journal").status_code == 204
    page.goto(f"{daemon.base_url}/#/library/tools/more")
    tools = page.get_by_test_id("discover-item")
    expect(tools.filter(has_text="journal")).to_have_count(0)  # an app: not a tool
    expect(  # the daemon's browser binding keeps it installed
        tools.filter(has_text="fake-browser").get_by_test_id("discover-item-installed")
    ).to_be_visible()
    # a tool's button opens its preview on Community (here installed: a reinstall)
    page.goto(f"{daemon.base_url}/#/library/tools/more?install=source:official/fake-shop")
    expect(page.get_by_test_id("addon-preview")).to_contain_text("source:official/fake-shop")
