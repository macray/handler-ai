"""Agent interfaces, built-in agents, skills written with an agent, automations and jobs (D.18).

Skipped when podman, the image or the built UI is missing."""

import io
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from ...support import dev_env
from ...support.daemon import Daemon
from ..browser import PW_IMAGE, image_present
from .ui import (
    UI_BUILT,
    choose_account,
    choose_helper_account,
    create_project,
    library_skill,
    open_new_skill,
    pick_account,
    say,
)

pytestmark = [
    pytest.mark.skipif(not UI_BUILT, reason="web UI not built (scripts/build-web-ui.sh)"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


def test_a_run_is_started_from_a_form_and_its_result_shown(page: Page, daemon: Daemon) -> None:
    """An agent with an interface: its page's form (a skill field, the others), then the run's
    page with its verdict and the lines of the skill it points at, read from the skill itself."""
    library_skill(daemon, "ui-subject")
    interface = {
        "fields": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "title": "Skill", "x-handler": "skill"},
                "fake": {"type": "string"},
                "answer": {"type": "object"},
            },
            "required": ["target", "fake"],
        },
        "result": {
            "type": "object",
            "properties": {
                "verdict": {
                    "enum": ["no-concerns", "caution", "do-not-install"],
                    "x-handler": "verdict",
                },
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "where": {"x-handler": "code-ref", "type": "object"},
                            "text": {"type": "string", "title": "What"},
                        },
                    },
                },
            },
        },
    }
    with daemon.http() as c:
        r = c.post(
            "/v1/agents",
            json={
                "model": {"account": "fake"},
                "name": "ui-reviewer",
                "permissions": "bypass",
                "interface": interface,
            },
        )
        agent = r.json()
    answer = {
        "verdict": "do-not-install",
        "findings": [
            {"where": {"path": "scripts/run.sh", "lines": [2, 2]}, "text": "deletes your keys"}
        ],
    }
    page.goto(f"{daemon.base_url}/#/agents/{agent['id']}")
    page.get_by_test_id("run-field-target").select_option("ui-subject")
    page.get_by_test_id("run-field-fake").fill("valid")
    page.get_by_test_id("run-field-answer").fill(json.dumps(answer))
    page.get_by_test_id("run-start").click()
    expect(page.get_by_test_id("run-verdict")).to_have_text("do-not-install", timeout=30_000)
    expect(page.get_by_test_id("code-ref")).to_contain_text("rm -rf ~/.ssh")
    expect(page.get_by_test_id("run-result")).to_contain_text("deletes your keys")
    page.get_by_test_id("run-watch").click()  # its conversation: no prompt, a link back
    expect(page.get_by_test_id("run-note")).to_be_visible()


def test_a_builtin_agent_set_up_and_the_skill_page(page: Page, daemon: Daemon) -> None:
    """The Skill reviewer turned on by its card (D.18; here on its page in Settings → Helpers, the
    card a skill's page shows when nothing reviews skills yet): what it can do said, its model
    chosen, Turn on. A skill's page then offers to review with it, and shows what handler found in
    its files; Skills names it."""
    library_skill(daemon, "ui-reviewed")
    page.goto(f"{daemon.base_url}/#/library/skills")
    expect(page.get_by_test_id("skill-helpers")).to_contain_text(
        "Reviewed by the skill reviewer, set up the first time you use it"
    )
    page.goto(f"{daemon.base_url}/#/settings/helpers/skill-review")
    card = page.get_by_test_id("helper-card")
    expect(card).to_contain_text("Review skills")
    expect(card.get_by_test_id("helper-can-do")).to_contain_text("reads the skill, read-only")
    choose_helper_account(page, "fake", card)
    card.get_by_test_id("helper-turn-on").click()
    expect(page.get_by_test_id("helper-who-works")).to_be_visible()  # its page now
    page.goto(f"{daemon.base_url}/#/skills/ui-reviewed")
    expect(page.get_by_test_id("skill-scan")).to_contain_text("scripts/run.sh")
    expect(page.get_by_test_id("skill-review").get_by_test_id("run-form")).to_be_visible()
    expect(page.get_by_test_id("run-field-skill")).to_have_value("ui-reviewed")  # this skill
    page.goto(f"{daemon.base_url}/#/library/skills")
    expect(page.get_by_test_id("skill-helpers")).to_contain_text("Reviewed by the skill reviewer ·")


