"""Projects and their agents in the web UI: made, their network, terminals, models.

Skipped when podman, the image or the built UI is missing."""

import re
import time
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, Route, expect

from handler_contracts import terminal_path

from ...support import dev_env
from ...support.daemon import Daemon
from ...support.terminal import Attached
from ..browser import PW_IMAGE, image_present
from .ui import (
    UI_BUILT,
    create_project,
    local_provider,
    new_project_page,
    pick_access,
    pick_program,
)

pytestmark = [
    pytest.mark.skipif(not UI_BUILT, reason="web UI not built (scripts/build-web-ui.sh)"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


@pytest.mark.rule("project.its-first-agent-is-its-default")
def test_a_new_project_starts_with_no_agent(page: Page, daemon: Daemon) -> None:
    """New project makes the project alone: its page offers an agent, added in one click as
    Assistant on what the last project used; its last agent removed, the offer is back."""
    create_project(daemon, daemon.make_scope())  # used last: dev, on fake
    folder = daemon.make_scope()
    new_project_page(page, daemon, folder)
    expect(
        page.get_by_test_id("project-folder-recent").filter(has_text=str(folder))
    ).to_be_visible()
    page.get_by_test_id("caches-global").click()
    page.get_by_test_id("project-save").click()
    offer = page.get_by_test_id("no-agent-suggestion")
    expect(offer).to_contain_text("An agent to work with you here")
    expect(page.get_by_test_id("no-agent-set-up")).to_be_visible()
    page.get_by_test_id("no-agent-add").click()
    expect(page.get_by_test_id("project-agents")).to_contain_text("Assistant")
    with daemon.http() as c:
        made = next(p for p in c.get("/v1/projects").json() if p["folder"] == str(folder))
    assert made["caches"] == "global" and made["defaultAgent"] == made["agents"][0]["id"]
    assistant = made["agents"][0]
    assert (assistant["name"], assistant["network"], assistant["permissions"]) == (
        "Assistant",
        "filtered",
        "bypass",
    )
    page.get_by_test_id("agent-edit").click()
    page.get_by_test_id("agent-delete").click()
    page.get_by_test_id("ask-yes").click()
    expect(page.get_by_test_id("no-agent")).to_be_visible()


def test_new_project_folder(page: Page, daemon: Daemon) -> None:
    project = daemon.make_scope()
    new_project_page(page, daemon, project)
    page.get_by_role("button", name="Browse").click()
    page.get_by_test_id("new-folder").click()
    page.get_by_label("new folder name").fill("fresh")
    page.get_by_role("button", name="Create folder").click()
    expect(page.get_by_label("folder path")).to_have_value(str(project / "fresh"))
    assert (project / "fresh").is_dir()


def test_agent_network_settings_apply_live(page: Page, daemon: Daemon) -> None:
    """An agent's own hosts and log-only (confirmed: wider, D.8), set in its editor, apply to its
    running sandbox (A.4); they are the agent's own."""
    project = create_project(
        daemon,
        daemon.make_scope(),
        agents=[
            {
                "model": {"account": "echo-box"},
                "name": "dev",
                "egress": "enforce",
                "allow": ["project.example:443"],
            }
        ],
    )
    agent = project["agents"][0]
    client = daemon.connect(agent["acpUrl"])  # a live container connection
    url = f"{daemon.base_url}/v1/agents/{agent['id']}"
    auth = {"Authorization": f"Bearer {daemon.token}"}
    try:
        deadline = time.monotonic() + 60  # connected once its sandbox started: then the page
        while not httpx.get(url, headers=auth).json()["connections"]:
            assert time.monotonic() < deadline, "the connection never started"
            time.sleep(0.2)
        page.goto(f"{daemon.base_url}/#/projects/{project['id']}/agents/{agent['id']}")
        network = page.get_by_test_id("agent-network")  # Can do, nothing folded
        expect(network.get_by_test_id("network-filtered")).to_have_attribute("aria-checked", "true")
        hosts = network.get_by_test_id("agent-hosts")
        expect(hosts).to_contain_text("project.example:443")  # its own
        learn = network.get_by_test_id("agent-log-only")
        learn.click()
        expect(learn).to_have_attribute("aria-checked", "true")
        network.get_by_test_id("agent-add-site").click()
        network.get_by_test_id("agent-site-input").fill("https://PyPI.org:443/simple")
        network.get_by_test_id("agent-site-allow").click()
        expect(hosts.get_by_test_id("allow-entry")).to_have_text(
            ["project.example:443", "pypi.org:443"]
        )
        expect(page.get_by_test_id("agent-editor")).to_contain_text("1 running")
        page.get_by_test_id("agent-save").click()
        expect(page.get_by_test_id("agent-risks")).to_contain_text("log only")  # wider (D.8)
        page.get_by_test_id("agent-confirm-risks").click()
        expect(page.get_by_test_id("agent-editor")).to_have_count(0)
        saved = httpx.get(url, headers=auth).json()
        assert (saved["allow"], saved["egress"]) == (
            ["project.example:443", "pypi.org:443"],
            "log-only",
        )
    finally:
        client.close()


def test_a_terminal_is_shown_with_its_network(page: Page, daemon: Daemon) -> None:
    """A terminal started with `handler terminal` (D.16) is listed live with its agent's
    sessions; Running shows it as a line, whose network changes at once (A.4), until it ends."""
    project = create_project(daemon, daemon.make_scope())
    agent = project["agents"][0]
    with daemon.http() as c:
        r = c.post(terminal_path(agent["id"]), json={})
    assert r.status_code == 201, r.text
    term = Attached(r.json()["attach"])
    ended = False
    try:
        term.until("args:")
        page.goto(f"{daemon.base_url}/#/projects/{project['id']}")
        panel = page.get_by_test_id("agent-panel")  # dev, the default agent
        chosen = page.get_by_test_id("agent-row").filter(has_text="dev")
        expect(chosen).to_have_attribute("aria-selected", "true")
        row = panel.get_by_test_id("live-terminal")
        expect(row).to_contain_text("account fake")
        row.get_by_role("link", name="Open").click()  # Running, its network open
        line = page.get_by_test_id("terminal-line").filter(has_text="dev, in your terminal")
        expect(line).to_have_attribute("title", re.compile("account fake"))
        expect(page.get_by_test_id("terminal-network")).to_contain_text("dev, in your terminal")
        page.get_by_test_id("egress-toggle").click()  # learn hosts
        expect(page.get_by_test_id("network-panel")).to_contain_text("Learning the sites")
        with daemon.http() as c:
            assert c.get(f"/v1/agents/{agent['id']}").json()["egress"] == "log-only"
        term.type("quit")
        ended = True
        assert term.exit_code() == 3
        expect(line).to_have_count(0, timeout=30_000)  # gone from Running, its network too
        expect(page.get_by_test_id("terminal-network")).to_have_count(0)
    finally:
        if not ended:
            term.type("quit")
            term.exit_code()


def test_a_terminal_outside_the_project_in_its_folder(page: Page, daemon: Daemon) -> None:
    """`handler terminal --anyway` in a project's folder runs an agent outside projects: its
    terminal is listed in the project all the same, marked so, and outside projects with that
    agent."""
    folder = daemon.make_scope()
    project = create_project(daemon, folder)
    agent = daemon.create_ad_hoc("fake", folder, name="anyway")
    with daemon.http() as c:
        r = c.post(terminal_path(agent["id"]), json={})
    assert r.status_code == 201, r.text
    term = Attached(r.json()["attach"])
    try:
        term.until("args:")
        page.goto(f"{daemon.base_url}/#/projects/{project['id']}")
        expect(page.get_by_test_id("live-terminal")).to_contain_text("outside the project")
        page.goto(f"{daemon.base_url}/#/agents?agent={agent['id']}")  # in what it did
        terminal = page.get_by_test_id("agent-panel").get_by_test_id("live-terminal")
        terminal.get_by_role("link", name="Open").click()
        expect(page.get_by_test_id("terminal-network")).to_contain_text("anyway")  # its name
    finally:
        term.type("quit")
        term.exit_code()


@pytest.mark.rule("save.widening-is-confirmed")
def test_widening_an_agent_outside_projects_is_confirmed(page: Page, daemon: Daemon) -> None:
    """D.8 outside projects too: an open network and a privileged sandbox are saved only once
    confirmed."""
    agent = daemon.create_ad_hoc("fake", daemon.make_scope(), name="loose")
    page.goto(f"{daemon.base_url}/#/agents/{agent['id']}/edit")
    page.get_by_test_id("network-open").click()
    page.get_by_test_id("confinement-privileged").click()
    page.get_by_test_id("agent-save").click()
    risks = page.get_by_test_id("agent-risks")
    expect(risks).to_contain_text("open network")
    expect(risks).to_contain_text("privileged")
    page.get_by_test_id("agent-confirm-risks").click()
    expect(page.get_by_test_id("agent-editor")).to_have_count(0)
    with daemon.http() as c:
        saved = c.get(f"/v1/agents/{agent['id']}").json()
    assert (saved["network"], saved["confinement"]) == ("open", "privileged")


def test_an_agent_on_the_model_alone(page: Page, daemon: Daemon) -> None:
    """D.18 in the UI: who works is the model alone, on a provider; what only a sandbox has is
    not offered, and its page says it does nothing outside its call."""
    local_provider(daemon, "qwen3.8-27B")
    project = create_project(daemon, daemon.make_scope())
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}/agents/new")
    who = page.get_by_test_id("agent-model")
    pick_access(page, "llamacpp", who)  # the provider first, then its program
    who.get_by_test_id("model-choice-harness").click()
    page.get_by_test_id("model-choice-program-alone").click()
    expect(who.get_by_test_id("model-choice-harness")).to_have_text("The model alone")
    expect(who.get_by_test_id("model-choice-access")).to_contain_text("llamacpp")
    expect(page.get_by_test_id("agent-alone-safe")).to_be_visible()
    expect(page.get_by_test_id("agent-network")).to_have_count(0)
    page.get_by_test_id("agent-name-input").fill("ask")
    page.get_by_test_id("agent-save").click()
    choice = page.get_by_test_id("model-choice")
    expect(choice.get_by_test_id("model-choice-access")).to_contain_text("llamacpp")
    program = choice.get_by_test_id("model-choice-harness")  # its kind is fixed: text, no menu
    expect(program).to_have_text("The model alone")
    expect(program).not_to_have_attribute("aria-haspopup", "dialog")
    expect(page.get_by_test_id("chip-network")).to_have_count(0)  # no sandbox
    with daemon.http() as c:
        agents = c.get(f"/v1/projects/{project['id']}").json()["agents"]
    alone = next(a for a in agents if a["name"] == "ask")
    assert alone["modelAlone"] is True and "harness" not in alone["model"]


def test_an_agent_on_a_provider_from_the_picker(page: Page, daemon: Daemon) -> None:
    """E in the UI: an agent runs on a provider, with a harness that speaks it and one of its
    models; the agent can be duplicated."""
    local_provider(daemon, "qwen3.8-27B")
    project = create_project(daemon, daemon.make_scope())
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}/agents/new")
    who = page.get_by_test_id("agent-model")
    pick_access(page, "llamacpp", who)
    pick_program(page, "pi")
    expect(who.get_by_test_id("model-choice-harness")).to_contain_text("pi")
    page.get_by_test_id("agent-name-input").fill("local")
    page.get_by_test_id("agent-save").click()
    choice = page.get_by_test_id("model-choice")  # chosen
    expect(choice.get_by_test_id("model-choice-harness")).to_contain_text("pi")
    expect(choice.get_by_test_id("model-choice-access")).to_contain_text("llamacpp")
    with daemon.http() as c:
        agents = c.get(f"/v1/projects/{project['id']}").json()["agents"]
    local = next(a for a in agents if a["name"] == "local")
    model = local["model"]
    assert (model["harness"], model["provider"], model.get("account")) == ("pi", "llamacpp", None)
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}/agents/{local['id']}")
    page.get_by_test_id("agent-duplicate").click()
    expect(page.get_by_test_id("agent-name-input")).to_have_value("local-copy")
    page.get_by_test_id("agent-save").click()
    expect(page.get_by_test_id("project-agents")).to_contain_text("local-copy")


