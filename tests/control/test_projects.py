"""Contract D conformance: projects and their agents (contract D.8)."""

import json
import time
from pathlib import Path
from typing import Any

import pytest

from handler_harness.render import FILTERED_NETWORK

from ..support.daemon import Daemon


def create_project(daemon: Daemon, folder: Path, **body: Any) -> dict[str, Any]:
    body = {
        "folder": str(folder),
        "agents": [{"model": {"account": "fake"}, "name": "dev"}],
    } | body
    with daemon.http() as c:
        r = c.post("/v1/projects", json=body)
        assert r.status_code == 201, r.text
        return r.json()


@pytest.mark.rule(
    "project.agents-take-only-what-it-gives", "save.new-agents-start-with-only-the-sites-they-need"
)
def test_create_list_and_defaults(daemon: Daemon) -> None:
    folder = daemon.make_scope()
    project = create_project(
        daemon,
        folder,
        description="the shop",
        agents=[
            {
                "model": {"account": "fake"},
                "name": "coder",
                "description": "writes code",
                "allow": ["npm.example:443"],
                "addons": [{"addon": "fake-browser", "binding": "browser"}],
            },
            {"model": {"account": "fake"}, "name": "review", "network": "none", "default": True},
        ],
    )
    assert project["name"] == folder.name and project["description"] == "the shop"
    review, coder = project["agents"]  # the default agent first
    assert project["defaultAgent"] == review["id"]
    assert (coder["name"], coder["description"]) == ("coder", "writes code")
    assert coder["allow"] == ["npm.example:443"] and coder["addons"] == [
        {"addon": "fake-browser", "binding": "browser"}
    ]
    assert (coder["network"], coder["egress"], coder["permissions"]) == (
        "filtered",
        "enforce",
        "bypass",
    )  # what a new agent starts with: only the sites it needs, never asking
    assert (review["addons"], review["network"]) == ([], "none")  # nothing from the project
    assert coder["projectId"] == project["id"] and coder["scope"] == str(folder)
    with daemon.http() as c:
        assert project["id"] in [p["id"] for p in c.get("/v1/projects").json()]
        # an agent of a project is listed with every agent, and sessions open on it
        assert coder["id"] in [w["id"] for w in c.get("/v1/agents").json()]


@pytest.mark.rule(
    "project.one-project-per-folder",
    "agent.its-home-never-changes",
    "agent.a-project-s-agent-is-named-for-its-goal",
    "folders.agents-work-only-inside-them",
)
def test_refusals(daemon: Daemon, tmp_path: Path) -> None:
    folder = daemon.make_scope()
    project = create_project(daemon, folder)
    agent = project["agents"][0]
    with daemon.http() as c:
        again = c.post(
            "/v1/projects",
            json={
                "folder": str(folder),
                "agents": [{"model": {"account": "fake"}, "name": "dev"}],
            },
        )
        assert again.status_code == 409 and again.json()["title"] == "folder already used"
        outside = c.post(
            "/v1/projects",
            json={
                "folder": str(tmp_path),
                "agents": [{"model": {"account": "fake"}, "name": "dev"}],
            },
        )
        assert outside.status_code == 403
        alone = c.post("/v1/projects", json={"folder": str(tmp_path)})  # with no agent, the same
        assert alone.status_code == 403 and alone.json()["title"] == "scope not allowed"
        twins = [
            {"model": {"account": "fake"}, "name": "dev"},
            {"model": {"account": "fake"}, "name": "DEV"},
        ]
        dupes = c.post("/v1/projects", json={"folder": str(daemon.make_scope()), "agents": twins})
        assert dupes.status_code == 409
        # an agent of a project is named after its goal, never after its model (D.8)
        for unnamed in (
            {"model": {"account": "fake"}},
            {"model": {"account": "fake"}, "name": " "},
        ):
            r = c.post("/v1/agents", json=unnamed | {"projectId": project["id"]})
            assert r.status_code == 400 and r.json()["title"] == "name required", unnamed
        # an agent stays in its home: never moved out of its project
        base = f"/v1/agents/{agent['id']}"
        moved = c.put(base, json={"model": {"account": "fake"}, "scope": str(folder)})
        assert moved.status_code == 409 and moved.json()["title"] == "home cannot change"
        assert c.get("/v1/projects/p_nope").status_code == 404


