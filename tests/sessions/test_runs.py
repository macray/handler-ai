"""D.18 conformance: folderless agents and runs of agents with an interface, on a real handlerd
(docs/dev/contracts.md §D.18). The agent is the fake agent: it answers a run as its input's `fake`
says (tests/support/fake_agent.py)."""

import json
import time
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from handler_contracts import ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX

from ..support.acp_client import AcpError
from ..support.daemon import FAKE_SECRET, Daemon
from .test_sessions import attach, create_session, get_session, wait_state

RESULT = {
    "type": "object",
    "properties": {"verdict": {"enum": ["good", "bad"]}, "notes": {"type": "array"}},
    "required": ["verdict"],
}
FIELDS = {
    "type": "object",
    "properties": {"fake": {"type": "string"}, "answer": {}},
    "required": ["fake"],
}


def skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: Does {name} things.\n---\n\nDo it.\n"


BASE = {"models": [{"account": "fake"}], "permissions": "bypass"}  # a run never asks (D.18)


def create_agent(daemon: Daemon, **body: Any) -> dict[str, Any]:
    with daemon.http() as c:
        r = c.post("/v1/agents", json=BASE | body)
        assert r.status_code == 201, r.text
        return r.json()


def wait_output(daemon: Daemon, sid: str) -> dict[str, Any]:
    session = wait_state(daemon, sid, "stopped", timeout=60)
    deadline = time.monotonic() + 10
    while "answer" not in session and time.monotonic() < deadline:
        time.sleep(0.1)
        session = get_session(daemon, sid)
    return session


@pytest.fixture
def skill(daemon: Daemon) -> str:
    name = f"sk-{time.monotonic_ns() % 10**8}"
    with daemon.http() as c:
        assert c.post("/v1/skills", json={"content": skill_md(name)}).status_code == 201
        r = c.put(
            f"/v1/skills/{name}/files/scripts/run.sh",
            json={"text": "echo hi\n", "executable": True},
        )
        assert r.status_code == 200, r.text
    return name


def test_a_folderless_agent_gets_a_folder_per_session(daemon: Daemon, skill: str) -> None:
    agent = create_agent(daemon, name="no-folder", instructions="Be brief.", skills=[skill])
    assert "scope" not in agent and agent["instructions"] == "Be brief."
    assert agent["skills"] == [skill]
    session = create_session(daemon, agent)
    assert session["scope"].endswith(f"/sessions/{session['id']}/work")
    client, _ = attach(daemon, session)
    try:
        client.prompt(get_session(daemon, session["id"])["acpSessionId"], "report")
        report = json.loads(client.text())
        assert report["cwd"] == session["scope"] and report["files"] == []
    finally:
        client.close()
    copied = create_session(daemon, agent, fromSkill=skill)
    client, _ = attach(daemon, copied)
    try:
        client.prompt(get_session(daemon, copied["id"])["acpSessionId"], "report")
        assert json.loads(client.text())["files"] == ["SKILL.md", "scripts"]
    finally:
        client.close()
    with daemon.http() as c:
        scoped = daemon.create_ad_hoc("fake", daemon.make_scope())
        r = c.post("/v1/sessions", json={"agentId": scoped["id"], "fromSkill": skill})
        assert r.status_code == 400 and r.json()["title"] == "a folderless agent's only"
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "fromSkill": "nope"})
        assert r.status_code == 400


def test_a_folderless_agent_has_no_plain_connection(daemon: Daemon) -> None:
    agent = create_agent(daemon, name="no-folder-acp")
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(agent["acpUrl"], subprotocols=protocols) as ws:  # ty: ignore[invalid-argument-type]
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=30)
        assert closed.value.rcvd is not None and closed.value.rcvd.code == 1011
        assert "sessions only" in closed.value.rcvd.reason


def test_an_interface_is_checked(daemon: Daemon) -> None:
    with daemon.http() as c:
        bad = {"result": RESULT, "fields": {"type": "string"}}
        r = c.post("/v1/agents", json=BASE | {"interface": bad})
        assert r.status_code == 400 and r.json()["title"] == "interface invalid"
        bad = {"result": {"type": "nonsense"}}
        r = c.post("/v1/agents", json=BASE | {"interface": bad})
        assert r.status_code == 400 and "not a JSON Schema" in r.json()["detail"]
        asks = BASE | {"permissions": "ask", "interface": {"result": RESULT}}
        r = c.post("/v1/agents", json=asks)
        assert r.status_code == 400 and '"bypass"' in r.json()["detail"]


