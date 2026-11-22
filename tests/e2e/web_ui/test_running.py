"""Running: every running session across projects, in panes; hidden, laid out, started from "+".

Skipped when podman, the image or the built UI is missing."""

import re
import uuid

import pytest
from playwright.sync_api import Page, expect

from ...support import dev_env
from ...support.daemon import Daemon
from ..browser import PW_IMAGE, image_present
from .ui import UI_BUILT, create_project

pytestmark = [
    pytest.mark.skipif(not UI_BUILT, reason="web UI not built (scripts/build-web-ui.sh)"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


def start(daemon: Daemon, agent: dict, title: str, then: str) -> str:
    """A session started elsewhere (as the CLI would): the fake agent answers `then`."""
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "prompt": f"{title}\n{then}"})
    assert r.is_success, r.text
    return r.json()["id"]


def project(daemon: Daemon, name: str) -> dict:
    return create_project(daemon, daemon.make_scope(), name=f"{name}-{uuid.uuid4().hex[:6]}")


def test_running_shows_every_project_s_sessions(page: Page, daemon: Daemon) -> None:
    """Sessions of two projects on one stage; a chip filters; those that need you come first;
    hiding never ends a session, and a hidden one that needs you comes back while it waits; the
    layout is kept by the browser; ⤢ shows one alone, its title switching between them."""
    alpha, beta = project(daemon, "alpha"), project(daemon, "beta")
    working = start(daemon, alpha["agents"][0], "Fix the login loop", "sleep")
    asking = start(daemon, alpha["agents"][0], "Add CSV export", "permission")
    other = start(daemon, beta["agents"][0], "Fix broken links", "ok")

    page.goto(f"{daemon.base_url}/#/running")
    expect(page.get_by_test_id("running-link-count")).to_be_visible()
    page.get_by_test_id("chip").filter(has_text=alpha["name"]).click()
    panes = page.get_by_test_id("session-pane")
    expect(panes).to_have_count(2, timeout=30_000)  # started elsewhere
    expect(page.locator(f'[data-session="{other}"]')).to_have_count(0)  # beta's, filtered
    expect(page.locator(f'[data-session="{working}"]')).to_contain_text("Fix the login loop")
    asks = page.locator(f'[data-session="{asking}"]')
    expect(asks.get_by_test_id("pane-state")).to_have_text("Needs you", timeout=30_000)
    # needs you first, whatever the order they came in
    expect(panes.first).to_have_attribute("data-session", asking)

    # hidden: one setting, listed in the bar; the session still runs
    pane = page.locator(f'[data-session="{working}"]')
    pane.get_by_test_id("pane-more").click()
    page.get_by_test_id("pane-hide").click()
    expect(pane).to_have_count(0)
    expect(page.get_by_test_id("hidden-toggle")).to_contain_text("1 hidden")
    with daemon.http() as c:
        assert c.get(f"/v1/sessions/{working}").json()["state"] == "running"
    # one waiting for you comes back while it waits, said so
    asks.get_by_test_id("pane-more").click()
    page.get_by_test_id("pane-hide").click()
    expect(asks.get_by_test_id("pane-state")).to_have_text("Needs you")
    expect(asks.get_by_test_id("pane-hidden")).to_have_text("hidden")
    page.get_by_test_id("hidden-toggle").click()
    page.get_by_test_id("hidden-show-all").click()
    expect(panes).to_have_count(2)

    # the layout is kept
    page.get_by_test_id("layout-columns").click()
    page.reload()
    expect(page.get_by_test_id("running")).to_have_attribute("data-layout", "columns")

    # alone: One, its title the switcher
    page.locator(f'[data-session="{asking}"]').get_by_test_id("pane-alone").click()
    expect(page).to_have_url(re.compile(f"#/sessions/{asking}$"))
    page.get_by_test_id("switcher-toggle").click()
    expect(
        page.get_by_test_id("switcher-needs-you").filter(has_text="Add CSV export")
    ).to_be_visible()
    page.get_by_test_id("switcher-session").filter(has_text="Fix broken links").click()
    expect(page).to_have_url(re.compile(f"#/sessions/{other}$"))


def test_a_session_started_elsewhere_comes_on_the_stage_at_once(page: Page, daemon: Daemon) -> None:
    """The page open first, then a session started as the CLI would: handlerd's event stream
    tells the page (D.30), no reload, no timer.

    If this fails: Running shows what runs only after a reload, or seconds late."""
    alpha = project(daemon, "alpha")
    page.goto(f"{daemon.base_url}/#/running")
    expect(page.get_by_text("Nothing is running.")).to_be_visible()
    started = start(daemon, alpha["agents"][0], "Tidy the README", "ok")
    expect(page.locator(f'[data-session="{started}"]')).to_have_count(1, timeout=4_000)