@pytest.mark.rule(
    "project.its-first-agent-is-its-default", "project.agents-take-only-what-it-gives"
)
def test_update_project_and_agents(daemon: Daemon) -> None:
    project = create_project(daemon, daemon.make_scope())
    pid, first = project["id"], project["agents"][0]
    with daemon.http() as c:
        r = c.post(
            "/v1/agents",
            json={
                "projectId": pid,
                "model": {"account": "fake"},
                "name": "review",
                "instructions": "  be brief ",
                "addons": [{"addon": "fake-browser", "binding": "browser"}],
            },
        )
        assert r.status_code == 201, r.text
        review = r.json()
        assert review["instructions"] == "be brief"

        moved = daemon.make_scope()
        body = {"folder": str(moved), "defaultAgent": review["id"]}
        r = c.put(f"/v1/projects/{pid}", json=body)
        assert r.status_code == 200, r.text
        updated = r.json()
        agents = {a["name"]: a for a in updated["agents"]}
        assert updated["defaultAgent"] == review["id"] and updated["name"] == moved.name
        assert (agents["dev"]["addons"], agents["review"]["addons"]) == (
            [],
            [{"addon": "fake-browser", "binding": "browser"}],
        )
        assert {a["scope"] for a in agents.values()} == {str(moved)}

        r = c.put(
            f"/v1/agents/{first['id']}",
            json={
                "projectId": pid,
                "model": {"account": "fake"},
                "name": "coder",
                "network": "none",
            },
        )
        assert r.status_code == 200 and r.json()["network"] == "none"
        assert c.delete(f"/v1/agents/{review['id']}").status_code == 204
        after = c.get(f"/v1/projects/{pid}").json()
        assert [a["name"] for a in after["agents"]] == ["coder"]
        assert after["defaultAgent"] == first["id"]
        # its last agent deleted: the project stays, with none
        assert c.delete(f"/v1/agents/{first['id']}").status_code == 204
        after = c.get(f"/v1/projects/{pid}").json()
        assert (after["agents"], after.get("defaultAgent")) == ([], None)
        assert after["folder"] == str(moved)

        assert c.delete(f"/v1/projects/{pid}").status_code == 204
        assert c.get(f"/v1/agents/{first['id']}").status_code == 404


@pytest.mark.rule("project.its-first-agent-is-its-default")
def test_a_project_made_with_no_agent(daemon: Daemon) -> None:
    """A project is made alone; its first agent becomes its default, and stays so when another is
    added."""
    folder = daemon.make_scope()
    with daemon.http() as c:
        r = c.post("/v1/projects", json={"folder": str(folder)})
        assert r.status_code == 201, r.text
        project = r.json()
        assert (project["agents"], project.get("defaultAgent")) == ([], None)
        assert project["folder"] == str(folder) and project["name"] == folder.name
        for name in ("Assistant", "review"):
            body = {"projectId": project["id"], "model": {"account": "fake"}, "name": name}
            assert c.post("/v1/agents", json=body).status_code == 201
        after = c.get(f"/v1/projects/{project['id']}").json()
        first = next(a for a in after["agents"] if a["name"] == "Assistant")
        assert after["defaultAgent"] == first["id"]


@pytest.mark.rule("session.instructions-go-with-the-first-turn")
def test_session_started_with_a_request(daemon: Daemon) -> None:
    project = create_project(
        daemon,
        daemon.make_scope(),
        agents=[{"model": {"account": "fake"}, "name": "dev", "instructions": "You review code."}],
    )
    agent = project["agents"][0]
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "prompt": "report"})
        assert r.status_code == 202, r.text
        session = r.json()
        assert session["projectId"] == project["id"] and session["title"] == "report"

    deadline = time.monotonic() + 30
    while True:
        with daemon.http() as c:
            state = c.get(f"/v1/sessions/{session['id']}").json()
        if state["state"] == "running" and not state["busy"]:
            break
        assert time.monotonic() < deadline, state
        time.sleep(0.1)

    client = daemon.connect(session["acpUrl"])
    try:
        client.initialize()
        params = {"sessionId": state["acpSessionId"], "cwd": session["scope"], "mcpServers": []}
        client.request("session/load", params)
        replayed = [
            u["params"]["update"] for u in client.updates if u["method"] == "session/update"
        ]
        sent = [
            u["content"]["text"] for u in replayed if u["sessionUpdate"] == "user_message_chunk"
        ]
        told = f"You review code.\n\n{FILTERED_NETWORK}\n\nreport"  # its network is filtered
        assert sent == [told]
        report = json.loads(client.text())
        assert report["prompt"] == [told]
    finally:
        client.close()