def test_a_project_s_agents_exported_then_added_to_another(page: Page, daemon: Daemon) -> None:
    """D.23: Export agents on a project's page (what of yours each agent leaves out, from the
    dry run) downloads one file; on another project, Get agents… opens Library → Agents → Get
    more for it, where From a file reads it and opens the set-up page there: each agent asks
    for its model; it ends on the project, its agents remembering the file,
    the file forgotten, and Library → Agents lists them as from it."""
    agents = [
        {
            "model": {"account": "fake"},
            "name": "Dev",
            "addons": [{"addon": "fake-browser", "binding": "browser"}],
        },
        {"model": {"account": "fake"}, "name": "Review", "network": "none"},
    ]
    project = create_project(daemon, daemon.make_scope(), name="Kit src", agents=agents)
    other = create_project(daemon, daemon.make_scope(), name="Shop", agents=[agents[1]])
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}")
    page.get_by_test_id("project-more").click()  # the page's ⋯
    page.get_by_test_id("project-export-agents").click()
    dialog = page.get_by_test_id("export-agents")
    expect(dialog.get_by_test_id("export-agents-agent")).to_have_count(2)  # all ticked
    expect(dialog).to_contain_text("connection browser")
    expect(dialog).to_contain_text("its model, chosen at set-up")
    with page.expect_download() as downloaded:
        dialog.get_by_test_id("export-agents-go").click()
    assert downloaded.value.suggested_filename == "kit-src-agents.zip"
    file = daemon.make_scope() / "kit-src-agents.zip"
    downloaded.value.save_as(file)  # the browser may run elsewhere (a browser server)

    page.goto(f"{daemon.base_url}/#/projects/{other['id']}")
    page.get_by_test_id("project-more").click()
    page.get_by_test_id("get-agents").click()
    expect(page).to_have_url(re.compile(r"#/library/agents/more\?project="))
    expect(page.get_by_test_id("agents-into")).to_contain_text("Shop")
    page.get_by_test_id("agents-file-input").set_input_files(str(file))
    expect(page).to_have_url(re.compile(r"#/setup/kit-src\?project="))
    expect(page.get_by_test_id("setup-project")).to_have_value(other["id"])
    for block in page.get_by_test_id("setup-agent").all():
        pick_account(page, "fake", block)
    expect(page.get_by_test_id("setup-todo")).to_have_count(0)
    page.get_by_test_id("setup-go").click()
    expect(page).to_have_url(re.compile(rf"#/projects/{other['id']}"))
    with daemon.http() as c:
        made = c.get(f"/v1/projects/{other['id']}").json()["agents"]
        origins = sorted((a.get("origin") or {}).get("agent", "") for a in made)
        assert origins == ["", "dev", "review"]
        assert {(a.get("origin") or {}).get("name") for a in made} == {None, "kit-src"}
        assert c.get("/v1/agents-files/kit-src").status_code == 404  # forgotten once set up
    page.goto(f"{daemon.base_url}/#/library/agents")
    shop = page.get_by_test_id("agents-group").filter(
        has=page.locator(f'a[href="#/projects/{other["id"]}"]')
    )
    expect(shop.get_by_test_id("agent-from")).to_have_text(
        ["from kit-src", "made here", "from kit-src"]
    )  # Dev, Review, Review 2
    page.get_by_test_id("agents-filter-here").click()
    expect(shop.get_by_test_id("library-agent")).to_have_count(1)


