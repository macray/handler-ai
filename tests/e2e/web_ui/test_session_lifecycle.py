"""A session's life in the web UI: resumed, stopped, waiting for its image, its turns and files.

Skipped when podman, the image or the built UI is missing."""

import json
import re
import time

import pytest
from playwright.sync_api import Page, expect

from handler_harness.render import FILTERED_NETWORK

from ...support import dev_env
from ...support.daemon import Daemon
from ..browser import PW_IMAGE, image_present
from .ui import UI_BUILT, create_project, new_project, open_run, say

pytestmark = [
    pytest.mark.skipif(not UI_BUILT, reason="web UI not built (scripts/build-web-ui.sh)"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


def end_then_open_its_project(page: Page) -> None:
    """End the session shown (Running then shows what still runs), then open its project, whose
    timeline lists it, stopped."""
    project = page.get_by_test_id("session-project").get_attribute("href")
    page.get_by_test_id("end-session").click()
    page.get_by_test_id("ask-yes").click()  # "End this session?"
    expect(page).to_have_url(re.compile(r"#/running$"))
    page.goto(page.url.split("#")[0] + (project or ""))


@pytest.mark.rule("session.attaching-resumes-a-stopped-session")
def test_closed_session_can_be_resumed(page: Page, daemon: Daemon) -> None:
    open_run(page, daemon)
    say(page, "hello")
    expect(page.get_by_test_id("agent-message").last).to_contain_text("ok")
    end_then_open_its_project(page)
    page.get_by_test_id("resume-session").first.click()  # on its timeline
    # the daemon's log; a resume starts a sandbox again: as long as a first start (open_run)
    expect(page.get_by_test_id("agent-message").last).to_contain_text("ok", timeout=30_000)
    say(page, "report")
    expect(page.get_by_test_id("agent-message").last).to_contain_text('"session/load"')


def test_how_full_the_context_is_stays_when_resumed(page: Page, daemon: Daemon) -> None:
    open_run(page, daemon)
    meter = page.get_by_test_id("context-meter")
    expect(meter).to_have_count(0)  # the agent has not said: nothing shown
    say(page, "usage")
    expect(meter).to_contain_text("85% · 170k / 200k")
    end_then_open_its_project(page)
    page.get_by_test_id("resume-session").first.click()
    expect(page.get_by_test_id("agent-message").last).to_contain_text("ok", timeout=30_000)
    expect(meter).to_contain_text("85% · 170k / 200k")  # from the daemon's log


@pytest.mark.rule("history.the-log-is-the-history")
def test_a_stopped_session_keeps_its_conversation(page: Page, daemon: Daemon) -> None:
    open_run(page, daemon)
    say(page, "hello")
    expect(page.get_by_test_id("agent-message").last).to_contain_text("ok")
    say(page, "exit")  # the agent exits
    closed = page.get_by_test_id("closed")
    expect(closed).to_contain_text("The agent is stopped")
    expect(page.get_by_test_id("agent-message").last).to_contain_text("ok")  # still readable
    expect(page.get_by_test_id("user-message").first).to_contain_text("hello")
    expect(page.get_by_label("prompt")).to_have_count(0)
    status = page.get_by_test_id("session-header").get_by_test_id("session-status")
    expect(status).to_have_attribute("data-status", "stopped")
    page.get_by_test_id("reconnect").click()
    expect(page.get_by_label("prompt")).to_be_visible()
    expect(status).to_have_attribute("data-status", "idle")
    say(page, "report")
    expect(page.get_by_test_id("agent-message").last).to_contain_text('"session/load"')


@pytest.mark.rule("session.a-start-that-fails-says-why")
def test_a_session_whose_image_is_not_built_says_what_to_prepare(
    page: Page, daemon: Daemon
) -> None:
    """F.1: its start refused, what it needs is said and prepared from the session (here the build
    fails: the fake harness has no Containerfile, or the test daemon no toolbox), the daemon's
    error folded under Details."""
    missing = daemon.config_dir.parent / "fake-ran" / "harness-image-missing"
    new_project(page, daemon, "fake", daemon.make_scope())
    missing.touch()
    try:
        page.get_by_test_id("project-start-button").click()
        panel = page.get_by_test_id("missing-image")
        expect(panel).to_contain_text("can't start yet")
        expect(panel).to_contain_text("not prepared on this computer yet")
        expect(page.get_by_test_id("error")).to_be_hidden()  # in Details, folded
        page.get_by_test_id("missing-image-prepare").click()
        # a real podman build when the machine has a toolbox: slow to fail under load
        expect(panel).to_contain_text("failed: ", timeout=60_000)
        expect(panel.get_by_role("link", name="Settings → Sandboxes")).to_be_visible()
        expect(page.get_by_test_id("missing-image-prepare")).to_have_text("Try again")
    finally:
        missing.unlink()


@pytest.mark.rule("session.a-first-request-waits-for-its-image")
def told(page: Page) -> None:
    """What handlerd tells of a build it runs (D.30), for one faked on disk: the event stream cut
    and opened again, its pages read everything again."""
    page.context.set_offline(True)
    page.wait_for_timeout(500)
    page.context.set_offline(False)


def test_a_session_waiting_for_a_build_follows_it_and_starts_with_its_request(
    page: Page, daemon: Daemon
) -> None:
    """F.1, D.4: a toolbox build is running (started elsewhere): the session follows it, starts
    no second build, starts by itself once it succeeded, and its first request is then sent."""
    missing = daemon.config_dir.parent / "fake-ran" / "harness-image-missing"
    new_project(page, daemon, "fake", daemon.make_scope())
    missing.touch()
    builds = daemon.config_dir.parent / "state" / "builds"
    toolbox = builds / "b_toolbox.json"
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    running = {
        "id": "b_toolbox",
        "target": "toolbox",
        "state": "running",
        "harnesses": ["fake"],
        "startedAt": started,
    }
    try:
        page.get_by_test_id("project-request").fill("report")
        page.get_by_test_id("project-request").press("Enter")
        panel = page.get_by_test_id("missing-image")
        expect(panel).to_contain_text("can't start yet")
        expect(page.get_by_test_id("missing-image-request")).to_have_text(
            "It will start with: report"
        )
        toolbox.write_text(json.dumps(running))  # `handler image rebuild toolbox`, say
        told(page)
        expect(page.get_by_test_id("missing-image-preparing")).to_contain_text(
            "with the toolbox build"
        )
        expect(panel).to_contain_text("the session will start by itself")
        expect(page.get_by_test_id("missing-image-prepare")).to_have_count(0)
        ended = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 1))
        missing.unlink()
        toolbox.write_text(json.dumps(running | {"state": "succeeded", "endedAt": ended}))
        told(page)
        expect(page.get_by_test_id("agent-message").last).to_contain_text('"prompt"')
        expect(page.get_by_test_id("agent-message").last).to_contain_text("report")
        made = [json.loads(p.read_text()) for p in builds.glob("*.json")]
        assert [b["id"] for b in made if b["startedAt"] >= started] == ["b_toolbox"]  # no other
    finally:
        missing.unlink(missing_ok=True)
        toolbox.unlink(missing_ok=True)


