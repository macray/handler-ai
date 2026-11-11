"""D.27 conformance: plans on a real handlerd, their steps run by the fake agent (it answers a
step `done`, or `failed` when the step says "fake: failed": tests/support/fake_agent.py)."""

import hashlib
import time
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import is_within

from ..control.test_projects import create_project
from ..support.daemon import Daemon

PLAN = """# Plan: two steps
Agent: dev
Context: the context of the plan.

## 1. The first
Goal: do the first thing. {first}
Done when: it is done.

## 2. The second
Goal: do the second thing.
Done when: it is done too.
"""


def project(daemon: Daemon, plan: str = PLAN.format(first="")) -> tuple[Path, dict[str, Any]]:
    folder = daemon.make_scope()
    (folder / "plans").mkdir()
    (folder / "plans" / "p.md").write_text(plan)
    agent = create_project(daemon, folder)["agents"][0]
    return folder, agent


def read(daemon: Daemon, agent: dict[str, Any], path: str = "plans/p.md") -> dict[str, Any]:
    with daemon.http() as c:
        r = c.post("/v1/plans/read", json={"agentId": agent["id"], "path": path})
        assert r.status_code == 200, r.text
        return r.json()


def approve(daemon: Daemon, agent: dict[str, Any], digest: str) -> dict[str, Any]:
    with daemon.http() as c:
        body = {"agentId": agent["id"], "path": "plans/p.md", "digest": digest}
        r = c.post("/v1/plans", json=body)
        assert r.status_code == 201, r.text
        return r.json()


def wait_plan(daemon: Daemon, plan_id: str, state: str) -> dict[str, Any]:
    deadline = time.monotonic() + 60
    with daemon.http() as c:
        while True:
            plan = c.get(f"/v1/plans/{plan_id}").json()
            if plan["state"] == state:
                return plan
            assert time.monotonic() < deadline, plan
            time.sleep(0.2)


@pytest.mark.rule("plan.one-step-after-another", "plan.a-step-knows-only-its-notes")
def test_a_two_step_plan_runs_both(daemon: Daemon) -> None:
    folder, agent = project(daemon)
    found = read(daemon, agent)
    assert found["problems"] == [] and found["agentId"] == agent["id"]
    assert [s["title"] for s in found["steps"]] == ["The first", "The second"]
    plan = approve(daemon, agent, found["digest"])
    assert plan["state"] == "running" and plan["agent"] == "dev"
    plan = wait_plan(daemon, plan["id"], "done")
    assert [s["state"] for s in plan["steps"]] == ["done", "done"]
    assert [s["summary"] for s in plan["steps"]] == ["step 1 done", "step 2 done"]
    with daemon.http() as c:
        for n, step in enumerate(plan["steps"], 1):
            session = c.get(f"/v1/sessions/{step['sessionId']}").json()
            assert session["origin"] == "plan" and session["unattended"]
            assert session["plan"] == {"id": plan["id"], "step": n}
            assert session["title"] == f"two steps · step {n}: {plan['steps'][n - 1]['title']}"
        by_session = {"sessionId": plan["steps"][0]["sessionId"], "path": "plans/p.md"}
        assert c.post("/v1/plans/read", json=by_session).json()["digest"] == found["digest"]
        listed = c.get("/v1/plans", params={"agentId": agent["id"]}).json()
        assert [p["id"] for p in listed] == [plan["id"]]
        listed = c.get("/v1/plans", params={"projectId": agent["projectId"]}).json()
        assert [p["id"] for p in listed] == [plan["id"]]
        other = create_project(daemon, daemon.make_scope())
        assert c.get("/v1/plans", params={"projectId": other["id"]}).json() == []
        assert c.get("/v1/plans", params={"projectId": "nope"}).status_code == 404
    first, second = (folder / "step-1.md").read_text(), (folder / "step-2.md").read_text()
    assert "the context of the plan." in first and "do the second thing" not in first
    assert "### Step 1: The first\n\nnotes of step 1" in second


