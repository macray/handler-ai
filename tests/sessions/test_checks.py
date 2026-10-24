"""D.20 conformance: an agent's checks, on a real handlerd, on the model alone with a stub
provider (no image needed): a run kept as a check, run again, a pass and a fail, what changed
since, one check run at a time, gone with the agent."""

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ..support.daemon import Daemon, start_daemon
from ..support.stub_llm import StubLlm
from .test_runs import wait_output
from .test_sessions import create_session

RESULT = {
    "type": "object",
    "required": ["status", "summary", "verdict"],
    "properties": {
        "status": {"enum": ["ok", "attention", "failed"]},
        "summary": {"type": "string"},
        "verdict": {"enum": ["send", "rewrite"]},
    },
}
FIELDS = {"type": "object", "properties": {"draft": {"type": "string"}}, "required": ["draft"]}


def answer(verdict: str, summary: str = "fine") -> str:
    return (
        f'```json handler-result\n{{"status": "ok", "summary": "{summary}", '
        f'"verdict": "{verdict}"}}\n```'
    )


@pytest.fixture(scope="module")
def stub() -> Iterator[StubLlm]:
    s = StubLlm(answer("send"))
    yield s
    s.close()


@pytest.fixture(scope="module")
def daemon(stub: StubLlm) -> Iterator[Daemon]:
    yield from start_daemon(
        extra_env={"HANDLER_TEST_STUB_KEY": "sk-stub"}, extra_providers={"stub": stub.provider()}
    )


def job(daemon: Daemon, name: str) -> dict[str, Any]:
    body = {
        "name": name,
        "modelAlone": True,
        "model": {"provider": "stub"},
        "instructions": "Judge {{draft}}.",
        "interface": {"fields": FIELDS, "result": RESULT},
    }
    with daemon.http() as c:
        r = c.post("/v1/agents", json=body)
        assert r.status_code == 201, r.text
        return r.json()


def checks(daemon: Daemon, agent: dict[str, Any]) -> dict[str, Any]:
    with daemon.http() as c:
        return c.get(f"/v1/agents/{agent['id']}/checks").json()


def wait_run_end(daemon: Daemon, agent: dict[str, Any]) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        last = checks(daemon, agent).get("last")
        if last and "endedAt" in last:
            return last
        time.sleep(0.2)
    raise AssertionError("the check run did not end")


def test_a_run_kept_as_a_check_passes_then_fails(daemon: Daemon, stub: StubLlm) -> None:
    stub.answer = answer("send")
    agent = job(daemon, "tone")
    run = wait_output(
        daemon, create_session(daemon, agent, input={"fields": {"draft": "Hi"}})["id"]
    )
    with daemon.http() as c:
        r = c.post(f"/v1/agents/{agent['id']}/checks", json={"fromRun": run["id"], "name": "a no"})
        assert r.status_code == 201, r.text
        check = r.json()
    assert check["input"] == {"draft": "Hi"} and check["compare"] == ["status", "verdict"]
    assert check["answer"]["verdict"] == "send"

    stub.answer = answer("send", summary="other words")  # free text is not compared
    with daemon.http() as c:
        assert c.post(f"/v1/agents/{agent['id']}/checks/run").status_code == 202
        assert c.post(f"/v1/agents/{agent['id']}/checks/run").status_code == 409  # one at a time
    [passed] = wait_run_end(daemon, agent)["results"]
    assert passed["state"] == "passed", passed

    stub.answer = answer("rewrite")
    with daemon.http() as c:
        c.post(f"/v1/agents/{agent['id']}/checks/run")
    [failed] = wait_run_end(daemon, agent)["results"]
    assert failed["state"] == "failed" and failed["why"] == 'verdict: "rewrite", not "send"'
    assert failed["got"] == {"status": "ok", "verdict": "rewrite"}

    with daemon.http() as c:  # its runs are not the agent's history: origin "check"
        session = c.get(f"/v1/sessions/{failed['sessionId']}").json()
    assert session["origin"] == "check"


