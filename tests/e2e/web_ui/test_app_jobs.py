"""An app's jobs in the web UI (H.1, H.2): Who works chosen on its install page, changed per job
on its page, what cannot run a job greyed with why; what each job can do, read only.

Skipped when podman, the image or the built UI is missing."""

import shutil
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import FilePayload, Page, expect

from ...apps.conftest import FIXTURES, app_file
from ...support import dev_env
from ...support.daemon import Daemon
from ..browser import PW_IMAGE, image_present
from .ui import UI_BUILT, local_provider, pick_access

pytestmark = [
    pytest.mark.skipif(not UI_BUILT, reason="web UI not built (scripts/build-web-ui.sh)"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]

SUGGESTS = (
    '\n[[automations]]\ndescription = "Sum up my notes each morning"\n'
    'when = { at = "08:00" }\nrun = { job = "summarize" }\n'
)


def jobs_app(daemon: Daemon, name: str, *, suggests: bool = False) -> Path:
    """The test app with jobs (tests/fixtures/app-jobs) under another name, maybe suggesting an
    automation running its job `summarize`."""
    source = daemon.make_scope() / f"{name}-app"
    shutil.copytree(FIXTURES / "app-jobs", source)
    text = (source / "app.toml").read_text().replace('name = "cv"', f'name = "{name}"')
    (source / "app.toml").write_text(text + (SUGGESTS if suggests else ""))
    return source


def give_folders(daemon: Daemon, name: str) -> dict[str, Path]:
    folders = {need: daemon.make_scope() / need for need in ("cv", "notes")}
    with daemon.http() as c:
        for need, path in folders.items():
            body = {"path": str(path), "create": True}
            r = c.put(f"/v1/apps/{name}/files/{need}", json=body)
            assert r.status_code == 200, r.text
    return folders


def app_view(daemon: Daemon, name: str) -> dict[str, Any]:
    with daemon.http() as c:
        return c.get(f"/v1/apps/{name}").json()


@pytest.mark.rule("app.its-automations-shown-before-install", "app-job.runs-as-its-who-works")
def test_an_app_with_jobs_is_installed_with_who_works(page: Page, daemon: Daemon) -> None:
    """H.2: an app with jobs asks who works on them at install (Install stays grey until
    chosen); its suggested automation running a job says who works, and Install makes it on,
    who works chosen first (so turning it on finds someone to run it)."""
    source = jobs_app(daemon, "cv-install", suggests=True)
    page.goto(f"{daemon.base_url}/#/library/apps/more")  # Install from a file
    file: FilePayload = {
        "name": "cv-install.zip",
        "mimeType": "application/zip",
        "buffer": app_file(source),
    }
    page.get_by_test_id("app-file").set_input_files(file)
    who = page.get_by_test_id("install-who-works")
    expect(who.get_by_test_id("install-jobs")).to_contain_text("Writes your CV")
    give_folders(daemon, "cv-install")  # its folders, given meanwhile: who works left
    page.reload()
    expect(page.get_by_test_id("install-todo")).to_contain_text("who works on its jobs")
    expect(page.get_by_test_id("install-go")).to_be_disabled()
    suggests = page.get_by_test_id("install-suggests")
    expect(suggests).to_contain_text("who you choose works")
    pick_access(page, "fake", who.get_by_test_id("model-choice"))
    expect(suggests).to_contain_text("fake works")
    expect(page.get_by_test_id("install-suggest")).to_have_attribute("aria-checked", "true")
    expect(page.get_by_test_id("install-may")).to_contain_text("Its jobs run as fake")
    expect(page.get_by_test_id("install-todo")).to_have_count(0)
    page.get_by_test_id("install-go").click()
    stopped = page.get_by_test_id("install-error")  # its deploy failed: what was done is kept
    installed = page.get_by_test_id("app-page")  # or it is installed: its page
    expect(stopped.or_(installed)).to_be_visible(timeout=120_000)
    assert app_view(daemon, "cv-install")["whoWorks"] == {"program": "fake", "account": "fake"}
    with daemon.http() as c:
        made = c.get("/v1/automations/cv-install-sum-up-my-notes-each-morning").json()
    assert made["enabled"] is True and made["definition"]["run"]["job"] == "summarize"
    assert made["problems"] == []


@pytest.mark.rule("app-job.runs-as-its-who-works", "app-job.can-do-is-the-app-s")
def test_a_job_s_who_works_is_changed_on_the_app_s_page(page: Page, daemon: Daemon) -> None:
    """H.2: the app's Settings list its jobs, each with who works on it ("as the app"), and what
    each can do among what it may touch (read only, the folders by what they are for); a job
    gets its own Who works in a dialog, then the app's again."""
    with daemon.http() as c:
        assert c.post("/v1/apps", content=app_file(jobs_app(daemon, "cv-page"))).status_code == 201
    give_folders(daemon, "cv-page")
    with daemon.http() as c:
        who = {"program": "fake", "account": "fake"}
        assert c.put("/v1/apps/cv-page/who-works", json=who).status_code == 200
    page.goto(f"{daemon.base_url}/#/apps/cv-page/settings")
    write = page.get_by_test_id("app-job").filter(has_text="Writes your CV")
    expect(write.get_by_test_id("app-job-as")).to_have_text("as the app")
    touch = page.get_by_test_id("app-reaches")
    expect(touch).to_contain_text(
        "Its job “Writes your CV”: reads and writes Your work experience, working in it · "
        "reads Your notes"
    )
    expect(touch.get_by_role("textbox")).to_have_count(0)  # what it can do: not changed here
    write.get_by_test_id("app-job-who-change").click()
    dialog = page.get_by_test_id("app-need-dialog")
    expect(dialog).to_contain_text("Who works on “Writes your CV”")
    pick_access(page, "echo-box", dialog.get_by_test_id("model-choice"))
    dialog.get_by_test_id("app-who-works-save").click()
    expect(write.get_by_test_id("app-job-as")).to_have_text("its own")
    expect(write.get_by_test_id("who-works-account")).to_have_text("echo-box")
    jobs = {j["name"]: j for j in app_view(daemon, "cv-page")["jobs"]}
    assert (jobs["write"]["own"], jobs["write"]["whoWorks"]["account"]) == (True, "echo-box")
    assert jobs["summarize"]["own"] is False
    write.get_by_test_id("app-job-who-back").click()  # the app's again
    expect(write.get_by_test_id("app-job-as")).to_have_text("as the app")
    assert {j["name"]: j["own"] for j in app_view(daemon, "cv-page")["jobs"]}["write"] is False


@pytest.mark.rule("app-job.runs-as-its-who-works")
def test_what_cannot_run_a_job_is_greyed_with_why(page: Page, daemon: Daemon) -> None:
    """H.2: in a job's Who works, the model alone is offered greyed for a job reaching folders,
    saying why; a job an automation runs on an account whose terms refuse runs nobody follows
    is greyed on the app's page, saying why (I.7)."""
    local_provider(daemon, "qwen3.8-27B")  # a provider with the model alone
    with daemon.http() as c:
        assert c.post("/v1/apps", content=app_file(jobs_app(daemon, "cv-grey"))).status_code == 201
    give_folders(daemon, "cv-grey")
    definition = {
        "apiVersion": "handler.automation/v1",
        "when": {"every": "5h"},
        "run": {"app": "cv-grey", "job": "summarize"},
    }
    with daemon.http() as c:
        who = {"program": "fake", "account": "fake"}
        assert c.put("/v1/apps/cv-grey/who-works", json=who).status_code == 200
        body = {"name": "cv-grey-notes", "definition": definition, "enable": True}
        assert c.post("/v1/automations", json=body).status_code == 201
        own = {"program": "login-box", "account": "login-box"}
        assert c.put("/v1/apps/cv-grey/jobs/summarize/who-works", json=own).status_code == 200
    page.goto(f"{daemon.base_url}/#/apps/cv-grey/settings")
    summarize = page.get_by_test_id("app-job").filter(has_text="Says what your notes hold")
    expect(summarize.get_by_test_id("app-job-problem")).to_contain_text(
        "login-box's terms don't allow runs nobody follows, and the automation cv-grey-notes "
        "runs it"
    )
    write = page.get_by_test_id("app-job").filter(has_text="Writes your CV")
    expect(write.get_by_test_id("app-job-problem")).to_have_count(0)
    write.get_by_test_id("app-job-who-change").click()
    dialog = page.get_by_test_id("app-need-dialog")
    pick_access(page, "llamacpp", dialog.get_by_test_id("model-choice"))
    dialog.get_by_test_id("model-choice-harness").click()
    alone = page.get_by_test_id("model-choice-program-alone")
    expect(alone).to_be_disabled()
    expect(alone).to_contain_text("“Writes your CV” reaches folders, schemas or hosts")