def test_a_tool_a_source_offers_is_installed_with_its_agent(page: Page, daemon: Daemon) -> None:
    """D.23, G.5: an agents file's agent needs a tool not installed, that the official source
    offers: the set-up page shows it in the agent's card and under Comes with it (with what it
    adds to the toolbox), asks nothing for it, and its button installs it, then sets the agent
    up using it. A tool no source has blocks the set-up, said in the agent's card."""
    folder = daemon.config_dir / "toolbox"
    before = (folder / "toolbox.toml").read_text()

    def agents_file(name: str, tool: str) -> dict[str, Any]:
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            z.writestr(f"{name}/agents.toml", f'name = "{name}"\nversion = 1\nplace = "outside"\n')
            agent = f'[agent]\nname = "Builder"\naddons = ["{tool}"]\n'
            z.writestr(f"{name}/agents/builder/agent.toml", agent)
        with daemon.http() as c:
            c.get("/v1/sources")  # read once
            r = c.post(
                "/v1/agents-files/import",
                content=data.getvalue(),
                headers={"Content-Type": "application/zip"},
            )
            assert r.status_code in (200, 201), r.text
            return r.json()

    try:
        agents_file("no-such-kit", "no-such-tool")
        page.goto(f"{daemon.base_url}/#/setup/no-such-kit")
        missing = page.get_by_test_id("setup-tool-missing")
        expect(missing).to_contain_text("none of your sources has")
        expect(page.get_by_test_id("setup-blocked")).to_contain_text("no-such-tool")
        expect(page.get_by_test_id("setup-go")).to_be_disabled()
        page.get_by_test_id("setup-cancel").click()
        # Cancel forgets the file, then goes back: gone before the next page, or it leaves that
        expect(page).not_to_have_url(re.compile(r"#/setup/no-such-kit$"))

        agents_file("builder-kit", "fake-toolchain")
        page.goto(f"{daemon.base_url}/#/setup/builder-kit")
        expect(page.get_by_role("heading", name="Set up Builder")).to_be_visible()
        expect(page.get_by_test_id("setup-tool-comes")).to_contain_text("fake-toolchain")
        expect(page.get_by_test_id("setup-comes")).to_contain_text("fake-cc in the toolbox")
        expect(page.get_by_test_id("setup-tool-missing")).to_have_count(0)
        pick_account(page, "fake")
        go = page.get_by_test_id("setup-go")
        expect(go).to_have_text("Install fake-toolchain and set it up")
        go.click()
        expect(page).to_have_url(re.compile(r"#/agents"))
        with daemon.http() as c:
            installed = {a["name"] for a in c.get("/v1/addons").json()}
            assert "fake-toolchain" in installed
            made = [a for a in c.get("/v1/agents").json() if a.get("name") == "Builder"]
            assert [a["addons"] for a in made] == [[{"addon": "fake-toolchain"}]]
            for a in made:
                c.delete(f"/v1/agents/{a['id']}")
            c.delete("/v1/addons/fake-toolchain")
    finally:
        (folder / "toolbox.toml").write_text(before)
        shutil.rmtree(daemon.config_dir / "system-packages", ignore_errors=True)
        (daemon.config_dir / "system-packages.lock.toml").unlink(missing_ok=True)


def test_a_skill_written_with_an_agent_is_saved_to_the_library(page: Page, daemon: Daemon) -> None:
    """Skills → With an agent: a session of the skill creator (a folder of its own);
    what it writes there is saved to the library from the session's page."""
    with daemon.http() as c:
        body = {
            "model": {"account": "fake"},
            "name": "Skill creator",
            "skills": ["handler-skills", "skill-creator"],
            "origin": {"kind": "handler-need", "name": "skill-creator", "version": 2},
        }
        made = c.post("/v1/agents", json=body)
        made.raise_for_status()
        given = {"agentId": made.json()["id"]}  # the one handler uses (D.18)
        c.put("/v1/handler-needs/skill-creator", json=given).raise_for_status()
    open_new_skill(page, daemon)
    expect(page.get_by_test_id("skill-with-agent")).to_contain_text("writes it with you")
    page.get_by_test_id("skill-with-agent").click()
    expect(page.get_by_test_id("mode-select")).to_have_value("yolo")
    sid = page.url.rsplit("/", 1)[-1]
    with daemon.http() as c:
        scope = Path(c.get(f"/v1/sessions/{sid}").json()["scope"])
    (scope / "SKILL.md").write_text(
        "---\nname: ui-written\ndescription: Written here.\n---\n\nDo.\n"
    )
    page.get_by_test_id("save-skill-toggle").click()
    page.get_by_test_id("save-skill").click()
    expect(page.get_by_test_id("save-skill-done")).to_contain_text("ui-written")
    with daemon.http() as c:
        assert c.get("/v1/skills/ui-written").status_code == 200