def test_a_turn_says_what_it_did_and_the_end_is_one_click_away(page: Page, daemon: Daemon) -> None:
    open_run(page, daemon)
    say(page, "write")  # one completed step
    expect(page.get_by_test_id("turn-summary").last).to_contain_text("1 step")
    say(page, "big")  # more than a screen
    expect(page.get_by_test_id("agent-message").last).to_contain_text("xxxx")
    expect(page.get_by_test_id("turn-summary")).to_have_count(1)  # a turn without a step: none
    page.locator(".screen").evaluate("e => e.scrollTo({top: 0})")
    latest = page.get_by_test_id("to-latest")
    expect(latest).to_be_visible()
    latest.click()
    expect(latest).to_have_count(0)


@pytest.mark.rule("files.changes-are-since-the-session-started")
def test_the_files_pane_follows_what_the_agent_changes(page: Page, daemon: Daemon) -> None:
    folder = daemon.make_scope()
    (folder / "src").mkdir()
    (folder / "src" / "app.py").write_text("print('hi')\n")
    open_run(page, daemon, folder)
    say(page, "write")
    expect(page.get_by_test_id("agent-message").last).to_contain_text("written")
    expect(page.get_by_test_id("files-count")).to_have_text("1")  # without opening the pane
    page.get_by_test_id("files-toggle").click()
    changes = page.get_by_test_id("changes-list")
    expect(changes).to_contain_text("New")
    changes.get_by_text("notes.md").click()
    expect(page.get_by_test_id("file-view")).to_contain_text("# plan")
    expect(page.get_by_test_id("reveal-file")).to_be_visible()  # clicked, it would open one
    page.get_by_test_id("files-tab-all").click()
    page.get_by_test_id("folder-list").get_by_text("src").click()
    page.get_by_test_id("folder-list").get_by_text("app.py").click()
    expect(page.get_by_test_id("file-view")).to_contain_text("print('hi')")
    page.get_by_test_id("files-tab-access").click()  # what it sees of the computer
    mounts = page.get_by_test_id("mounts-list")
    expect(mounts).to_contain_text("This session's folder")
    expect(mounts).to_contain_text(str(folder))
    mounts.get_by_text("This session's folder").click()
    expect(page.get_by_test_id("folder-list")).to_contain_text("notes.md")


