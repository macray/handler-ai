"""D.29 through a real handlerd: the Library's schemas added, asked before one is replaced,
removed; an agent's knowledge uses checked, linked, and its schemas given read-only, with the
knowledge tool, in the sandbox handlerd composes (the fake sandbox keeps it)."""

import json
import time
from typing import Any

import pytest

from ..support.daemon import Daemon


def schema(schema_id: str, title: str = "Contacts", extends: str | None = None) -> str:
    found = {"$id": schema_id, "title": title, "item": {"fields": {"email": {"type": "string"}}}}
    return json.dumps(found | ({"extends": extends} if extends else {}), indent=2) + "\n"


def add(daemon: Daemon, content: str, replace: bool = False) -> Any:
    with daemon.http() as c:
        return c.post("/v1/schemas", json={"content": content, "replace": replace})


@pytest.mark.rule("knowledge.one-schema-per-id")
def test_one_schema_per_id_a_different_one_asks(daemon: Daemon) -> None:
    r = add(daemon, schema("people@1"))
    assert r.status_code == 201, r.text
    assert r.json() | {"content": None} == {
        "id": "people@1",
        "title": "Contacts",
        "content": None,
    }
    assert add(daemon, schema("people@1")).status_code == 200  # the same: kept
    clash = add(daemon, schema("people@1", title="People"))
    assert clash.status_code == 409 and clash.json()["title"] == "schema exists"
    assert add(daemon, schema("people@1", title="People"), replace=True).status_code == 201
    assert add(daemon, schema("people@2")).status_code == 201  # side by side
    bad = add(daemon, '{"$id": "x@1"}')
    assert bad.status_code == 422 and bad.json()["title"] == "not a schema"
    with daemon.http() as c:
        listed = {s["id"]: s for s in c.get("/v1/schemas").json()}
        assert {"people@1", "people@2"} <= set(listed)
        assert listed["people@1"]["title"] == "People"
        assert c.get("/v1/schemas/people@1").json()["content"] == schema("people@1", "People")
        assert c.get("/v1/schemas/nope@1").status_code == 404
        assert c.delete("/v1/schemas/people@2").status_code == 204
        assert "people@2" not in {s["id"] for s in c.get("/v1/schemas").json()}


@pytest.mark.rule("knowledge.schemas-read-only", "knowledge.one-schema-per-id")
def test_an_agent_uses_schemas_of_the_library(daemon: Daemon) -> None:
    add(daemon, schema("base@1"))
    add(daemon, schema("contacts@1", extends="base@1"))
    scope = daemon.make_scope()
    with daemon.http() as c:
        body = {"model": {"account": "echo-box"}, "scope": str(scope)}
        r = c.post("/v1/agents", json=body | {"schemas": [{"schemaId": "gone@1"}]})
        assert r.status_code == 400 and r.json()["title"] == "schemas unusable", r.text
        alone = {"model": {"provider": "nowhere", "model": "m"}, "modelAlone": True}
        r = c.post("/v1/agents", json=alone | {"schemas": [{"schemaId": "contacts@1"}]})
        assert r.status_code == 400, r.text
    uses = [{"schemaId": "contacts@1", "access": "write"}]
    agent = daemon.create_ad_hoc("echo-box", scope, schemas=uses)
    assert agent["schemas"] == uses
    with daemon.http() as c:
        seen = c.get("/v1/uses/schema/contacts@1").json()["usedBy"]
        assert [(r["kind"], r["how"]) for r in seen] == [("agent", "writes it")]
        r = c.delete("/v1/schemas/contacts@1")
        assert r.status_code == 409 and r.json()["title"] == "schema in use by agents"
        r = c.delete("/v1/schemas/base@1")
        assert r.status_code == 409 and r.json()["title"] == "schema extended"


@pytest.mark.rule("knowledge.schemas-read-only", "tool.each-start-gets-what-it-gives")
def test_its_sandbox_gets_its_schemas_read_only_and_the_tool(daemon: Daemon) -> None:
    """What handlerd composes for an agent with a knowledge use: its schemas and those they
    extend as read-only files where `SMD_SCHEMAS` says, nothing else of the Library, and the
    knowledge tool (its command and skill) without being picked.

    If this fails: an agent rewrites the schema its documents are checked against, sees schemas
    it does not use, or has no command to write its documents with."""
    add(daemon, schema("base@1"))
    add(daemon, schema("books@1", extends="base@1"))
    add(daemon, schema("unused@1"))
    agent = daemon.create_ad_hoc("fake", daemon.make_scope(), schemas=[{"schemaId": "books@1"}])
    spec = started_spec(daemon, agent)
    folder = spec["env"]["SMD_SCHEMAS"]
    assert folder == f"{spec['home']}/.smd-schemas"
    given = {f["target"]: f for f in spec["files"] if f["target"].startswith(folder + "/")}
    assert sorted(given) == [f"{folder}/base@1.schema.json", f"{folder}/books@1.schema.json"]
    assert given[f"{folder}/books@1.schema.json"]["content"] == schema("books@1", extends="base@1")
    assert all(f["mode"] == "0444" and not f.get("writable") for f in given.values())
    assert [a["target"] for a in spec["addons"]] == ["/opt/tools/knowledge"]


def started_spec(daemon: Daemon, agent: dict[str, Any]) -> dict[str, Any]:
    """The SandboxSpec of the agent's first session, as the fake sandbox kept it."""
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"]})
        assert r.status_code == 202, r.text
    ran = daemon.config_dir.parent / "fake-ran"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        found = [p for p in ran.glob(f"handler-{agent['id']}-*") if p.is_file()]
        if found:
            return json.loads(found[0].read_text())
        time.sleep(0.1)
    raise TimeoutError(f"no sandbox for agent {agent['id']}")
