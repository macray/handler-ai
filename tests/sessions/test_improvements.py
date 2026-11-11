"""D.21 conformance: an improvement of a job's instructions, on a real handlerd, the job and the
prompt writer both on the model alone with a stub provider: attempts written and checked until
every check passes, nothing changed until one is kept, then kept; refused without a writer."""

import contextlib
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


@pytest.mark.rule("improve.the-writer-is-the-one-you-gave")
def test_without_a_prompt_writer_it_is_refused(daemon: Daemon, stub: StubLlm) -> None:
    job = a_job_with_a_failing_check(daemon, stub, "early")
    with daemon.http() as c:
        r = c.post(f"/v1/agents/{job['id']}/improvements", json={"goal": "polite no"})
    assert r.status_code == 409 and "no prompt writer" in r.text


@pytest.mark.rule(
    "improve.the-writer-is-the-one-you-gave",
    "improve.judged-by-the-checks",
    "improve.within-its-budget",
    "improve.nothing-changes-until-kept",
)
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


# ── refusals, budget and ends (D.21) ────────────────────────────────────

WRITER_ASKED = "You improve the instructions of an AI job"


def a_writer(daemon: Daemon) -> None:
    origin = {"kind": "handler-need", "name": "prompt-writer", "version": 1}
    writer = agent(daemon, f"writer-{time.monotonic_ns()}", origin=origin, **definition(daemon))
    with daemon.http() as c:
        assert c.put("/v1/handler-needs/prompt-writer", json={"agentId": writer["id"]}).is_success


@contextlib.contextmanager
def writer_says(stub: StubLlm, instructions: str, seconds: float = 0) -> Iterator[None]:
    """The prompt writer answers `instructions` (after `seconds`); the job as `provider`."""

    def answering(body: dict[str, Any]) -> str:
        if WRITER_ASKED not in json.dumps(body["messages"]):
            return provider(body)
        time.sleep(seconds)
        return (
            '```json handler-result\n{"status": "ok", "summary": "rewrote", '
            f'"instructions": {json.dumps(instructions)}, "change": "rewrote"}}\n```'
        )

    stub.answer = answering
    try:
        yield
    finally:
        stub.answer = provider


def improve(daemon: Daemon, job: dict[str, Any], **body: Any) -> Any:
    with daemon.http() as c:
        return c.post(f"/v1/agents/{job['id']}/improvements", json={"goal": "send"} | body)


@pytest.mark.rule("improve.judged-by-the-checks")
def test_only_a_job_with_a_check_it_can_run_is_improved(daemon: Daemon, stub: StubLlm) -> None:
    """If this fails: an improvement starts with nothing to judge its attempts by."""
    a_writer(daemon)
    no_job = agent(daemon, "chatty", instructions="Talk.")
    r = improve(daemon, no_job)
    assert r.status_code == 400 and "only a job" in r.text, r.text
    unchecked = agent(daemon, "unchecked", interface={"fields": FIELDS, "result": RESULT})
    r = improve(daemon, unchecked)
    assert r.status_code == 400 and "no check it can run" in r.text, r.text


@pytest.mark.rule("improve.judged-by-the-checks")
def test_one_improvement_at_a_time_never_while_its_checks_run(
    daemon: Daemon, stub: StubLlm
) -> None:
    """If this fails: two improvements, or an improvement and a check run, judge one agent at
    once and each other's attempts."""
    a_writer(daemon)
    job = a_job_with_a_failing_check(daemon, stub, "busy")
    with writer_says(stub, "Judge {{draft}}.", seconds=3):
        assert improve(daemon, job, maxAttempts=1).status_code == 202
        r = improve(daemon, job)
        assert r.status_code == 409 and "being improved" in r.text, r.text
        wait_end(daemon, job)
    stub.answer = provider
    with daemon.http() as c:
        assert c.post(f"/v1/agents/{job['id']}/checks/run").status_code == 202
        r = improve(daemon, job)
        assert r.status_code == 409 and "its checks are running" in r.text, r.text


