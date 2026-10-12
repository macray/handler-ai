"""Contract D conformance: project contexts and the accounts and providers made for them
(docs/dev/contracts.md §D.19)."""

from typing import Any

from ..support.daemon import Daemon
from .test_projects import create_project


def put_contexts(daemon: Daemon, account: str, contexts: list[str]) -> None:
    """The test account's contexts (its harness and the rest unchanged)."""
    with daemon.http() as c:
        info = next(a for a in c.get("/v1/accounts").json() if a["name"] == account)
        body = {"name": account, "harness": info["harness"], "contexts": contexts}
        assert c.put(f"/v1/accounts/{account}", json=body).status_code == 200


def session(daemon: Daemon, agent: dict[str, Any], model: dict[str, Any] | None) -> Any:
    with daemon.http() as c:
        return c.post("/v1/sessions", json={"agentId": agent["id"], "model": model})


def test_contexts_are_named_coloured_and_kept_while_used(daemon: Daemon) -> None:
    with daemon.http() as c:
        r = c.post("/v1/contexts", json={"name": "Work", "color": "blue"})
        assert r.status_code == 201 and r.json()["color"] == "blue"
        assert c.post("/v1/contexts", json={"name": "work", "color": "pink"}).status_code == 409
        assert c.post("/v1/contexts", json={"name": "Any", "color": "pink"}).status_code == 422
        assert c.post("/v1/contexts", json={"name": "Work", "color": "red"}).status_code == 422
        r = c.put("/v1/contexts/Work", json={"name": "Work", "color": "violet"})
        assert r.json()["color"] == "violet"
        renamed = c.put("/v1/contexts/Work", json={"name": "Job", "color": "violet"})
        assert renamed.status_code == 409
        assert c.put("/v1/contexts/Nope", json={"name": "Nope", "color": "cyan"}).status_code == 404
        unknown = {"name": "pro", "harness": "fake", "contexts": ["Nope"]}
        assert c.post("/v1/accounts", json=unknown).status_code == 400
        made = c.post("/v1/accounts", json={"name": "pro", "harness": "fake", "contexts": ["Work"]})
        assert made.status_code == 201 and made.json()["contexts"] == ["Work"]
        assert c.delete("/v1/contexts/Work").status_code == 409  # the account names it
        work = next(x for x in c.get("/v1/contexts").json() if x["name"] == "Work")
        assert work["accounts"] == ["pro"]
        assert c.delete("/v1/accounts/pro").status_code == 204
        assert c.delete("/v1/contexts/Work").status_code == 204


def test_a_project_runs_only_the_accounts_made_for_its_context(daemon: Daemon) -> None:
    with daemon.http() as c:
        for name, color in (("Client", "cyan"), ("Home", "pink")):
            assert c.post("/v1/contexts", json={"name": name, "color": color}).status_code == 201
    put_contexts(daemon, "fake", [])
    folder = daemon.make_scope()
    body = {"folder": str(folder), "context": "Client"}
    with daemon.http() as c:
        r = c.post(
            "/v1/projects",
            json=body | {"agents": [{"models": [{"account": "fake"}], "name": "dev"}]},
        )
        assert r.status_code == 409 and r.json()["title"] == "not for this project's context"
        r = c.post(
            "/v1/projects",
            json=body
            | {"context": "Nope", "agents": [{"models": [{"account": "fake"}], "name": "dev"}]},
        )
        assert r.status_code == 400 and r.json()["title"] == "unknown context"
    put_contexts(daemon, "fake", ["Client"])
    project = create_project(daemon, folder, context="Client")
    agent = project["agents"][0]
    assert project["context"] == "Client" and agent["context"] == "Client"
    with daemon.http() as c:
        # a model the agent does not list: run if made for the context
        other = c.post(
            "/v1/accounts", json={"name": "home", "harness": "fake", "contexts": ["Home"]}
        )
        assert other.status_code == 201
    refused = session(daemon, agent, {"account": "home"})
    assert refused.status_code == 409 and "not for Client projects" in refused.json()["detail"]
    put_contexts(daemon, "home", ["any"])
    assert session(daemon, agent, {"account": "home"}).status_code == 202
    # the account's contexts changed since: its agent's model says why it cannot start
    put_contexts(daemon, "fake", ["Home"])
    with daemon.http() as c:
        listed = c.get(f"/v1/projects/{project['id']}").json()["agents"][0]["models"][0]
        assert "not for Client projects" in listed["problem"]
        # nor can its project move to a context its agents' models are not made for
        move = {"folder": str(folder), "context": "Client"}
        assert c.put(f"/v1/projects/{project['id']}", json=move).status_code == 409
        free = c.put(f"/v1/projects/{project['id']}", json={"folder": str(folder)})
        assert free.status_code == 200 and free.json().get("context") is None  # any account
    put_contexts(daemon, "fake", [])


def test_a_provider_is_kept_to_its_contexts_as_an_account(daemon: Daemon) -> None:
    """D.19: a provider says which contexts it is made for, as an account: a work API key never
    runs a personal project's agent; `any` (a local model) runs everywhere."""
    provider = {
        "name": "work-api",
        "endpoints": {"openai-chat": "https://api.example.com/v1"},
        "models": [{"id": "m1"}],
    }
    model = {"provider": "work-api", "harness": "pi"}
    with daemon.http() as c:
        for name, color in (("Office", "blue"), ("Family", "violet")):
            assert c.post("/v1/contexts", json={"name": name, "color": color}).status_code == 201
        unknown = c.post("/v1/providers", json=provider | {"contexts": ["Nope"]})
        assert unknown.status_code == 400
        made = c.post("/v1/providers", json=provider | {"contexts": ["Office"]})
        assert made.status_code == 201 and made.json()["contexts"] == ["Office"]
        assert 'contexts = ["Office"]' in (daemon.providers_dir / "work-api.toml").read_text()
        office = next(x for x in c.get("/v1/contexts").json() if x["name"] == "Office")
        assert office["providers"] == ["work-api"]
        family = {"folder": str(daemon.make_scope()), "context": "Family"}
        agents = [{"models": [model], "name": "dev"}]
        r = c.post("/v1/projects", json=family | {"agents": agents})
        assert r.status_code == 409 and "provider work-api is not for Family" in r.json()["detail"]
    put_contexts(daemon, "fake", ["Family"])
    project = create_project(daemon, daemon.make_scope(), context="Family")
    refused = session(daemon, project["agents"][0], model)
    assert refused.status_code == 409 and "provider work-api" in refused.json()["detail"]
    with daemon.http() as c:  # a local model: any context
        local = provider | {"contexts": ["any"]}
        assert c.put("/v1/providers/work-api", json=local).status_code == 200
    assert session(daemon, project["agents"][0], model).status_code == 202
    put_contexts(daemon, "fake", [])