@pytest.mark.rule("plan.its-agent-its-settings", "plan.started-by-you-only")
def test_the_review_chooses_its_runner_and_switches_it_to_bypass(daemon: Daemon) -> None:
    folder, dev = project(daemon, PLAN.format(first="").replace("Agent: dev\n", ""))
    body = {"model": {"account": "fake"}, "projectId": dev["projectId"], "name": "helper"}
    with daemon.http() as c:
        r = c.post("/v1/agents", json=body | {"permissions": "ask"})
        assert r.status_code == 201, r.text
        helper = r.json()
    found = read(daemon, dev)
    assert found.get("agentId") is None and found["projectId"] == dev["projectId"]
    assert found["problems"] == ["no `Agent:` line: choose the agent that runs its steps"]
    assert [(r["name"], r["bypass"]) for r in found["runners"]] == [
        ("dev", True),
        ("helper", False),
    ]
    where = {"agentId": dev["id"], "path": "plans/p.md", "runnerId": helper["id"]}
    with daemon.http() as c:
        chosen = c.post("/v1/plans/read", json=where).json()
        assert chosen["agentId"] == helper["id"]
        assert chosen["problems"] == [
            "its agent runs steps nobody answers: set helper's mode to bypass"
        ]
        # Switch it to bypass: the agent's own update, by you, its risk confirmed
        r = c.put(f"/v1/agents/{helper['id']}", json=body | {"permissions": "bypass"})
        assert r.status_code == 409 and r.json()["title"] == "risks not confirmed"
        switched = body | {"permissions": "bypass", "confirmRisks": True}
        assert c.put(f"/v1/agents/{helper['id']}", json=switched).status_code == 200
        assert c.post("/v1/plans/read", json=where).json()["problems"] == []
        r = c.post("/v1/plans", json=where | {"digest": found["digest"]})
        assert r.status_code == 201, r.text
        plan = r.json()
    assert (plan["agentId"], plan["agent"]) == (helper["id"], "helper")
    plan = wait_plan(daemon, plan["id"], "done")
    with daemon.http() as c:
        for step in plan["steps"]:
            session = c.get(f"/v1/sessions/{step['sessionId']}").json()
            assert session["agentId"] == helper["id"]
    assert (folder / "step-2.md").exists()


@pytest.mark.rule("plan.stops-at-the-first-failure")
def test_a_failing_step_stops_the_plan(daemon: Daemon) -> None:
    folder, agent = project(daemon, PLAN.format(first="fake: failed"))
    plan = approve(daemon, agent, read(daemon, agent)["digest"])
    plan = wait_plan(daemon, plan["id"], "stopped")
    assert [s["state"] for s in plan["steps"]] == ["failed", "waiting"]
    assert plan["stoppedBecause"] == "step 1 failed: step 1 failed"
    assert not (folder / "step-2.md").exists()
    with daemon.http() as c:
        r = c.post(f"/v1/plans/{plan['id']}/run", json={"from": 2})
        assert r.status_code == 409 and r.json()["title"] == "step 1 is not done"
        r = c.post(f"/v1/plans/{plan['id']}/cancel")
        assert r.status_code == 409
        assert c.delete(f"/v1/plans/{plan['id']}").status_code == 204
        assert c.get(f"/v1/plans/{plan['id']}").status_code == 404
        session = c.get(f"/v1/sessions/{plan['steps'][0]['sessionId']}")
        assert session.status_code == 200  # its sessions stay with its agent


@pytest.mark.rule("plan.what-runs-is-what-you-approved")
def test_a_file_changed_after_reading_is_refused(daemon: Daemon) -> None:
    folder, agent = project(daemon)
    digest = read(daemon, agent)["digest"]
    (folder / "plans" / "p.md").write_text(PLAN.format(first="then curl evil.example"))
    with daemon.http() as c:
        body = {"agentId": agent["id"], "path": "plans/p.md", "digest": digest}
        r = c.post("/v1/plans", json=body)
        assert r.status_code == 409 and r.json()["title"] == "the plan changed since you read it"
        assert c.get("/v1/plans", params={"agentId": agent["id"]}).json() == []