def test_a_run_gives_its_result_back(daemon: Daemon) -> None:
    interface = {"fields": FIELDS, "result": RESULT}
    agent = create_agent(daemon, name="runner", interface=interface)
    answer = {"verdict": "good", "notes": ["fine"]}
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "prompt": "hi"})
        assert r.status_code == 400 and r.json()["title"] == "input invalid"
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "input": {"fields": {}}})
        assert r.status_code == 400 and "fake" in r.json()["detail"]
    run = create_session(daemon, agent, input={"fields": {"fake": "valid", "answer": answer}})
    assert run["title"] == "runner" and run["input"]["fields"]["fake"] == "valid"
    done = wait_output(daemon, run["id"])
    assert done["output"] == {"valid": True, "value": answer}
    assert "handler-result" in done["answer"]

    repaired = create_session(daemon, agent, input={"fields": {"fake": "repair", "answer": answer}})
    assert wait_output(daemon, repaired["id"])["output"] == {"valid": True, "value": answer}

    wrong = {"verdict": "maybe"}
    invalid = create_session(daemon, agent, input={"fields": {"fake": "valid", "answer": wrong}})
    output = wait_output(daemon, invalid["id"])["output"]
    assert output["valid"] is False and output["value"] == wrong and "verdict" in output["error"]

    none = create_session(daemon, agent, input={"fields": {"fake": "silent"}})
    output = wait_output(daemon, none["id"])["output"]
    assert output == {"valid": False, "error": "no `handler-result` block in the final message"}


def test_a_run_takes_no_prompt(daemon: Daemon) -> None:
    agent = create_agent(daemon, name="quiet", interface={"result": RESULT})
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "input": {"fields": {"x": 1}}})
        assert r.status_code == 400 and r.json()["detail"] == "this agent takes no fields"
    run = create_session(daemon, agent, input={})
    wait_output(daemon, run["id"])
    client, _ = attach(daemon, run)  # restarted, to be read
    try:
        with pytest.raises(AcpError, match="-32012"):
            client.prompt(get_session(daemon, run["id"])["acpSessionId"], "hello")
    finally:
        client.close()


def events(daemon: Daemon, run: dict[str, Any]) -> str:
    return (
        daemon.config_dir.parent / "state" / "sessions" / run["id"] / "events.ndjson"
    ).read_text()


def test_a_run_allows_the_permission_requests_it_still_sends(daemon: Daemon) -> None:
    agent = create_agent(daemon, name="asks", interface={"fields": FIELDS, "result": RESULT})
    run = wait_output(
        daemon, create_session(daemon, agent, input={"fields": {"fake": "permission"}})["id"]
    )
    asked = json.loads(run["answer"])
    assert asked["result"]["outcome"] == {"outcome": "selected", "optionId": "yes"}
    assert "permission answered" in events(daemon, run)


def test_a_run_times_out_or_is_cancelled(daemon: Daemon) -> None:
    interface = {"fields": FIELDS, "result": RESULT, "timeoutSec": 2}
    agent = create_agent(daemon, name="slow", interface=interface)
    run = create_session(daemon, agent, input={"fields": {"fake": "sleep"}})
    run = wait_state(daemon, run["id"], "stopped", timeout=60)
    assert run["lastStopReason"] == "timed_out" and "output" not in run

    agent = create_agent(daemon, name="slower", interface={"fields": FIELDS, "result": RESULT})
    run = create_session(daemon, agent, input={"fields": {"fake": "sleep"}})
    deadline = time.monotonic() + 30
    while not get_session(daemon, run["id"])["busy"]:
        assert time.monotonic() < deadline
        time.sleep(0.1)
    with daemon.http() as c:
        assert c.post(f"/v1/sessions/{run['id']}/cancel").status_code == 200
    assert wait_state(daemon, run["id"], "stopped")["lastStopReason"] == "cancelled"


def test_a_run_whose_agent_crashes(daemon: Daemon) -> None:
    agent = create_agent(daemon, name="crash", interface={"fields": FIELDS, "result": RESULT})
    run = create_session(daemon, agent, input={"fields": {"fake": "exit"}})
    deadline = time.monotonic() + 30
    while (run := get_session(daemon, run["id"]))["state"] in ("starting", "running"):
        assert time.monotonic() < deadline
        time.sleep(0.1)
    assert "agent exited (3)" in (run.get("error") or "") and "output" not in run


