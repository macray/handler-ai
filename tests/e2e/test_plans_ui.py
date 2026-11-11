"""Plans in the web UI (D.27), in a real browser against a real handlerd: a plan file opened in a
session's Files, reviewed, approved and run to its end; one with problems cannot be approved; who
runs it chosen and fixed on review; New plan (the plan builder set up, its session on a draft),
the draft edited, approved, copied, thrown away. The steps are answered by the fake agent
(tests/support/fake_agent.py)."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from handler_control.settings import WEB_UI

from ..plans.test_plans import PLAN, project
from ..support import dev_env
from ..support.daemon import Daemon, start_daemon
from .browser import PW_IMAGE, image_present
from .test_web_ui import choose_helper_account

pytestmark = [
    pytest.mark.skipif(not (WEB_UI / "index.html").is_file(), reason="web UI not built"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


@pytest.fixture(scope="module")
def daemon() -> Iterator[Daemon]:
    yield from start_daemon()


@pytest.fixture
def page(browser: Browser, daemon: Daemon) -> Iterator[Page]:
    context = browser.new_context()
    page = context.new_page()
    page.goto(daemon.ui_url())
    yield page
    context.close()


@pytest.mark.rule("plan.what-runs-is-what-you-approved", "plan.one-step-after-another")
def test_a_plan_is_reviewed_from_the_files_approved_and_followed(
    daemon: Daemon, page: Page
) -> None:
    folder, agent = project(daemon)
    (Path(folder) / "plans" / "broken.md").write_text(
        PLAN.format(first="").replace("Agent: dev\n", "")
    )
    with daemon.http() as c:
        sid = c.post("/v1/sessions", json={"agentId": agent["id"], "prompt": "hi"}).json()["id"]
    page.goto(f"{daemon.base_url}/#/sessions/{sid}")
    page.get_by_test_id("files-toggle").click()
    page.get_by_test_id("files-tab-all").click()
    page.get_by_test_id("folder-list").get_by_text("plans", exact=True).click()
    page.get_by_test_id("folder-list").get_by_text("broken.md", exact=True).click()
    page.get_by_test_id("review-plan").click()
    expect(page.get_by_test_id("plan-problems")).to_contain_text("no `Agent:` line")
    expect(page.get_by_test_id("plan-approve")).to_be_disabled()

    page.goto(f"{daemon.base_url}/#/plans/review?session={sid}&path=plans%2Fp.md")
    expect(page.get_by_test_id("plan-what-runs")).to_contain_text("each a new session of dev")
    expect(page.get_by_test_id("plan-review-steps").get_by_role("listitem")).to_have_count(2)
    page.get_by_test_id("plan-approve").click()
    expect(page.get_by_test_id("plan-facts")).to_contain_text("2 of 2 steps done", timeout=30_000)
    expect(page.get_by_test_id("plan-step-summary")).to_have_text(["step 1 done", "step 2 done"])
    page.get_by_test_id("page-crumb").click()  # its project's Plans
    page.get_by_test_id("plans-finished").locator("summary").click()  # done: folded
    expect(page.get_by_test_id("plan-finished")).to_contain_text("two steps")


@pytest.mark.rule("plan.what-runs-is-what-you-approved")
def test_a_file_changed_after_reading_is_read_again(daemon: Daemon, page: Page) -> None:
    folder, agent = project(daemon)
    page.goto(f"{daemon.base_url}/#/plans/review?agent={agent['id']}&path=plans%2Fp.md")
    expect(page.get_by_test_id("plan-what-runs")).to_be_visible()
    (Path(folder) / "plans" / "p.md").write_text(PLAN.format(first="then something else"))
    page.get_by_test_id("plan-approve").click()
    expect(page.get_by_test_id("plan-review-error")).to_contain_text(
        "the plan changed since you read it"
    )
    expect(page.get_by_test_id("plan-approve")).to_be_disabled()
    page.get_by_test_id("plan-read-again").click()
    expect(page.get_by_test_id("plan-review-steps")).to_contain_text("then something else")
    expect(page.get_by_test_id("plan-approve")).to_be_enabled()


@pytest.mark.rule("plan.its-agent-its-settings", "plan.started-by-you-only")
def test_the_review_chooses_its_runner_and_switches_it_to_auto_approve(
    daemon: Daemon, page: Page
) -> None:
    _, agent = project(daemon, PLAN.format(first="").replace("Agent: dev\n", ""))
    body = {"model": {"account": "fake"}, "projectId": agent["projectId"], "name": "dev"}
    with daemon.http() as c:
        r = c.put(f"/v1/agents/{agent['id']}", json=body | {"permissions": "ask"})
        assert r.status_code == 200, r.text
    page.goto(f"{daemon.base_url}/#/plans/review?agent={agent['id']}&path=plans%2Fp.md")
    expect(page.get_by_test_id("plan-problems")).to_contain_text("choose the agent")
    page.get_by_test_id("plan-runner-choice").select_option(label="dev (asks before acting)")
    expect(page.get_by_test_id("plan-problems")).to_contain_text("set dev's mode to bypass")
    page.get_by_test_id("plan-switch-bypass").click()
    expect(page.get_by_test_id("plan-what-runs")).to_contain_text("each a new session of dev")
    expect(page.get_by_test_id("plan-runner-switch")).to_have_count(0)
    with daemon.http() as c:
        assert c.get(f"/v1/agents/{agent['id']}").json()["permissions"] == "bypass"
    page.get_by_test_id("plan-approve").click()
    expect(page.get_by_test_id("plan-facts")).to_contain_text("2 of 2 steps done", timeout=30_000)


@pytest.mark.rule("plan.its-agent-its-settings")
def test_a_plan_runner_is_created_from_the_review(daemon: Daemon, page: Page) -> None:
    folder, agent = project(daemon)  # names dev, which takes a form: no agent may run steps
    job = {"result": {"type": "object"}}
    body = {"model": {"account": "fake"}, "projectId": agent["projectId"], "name": "dev"}
    with daemon.http() as c:
        r = c.put(f"/v1/agents/{agent['id']}", json=body | {"interface": job})
        assert r.status_code == 200, r.text
    page.goto(f"{daemon.base_url}/#/plans/review?agent={agent['id']}&path=plans%2Fp.md")
    expect(page.get_by_test_id("plan-problems")).to_contain_text("takes a form")
    page.get_by_test_id("plan-create-runner").click()
    expect(page.get_by_role("heading", name="New plan runner")).to_be_visible()
    page.get_by_test_id("agent-save").click()
    expect(page.get_by_test_id("plan-runner-overridden")).to_contain_text(
        "The plan names dev; plan-runner runs it"
    )
    expect(page.get_by_test_id("plan-what-runs")).to_contain_text("a new session of plan-runner")
    with daemon.http() as c:
        made = [a for a in c.get("/v1/agents").json() if a.get("name") == "plan-runner"]
    assert len(made) == 1 and made[0]["permissions"] == "bypass"
    assert (made[0]["network"], made[0]["scope"]) == ("filtered", str(folder))
    page.get_by_test_id("plan-approve").click()
    expect(page.get_by_test_id("plan-facts")).to_contain_text("2 of 2 steps done", timeout=30_000)


@pytest.mark.rule("plan.a-draft-is-not-a-plan", "plan.builder-reads-the-project-only")
def test_a_plan_is_built_edited_approved_and_copied(daemon: Daemon, page: Page) -> None:
    _, dev = project(daemon)
    page.goto(f"{daemon.base_url}/#/projects/{dev['projectId']}/plans")
    expect(page.get_by_test_id("plans-builder")).to_contain_text("Written by the plan builder")
    page.get_by_test_id("new-plan-start").click()  # no plan builder yet: its card, in place
    card = page.get_by_test_id("helper-card")
    expect(card).to_contain_text("Plans for")
    expect(card.get_by_test_id("helper-can-do")).to_contain_text("reads the project, read-only")
    choose_helper_account(page, "fake")
    card.get_by_test_id("helper-turn-on").click()  # then the plan starts
    expect(page.get_by_test_id("session-plan-draft")).to_contain_text("A plan for")
    with daemon.http() as c:
        (session,) = [s for s in c.get("/v1/sessions").json() if s.get("planDraft")]
    (Path(session["scope"]) / "plan.md").write_text(PLAN.format(first=""))  # the builder writes
    page.get_by_test_id("plan-draft-review").click()
    expect(page.get_by_test_id("plan-review-facts")).to_contain_text("a draft for")
    expect(page.get_by_test_id("plan-review-steps").get_by_role("listitem")).to_have_count(2)
    page.get_by_test_id("plan-draft-edit").click()
    text = page.get_by_test_id("plan-draft-text")
    text.fill(text.input_value().replace("The second", "The edited one"))
    page.get_by_test_id("plan-draft-save").click()
    expect(page.get_by_test_id("plan-review-steps")).to_contain_text("The edited one")
    page.get_by_test_id("plan-approve").click()
    expect(page.get_by_test_id("plan-facts")).to_contain_text("2 of 2 steps done", timeout=30_000)
    expect(page.get_by_test_id("plan-facts")).to_contain_text("from a draft")
    page.get_by_test_id("plan-edit-as-draft").click()
    expect(page).to_have_url(re.compile(r"#/plans/review\?draft=d_"))
    expect(page.get_by_test_id("plan-review-steps")).to_contain_text("The edited one")
    page.get_by_test_id("page-crumb").click()  # its project's Plans
    drafts = page.get_by_test_id("plan-draft")
    expect(drafts).to_have_count(2)  # the one approved stays, and its copy
    page.once("dialog", lambda d: d.accept())
    drafts.first.get_by_test_id("plan-draft-throw").click()
    expect(drafts).to_have_count(1)
    page.get_by_test_id("plans-finished").locator("summary").click()
    expect(page.get_by_test_id("plan-finished")).to_contain_text("two steps")  # its plan stays