@pytest.mark.rule("session.runs-with-the-model-asked-for")
def test_another_model_for_one_session(page: Page, daemon: Daemon) -> None:
    """D.1 in the UI: a session can run on another provider and program than the agent's, picked
    in Who works (account or provider, then its program, then its model), marked as for this
    session only; picking the agent's again starts with its own (no model sent)."""
    local_provider(daemon, "qwen3.8-27B")
    project = create_project(daemon, daemon.make_scope())
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}")
    choice = page.get_by_test_id("agent-panel").get_by_test_id("model-choice")
    pick_access(page, "llamacpp", choice)
    pick_program(page, "pi")
    expect(choice.get_by_test_id("model-choice-harness")).to_contain_text("pi")
    expect(choice.get_by_test_id("model-choice-model-name")).to_have_text("default model")
    expect(choice.get_by_test_id("model-choice-changed")).to_have_count(1)
    sent: list[Any] = []  # what it asks for; nothing started

    def refuse(route: Route) -> None:
        if route.request.method != "POST":
            return route.fallback()
        sent.append(route.request.post_data_json)
        route.fulfill(status=503, json={"title": "not in this test"})

    page.route("**/v1/sessions", refuse)
    page.get_by_test_id("project-start-button").click()
    expect(page.get_by_test_id("project-error")).to_be_visible()
    model = sent[0]["model"]
    assert (model["harness"], model["provider"], model.get("account")) == ("pi", "llamacpp", None)
    pick_access(page, "fake", choice)  # back to the agent's
    expect(choice.get_by_test_id("model-choice-changed")).to_have_count(0)
    with page.expect_request(lambda r: r.method == "POST" and "/v1/sessions" in r.url) as again:
        page.get_by_test_id("project-start-button").click()
    assert (again.value.post_data_json or {}).get("model") is None