@pytest.mark.rule("improve.judged-by-the-checks", "improve.within-its-budget")
def test_attempts_that_never_fix_it_end_it_after_its_attempts(
    daemon: Daemon, stub: StubLlm
) -> None:
    """A writer whose every attempt names a field the form has not: each attempt is an error
    and counts; after `maxAttempts`, the improvement is done ("2 attempts made"), best still
    attempt 0.

    If this fails: an improvement runs, and spends, past what you allowed, or an attempt that
    cannot run is said better."""
    a_writer(daemon)
    job = a_job_with_a_failing_check(daemon, stub, "stubborn")
    with writer_says(stub, "Judge {{letter}}."):
        assert improve(daemon, job, maxAttempts=2).status_code == 202
        done = wait_end(daemon, job)
    assert (done["state"], done["why"], done["best"]) == ("done", "2 attempts made", 0), done
    assert [a["state"] for a in done["attempts"][1:]] == ["error", "error"]
    assert "letter" in done["attempts"][1]["why"]


@pytest.mark.rule("improve.within-its-budget", "improve.nothing-changes-until-kept")
def test_a_stopped_improvement_ends_stopped_and_cannot_be_kept_while_it_runs(
    daemon: Daemon, stub: StubLlm
) -> None:
    """If this fails: an improvement goes on after you stopped it, or one under way rewrites the
    agent's instructions."""
    a_writer(daemon)
    job = a_job_with_a_failing_check(daemon, stub, "stopped")
    with writer_says(stub, "Judge {{draft}}.", seconds=2):
        started = improve(daemon, job, maxAttempts=10).json()
        url = f"/v1/agents/{job['id']}/improvements/{started['id']}"
        with daemon.http() as c:
            kept = c.post(f"{url}/keep", json={"attempt": 0})
            assert kept.status_code == 409 and "stop it first" in kept.text, kept.text
            assert c.post(f"{url}/stop").is_success
        done = wait_end(daemon, job)
    assert (done["state"], done["why"]) == ("stopped", "stopped"), done
    assert len(done["attempts"]) < 10


@pytest.mark.rule("improve.nothing-changes-until-kept")
def test_keeping_after_the_instructions_were_saved_meanwhile_is_refused(
    daemon: Daemon, stub: StubLlm
) -> None:
    """If this fails: keeping an attempt overwrites a change someone saved meanwhile."""
    a_writer(daemon)
    job = a_job_with_a_failing_check(daemon, stub, "edited")
    assert improve(daemon, job, maxAttempts=3).status_code == 202
    done = wait_end(daemon, job)
    mine = "Judge {{draft}} kindly."
    body: dict[str, Any] = {"name": "edited", "modelAlone": True, "model": {"provider": "stub"}}
    body |= {"instructions": mine, "interface": {"fields": FIELDS, "result": RESULT}}
    with daemon.http() as c:
        assert c.put(f"/v1/agents/{job['id']}", json=body).status_code == 200
        url = f"/v1/agents/{job['id']}/improvements/{done['id']}/keep"
        kept = c.post(url, json={"attempt": 1})
        assert kept.status_code == 409 and "changed since" in kept.text, kept.text
        assert c.get(f"/v1/agents/{job['id']}").json()["instructions"] == mine


@pytest.mark.rule("improve.within-its-budget")
def test_an_improvement_running_when_handlerd_stops_ends_failed(
    daemon: Daemon, stub: StubLlm
) -> None:
    """If this fails: an improvement shows "running" for ever after a restart."""
    a_writer(daemon)
    job = a_job_with_a_failing_check(daemon, stub, "interrupted")
    with writer_says(stub, "Judge {{draft}}.", seconds=5):
        assert improve(daemon, job, maxAttempts=3).status_code == 202
        daemon.restart(kill=True)
    with daemon.http() as c:
        [last, *_] = c.get(f"/v1/agents/{job['id']}/improvements").json()
    assert (last["state"], last["why"]) == ("failed", "handlerd stopped meanwhile"), last