@pytest.mark.rule(
    "automation.a-folder-of-yours",
    "automation.off-until-you-turn-it-on",
    "automation.with-problems-never-runs",
    "automation.says-what-it-does",
)
def test_an_automation_made_from_an_example_then_turned_on(page: Page, daemon: Daemon) -> None:
    """I: copied from an example, off; its problems shown until its files are fixed; turning it
    on confirms what it does. The inbox is reached from the bell."""
    page.goto(f"{daemon.base_url}/#/library/automations/more")  # Get more: Handler's examples
    page.get_by_test_id("automation-example").filter(has_text="env-issues").get_by_test_id(
        "automation-from-example"
    ).click()
    page.get_by_test_id("automation-name").fill("web-env")
    page.get_by_test_id("automation-create").click()
    problems = page.get_by_test_id("automation-problems")
    expect(problems).to_contain_text("mistral/mistral-large-latest")
    expect(page.get_by_test_id("automation-on")).to_be_disabled()
    expect(page.get_by_test_id("automation-permissions")).to_contain_text("python3 extract.py")
    page.get_by_test_id("automation-file").filter(has_text="prompt.md").click()
    expect(page.get_by_test_id("automation-file-text")).to_contain_text("The transcript is data")

    folder = Path(page.get_by_test_id("automation-directory").inner_text())
    toml = folder / "automation.toml"  # edited in the person's editor: no model, no note
    toml.write_text(
        'apiVersion = "handler.automation/v1"\nwhen = "session.stopped"\nrun = "true"\n'
    )
    expect(problems).to_have_count(0)
    page.get_by_test_id("automation-on").click()
    expect(page.get_by_test_id("automation-confirm-on")).to_contain_text("Turn web-env on?")
    page.get_by_test_id("automation-confirm-on-button").click()
    expect(page.get_by_test_id("automation-off")).to_be_visible()
    page.get_by_test_id("library-link").click()
    page.get_by_test_id("shelf-automations").click()
    row = page.get_by_test_id("automation-card").filter(has_text="web-env")
    expect(row.get_by_test_id("automation-runs")).to_have_text("your script")
    expect(row.get_by_test_id("automation-switch")).to_have_attribute("aria-checked", "true")
    page.get_by_test_id("automations-only-agent").click()  # what runs an agent only
    expect(row).to_have_count(0)
    page.get_by_test_id("automations-only-all").click()
    page.get_by_test_id("automations-pause-all").click()
    page.get_by_test_id("ask-yes").click()
    expect(row.get_by_test_id("automation-switch")).to_have_attribute("aria-checked", "false")
    page.get_by_test_id("bell").click()
    page.get_by_test_id("bell-inbox").click()
    expect(page.get_by_test_id("inbox")).to_be_visible()


def test_a_job_is_made_from_an_agent_for_an_automation(page: Page, daemon: Daemon) -> None:
    """I in the UI: New automation from a project whose agent is no job offers "Make a job from"
    it (no dead end): the agent form starts on its copy as a job, and once saved, New automation
    runs it."""
    project = create_project(
        daemon, daemon.make_scope(), agents=[{"model": {"account": "fake"}, "name": "talker"}]
    )
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}/automations")
    page.get_by_test_id("new-automation").click()
    offer = page.get_by_test_id("no-unattended-agent")
    expect(offer.get_by_test_id("make-job").first).to_have_text("Make a job from talker")  # first
    offer.get_by_test_id("make-job").first.click()
    expect(page.get_by_test_id("page-header")).to_contain_text("A job from talker")
    expect(page.get_by_test_id("agent-name-input")).to_have_value("talker-job")
    page.get_by_test_id("agent-save").click()
    expect(page).to_have_url(re.compile(r"#/automations/new\?agent="))
    with daemon.http() as c:
        made = next(a for a in c.get("/v1/agents").json() if a.get("name") == "talker-job")
    assert made["interface"]["result"] and made["projectId"] == project["id"]
    expect(page.get_by_test_id("new-automation-agent")).to_have_value(made["id"])