def test_what_changed_since_and_a_check_that_no_longer_fits(daemon: Daemon, stub: StubLlm) -> None:
    stub.answer = answer("send")
    agent = job(daemon, "fits")
    run = wait_output(
        daemon, create_session(daemon, agent, input={"fields": {"draft": "Hi"}})["id"]
    )
    with daemon.http() as c:
        c.post(f"/v1/agents/{agent['id']}/checks", json={"fromRun": run["id"]})
        c.post(f"/v1/agents/{agent['id']}/checks/run")
    wait_run_end(daemon, agent)
    assert checks(daemon, agent)["changed"] == []
    body = {
        "name": "fits",
        "modelAlone": True,
        "model": {"provider": "stub"},
        "instructions": "Judge it.",
        "interface": {"fields": FIELDS, "result": RESULT | {"properties": {}}},
    }
    with daemon.http() as c:
        assert c.put(f"/v1/agents/{agent['id']}", json=body).status_code == 200
    seen = checks(daemon, agent)
    assert seen["changed"] == ["its instructions", "its form or its result"]
    assert seen["checks"][0]["problem"] == "its result no longer has status, verdict"
    with daemon.http() as c:
        r = c.post(f"/v1/agents/{agent['id']}/checks/run")
    assert r.status_code == 400 and "no check it can run" in r.text


def test_checks_go_with_their_agent(daemon: Daemon, stub: StubLlm) -> None:
    stub.answer = answer("send")
    agent = job(daemon, "gone")
    run = wait_output(
        daemon, create_session(daemon, agent, input={"fields": {"draft": "Hi"}})["id"]
    )
    with daemon.http() as c:
        c.post(f"/v1/agents/{agent['id']}/checks", json={"fromRun": run["id"]})
        c.post(f"/v1/agents/{agent['id']}/checks/run")
    session_id = wait_run_end(daemon, agent)["results"][0]["sessionId"]
    with daemon.http() as c:
        assert c.delete(f"/v1/agents/{agent['id']}").status_code == 204
        assert c.get(f"/v1/sessions/{session_id}").status_code == 404
    assert not (
        Path(daemon.env["HANDLER_STATE_DIR"]) / "agent-checks" / f"{agent['id']}.json"
    ).exists()


def test_only_a_job_with_a_valid_result_is_kept(daemon: Daemon, stub: StubLlm) -> None:
    stub.answer = "no result block at all"
    agent = job(daemon, "bad")
    run = wait_output(
        daemon, create_session(daemon, agent, input={"fields": {"draft": "Hi"}})["id"]
    )
    with daemon.http() as c:
        r = c.post(f"/v1/agents/{agent['id']}/checks", json={"fromRun": run["id"]})
    assert r.status_code == 400 and "valid result" in r.text


def test_the_cli_runs_them_and_says_when_one_fails(daemon: Daemon, stub: StubLlm) -> None:
    stub.answer = answer("send")
    agent = job(daemon, "cli")
    run = wait_output(
        daemon, create_session(daemon, agent, input={"fields": {"draft": "Hi"}})["id"]
    )
    with daemon.http() as c:
        c.post(f"/v1/agents/{agent['id']}/checks", json={"fromRun": run["id"], "name": "a no"})
    cli = [str(Path(sys.executable).parent / "handler"), "agent", "checks", agent["id"], "--run"]
    env = os.environ | {
        "HANDLER_URL": daemon.base_url,
        "HANDLER_CONFIG_DIR": str(daemon.config_dir),
    }
    ok = subprocess.run(cli, env=env, capture_output=True, text=True, timeout=60, check=False)
    assert ok.returncode == 0 and "a no" in ok.stdout and "passed" in ok.stdout, ok.stderr
    stub.answer = answer("rewrite")
    bad = subprocess.run(cli, env=env, capture_output=True, text=True, timeout=60, check=False)
    assert bad.returncode == 1 and 'verdict: "rewrite", not "send"' in bad.stdout
