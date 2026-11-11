"""D.18 conformance: folderless agents, runs of jobs and briefs' sessions, on a real handlerd
(contract D.18). The agent is the fake agent: it answers a run as its input's `fake`
says (tests/support/fake_agent.py)."""

import json
import time
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from handler_contracts import ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX

from ..support.acp_client import AcpError
from ..support.daemon import FAKE_SECRET, Daemon, start_daemon
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
SKILL_FIELD = {"type": "string", "title": "Skill", "x-handler": "skill"}


def skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: Does {name} things.\n---\n\nDo it.\n"


BASE = {"model": {"account": "fake"}, "permissions": "bypass"}  # a run never asks (D.18)


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


@pytest.mark.rule("agent.folderless-works-in-sessions-only")
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


@pytest.mark.rule("agent.folderless-works-in-sessions-only")
def test_a_folderless_agent_has_no_plain_connection(daemon: Daemon) -> None:
    agent = create_agent(daemon, name="no-folder-acp")
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(agent["acpUrl"], subprotocols=protocols) as ws:  # ty: ignore[invalid-argument-type]
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=30)
        assert closed.value.rcvd is not None and closed.value.rcvd.code == 1011
        assert "sessions only" in closed.value.rcvd.reason


@pytest.mark.rule("job.never-asks")
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
        brief = BASE | {"permissions": "ask", "interface": {"fields": FIELDS, "timeoutSec": 60}}
        r = c.post("/v1/agents", json=brief)
        assert r.status_code == 400 and "timeoutSec" in r.json()["detail"]
        r = c.post("/v1/agents", json=BASE | {"interface": {}})
        assert r.status_code == 400 and "a brief" in r.json()["detail"]


@pytest.mark.rule("form.sessions-start-from-the-form", "form.instructions-name-only-its-fields")
def test_a_brief_starts_a_session_from_its_form(daemon: Daemon) -> None:
    """D.18: an interface without a result is a brief: its form starts a session that goes on
    as a chat (its own permission mode, prompts taken, no result, not stopped)."""
    form = {
        "type": "object",
        "properties": {"ask": {"type": "string", "x-handler": "long-text"}, "who": {}},
        "required": ["ask"],
    }
    agent = create_agent(
        daemon,
        name="briefed",
        permissions="ask",
        instructions="Be kind to {{who}}.",
        interface={"fields": form},
    )
    with daemon.http() as c:
        wrong = BASE | {"instructions": "For {{whom}}.", "interface": {"fields": form}}
        r = c.post("/v1/agents", json=wrong)
        assert r.status_code == 400 and r.json()["title"] == "instructions invalid"
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "prompt": "hi"})
        assert r.status_code == 400 and r.json()["title"] == "input invalid"
    session = create_session(
        daemon, agent, input={"fields": {"ask": "Write the notes\nin full", "who": "users"}}
    )
    assert session["title"] == "Write the notes" and session["unattended"] is False
    assert session["input"]["fields"]["ask"].startswith("Write")
    deadline = time.monotonic() + 30
    while (now := get_session(daemon, session["id"]))["busy"] or now["state"] != "running":
        assert time.monotonic() < deadline
        time.sleep(0.1)
    client, _ = attach(daemon, session)
    try:
        client.updates.clear()  # its first turn's answer, replayed
        client.prompt(now["acpSessionId"], "report")
        assert json.loads(client.text())["mode"] == "ask"
    finally:
        client.close()
    raw = events(daemon, session)
    assert "Be kind to users." in raw and "## Input" in raw and "## Result" not in raw
    assert get_session(daemon, session["id"])["state"] == "running"


def test_a_project_with_a_brief_is_saved_again(daemon: Daemon) -> None:
    """D.18: a brief has no time limit, as stored too: its project, saved again after handlerd
    restarted (its agents checked again), is accepted; a job's default limit is not written."""
    form = {"type": "object", "properties": {"ask": {"type": "string"}}}
    agents = [
        {"model": {"account": "fake"}, "name": "b", "interface": {"fields": form}},
        {"model": {"account": "fake"}, "name": "j", "interface": {"result": RESULT}},
    ]
    folder = str(daemon.make_scope())
    with daemon.http() as c:
        r = c.post("/v1/projects", json={"folder": folder, "agents": agents})
        assert r.status_code == 201, r.text
        project = r.json()
    assert all("timeoutSec" not in a["interface"] for a in project["agents"])
    daemon.restart()
    with daemon.http() as c:
        r = c.put(f"/v1/projects/{project['id']}", json={"folder": folder, "name": "renamed"})
        assert r.status_code == 200, r.text


@pytest.mark.rule("form.sessions-start-from-the-form", "job.its-result-is-checked")
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
    assert run["unattended"] is True
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


@pytest.mark.rule("form.sessions-start-from-the-form", "job.nobody-prompts-a-run")
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