@pytest.mark.rule("save.a-mode-its-harness-offers")
def test_agent_permission_mode(daemon: Daemon) -> None:
    """An agent's own starting mode: shown, given to its sessions, and only one its harness
    offers."""
    project = create_project(
        daemon,
        daemon.make_scope(),
        agents=[{"model": {"account": "fake"}, "name": "dev", "permissions": "accept-edits"}],
    )
    pid, agent = project["id"], project["agents"][0]
    assert agent["permissions"] == "accept-edits"
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"]})
        assert r.status_code == 202, r.text
        session = r.json()
        deadline = time.monotonic() + 30
        while (state := c.get(f"/v1/sessions/{session['id']}").json())["state"] != "running":
            assert time.monotonic() < deadline, state
            time.sleep(0.1)
    client = daemon.connect(session["acpUrl"])
    try:
        client.initialize()
        params = {"sessionId": state["acpSessionId"], "cwd": session["scope"], "mcpServers": []}
        loaded = client.request("session/load", params)
        assert loaded["modes"]["currentModeId"] == "edits"  # the fake harness's accept-edits
    finally:
        client.close()

    with daemon.http() as c:  # the login-box harness only has bypass
        body = {"model": {"account": "login-box"}, "name": "login", "permissions": "ask"}
        r = c.post("/v1/agents", json=body | {"projectId": pid})
        assert r.status_code == 400 and r.json()["title"] == "permission mode not offered"
        assert "it offers: bypass" in r.json()["detail"]


@pytest.mark.rule("save.widening-is-confirmed")
def test_saves_that_widen_an_agent_need_confirming(daemon: Daemon) -> None:
    """PE4 on agents: an open network, containers, a privileged sandbox or auto-approve beyond
    what it had (a new agent: beyond the preset) is saved only once confirmed."""
    folder = daemon.make_scope()
    open_agent = {"model": {"account": "fake"}, "name": "dev", "network": "open"}
    with daemon.http() as c:
        r = c.post("/v1/projects", json={"folder": str(folder), "agents": [open_agent]})
        assert r.status_code == 409 and "open network" in r.json()["detail"]
    project = create_project(
        daemon,
        folder,
        agents=[{"model": {"account": "fake"}, "name": "dev", "permissions": "ask"}],
    )
    url = f"/v1/agents/{project['agents'][0]['id']}"
    with daemon.http() as c:
        wider = {
            "projectId": project["id"],
            "model": {"account": "fake"},
            "name": "dev",
            "permissions": "bypass",
            "confinement": "privileged",
        }
        r = c.put(url, json=wider)
        assert r.status_code == 409 and r.json()["title"] == "risks not confirmed"
        assert "auto-approve" in r.json()["detail"] and "privileged" in r.json()["detail"]
        r = c.put(url, json=wider | {"confirmRisks": True})
        assert r.status_code == 200 and r.json()["confinement"] == "privileged"
        assert c.put(url, json=wider).status_code == 200  # nothing wider than before
        assert (
            c.put(
                url, json=wider | {"permissions": "ask", "confinement": "strict", "network": "none"}
            ).status_code
            == 200
        )


@pytest.mark.rule("save.widening-is-confirmed")
def test_log_only_is_a_wider_network(daemon: Daemon) -> None:
    """D.8: log only lets every host through, so a save that turns it on is confirmed, as one
    that opens the network further is."""
    folder = daemon.make_scope()
    dev = {"model": {"account": "fake"}, "name": "dev"}
    learning = dev | {"egress": "log-only"}
    with daemon.http() as c:
        r = c.post("/v1/projects", json={"folder": str(folder), "agents": [learning]})
        assert r.status_code == 409 and "log only" in r.json()["detail"]
    project = create_project(daemon, folder, agents=[dev])
    url = f"/v1/agents/{project['agents'][0]['id']}"
    dev |= {"projectId": project["id"]}
    learning |= {"projectId": project["id"]}
    with daemon.http() as c:
        r = c.put(url, json=learning)
        assert r.status_code == 409 and "log only" in r.json()["detail"]
        assert c.put(url, json=learning | {"confirmRisks": True}).status_code == 200
        assert c.put(url, json=learning).status_code == 200  # nothing wider than before
        r = c.put(url, json=dev | {"network": "open"})
        assert r.status_code == 409 and "open network" in r.json()["detail"]
        assert c.put(url, json=dev).status_code == 200  # enforcing again: narrower


