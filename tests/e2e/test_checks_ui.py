"""Checks in the web UI (D.20), in a real browser against a real handlerd: a job's run kept as a
check from its page, then run from the agent's page. The job is on the model alone, on a stub
provider in the test process (no harness image needed)."""

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from handler_control.settings import WEB_UI

from ..support import dev_env
from ..support.daemon import Daemon, start_daemon
from ..support.stub_llm import StubLlm
from .browser import PW_IMAGE, image_present

pytestmark = [
    pytest.mark.skipif(not (WEB_UI / "index.html").is_file(), reason="web UI not built"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]
RESULT = {
    "type": "object",
    "required": ["status", "summary", "verdict"],
    "properties": {
        "status": {"enum": ["ok", "attention", "failed"]},
        "summary": {"type": "string"},
        "verdict": {"enum": ["send", "rewrite"]},
    },
}
SEND = '```json handler-result\n{"status": "ok", "summary": "fine", "verdict": "send"}\n```'
REWRITE = SEND.replace('"send"', '"rewrite"')


@pytest.fixture(scope="module")
def stub() -> Iterator[StubLlm]:
    s = StubLlm(SEND)
    yield s
    s.close()


@pytest.fixture(scope="module")
def daemon(stub: StubLlm) -> Iterator[Daemon]:
    yield from start_daemon(
        extra_env={"HANDLER_TEST_STUB_KEY": "sk-stub"}, extra_providers={"stub": stub.provider()}
    )


@pytest.fixture
def page(browser: Browser, daemon: Daemon) -> Iterator[Page]:
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{daemon.base_url}/#token={daemon.token}")
    yield page
    context.close()


def finished_run(daemon: Daemon, agent: dict[str, Any]) -> str:
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"], "input": {"fields": {}}})
        assert r.status_code == 202, r.text
        sid = r.json()["id"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if c.get(f"/v1/sessions/{sid}").json().get("output"):
                return sid
            time.sleep(0.2)
    raise AssertionError("the run did not end")


def test_keep_a_run_as_a_check_then_run_it(page: Page, daemon: Daemon, stub: StubLlm) -> None:
    body = {
        "name": "tone",
        "modelAlone": True,
        "model": {"provider": "stub"},
        "interface": {"result": RESULT},
    }
    with daemon.http() as c:
        agent = c.post("/v1/agents", json=body).json()
    stub.answer = SEND
    run = finished_run(daemon, agent)
    page.goto(f"{daemon.base_url}/#/runs/{run}")
    page.get_by_test_id("run-keep-check").click()
    dialog = page.get_by_test_id("check-dialog")
    expect(dialog).to_contain_text("Free text: shown, never compared.")  # its summary
    dialog.get_by_test_id("check-name").fill("a polite no")
    dialog.get_by_test_id("check-save").click()
    expect(page.get_by_test_id("run-kept")).to_be_visible()

    page.goto(f"{daemon.base_url}/#/agents/{agent['id']}")
    checks = page.get_by_test_id("agent-checks")
    expect(checks.get_by_test_id("check-row")).to_contain_text("a polite no")
    stub.answer = REWRITE
    checks.get_by_test_id("checks-run").click()
    expect(checks.get_by_test_id("check-state")).to_contain_text('verdict: "rewrite", not "send"')
    expect(checks.get_by_test_id("checks-summary")).to_contain_text("0 of 1 pass")


RULE = "A polite no is fine: say send."


def improving(body: dict[str, Any]) -> str:
    """The prompt writer adds RULE; the job says send only with it."""
    text = json.dumps(body["messages"])
    if "You improve the instructions of an AI job" in text:
        new = json.dumps("Judge it. " + RULE)
        return (
            '```json handler-result\n{"status": "ok", "summary": "added a rule", '
            f'"instructions": {new}, "change": "added a rule"}}\n```'
        )
    return SEND if RULE in text else REWRITE


def test_improve_until_the_checks_pass_then_keep(page: Page, daemon: Daemon, stub: StubLlm) -> None:
    body = {
        "name": "judge",
        "modelAlone": True,
        "model": {"provider": "stub"},
        "instructions": "Judge it.",
        "interface": {"result": RESULT},
    }
    with daemon.http() as c:
        agent = c.post("/v1/agents", json=body).json()
        stub.answer = SEND
        run = finished_run(daemon, agent)
        c.post(f"/v1/agents/{agent['id']}/checks", json={"fromRun": run, "name": "a no"})
    stub.answer = improving
    page.goto(f"{daemon.base_url}/#/agents/{agent['id']}")
    page.get_by_test_id("checks-improve").click()
    expect(page.get_by_test_id("improve-no-writer")).to_be_visible()  # set it up first

    with daemon.http() as c:
        needs = c.get("/v1/handler-needs").json()
        writer = next(n for n in needs if n["name"] == "prompt-writer")["definition"]
        made = c.post(
            "/v1/agents",
            json={
                "name": "writer",
                "origin": {"kind": "handler-need", "name": "prompt-writer", "version": 1},
                "modelAlone": True,
                "model": {"provider": "stub"},
                "instructions": writer["instructions"],
                "interface": writer["interface"],
            },
        ).json()
        c.put("/v1/handler-needs/prompt-writer", json={"agentId": made["id"]}).raise_for_status()
    page.reload()
    page.get_by_test_id("checks-improve").click()
    dialog = page.get_by_test_id("improve-dialog")
    expect(dialog.get_by_test_id("improve-few-checks")).to_be_visible()
    dialog.get_by_test_id("improve-goal").fill("It says rewrite for a polite no.")
    dialog.get_by_test_id("improve-start").click()
    block = page.get_by_test_id("agent-improvement")
    expect(block.get_by_test_id("improvement-state")).to_have_text("every check passes")
    expect(block.get_by_test_id("attempt-row")).to_have_count(2)
    block.get_by_test_id("attempt-keep").click()
    expect(block.get_by_test_id("attempt-kept")).to_be_visible()
    with daemon.http() as c:
        assert RULE in c.get(f"/v1/agents/{agent['id']}").json()["instructions"]