def test_an_agent_given_a_job_with_the_field_editor(page: Page, daemon: Daemon) -> None:
    """D.18: a new agent outside projects given a job: its form and its result made as fields,
    both shown as they will look; "Edit as JSON" shows the schemas; "Save and try" saves it
    and opens its page on the run form."""
    page.goto(f"{daemon.base_url}/#/agents/new")
    choose_account(page, "fake")
    page.get_by_test_id("agent-name-input").fill("web-invoices")
    page.get_by_test_id("agent-use-job").click()
    expect(page.get_by_test_id("agent-confirm-bypass")).to_have_count(0)  # a new one never asks
    expect(page.get_by_test_id("job-no-fields")).to_be_visible()  # the person names its fields
    page.get_by_test_id("job-field-add").click()
    page.get_by_test_id("job-field-title").fill("Invoice text")
    for n in (1, 2):  # a skill to work on: a field like the others, one at most
        page.get_by_test_id("job-field-add").click()
        page.get_by_test_id("job-field-type").nth(n).select_option("skill")
        page.get_by_test_id("job-field-title").nth(n).fill(f"Skill {n}")
    expect(page.get_by_test_id("job-field-second-skill")).to_have_count(1)
    expect(page.get_by_test_id("job-preview").get_by_test_id("run-field-skill1")).to_be_visible()
    page.get_by_test_id("job-field-remove").nth(2).click()
    page.get_by_test_id("job-field-remove").nth(1).click()
    page.get_by_test_id("job-result-add").click()
    page.get_by_test_id("job-result-type").select_option("items")
    page.get_by_test_id("job-result-title").fill("Invoices")
    page.get_by_test_id("job-result-item-add").click()
    page.get_by_test_id("job-result-item-title").fill("Supplier")
    preview = page.get_by_test_id("job-preview")
    expect(preview.get_by_test_id("run-field-invoiceText")).to_be_visible()
    expect(page.get_by_test_id("job-preview-result")).to_contain_text("Supplier")
    page.get_by_test_id("job-as-json").click()
    expect(page.get_by_test_id("agent-interface-json")).to_have_value(re.compile('"supplier"'))
    page.get_by_test_id("job-as-fields").click()
    expect(page.get_by_test_id("job-result-item-title")).to_have_value("Supplier")
    page.get_by_test_id("agent-save-try").click()
    expect(page.get_by_test_id("run-form")).to_be_visible()
    expect(page.get_by_test_id("run-field-invoiceText")).to_be_visible()