def test_set_up_handler_follows_you_until_the_first_project(page: Page, daemon: Daemon) -> None:
    """E1 in the UI: with no project and no model, the menu's Set up Handler card says how far
    and the next step on every page but Projects; its steps open their dialogs over the page,
    which is never left. Projects shows the same steps large; the card is gone once a project
    exists. (The shared daemon's projects, models and folders answered as on a first day.)"""
    missing = [{"root": "~/nowhere-yet", "path": "/nowhere-yet", "exists": False}]

    def first_day(route: Route) -> None:
        if route.request.method != "GET":
            route.fallback()
        elif route.request.url.endswith("/v1/folders"):
            route.fulfill(json={"folders": missing})
        else:
            route.fulfill(json=[])

    for what in ("projects", "accounts", "providers", "folders"):
        page.route(f"**/v1/{what}", first_day)
    url = f"{daemon.base_url}/#/library"
    page.goto(url)
    card = page.get_by_test_id("setup-card")
    expect(card.get_by_test_id("setup-progress")).to_have_text("0 of 3")
    expect(card.get_by_test_id("setup-next")).to_have_text("Next: Connect a model")
    card.click()
    panel = page.get_by_test_id("setup-panel")
    expect(panel.get_by_test_id("step-project")).to_contain_text("After step 1")
    panel.get_by_test_id("setup-connect").click()
    expect(page.get_by_test_id("model-picker-dialog")).to_contain_text("Connect a model")
    expect(panel).to_have_count(0)  # the panel closed, the page kept
    expect(page).to_have_url(url)
    page.keyboard.press("Escape")
    card.click()
    panel.get_by_test_id("setup-folder").click()
    expect(page.get_by_test_id("work-folder-dialog")).to_be_visible()
    expect(page).to_have_url(url)
    page.keyboard.press("Escape")

    page.goto(f"{daemon.base_url}/#/projects")  # the landing: the steps large, no card
    steps = page.get_by_test_id("get-started").get_by_test_id("setup-steps")
    expect(steps.get_by_test_id("step-model")).to_contain_text("Connect a model")
    expect(card).to_have_count(0)
    steps.get_by_test_id("setup-connect").click()
    expect(page.get_by_test_id("model-picker-dialog")).to_be_visible()
    page.keyboard.press("Escape")

    page.goto(url)
    expect(card).to_be_visible()
    page.unroute("**/v1/projects")  # a project exists: the card is gone at the next page
    create_project(daemon, daemon.make_scope())
    page.get_by_test_id("apps-link").click()
    expect(card).to_have_count(0)