@pytest.mark.rule("job.never-asks")
def test_a_run_allows_the_permission_requests_it_still_sends(daemon: Daemon) -> None:
    agent = create_agent(daemon, name="asks", interface={"fields": FIELDS, "result": RESULT})
    run = wait_output(
        daemon, create_session(daemon, agent, input={"fields": {"fake": "permission"}})["id"]
    )
    asked = json.loads(run["answer"])
    assert asked["result"]["outcome"] == {"outcome": "selected", "optionId": "yes"}
    assert "permission answered" in events(daemon, run)


@pytest.mark.rule("job.a-turn-has-a-time-limit")
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


def wait_busy(daemon: Daemon, sid: str) -> None:
    deadline = time.monotonic() + 30
    while not get_session(daemon, sid)["busy"]:
        assert time.monotonic() < deadline
        time.sleep(0.1)


def wait_waiting(daemon: Daemon, sid: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while "waitingFor" not in (session := get_session(daemon, sid)):
        assert time.monotonic() < deadline
        time.sleep(0.1)
    return session


@pytest.mark.rule("job.one-run-of-an-agent-at-a-time")
def test_runs_of_one_agent_take_turns(daemon: Daemon) -> None:
    agent = create_agent(
        daemon, name="one-at-a-time", interface={"fields": FIELDS, "result": RESULT}
    )
    other = create_agent(daemon, name="meanwhile", interface={"fields": FIELDS, "result": RESULT})
    first = create_session(daemon, agent, input={"fields": {"fake": "sleep"}})
    wait_busy(daemon, first["id"])
    answer = {"verdict": "good"}
    second = create_session(daemon, agent, input={"fields": {"fake": "valid", "answer": answer}})
    third = create_session(daemon, agent, input={"fields": {"fake": "valid", "answer": answer}})
    assert wait_waiting(daemon, second["id"])["waitingFor"] == first["id"]
    assert wait_waiting(daemon, third["id"])["state"] == "starting"
    # another agent's run does not wait
    alone = create_session(daemon, other, input={"fields": {"fake": "valid", "answer": answer}})
    assert wait_output(daemon, alone["id"])["output"]["valid"] is True
    protocols = [ACP_SUBPROTOCOL, BEARER_SUBPROTOCOL_PREFIX + daemon.token]
    with connect(second["acpUrl"], subprotocols=protocols) as ws:  # ty: ignore[invalid-argument-type]
        with pytest.raises(ConnectionClosed) as closed:  # a client cannot start it early
            ws.recv(timeout=10)
        assert closed.value.rcvd is not None and "waits for its agent" in closed.value.rcvd.reason
    with daemon.http() as c:
        assert c.post(f"/v1/sessions/{third['id']}/cancel").status_code == 200
    stopped = wait_state(daemon, third["id"], "failed")
    assert stopped["error"] == "cancelled before its turn" and "waitingFor" not in stopped
    with daemon.http() as c:
        assert c.post(f"/v1/sessions/{first['id']}/cancel").status_code == 200
    done = wait_output(daemon, second["id"])  # its turn came
    assert done["output"] == {"valid": True, "value": answer} and "waitingFor" not in done


@pytest.mark.rule("job.one-run-of-an-agent-at-a-time")
def test_a_run_waits_for_its_turn_at_most_its_limit() -> None:
    for daemon in start_daemon(extra_env={"HANDLER_RUN_WAIT_TIMEOUT": "1"}):
        agent = create_agent(daemon, name="busy", interface={"fields": FIELDS, "result": RESULT})
        first = create_session(daemon, agent, input={"fields": {"fake": "sleep"}})
        wait_busy(daemon, first["id"])
        late = create_session(daemon, agent, input={"fields": {"fake": "valid", "answer": {}}})
        failed = wait_state(daemon, late["id"], "failed", timeout=20)
        assert failed["error"] == "waited 1 s: its agent was still running busy"
        assert '"how": "error"' in events(daemon, failed)


@pytest.mark.rule("session.agent-exit-stops-the-session")
def test_a_run_whose_agent_crashes(daemon: Daemon) -> None:
    agent = create_agent(daemon, name="crash", interface={"fields": FIELDS, "result": RESULT})
    run = create_session(daemon, agent, input={"fields": {"fake": "exit"}})
    deadline = time.monotonic() + 30
    while (run := get_session(daemon, run["id"]))["state"] in ("starting", "running"):
        assert time.monotonic() < deadline
        time.sleep(0.1)
    assert "agent exited (3)" in (run.get("error") or "") and "output" not in run


@pytest.mark.rule("history.the-log-holds-no-secret")
def test_a_runs_secret_values_are_redacted(daemon: Daemon) -> None:
    agent = create_agent(daemon, name="leaky", interface={"fields": FIELDS, "result": RESULT})
    run = wait_output(
        daemon, create_session(daemon, agent, input={"fields": {"fake": "leak"}})["id"]
    )
    raw = events(daemon, run)
    assert FAKE_SECRET not in raw and "the token is «redacted»" in raw


@pytest.mark.rule("form.the-subject-is-read-only")
def test_a_run_on_a_skill(daemon: Daemon, skill: str) -> None:
    """D.18: the form's skill field names the skill the run works on (its subject)."""
    two = {"type": "object", "properties": {"a": SKILL_FIELD, "b": SKILL_FIELD}}
    with daemon.http() as c:
        body = BASE | {"name": "two", "interface": {"fields": two, "result": RESULT}}
        r = c.post("/v1/agents", json=body)
        assert r.status_code == 400 and "one skill field at most" in r.text
    form = {"type": "object", "properties": {"target": SKILL_FIELD}, "required": ["target"]}
    agent = create_agent(daemon, name="reviewer", interface={"fields": form, "result": RESULT})
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "input": {}})
        assert r.status_code == 400 and "target" in r.json()["detail"]
        nope = {"fields": {"target": "nope"}}
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "input": nope})
        assert r.status_code == 400
    run = create_session(daemon, agent, input={"fields": {"target": skill}})
    assert run["subject"]["skill"] == skill and run["subject"]["digest"].startswith("sha256:")
    assert run["title"] == f"reviewer: {skill}"
    with daemon.http() as c:
        listed = c.get("/v1/sessions", params={"subject": f"skill:{skill}"}).json()
        assert [s["id"] for s in listed] == [run["id"]]
    wait_output(daemon, run["id"])