def test_a_brief_made_in_the_editor_starts_a_chat(page: Page, daemon: Daemon) -> None:
    """D.18: "Brief" gives a new agent of a project a form (one long text to start with) and no
    result, its permission mode its own; on the project page its form starts a session that
    shows the brief filled in, then takes prompts. Its instructions name a field of the form,
    inserted by its label, followed when the label changes, refused when it names none. Back to
    Chat says the brief goes."""
    project = create_project(daemon, daemon.make_scope(), name="brief-project")
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}/agents/new")
    choose_account(page, "fake")
    page.get_by_test_id("agent-name-input").fill("Writer")
    page.get_by_test_id("agent-use-brief").click()
    expect(page.get_by_test_id("agent-confirm-bypass")).to_have_count(0)
    editor = page.get_by_test_id("job-editor")
    expect(editor).to_contain_text("The brief")
    expect(page.get_by_test_id("job-field-title")).to_have_value("What should it do?")
    expect(page.get_by_test_id("job-result-add")).to_have_count(0)  # no result, no time limit
    expect(page.get_by_test_id("job-timeout")).to_have_count(0)
    expect(page.get_by_test_id("agent-unattended-permissions")).to_have_count(0)
    page.get_by_test_id("job-field-add").click()
    page.get_by_test_id("job-field-title").nth(1).fill("Audience")
    instructions = page.get_by_test_id("agent-instructions")
    instructions.fill("Write for ")
    page.get_by_test_id("instructions-field").filter(has_text="Audience").click()
    expect(instructions).to_have_value("Write for {{audience}}")
    page.get_by_test_id("job-field-title").nth(1).fill("Readers")  # not saved: its key follows
    expect(instructions).to_have_value("Write for {{readers}}")
    instructions.fill("Write for {{nobody}}")
    expect(page.get_by_test_id("agent-save-blocker")).to_contain_text("{{nobody}}")
    instructions.fill("Write for {{readers}}.")
    page.get_by_test_id("agent-use-job").click()  # a job keeps the brief's form
    expect(page.get_by_test_id("job-result-add")).to_be_visible()
    expect(page.get_by_test_id("job-field-title")).to_have_count(2)
    page.get_by_test_id("agent-use-brief").click()
    page.get_by_test_id("agent-save").click()

    page.get_by_test_id("agent-row").filter(has_text="Writer").click()
    panel = page.get_by_test_id("agent-panel")
    brief = panel.get_by_test_id("project-brief")  # a brief: its form is the box
    brief.get_by_test_id("run-field-whatShouldItDo").fill("Draft the release notes\nfor 1.2")
    brief.get_by_test_id("run-field-readers").fill("users")
    brief.get_by_test_id("run-start").click()
    expect(page).to_have_url(re.compile(r"#/sessions/"))
    card = page.get_by_test_id("session-brief")
    expect(card).to_contain_text("The brief")
    expect(card).to_contain_text("users")
    expect(page.get_by_test_id("session-header")).to_contain_text("Draft the release notes")
    say(page, "report")
    expect(page.get_by_test_id("agent-message").last).to_contain_text('"mode"')

    with daemon.http() as c:
        agent = next(a for a in c.get("/v1/agents").json() if a.get("name") == "Writer")
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}/agents/{agent['id']}")
    page.get_by_test_id("agent-use-chat").click()
    expect(page.get_by_test_id("agent-use-drops")).to_contain_text("Its brief goes")