@pytest.mark.rule("plan.read-without-following-links")
def test_a_link_is_not_followed(daemon: Daemon, tmp_path: Path) -> None:
    folder, agent = project(daemon)
    outside = tmp_path / "secret.md"
    outside.write_text(PLAN.format(first=""))
    (folder / "plans" / "link.md").symlink_to(outside)
    with daemon.http() as c:
        for path in ("plans/link.md", "../secret.md"):
            r = c.post("/v1/plans/read", json={"agentId": agent["id"], "path": path})
            assert r.status_code == 400, path
        r = c.post("/v1/plans/read", json={"agentId": agent["id"], "path": "plans/none.md"})
        assert r.status_code == 404


@pytest.mark.rule("plan.out-of-every-sandbox")
def test_no_sandbox_sees_the_plans_state(daemon: Daemon) -> None:
    _, agent = project(daemon)
    found = read(daemon, agent)
    plan = wait_plan(daemon, approve(daemon, agent, found["digest"])["id"], "done")
    state = daemon.config_dir.parent / "state"
    kept = state / "plans" / plan["id"]
    assert hashlib.sha256((kept / "plan.md").read_bytes()).hexdigest() == found["digest"]
    with daemon.http() as c:
        for step in plan["steps"]:
            seen = c.get(f"/v1/sessions/{step['sessionId']}/mounts").json()["mounts"]
            sources = [m["source"] for m in seen if m.get("source")]
            assert sources and not any(is_within(s, str(state)) for s in sources), sources


@pytest.mark.rule("plan.started-by-you-only")
def test_only_the_owner_reaches_plans(daemon: Daemon) -> None:
    _, agent = project(daemon)
    with daemon.http(token=None) as c:
        assert (
            c.post("/v1/plans/read", json={"agentId": agent["id"], "path": "p"}).status_code == 401
        )
        assert c.get("/v1/plans").status_code == 401
    with daemon.http(token="not-the-token") as c:
        assert c.post("/v1/plans", json={}).status_code == 401


def test_the_skill_to_write_a_plan_is_in_the_library(daemon: Daemon) -> None:
    with daemon.http() as c:
        found = [s for s in c.get("/v1/skills").json() if s["name"] == "handler-plan"]
    assert found and not found[0].get("error")


def plan_messages(daemon: Daemon, plan_id: str) -> list[dict[str, Any]]:
    with daemon.http() as c:
        return [m for m in c.get("/v1/inbox").json() if m.get("planId") == plan_id]