@pytest.mark.rule(
    "agent.deleting-it-stops-what-runs-on-it",
    "definition.only-the-origin-follows",
    "helper.handler-uses-the-one-given",
)
def test_handler_s_needs_are_set_up_from_their_definitions_then_given(daemon: Daemon) -> None:
    """D.18: an ad-hoc agent with the origin of one of Handler's needs; its skills go to the
    library first; handler uses the one given (an agent that fits: a chat's, one set up for it);
    an agent keeps its origin."""
    with daemon.http() as c:
        needs = {n["name"]: n for n in c.get("/v1/handler-needs").json()}
        review = needs["skill-review"]["definition"]
        skill_field = review["interface"]["fields"]["properties"]["skill"]
        assert skill_field["x-handler"] == "skill"
        assert review["permissions"] == "bypass"
        creator = needs["skill-creator"]["definition"]
        assert creator["skills"] == ["handler-skills", "skill-creator"]
        assert "interface" not in creator
        assert creator["agentName"] == "Skill creator" and needs["skill-creator"]["version"] == 2
        assert "agentId" not in needs["skill-creator"]
        origin = {"kind": "handler-need", "name": "skill-creator", "version": 2}
        body = {
            "model": {"account": "fake"},
            "name": creator["agentName"],
            "skills": creator["skills"],
            "instructions": creator["instructions"],
            "origin": origin,
        }
        r = c.post("/v1/agents", json=body)
        assert r.status_code == 201, r.text
        agent = r.json()
        assert agent["origin"] == origin
        assert {"handler-skills", "skill-creator"} <= {
            s["name"] for s in c.get("/v1/skills").json()
        }
        listed = {n["name"]: n for n in c.get("/v1/handler-needs").json()}
        assert "agentId" not in listed["skill-creator"]  # set up, not given yet
        assert agent["id"] in listed["skill-creator"]["fits"]
        r = c.put("/v1/handler-needs/skill-creator", json={"agentId": agent["id"]})
        assert r.status_code == 200 and r.json()["agentId"] == agent["id"]
        # another one may be set up; a chat not set up for it does not fit
        another = c.post("/v1/agents", json=body | {"name": "Another"})
        assert another.status_code == 201
        plain = c.post("/v1/agents", json={"model": {"account": "fake"}, "name": "plain"})
        r = c.put("/v1/handler-needs/skill-creator", json={"agentId": plain.json()["id"]})
        assert r.status_code == 409 and "set up as the Skill creator" in r.json()["detail"]
        nope = c.post(
            "/v1/agents",
            json=body | {"origin": {"kind": "handler-need", "name": "nope", "version": 1}},
        )
        assert nope.status_code == 400 and nope.json()["title"] == "unknown handler need"
        later = {"kind": "handler-need", "name": "skill-creator", "version": 9}
        old = c.post("/v1/agents", json=body | {"origin": later})
        assert old.status_code == 409 and old.json()["title"] == "handler need changed"
        assert c.post("/v1/agents", json=body | {"origin": "skill-creator"}).status_code == 422
        # its settings are the user's; its origin stays
        url = f"/v1/agents/{agent['id']}"
        assert c.put(url, json=body | {"network": "none"}).status_code == 200
        r = c.put(url, json=body | {"origin": None})
        assert r.status_code == 409 and r.json()["title"] == "origin cannot change"
        # deleted, none is given any more
        assert c.delete(url).status_code == 204
        listed = {n["name"]: n for n in c.get("/v1/handler-needs").json()}
        assert "agentId" not in listed["skill-creator"]


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