@pytest.mark.rule("automation.deleting-it-stops-and-removes-all")
def test_an_agent_scheduled_from_its_settings(page: Page, daemon: Daemon) -> None:
    """I.1: in the agent's settings, "Job" (a form with one field) then "Save and run it on a
    schedule…" saves it and opens the form with the agent chosen; handlerd checks it as it is
    filled in; "Create and turn on" writes it and turns it on; "Change" opens it in the same form;
    the agent's settings then list it."""
    body = {"model": {"account": "fake"}, "name": "web-reviewer", "permissions": "ask"}
    with daemon.http() as c:
        r = c.post("/v1/agents", json=body)
        assert r.status_code == 201, r.text
        agent = r.json()
    page.goto(f"{daemon.base_url}/#/agents/{agent['id']}/edit")
    expect(page.get_by_test_id("agent-schedule")).to_be_disabled()  # no job yet
    page.get_by_test_id("agent-use-job").click()
    page.get_by_test_id("agent-accept-bypass").click()
    expect(page.get_by_test_id("agent-interface-lacks")).to_have_count(0)  # its starting result
    page.get_by_test_id("job-field-add").click()
    page.get_by_test_id("job-field-title").fill("Request")
    page.get_by_test_id("agent-schedule").click()  # saved, then the form: no going back first
    expect(page.get_by_test_id("agent-risks")).to_contain_text("auto-approve")  # wider (D.8)
    page.get_by_test_id("agent-confirm-risks").click()

    expect(page.get_by_test_id("new-automation-agent")).to_have_value(agent["id"])
    model = page.get_by_test_id("new-automation-model")
    expect(model).to_contain_text("as in its sessions")
    page.get_by_role("button", name="Weekdays at 08:30").click()
    expect(page.get_by_test_id("new-automation-name")).to_have_value("web-reviewer-weekdays")
    problems = page.get_by_test_id("new-automation-problems")
    expect(problems).to_contain_text("run.input")  # its required request is not given yet
    expect(page.get_by_test_id("new-automation-create-on")).to_be_disabled()
    page.get_by_test_id("run-field-request").fill("security")
    expect(problems).to_have_count(0)
    expect(page.get_by_test_id("new-automation-permissions")).to_contain_text(
        "Starts at 08:30 (local time) on mon, tue, wed, thu, fri"
    )
    expect(page.get_by_test_id("new-automation-first")).to_contain_text("First run")
    page.get_by_test_id("new-automation-create-on").click()

    expect(page.get_by_test_id("automation-off")).to_be_visible()
    expect(page.get_by_test_id("automation-next")).to_be_visible()
    toml = daemon.config_dir / "automations" / "web-reviewer-weekdays" / "automation.toml"
    assert 'request = "security"' in toml.read_text()

    page.get_by_test_id("automation-edit").click()  # changed with the same form, still on
    expect(page.get_by_test_id("run-field-request")).to_have_value("security")
    page.get_by_role("button", name="Every hour").click()
    expect(page.get_by_test_id("new-automation-how-often")).to_contain_text("24 runs a day")
    page.get_by_test_id("automation-save").click()
    expect(page.get_by_test_id("automation-permissions")).to_contain_text("Starts every 1h")
    expect(page.get_by_test_id("automation-off")).to_be_visible()
    page.goto(f"{daemon.base_url}/#/agents/{agent['id']}/edit")
    expect(page.get_by_test_id("agent-automations")).to_contain_text("web-reviewer-weekdays")

    page.get_by_role("link", name="web-reviewer-weekdays").click()  # deleted, said first
    page.get_by_test_id("automation-delete").click()
    expect(page.get_by_test_id("automation-confirm-delete")).to_contain_text("every file in it")
    page.get_by_test_id("automation-confirm-delete-button").click()
    expect(page).to_have_url(re.compile(r"#/library/automations$"))
    cards = page.get_by_test_id("automation-card")  # the module's other tests have theirs
    expect(cards.filter(has_text="web-reviewer-weekdays")).to_have_count(0)
    assert not toml.parent.exists()


def test_a_run_s_page_is_under_its_agent_s_place_in_the_menu(page: Page, daemon: Daemon) -> None:
    """A run of a project's agent: the menu shows its project (pinned) as the place; a run of an
    agent outside projects: Projects. (Whether the runs start does not matter.)

    If this fails: a run's page highlights nothing in the menu, or the wrong place."""
    interface = {"fields": {"type": "object", "properties": {"x": {"type": "string"}}}}
    agent = {"model": {"account": "fake"}, "name": "runner", "interface": interface}
    project = create_project(daemon, daemon.make_scope(), agents=[agent])
    with daemon.http() as c:
        items = c.get("/v1/pins").json()["items"]
        mine = {"kind": "project", "id": project["id"]}
        if mine not in items:
            assert c.put("/v1/pins", json={"items": [*items, mine]}).status_code == 200
        outside = c.post("/v1/agents", json=agent | {"name": "outside-runner"}).json()
        runs = [
            c.post(
                "/v1/sessions",
                json={"agentId": a, "input": {"fields": {"x": "y"}}, "origin": "ui"},
            ).json()["id"]
            for a in (project["agents"][0]["id"], outside["id"])
        ]
    projects_link = page.get_by_test_id("projects-link")
    pinned = page.get_by_test_id("sidebar-project").filter(has_text=project["name"])
    page.goto(f"{daemon.base_url}/#/runs/{runs[0]}")
    expect(pinned).to_have_attribute("data-active", "true")
    expect(projects_link).not_to_have_attribute("data-active", "true")
    page.goto(f"{daemon.base_url}/#/runs/{runs[1]}")
    expect(projects_link).to_have_attribute("data-active", "true")
    expect(pinned).not_to_have_attribute("data-active", "true")