@pytest.mark.rule("session.instructions-go-with-the-first-turn")
def test_start_with_a_request_and_an_agents_instructions(page: Page, daemon: Daemon) -> None:
    """The project page: add an agent with instructions, choose it, type the request, Enter."""
    folder = daemon.make_scope()
    project = create_project(daemon, folder)
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}")
    page.get_by_test_id("add-agent").click()
    page.get_by_test_id("agent-name-input").fill("reviewer")
    page.get_by_test_id("agent-description").fill("reviews, never edits")
    page.get_by_test_id("agent-instructions").fill("Be brief.")
    page.get_by_test_id("agent-save").click()
    expect(page.get_by_test_id("agent-row")).to_have_count(2)
    tab = page.get_by_test_id("agent-row").filter(has_text="reviewer")
    tab.click()
    expect(tab).to_have_attribute("title", "reviewer: reviews, never edits")
    page.get_by_test_id("project-request").fill("report")
    page.get_by_test_id("project-request").press("Enter")
    told = json.dumps([f"Be brief.\n\n{FILTERED_NETWORK}\n\nreport"])  # its network is filtered
    expect(page.get_by_test_id("agent-message").last).to_contain_text(f'"prompt": {told}')
    expect(page.get_by_test_id("user-message").first).to_have_text("report")  # the person's
    instructions = page.get_by_test_id("handler-instructions")
    told = instructions.get_by_text("Be brief.")
    expect(told).to_be_hidden()  # folded under Handler's line
    instructions.get_by_text("Handler gave the agent its instructions").click()
    expect(told).to_be_visible()
    expect(instructions).to_contain_text(FILTERED_NETWORK)
    expect(page.get_by_test_id("session-header")).to_contain_text("reviewer")
    expect(page.get_by_test_id("session-caption")).to_contain_text(
        "report"
    )  # the request is the title


def test_many_agents_stay_on_one_line(page: Page, daemon: Daemon) -> None:
    """A project's agent tabs never wrap: those that do not fit are under "+N more", picking one
    brings it into the row, and its Edit is the pencil in its tab."""
    names = [f"agent with a rather long name number {i}" for i in range(12)]
    agents = [{"model": {"account": "fake"}, "name": n} for n in names]
    project = create_project(daemon, daemon.make_scope(), name="crowded", agents=agents)
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}")
    tabs = page.get_by_test_id("agent-row")
    expect(page.get_by_test_id("agents-more")).to_be_visible()
    boxes = [t.bounding_box() for t in tabs.all()]
    assert all(boxes), "a tab is not shown"
    tops = {round(b["y"]) for b in boxes if b}
    assert len(tops) == 1, tops
    shown = tabs.count()
    assert 0 < shown < len(names)
    expect(page.get_by_test_id("agents-more")).to_contain_text(f"+{len(names) - shown} more")
    page.get_by_test_id("agents-more").click()
    page.get_by_test_id("agents-more-find").fill("number 11")
    page.get_by_test_id("agents-more-item").click()
    chosen = tabs.filter(has_text="number 11")
    expect(chosen).to_have_attribute("aria-selected", "true")
    expect(chosen).to_have_attribute("title", names[11])
    page.get_by_test_id("agent-edit").click()
    expect(page.get_by_test_id("agent-name-input")).to_have_value(names[11])


def test_sessions_started_elsewhere_are_listed(page: Page, daemon: Daemon) -> None:
    """A session started by `handler run` (an ad-hoc agent) is listed with its agent's sessions
    without being attached; opening it attaches, and its conversation is there."""
    folder = daemon.make_scope()
    ad_hoc = daemon.create_ad_hoc("fake", folder)
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": ad_hoc["id"], "prompt": "report"})
        sid = r.json()["id"]
    page.goto(f"{daemon.base_url}/#/agents?agent={ad_hoc['id']}")  # outside projects, its agent
    adhoc = page.get_by_test_id("agent-session").filter(has_text="report")
    expect(adhoc).to_be_visible()
    with daemon.http() as c:
        assert c.get(f"/v1/sessions/{sid}").json()["attached"] == 0
    adhoc.get_by_test_id("open-session").click()
    expect(page.get_by_test_id("agent-message").last).to_contain_text('"mode": "yolo"')
    with daemon.http() as c:
        assert c.get(f"/v1/sessions/{sid}").json()["attached"] == 1