def test_connect_another_opens_over_the_page_and_chooses_the_new_one(
    page: Page, daemon: Daemon
) -> None:
    """E1 and E2 in the UI: Who works' Connect another… opens Model access's Connect over the
    project's page, which it never leaves; the provider made there is chosen for the session."""
    project = create_project(daemon, daemon.make_scope())
    url = f"{daemon.base_url}/#/projects/{project['id']}"
    page.goto(url)
    choice = page.get_by_test_id("agent-panel").get_by_test_id("model-choice")
    choice.get_by_test_id("model-choice-access").click()
    page.get_by_test_id("who-works-connect").click()
    picker = page.get_by_test_id("model-picker-dialog")
    expect(picker).to_contain_text("Connect a model")
    picker.get_by_test_id("connect-api").filter(has_text="OpenRouter").click()
    form = page.get_by_test_id("provider-form")
    name = form.get_by_test_id("provider-name").input_value()
    try:
        form.get_by_test_id("provider-key").fill("sk-or-not-real")
        form.get_by_test_id("provider-save").click()
        expect(page.get_by_test_id("provider-dialog")).not_to_be_visible()
        expect(page).to_have_url(url)
        expect(page.get_by_test_id("agent-panel")).to_be_visible()
        expect(choice.get_by_test_id("model-choice-access")).to_contain_text(name)
        expect(choice.get_by_test_id("model-choice-changed")).to_have_count(1)  # this session only
    finally:
        with daemon.http() as c:
            c.delete(f"/v1/providers/{name}")