@pytest.mark.rule("project.caches-are-its-own-unless-shared")
def test_project_caches(daemon: Daemon) -> None:
    """Its own by default; the global ones or none on request; refused otherwise (D.8)."""
    project = create_project(daemon, daemon.make_scope())
    assert project["caches"] == "project"
    with daemon.http() as c:
        url = f"/v1/projects/{project['id']}"
        r = c.put(url, json={"folder": project["folder"], "caches": "global"})
        assert r.status_code == 200 and r.json()["caches"] == "global"
        assert c.get(url).json()["caches"] == "global"
        bad = c.put(url, json={"folder": project["folder"], "caches": "per-scope"})
        assert bad.status_code == 422


@pytest.mark.rule("project.what-it-gives-is-not-picked-again")
def test_a_project_gives_addons_to_all_its_agents(daemon: Daemon) -> None:
    """G.3: as its skills (D.17): its agents get them, one that picked one drops it, none may pick
    one it gives; they are checked with each agent's own; an addon given is not uninstalled."""
    browser = {"addon": "fake-browser", "binding": "browser"}
    project = create_project(
        daemon,
        daemon.make_scope(),
        agents=[
            {"model": {"account": "fake"}, "name": "dev", "addons": [browser]},
            {"model": {"account": "fake"}, "name": "review"},
        ],
    )
    pid = project["id"]
    with daemon.http() as c:
        body = {"folder": project["folder"], "addons": [browser]}
        r = c.put(f"/v1/projects/{pid}", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["addons"] == [browser]
        for agent in r.json()["agents"]:  # dev's own moved to the project
            assert (agent["addons"], agent["projectAddons"]) == ([], [browser])
        r = c.post(
            "/v1/agents",
            json={"projectId": pid, "model": {"account": "fake"}, "name": "x", "addons": [browser]},
        )
        assert (r.status_code, r.json()["title"]) == (400, "given by its project")
        r = c.put(f"/v1/projects/{pid}", json={**body, "addons": [{"addon": "fake-browser"}]})
        assert r.status_code == 400 and "needs a connection" in r.json()["detail"]
        r = c.delete("/v1/addons/fake-browser")
        assert r.status_code == 409 and "in use" in r.json()["title"]


def _wait_session(daemon: Daemon, sid: str, state: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    with daemon.http() as c:
        while (session := c.get(f"/v1/sessions/{sid}").json())["state"] != state:
            assert time.monotonic() < deadline, session
            time.sleep(0.1)
    return session


@pytest.mark.rule("project.deleting-it-never-touches-its-folder")
def test_deleting_a_project_leaves_its_folder_as_it_is(daemon: Daemon) -> None:
    """A project with your files in its folder and a session running, deleted: its session is
    stopped, the project and its agents forgotten; its folder and every file in it are still
    there, unchanged (its own caches removed with it: test_caches).

    If this fails: removing a project from Handler deletes your code."""
    folder = daemon.make_scope()
    (folder / "src").mkdir()
    (folder / "src" / "main.py").write_text("print('mine')\n")
    (folder / ".git").mkdir()
    project = create_project(daemon, folder)
    (agent,) = project["agents"]
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"]})
        assert r.status_code == 202, r.text
        session = _wait_session(daemon, r.json()["id"], "running")
        assert c.delete(f"/v1/projects/{project['id']}").status_code == 204
        assert c.get(f"/v1/projects/{project['id']}").status_code == 404
        assert c.get(f"/v1/agents/{agent['id']}").status_code == 404
    assert _wait_session(daemon, session["id"], "stopped")
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")) == [
        ".git",
        "src",
        "src/main.py",
    ]
    assert (folder / "src" / "main.py").read_text() == "print('mine')\n"