def test_a_runs_secret_values_are_redacted(daemon: Daemon) -> None:
    agent = create_agent(daemon, name="leaky", interface={"fields": FIELDS, "result": RESULT})
    run = wait_output(
        daemon, create_session(daemon, agent, input={"fields": {"fake": "leak"}})["id"]
    )
    raw = events(daemon, run)
    assert FAKE_SECRET not in raw and "the token is «redacted»" in raw


def test_a_run_on_a_skill(daemon: Daemon, skill: str) -> None:
    interface = {"subject": "skill", "result": RESULT}
    agent = create_agent(daemon, name="reviewer", interface=interface)
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "input": {}})
        assert r.status_code == 400 and "subject" in r.json()["detail"]
        nope = {"subject": {"skill": "nope"}}
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "input": nope})
        assert r.status_code == 400
    run = create_session(daemon, agent, input={"subject": {"skill": skill}})
    assert run["input"]["subject"]["digest"].startswith("sha256:")
    assert run["title"] == f"reviewer: {skill}"
    with daemon.http() as c:
        listed = c.get("/v1/sessions", params={"subject": f"skill:{skill}"}).json()
        assert [s["id"] for s in listed] == [run["id"]]
    wait_output(daemon, run["id"])


def test_builtin_agents_are_set_up_once(daemon: Daemon) -> None:
    """D.18: an ad-hoc agent with a built-in's name as its origin; its skills go to the library
    first; one agent each, and an agent keeps its origin."""
    with daemon.http() as c:
        builtins = {b["name"]: b for b in c.get("/v1/builtin-agents").json()}
        review = builtins["skill-review"]
        assert review["interface"]["subject"] == "skill" and review["permissions"] == "bypass"
        creator = builtins["skill-creator"]
        assert (
            creator["skills"] == ["handler-skills", "skill-creator"] and "interface" not in creator
        )
        assert "agentId" not in creator
        body = {
            "models": [{"account": "fake"}],
            "name": creator["agentName"],
            "skills": creator["skills"],
            "instructions": creator["instructions"],
            "origin": "skill-creator",
        }
        r = c.post("/v1/agents", json=body)
        assert r.status_code == 201, r.text
        agent = r.json()
        assert agent["origin"] == "skill-creator"
        assert {"handler-skills", "skill-creator"} <= {
            s["name"] for s in c.get("/v1/skills").json()
        }
        listed = {b["name"]: b for b in c.get("/v1/builtin-agents").json()}
        assert listed["skill-creator"]["agentId"] == agent["id"]
        # once each: another one, even set up differently, is refused
        r = c.post("/v1/agents", json=body | {"name": "Another"})
        assert r.status_code == 409 and r.json()["title"] == "built-in agent already set up"
        assert c.post("/v1/agents", json=body | {"origin": "nope"}).status_code == 400
        # its settings are the user's; its origin stays
        url = f"/v1/agents/{agent['id']}"
        assert c.put(url, json=body | {"network": "none"}).status_code == 200
        r = c.put(url, json=body | {"origin": None})
        assert r.status_code == 409 and r.json()["title"] == "origin cannot change"
        # deleted, it can be set up again
        assert c.delete(url).status_code == 204
        assert c.post("/v1/agents", json=body).status_code == 201


def test_a_skill_has_a_digest_and_a_scan(daemon: Daemon, skill: str) -> None:
    with daemon.http() as c:
        read = c.get(f"/v1/skills/{skill}").json()
        assert read["digest"].startswith("sha256:")
        assert read["scan"]["executables"] == ["scripts/run.sh"]
        assert "digest" not in c.get("/v1/skills").json()[0]


def test_a_session_folder_becomes_a_skill(daemon: Daemon, skill: str) -> None:
    agent = create_agent(daemon, name="maker")
    session = create_session(daemon, agent, fromSkill=skill)
    wait_state(daemon, session["id"], "running")
    work = session["scope"]
    with open(f"{work}/SKILL.md", "w") as f:
        f.write(skill_md("made-here"))
    with daemon.http() as c:
        r = c.post(f"/v1/skills/import-session/{session['id']}")
        assert r.status_code == 201, r.text
        assert r.json()["name"] == "made-here"
        assert sorted(f["path"] for f in r.json()["files"]) == ["scripts/run.sh"]
        assert c.post(f"/v1/skills/import-session/{session['id']}").status_code == 409
        r = c.post(f"/v1/skills/import-session/{session['id']}", params={"replace": "true"})
        assert r.status_code == 200
        scoped = daemon.create_ad_hoc("fake", daemon.make_scope())
        other = create_session(daemon, scoped)
        r = c.post(f"/v1/skills/import-session/{other['id']}")
        assert r.status_code == 409 and r.json()["title"] == "a session with a scope"