def test_the_agents_model_comes_first_in_the_model_list(page: Page, daemon: Daemon) -> None:
    """D.1 in the UI: the account menu names the provider once; its model menu has the default,
    the agent's own (with its name, chosen), then the provider's others; another one picked is
    sent for that session, said to be for this session only, and can be made the agent's own."""
    local_provider(daemon, "qwen3.8-27B", "qwen-long", "qwen-small")
    long = {"harness": "pi", "provider": "llamacpp", "model": "qwen-long"}
    local = {"name": "local", "model": long}
    project = create_project(daemon, daemon.make_scope(), agents=[local])
    page.goto(f"{daemon.base_url}/#/projects/{project['id']}")
    choice = page.get_by_test_id("agent-panel").get_by_test_id("model-choice")
    expect(choice.get_by_test_id("model-choice-access")).to_contain_text("llamacpp")
    expect(choice.get_by_test_id("model-choice-model-name")).to_have_text("qwen-long")
    choice.get_by_test_id("model-choice-access").click()
    accounts = page.get_by_test_id("model-choice-runs-on")
    rows = accounts.get_by_test_id("model-choice-access-row")
    expect(rows.filter(has_text="llamacpp")).to_have_count(1)  # named once
    expect(rows.first).to_contain_text("llamacpp")  # the agent's own first
    page.keyboard.press("Escape")
    choice.get_by_test_id("who-works-model").click()
    menu = page.get_by_test_id("who-works-models")
    model = menu.get_by_test_id("model-choice-model")
    expect(model).to_have_text(["default model qwen3.8-27B", "qwen-longlocal's", "qwen-small"])
    expect(model.nth(1)).to_have_attribute("aria-pressed", "true")
    expect(menu.get_by_test_id("model-choice-session-only")).to_have_count(0)
    sent: list[Any] = []

    def refuse(route: Route) -> None:
        if route.request.method != "POST":
            return route.fallback()
        sent.append(route.request.post_data_json)
        route.fulfill(status=503, json={"title": "not in this test"})

    page.route("**/v1/sessions", refuse)
    model.filter(has_text="qwen-small").click()
    page.get_by_test_id("project-start-button").click()
    expect(page.get_by_test_id("project-error")).to_be_visible()
    assert sent[0]["model"]["model"] == "qwen-small"
    choice.get_by_test_id("who-works-model").click()
    footer = menu.get_by_test_id("model-choice-session-only")
    expect(footer).to_contain_text(
        "qwen-small on llamacpp, for this session only. local stays on llamacpp · qwen-long."
    )
    footer.get_by_test_id("model-choice-make-default").click()  # the agent's own now
    expect(footer).to_have_count(0)
    with daemon.http() as c:
        agent = c.get(f"/v1/projects/{project['id']}").json()["agents"][0]
    assert agent["model"]["model"] == "qwen-small"