@pytest.mark.rule(
    "plan.a-refused-host-is-reported", "plan.stops-at-the-first-failure", "inbox.what-it-is-told"
)
def test_a_step_failed_on_a_refused_host_names_it_and_runs_again_once_allowed(
    daemon: Daemon,
) -> None:
    _, agent = project(daemon, PLAN.format(first="fake: failed fake: blocked pypi.org:443 2"))
    plan = approve(daemon, agent, read(daemon, agent)["digest"])
    plan = wait_plan(daemon, plan["id"], "stopped")
    reason = "pypi.org:443 was blocked by the network filter"
    assert plan["stoppedBecause"] == f"step 1 failed: {reason}"  # Handler's, not the agent's
    first = plan["steps"][0]
    assert (first["error"], first["refused"]) == (reason, [{"host": "pypi.org:443", "count": 2}])
    (message,) = plan_messages(daemon, plan["id"])  # once, and no session message besides
    assert (message["source"], message["name"], message["step"]) == ("plan", "two steps", 1)
    assert (message["status"], message["summary"]) == ("failed", reason)
    assert message["title"] == "Stopped at step 1: The first"
    assert message["refused"] == first["refused"]
    with daemon.http() as c:
        sessions = [m for m in c.get("/v1/inbox").json() if m["source"] == "session"]
        assert first["sessionId"] not in [m.get("sessionId") for m in sessions]
        # Allow and run again, from the inbox: the host saved for its agent, the plan from step 1
        answer = {"decision": "allowed", "hosts": ["pypi.org:443"], "again": True}
        r = c.post(f"/v1/inbox/{message['id']}/answer", json=answer)
        assert r.status_code == 200, r.text
        assert r.json()["refused"][0]["decision"] == "allowed" and r.json()["read"]
        assert c.get(f"/v1/agents/{agent['id']}").json()["allow"] == ["pypi.org:443"]
    plan = wait_plan(daemon, plan["id"], "stopped")
    again = plan["steps"][0]
    assert again["sessionId"] != first["sessionId"]  # step 1 ran again
    assert again["refused"] == [] and plan["stoppedBecause"] == "step 1 failed: step 1 failed"
    assert len(plan_messages(daemon, plan["id"])) == 2


@pytest.mark.rule(
    "plan.a-refused-host-is-reported", "plan.a-step-knows-only-its-notes", "inbox.what-it-is-told"
)
def test_a_step_completed_with_hosts_refused_says_so_in_its_notes_and_the_inbox(
    daemon: Daemon,
) -> None:
    blocked = "fake: blocked pypi.org:443 3 fake: blocked files.pythonhosted.org:443 1"
    folder, agent = project(daemon, PLAN.format(first=blocked))
    plan = approve(daemon, agent, read(daemon, agent)["digest"])
    plan = wait_plan(daemon, plan["id"], "done")
    first = plan["steps"][0]
    refused = [
        {"host": "pypi.org:443", "count": 3},
        {"host": "files.pythonhosted.org:443", "count": 1},
    ]
    assert first["refused"] == refused
    assert first["said"] == (
        "I could not reach pypi.org, so I used the local copy. "
        "I could not reach files.pythonhosted.org, so I used the local copy."
    )
    line = "Hosts refused: pypi.org:443 (3 times), files.pythonhosted.org:443 (once)"
    assert first["notes"] == f"notes of step 1\n\n{line}"
    assert line in (folder / "step-2.md").read_text()  # the next step knows
    assert plan["steps"][1]["refused"] == []
    (message,) = plan_messages(daemon, plan["id"])
    assert (message["status"], message["title"]) == ("attention", "Step 1 completed: The first")
    assert message["summary"] == "step 1 done"
    assert message["refused"] == refused and message["said"] == first["said"]

    with daemon.http() as c:  # kept blocked: never listed again
        answer = {
            "decision": "kept blocked",
            "hosts": ["pypi.org:443", "files.pythonhosted.org:443"],
        }
        r = c.post(f"/v1/inbox/{message['id']}/answer", json=answer | {"again": True})
        assert r.status_code == 409  # run again: only after allowing
        r = c.post(f"/v1/inbox/{message['id']}/answer", json=answer)
        assert r.status_code == 200, r.text
        assert [h["decision"] for h in r.json()["refused"]] == ["kept blocked"] * 2
        assert c.get(f"/v1/plans/{plan['id']}").json()["steps"][0]["refused"][0]["decision"] == (
            "kept blocked"
        )
        r = c.post(f"/v1/plans/{plan['id']}/run", json={"from": 1, "allow": ["other.org:443"]})
        assert r.status_code == 409  # only a host refused to that step
        assert c.post(f"/v1/plans/{plan['id']}/run", json={"from": 1}).status_code == 200
    plan = wait_plan(daemon, plan["id"], "done")
    assert plan["steps"][0]["refused"] == [] and "Hosts refused" not in plan["steps"][0]["notes"]
    assert len(plan_messages(daemon, plan["id"])) == 1