def test_a_pane_s_menu_holds_the_header_s_actions(page: Page, daemon: Daemon) -> None:
    """A Grid tile's ⋯: the header's actions (Files, Network, On your phone, Agent settings),
    Hide, then End session…, which asks first; ⤢ stays beside it. Files opens the session in
    One with its files panel."""
    delta = project(daemon, "delta")
    key = start(daemon, delta["agents"][0], "Tidy the changelog", "sleep")
    page.goto(f"{daemon.base_url}/#/running")
    page.get_by_test_id("layout-grid").click()
    pane = page.locator(f'[data-session="{key}"]')
    expect(pane).to_have_count(1, timeout=30_000)
    expect(pane.get_by_test_id("pane-alone")).to_be_visible()

    pane.get_by_test_id("pane-more").click()
    menu = page.get_by_test_id("pane-menu")
    for item in ("pane-files", "pane-network", "pane-agent-settings", "pane-hide", "pane-end"):
        expect(menu.get_by_test_id(item)).to_be_visible()
    expect(menu.get_by_test_id("pane-remote")).to_contain_text("On your phone")
    expect(menu).not_to_contain_text("Full screen")

    # End session… asks; Cancel keeps it running
    menu.get_by_test_id("pane-end").click()
    expect(page.get_by_test_id("ask-yes")).to_have_text("End session")
    page.get_by_test_id("ask-no").click()
    expect(pane).to_have_count(1)
    with daemon.http() as c:
        assert c.get(f"/v1/sessions/{key}").json()["state"] == "running"

    # Files: the session in One, its files panel open
    pane.get_by_test_id("pane-more").click()
    page.get_by_test_id("pane-files").click()
    expect(page).to_have_url(re.compile(f"#/sessions/{key}\\?panel=files$"))
    expect(page.get_by_test_id("files-toggle")).to_have_attribute("aria-pressed", "true")

    # back in Grid, End session… confirmed ends it
    page.goto(f"{daemon.base_url}/#/running")
    page.locator(f'[data-session="{key}"]').get_by_test_id("pane-more").click()
    page.get_by_test_id("pane-end").click()
    page.get_by_test_id("ask-yes").click()
    expect(page.locator(f'[data-session="{key}"]')).to_have_count(0)
    with daemon.http() as c:
        state = c.get(f"/v1/sessions/{key}").json()["state"]
    assert state != "running"


def test_plus_starts_a_session_in_a_new_pane(page: Page, daemon: Daemon) -> None:
    """ "+" adds a pane holding the form, with no prompt: Start makes it the session, its
    composer focused for the first message."""
    gamma = project(daemon, "gamma")
    page.goto(f"{daemon.base_url}/#/running")
    page.get_by_test_id("running-new").click()
    form = page.get_by_test_id("new-session-pane")
    form.get_by_test_id("new-session-project").click()
    form.get_by_test_id("new-session-project-option").filter(has_text=gamma["name"]).click()
    expect(form.get_by_test_id("new-session-agent")).to_contain_text("dev")
    form.get_by_test_id("new-session-start").click()
    expect(form).to_have_count(0)
    prompt = page.locator('[data-focused="true"]').get_by_label("prompt")
    expect(prompt).to_be_focused(timeout=30_000)
    with daemon.http() as c:
        mine = [s for s in c.get("/v1/sessions").json() if s["projectId"] == gamma["id"]]
    assert len(mine) == 1 and mine[0]["state"] in ("starting", "running")


def test_full_screen_in_one_always_has_a_way_out(page: Page, daemon: Daemon) -> None:
    """Full screen in One folds the bar too, its control in the session's caption: a new-session
    pane there has no caption, so the bar stays and its toggle exits full screen."""
    delta = project(daemon, "delta")
    key = start(daemon, delta["agents"][0], "Fix the login loop", "sleep")
    page.goto(f"{daemon.base_url}/#/sessions/{key}")
    page.get_by_test_id("fullscreen").click()
    expect(page.get_by_test_id("running-bar")).to_have_count(0)  # folded into the caption
    expect(page.get_by_test_id("fullscreen-exit")).to_be_visible(timeout=30_000)
    page.get_by_test_id("switcher-toggle").click()
    page.get_by_test_id("switcher-new").click()
    expect(page.get_by_test_id("new-session-pane")).to_be_visible()
    page.get_by_test_id("fullscreen").click()
    expect(page.get_by_test_id("fullscreen")).to_have_attribute("aria-pressed", "false")
    expect(page.locator('[data-sidebar="sidebar"]').first).to_be_visible()