def test_only_the_accounts_made_for_the_area_are_offered(page: Page, daemon: Daemon) -> None:
    """D.19 in the UI: a session of a project with an area starts only on an account made for it,
    the agent's own included when that account's areas changed since; the line under the
    sentence says which are not offered."""

    def areas_of(account: str, areas: list[str]) -> None:
        with daemon.http() as c:
            info = next(a for a in c.get("/v1/accounts").json() if a["name"] == account)
            body = {"name": account, "harness": info["harness"], "areas": areas}
            assert c.put(f"/v1/accounts/{account}", json=body).status_code == 200

    with daemon.http() as c:
        for name, color in (("Desk", "blue"), ("Home", "pink")):
            assert c.post("/v1/areas", json={"name": name, "color": color}).status_code == 201
    areas_of("fake", ["Desk"])
    areas_of("echo-box", ["Desk"])
    project = create_project(daemon, daemon.make_scope(), area="Desk")
    areas_of("fake", ["Home"])  # the agent's own account, no longer for Desk
    try:
        page.goto(f"{daemon.base_url}/#/projects/{project['id']}")
        choice = page.get_by_test_id("agent-panel").get_by_test_id("model-choice")
        expect(choice).to_contain_text("echo-box")
        choice.get_by_test_id("model-choice-access").click()
        menu = page.get_by_test_id("model-choice-runs-on")
        expect(menu.get_by_test_id("model-choice-hidden")).to_contain_text("fake")
        page.keyboard.press("Escape")
        sent: list[Any] = []  # what it asks for; nothing started

        def refuse(route: Route) -> None:
            if route.request.method != "POST":
                return route.fallback()
            sent.append(route.request.post_data_json)
            route.fulfill(status=503, json={"title": "not in this test"})

        page.route("**/v1/sessions", refuse)
        page.get_by_test_id("project-start-button").click()
        expect(page.get_by_test_id("project-error")).to_be_visible()
        assert sent[0]["model"]["account"] == "echo-box"
    finally:
        with daemon.http() as c:
            assert c.delete(f"/v1/projects/{project['id']}").status_code == 204
        areas_of("fake", [])
        areas_of("echo-box", [])
        with daemon.http() as c:
            for name in ("Desk", "Home"):
                assert c.delete(f"/v1/areas/{name}").status_code == 204
