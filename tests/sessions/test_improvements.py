"""D.21 conformance: an improvement of a job's instructions, on a real handlerd, the job and the
prompt writer both on the model alone with a stub provider: attempts written and checked until
every check passes, nothing changed until one is kept, then kept; refused without a writer."""

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest

from ..support.daemon import Daemon, start_daemon
from ..support.stub_llm import StubLlm
from .test_checks import FIELDS, RESULT, answer
from .test_runs import wait_output
from .test_sessions import create_session

RULE = "A polite no is fine: say send."


def provider(body: dict[str, Any]) -> str:
    """The prompt writer adds RULE; the job says send only when its instructions have it."""
    text = json.dumps(body["messages"])
    if "You improve the instructions of an AI job" in text:
        new = "Judge {{draft}}. " + RULE
        return (
            '```json handler-result\n{"status": "ok", "summary": "added a rule", '
            f'"instructions": {json.dumps(new)}, "change": "added a rule"}}\n```'
        )
    return answer("send" if RULE in text else "rewrite")


@pytest.fixture(scope="module")
def stub() -> Iterator[StubLlm]:
    s = StubLlm(provider)
    yield s
    s.close()


@pytest.fixture(scope="module")
def daemon(stub: StubLlm) -> Iterator[Daemon]:
    yield from start_daemon(
        extra_env={"HANDLER_TEST_STUB_KEY": "sk-stub"}, extra_providers={"stub": stub.provider()}
    )


def agent(daemon: Daemon, name: str, **more: Any) -> dict[str, Any]:
    with daemon.http() as c:
        r = c.post(
            "/v1/agents",
            json={"name": name, "modelAlone": True, "model": {"provider": "stub"}} | more,
        )
        assert r.status_code == 201, r.text
        return r.json()


def a_job_with_a_failing_check(daemon: Daemon, stub: StubLlm, name: str) -> dict[str, Any]:
    """Its check's right answer is send; as it is, it says rewrite."""
    job = agent(
        daemon,
        name,
        instructions="Judge {{draft}}.",
        interface={"fields": FIELDS, "result": RESULT},
    )
    stub.answer = answer("send")
    run = wait_output(daemon, create_session(daemon, job, input={"fields": {"draft": "No."}})["id"])
    stub.answer = provider
    with daemon.http() as c:
        r = c.post(f"/v1/agents/{job['id']}/checks", json={"fromRun": run["id"], "name": "a no"})
        assert r.status_code == 201, r.text
    return job


def wait_end(daemon: Daemon, job: dict[str, Any]) -> dict[str, Any]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        with daemon.http() as c:
            [last, *_] = c.get(f"/v1/agents/{job['id']}/improvements").json()
        if last["state"] != "running":
            return last
        time.sleep(0.3)
    raise AssertionError("the improvement did not end")


def test_without_a_prompt_writer_it_is_refused(daemon: Daemon, stub: StubLlm) -> None:
    job = a_job_with_a_failing_check(daemon, stub, "early")
    with daemon.http() as c:
        r = c.post(f"/v1/agents/{job['id']}/improvements", json={"goal": "polite no"})
    assert r.status_code == 409 and "no prompt writer" in r.text


def test_improved_until_its_checks_pass_then_kept(daemon: Daemon, stub: StubLlm) -> None:
    origin = {"kind": "handler-need", "name": "prompt-writer", "version": 1}
    writer = agent(daemon, "writer", origin=origin, **definition(daemon))
    with daemon.http() as c:
        assert c.put("/v1/handler-needs/prompt-writer", json={"agentId": writer["id"]}).is_success
    job = a_job_with_a_failing_check(daemon, stub, "tone")
    with daemon.http() as c:
        r = c.post(
            f"/v1/agents/{job['id']}/improvements", json={"goal": "a polite no", "maxAttempts": 3}
        )
        assert r.status_code == 202, r.text
    done = wait_end(daemon, job)
    assert done["state"] == "done" and done["why"] == "every check passes", done
    first, second = done["attempts"]
    assert first["passed"] == 0 and first["instructions"] == "Judge {{draft}}."
    assert second["passed"] == 1 and RULE in second["instructions"]
    assert second["change"] == "added a rule" and done["best"] == 1
    with daemon.http() as c:  # nothing changed until it is kept
        assert c.get(f"/v1/agents/{job['id']}").json()["instructions"] == "Judge {{draft}}."
        kept = c.post(f"/v1/agents/{job['id']}/improvements/{done['id']}/keep", json={"attempt": 1})
        assert kept.status_code == 200 and kept.json()["kept"] == 1
        assert RULE in c.get(f"/v1/agents/{job['id']}").json()["instructions"]
        back = c.post(f"/v1/agents/{job['id']}/improvements/{done['id']}/keep", json={"attempt": 0})
        assert back.status_code == 200  # back to how it was
        assert c.get(f"/v1/agents/{job['id']}").json()["instructions"] == "Judge {{draft}}."


def definition(daemon: Daemon) -> dict[str, Any]:
    """The prompt writer's defaults (D.18: its need's definition), as the set-up page starts from
    them."""
    with daemon.http() as c:
        need = next(n for n in c.get("/v1/handler-needs").json() if n["name"] == "prompt-writer")
    return {k: need["definition"][k] for k in ("instructions", "interface")}
