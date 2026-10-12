"""Contract I conformance: automations on a real handlerd (docs/dev/contracts.md §I). Sessions run
the fake agent; an automation's run runs on the host (the fake sandbox) with handler's
`handler-llm`, which reaches a stub provider through handlerd's `llm` service."""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ..support.daemon import Daemon
from ..support.stub_llm import StubLlm
from .conftest import STUB_KEY

SECRET_IN_LOG = "sk-ant-api03-a-key-pasted-in-the-chat"


def automation(daemon: Daemon, name: str, run: str | None = None) -> Path:
    """The env-issues example copied as `name`, off: on the stub's model, appending to
    `handler/<name>.md`, and running `run` instead of its script if given."""
    with daemon.http() as c:
        r = c.post("/v1/automations", json={"name": name, "from": "env-issues"})
        assert r.status_code == 201, r.text
        assert r.json()["enabled"] is False
    folder = daemon.config_dir / "automations" / name
    toml = folder / "automation.toml"
    text = toml.read_text().replace("mistral/mistral-large-latest", "stub/m")
    text = text.replace("handler/env-issues.md", f"handler/{name}.md")
    if run is not None:
        text = text.replace('run = "python3 extract.py"', f"run = {json.dumps(run)}")
    toml.write_text(text)
    return folder


def enable(daemon: Daemon, name: str) -> dict[str, Any]:
    with daemon.http() as c:
        view = c.get(f"/v1/automations/{name}").json()
        assert view["problems"] == [], view
        r = c.post(f"/v1/automations/{name}/enable")
        assert r.status_code == 200, r.text
        return r.json()


def conversation(daemon: Daemon, agent: dict[str, Any], session: dict[str, Any] | None = None,
                 text: str = "hello") -> dict[str, Any]:  # fmt: skip
    """A session of `agent` (or `session` again) with one turn, then stopped (`explicit`)."""
    with daemon.http() as c:
        if session is None:
            r = c.post("/v1/sessions", json={"agentId": agent["id"]})
            assert r.status_code == 202
            session = r.json()
        client = daemon.connect(session["acpUrl"])
        try:
            client.initialize()
            acp_id = c.get(f"/v1/sessions/{session['id']}").json()["acpSessionId"]
            params = {"sessionId": acp_id, "cwd": session["scope"], "mcpServers": []}
            client.request("session/load", params)
            client.prompt(acp_id, text)
        finally:
            client.close()
        assert c.post(f"/v1/sessions/{session['id']}/stop").status_code == 200
    return session


def runs(daemon: Daemon, name: str) -> list[dict[str, Any]]:
    with daemon.http() as c:
        return c.get(f"/v1/automations/{name}/runs").json()


def wait_runs(daemon: Daemon, name: str, count: int, timeout: float = 30) -> list[dict[str, Any]]:
    """Once `name` has `count` runs, all ended."""
    deadline = time.monotonic() + timeout
    found: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        found = runs(daemon, name)
        if len(found) >= count and all(r["state"] not in ("queued", "running") for r in found):
            return found
        time.sleep(0.2)
    raise AssertionError(f"{name}: {found}")


def run_folder(daemon: Daemon, name: str, run_id: str) -> Path:
    return daemon.config_dir.parent / "state" / "automations" / name / "runs" / run_id


@pytest.fixture
def agent(daemon: Daemon) -> dict[str, Any]:
    return daemon.create_ad_hoc("fake", daemon.make_scope())


def test_a_stop_runs_it_and_appends_once(
    daemon: Daemon, agent: dict[str, Any], stub: StubLlm, knowledge: Path
) -> None:
    folder = automation(daemon, "once")
    view = enable(daemon, "once")
    assert view["enabled"] and "May call the models stub/m." in view["permissions"]
    assert "Appends what it writes to the notes handler/once.md." in view["permissions"]
    assert "extract.py" in view["files"] and view["directory"] == str(folder)

    session = conversation(daemon, agent, text=f"my key is {SECRET_IN_LOG}")
    [run] = wait_runs(daemon, "once", 1)
    assert run["state"] == "succeeded", run
    assert run["sessionId"] == session["id"] and run["seqFrom"] == 1 and not run["trial"]
    assert run["llm"]["calls"] == 1 and run["llm"]["inTokens"] == 100
    note = (knowledge / "handler" / "once.md").read_text()
    assert note.count("<!-- handler automation once") == 1
    assert f"run {run['id']} · session {session['id']}" in note
    assert f"missing-tool · npm: command not found · session {session['id']}" in note
    assert run["appended"] == [{"to": "handler/once.md", "bytes": len(note.encode())}]

    # the model got the transcript; the key never reached the run, the key of the store never
    # left handlerd but to the provider
    sent = stub.requests[-1]
    assert sent["headers"]["Authorization"] == f"Bearer {STUB_KEY}"
    assert "# Session transcript" in sent["messages"][-1]["content"]
    ran = run_folder(daemon, "once", run["id"])
    given = (ran / "input" / "transcript.md").read_text()
    assert "## [" in given and "my key is" in given
    event = json.loads((ran / "input" / "event.json").read_text())
    assert event["how"] == "explicit" and event["seqTo"] == run["seqTo"]
    for path in ran.rglob("*"):
        if path.is_file():
            assert STUB_KEY not in path.read_text(errors="replace"), path
    calls = [json.loads(line) for line in (ran / "services.ndjson").read_text().splitlines()]
    assert calls[0]["interface"] == "llm/v1" and calls[0]["model"] == "stub/m"
    assert "1 finding(s)" in (ran / "run.log").read_text()
    with daemon.http() as c:
        assert c.get(f"/v1/automations/once/runs/{run['id']}/log").text.startswith("1 finding")
        linked = c.get(f"/v1/sessions/{session['id']}/automation-runs").json()
        assert [r["id"] for r in linked] == [run["id"]]


def test_the_store_secrets_are_redacted_from_the_input(
    daemon: Daemon, agent: dict[str, Any]
) -> None:
    with daemon.http() as c:
        body = {"value": SECRET_IN_LOG}
        assert c.put("/v1/secrets/tests/pasted", json=body).status_code in (200, 201, 204)
    automation(daemon, "redact")
    enable(daemon, "redact")
    conversation(daemon, agent, text=f"my key is {SECRET_IN_LOG}")
    [run] = wait_runs(daemon, "redact", 1)
    given = run_folder(daemon, "redact", run["id"]) / "input"
    for file in ("transcript.md", "events.ndjson"):
        text = (given / file).read_text()
        assert SECRET_IN_LOG not in text and "«redacted»" in text, file


def test_only_conversations_past_since_and_not_deleted_fire(
    daemon: Daemon, agent: dict[str, Any], knowledge: Path
) -> None:
    before = conversation(daemon, agent)  # before it is on: never read
    automation(daemon, "since")
    enable(daemon, "since")
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"]})
        doomed = r.json()
        client = daemon.connect(doomed["acpUrl"])
        client.initialize()
        acp_id = c.get(f"/v1/sessions/{doomed['id']}").json()["acpSessionId"]
        client.request(
            "session/load", {"sessionId": acp_id, "cwd": doomed["scope"], "mcpServers": []}
        )
        client.prompt(acp_id, "hello")
        client.close()
        assert c.delete(f"/v1/sessions/{doomed['id']}").status_code == 204
        idle = c.post("/v1/sessions", json={"agentId": agent["id"]}).json()  # no turn
        time.sleep(1)
        assert c.post(f"/v1/sessions/{idle['id']}/stop").status_code == 200
    time.sleep(2)
    assert runs(daemon, "since") == []
    assert before["id"]  # its stop was before `since`
    assert not (knowledge / "handler" / "since.md").exists()


def test_resumed_then_stopped_reads_only_the_new_part(
    daemon: Daemon, agent: dict[str, Any]
) -> None:
    automation(daemon, "parts")
    enable(daemon, "parts")
    session = conversation(daemon, agent)
    [first] = wait_runs(daemon, "parts", 1)
    conversation(daemon, agent, session, text="again")
    second, again = wait_runs(daemon, "parts", 2)
    assert again["id"] == first["id"] and second["seqFrom"] == first["seqTo"] + 1
    given = (run_folder(daemon, "parts", second["id"]) / "input" / "transcript.md").read_text()
    assert "again" in given and "hello" not in given


def test_a_try_appends_nothing_and_shows_what_it_would(
    daemon: Daemon, agent: dict[str, Any], knowledge: Path
) -> None:
    automation(daemon, "trial")  # off
    session = conversation(daemon, agent)
    with daemon.http() as c:
        r = c.post("/v1/automations/trial/try", json={"sessionId": session["id"]})
        assert r.status_code == 202 and r.json()["trial"] and r.json()["seqFrom"] == 1
        assert c.post("/v1/automations/trial/try", json={"sessionId": "s_nope"}).status_code == 404
    [run] = wait_runs(daemon, "trial", 1)
    assert run["state"] == "succeeded" and run["trial"]
    [would] = run["appended"]
    assert would["to"] == "handler/trial.md" and "npm: command not found" in would["text"]
    assert not (knowledge / "handler" / "trial.md").exists()
    ran = run_folder(daemon, "trial", run["id"])
    assert "HANDLER_TRY" not in (ran / "run.log").read_text()


def test_the_owner_s_edits_apply_while_it_is_on(daemon: Daemon) -> None:
    """Turning it on is the only approval: no sandbox can write its files (§2, invariant 6)."""
    folder = automation(daemon, "edited")
    enable(daemon, "edited")
    toml = folder / "automation.toml"
    toml.write_text(toml.read_text().replace('"stub/m"', '"stub/m", "stub/m2"'))
    (daemon.providers_dir / "stub.toml").write_text(
        (daemon.providers_dir / "stub.toml").read_text() + '[[models]]\nid = "m2"\n'
    )
    with daemon.http() as c:
        view = c.get("/v1/automations/edited").json()
    assert view["enabled"] is True and "May call the models stub/m, stub/m2." in view["permissions"]


def test_problems_and_errors(daemon: Daemon) -> None:
    with daemon.http() as c:
        examples = c.get("/v1/automation-examples").json()
        assert "env-issues" in [e["name"] for e in examples]
        r = c.post("/v1/automations", json={"name": "probs", "from": "nope"})
        assert r.status_code == 404
        r = c.post("/v1/automations", json={"name": "probs", "from": "env-issues"})
        assert r.status_code == 201
        problems = r.json()["problems"]  # its model is not one of ours, its note's folder exists
        assert any("mistral/mistral-large-latest" in p for p in problems), problems
        assert (
            c.post("/v1/automations", json={"name": "probs", "from": "env-issues"}).status_code
            == 409
        )
        r = c.post("/v1/automations/probs/enable")
        assert r.status_code == 409 and "problems" in r.json()["detail"]
        assert c.get("/v1/automations/probs/files/prompt.md").text.startswith("You read")
        assert c.get("/v1/automations/probs/files/../../token").status_code in (400, 404)
        assert c.get("/v1/automations/nope").status_code == 404
        assert c.get("/v1/automations/probs/runs/a_0000000000000000").status_code == 404


def test_a_failing_script_appends_nothing_and_moves_on(
    daemon: Daemon, agent: dict[str, Any], knowledge: Path
) -> None:
    automation(daemon, "fails", run="echo out > $HANDLER_OUTPUT/note.md; exit 3")
    enable(daemon, "fails")
    conversation(daemon, agent)
    [run] = wait_runs(daemon, "fails", 1)
    assert run["state"] == "failed" and run["exitCode"] == 3 and "exited with 3" in run["error"]
    assert not (knowledge / "handler" / "fails.md").exists()


def test_a_run_cut_by_handlerd_stopping_runs_again(
    daemon: Daemon, agent: dict[str, Any], knowledge: Path
) -> None:
    once = "$HANDLER_INPUT/../../slow-done"  # the first run waits, the next one does not
    automation(
        daemon,
        "restart",
        run=f"test -e {once} || {{ touch {once}; sleep 60; }}; "
        "echo - done > $HANDLER_OUTPUT/note.md",
    )
    enable(daemon, "restart")
    conversation(daemon, agent)
    deadline = time.monotonic() + 30
    while not any(r["state"] == "running" for r in runs(daemon, "restart")):
        assert time.monotonic() < deadline
        time.sleep(0.2)
    daemon.restart()
    found = wait_runs(daemon, "restart", 2)
    assert [r["state"] for r in found] == ["succeeded", "interrupted"]
    assert found[0]["seqFrom"] == found[1]["seqFrom"]
    assert (knowledge / "handler" / "restart.md").read_text().count("- done") == 1


def test_deleting_one_stops_its_run_and_removes_its_folder_and_state(
    daemon: Daemon, agent: dict[str, Any], knowledge: Path
) -> None:
    folder = automation(daemon, "gone", run="sleep 60; echo - late > $HANDLER_OUTPUT/note.md")
    enable(daemon, "gone")
    conversation(daemon, agent)
    deadline = time.monotonic() + 30
    while not any(r["state"] == "running" for r in runs(daemon, "gone")):
        assert time.monotonic() < deadline
        time.sleep(0.2)
    state = daemon.config_dir.parent / "state" / "automations" / "gone"
    assert state.is_dir()
    with daemon.http() as c:
        r = c.delete("/v1/automations/gone")
        assert r.status_code == 204, r.text
        assert "gone" not in [a["name"] for a in c.get("/v1/automations").json()]
        assert c.get("/v1/automations/gone").status_code == 404
        assert c.delete("/v1/automations/gone").status_code == 404
    assert not folder.exists() and not state.exists()
    assert not (knowledge / "handler" / "gone.md").exists()  # the run stopped added nothing
    time.sleep(1)
    assert not state.exists(), "nothing the stopped run wrote brought its state back"
    automation(daemon, "gone")  # the name is free again, with no runs of the one before
    assert runs(daemon, "gone") == []


# ── schedules, agent runs, the inbox (I.2, I.3, I.7) ────────────────────

RESULT = {
    "type": "object",
    "properties": {
        "status": {"enum": ["ok", "attention", "failed"]},
        "summary": {"type": "string"},
        "issues": {"type": "array"},
    },
    "required": ["status", "summary"],
}
FIELDS = {"type": "object", "properties": {"fake": {"type": "string"}, "answer": {}}}


def write(daemon: Daemon, name: str, toml: str) -> Path:
    folder = daemon.config_dir / "automations" / name
    folder.mkdir(parents=True)
    (folder / "automation.toml").write_text('apiVersion = "handler.automation/v1"\n' + toml)
    return folder


def reviewer(daemon: Daemon, name: str, account: str = "fake") -> dict[str, Any]:
    """A folderless agent with an interface: the fake agent answers its input's `answer`."""
    body = {"models": [{"account": account}], "permissions": "bypass", "name": name}
    with daemon.http() as c:
        r = c.post("/v1/agents", json=body | {"interface": {"fields": FIELDS, "result": RESULT}})
        assert r.status_code == 201, r.text
        return r.json()


def test_an_agent_run_s_result_goes_to_the_inbox(daemon: Daemon) -> None:
    reviewer(daemon, "nightly-reviewer")
    answer = '{ status = "attention", summary = "2 issues", issues = ["a", "b"] }'
    write(
        daemon,
        "review",
        'when = { every = "1h" }\n[run]\nagent = "nightly-reviewer"\n'
        f'input = {{ fields = {{ fake = "valid", answer = {answer} }} }}\n',
    )
    with daemon.http() as c:
        view = c.get("/v1/automations/review").json()
        assert view["problems"] == [] and view["warnings"] == []
        assert "Runs the agent nightly-reviewer of no project unattended" in view["permissions"][1]
        r = c.post("/v1/automations/review/try", json={})
        assert r.status_code == 202, r.text
        assert c.post("/v1/automations/review/try", json={"sessionId": "s_x"}).status_code == 409
    [run] = wait_runs(daemon, "review", 1, timeout=60)
    assert run["state"] == "succeeded" and run["trial"], run
    with daemon.http() as c:
        session = c.get(f"/v1/sessions/{run['agentSessionId']}").json()
        assert session["origin"] == "automation" and session["output"]["valid"]
        message = c.get("/v1/inbox").json()[0]
        assert (message["source"], message["name"], message["agent"]) == (
            "automation",
            "review",
            "nightly-reviewer",
        )
        assert message["status"] == "attention" and message["summary"] == "2 issues"
        assert message["data"]["issues"] == ["a", "b"] and not message["read"]
        assert message["sessionId"] == run["agentSessionId"]
        read = c.post(f"/v1/inbox/{message['id']}/read").json()
        assert read["read"] is True
        linked = c.get(f"/v1/sessions/{run['agentSessionId']}/automation-runs").json()
        assert [r["id"] for r in linked] == [run["id"]]


def test_an_agent_run_without_a_result_is_a_failure_in_the_inbox(daemon: Daemon) -> None:
    reviewer(daemon, "quiet-reviewer")
    write(daemon, "quiet", 'when = { every = "1h" }\nrun = { agent = "quiet-reviewer" }\n')
    with daemon.http() as c:
        assert c.post("/v1/automations/quiet/try", json={}).status_code == 202
    [run] = wait_runs(daemon, "quiet", 1, timeout=60)
    assert run["state"] == "failed" and "no valid result" in run["error"]
    with daemon.http() as c:
        message = next(m for m in c.get("/v1/inbox").json() if m["name"] == "quiet")
    assert message["status"] == "failed" and message["summary"] == run["error"]


def test_an_agent_run_needs_its_result_and_its_account_s_terms(daemon: Daemon) -> None:
    with daemon.http() as c:
        r = c.post(
            "/v1/agents",
            json={"models": [{"account": "fake"}], "permissions": "bypass", "name": "loose"}
            | {"interface": {"result": {"type": "object"}}},
        )
        assert r.status_code == 201, r.text
    reviewer(daemon, "on-echo", account="echo-box")
    reviewer(daemon, "on-login", account="login-box")
    for name, agent in (("loose", "loose"), ("echo", "on-echo"), ("login", "on-login")):
        write(
            daemon, f"terms-{name}", f'when = {{ every = "1h" }}\nrun = {{ agent = "{agent}" }}\n'
        )
    with daemon.http() as c:
        loose = c.get("/v1/automations/terms-loose").json()
        assert "its result has no required 'summary' string" in loose["problems"]
        echo = c.get("/v1/automations/terms-echo").json()
        assert echo["problems"] == []
        assert "Check your Echo plan's terms" in echo["warnings"][0]
        assert "https://example.org/echo-terms" in echo["warnings"][0]
        login = c.get("/v1/automations/terms-login").json()
        assert any("refused" in p for p in login["problems"]), login
        assert c.post("/v1/automations/terms-login/enable").status_code == 409
        write(daemon, "terms-none", 'when = { every = "1h" }\nrun = { agent = "nobody" }\n')
        none = c.get("/v1/automations/terms-none").json()
        assert none["problems"] == ["run.agent: no agent named nobody of no project"]


def test_one_made_from_a_definition_is_checked_written_and_turned_on(daemon: Daemon) -> None:
    reviewer(daemon, "form-reviewer")
    definition = {
        "apiVersion": "handler.automation/v1",
        "description": "Review every weekday",
        "when": {"at": "08:30", "days": ["mon", "fri"]},
        "run": {"agent": "form-reviewer", "input": {"fields": {"fake": "valid"}}},
    }
    with daemon.http() as c:
        check = c.post("/v1/automations/check", json={"definition": definition}).json()
        assert check["problems"] == [] and check["warnings"] == [], check
        assert check["permissions"][0].startswith("Starts at 08:30 (local time) on mon, fri")
        first = datetime.fromisoformat(check["nextAt"]).astimezone()
        assert first > datetime.now().astimezone() and first.strftime("%a %H:%M")[4:] == "08:30"
        nobody = definition | {"run": {"agent": "nobody"}}
        check = c.post("/v1/automations/check", json={"definition": nobody}).json()
        assert check["problems"] == ["run.agent: no agent named nobody of no project"]
        bad = definition | {"when": {"every": "1m"}}
        assert c.post("/v1/automations/check", json={"definition": bad}).status_code == 422
        both = {"name": "x", "from": "env-issues", "definition": definition}
        assert c.post("/v1/automations", json=both).status_code == 422

        made = {"name": "weekdays", "definition": definition, "enable": True}
        r = c.post("/v1/automations", json=made)
        assert r.status_code == 201, r.text
        assert r.json()["enabled"] and r.json()["nextAt"]
        assert c.post("/v1/automations", json=made).status_code == 409
        r = c.post("/v1/automations", json={"name": "nobody", "definition": nobody, "enable": True})
        assert r.status_code == 409 and "problems" in r.json()["detail"]
        assert c.get("/v1/automations/nobody").json()["enabled"] is False  # made, off
    toml = (daemon.config_dir / "automations" / "weekdays" / "automation.toml").read_text()
    assert 'when = {at = "08:30", days = ["mon", "fri"]}' in toml
    assert 'agent = "form-reviewer"' in toml and 'fake = "valid"' in toml

    every = definition | {"when": {"every": "2h"}}
    with daemon.http() as c:
        r = c.put("/v1/automations/weekdays", json={"definition": every})
        assert r.status_code == 200, r.text
        assert r.json()["enabled"], "an edit keeps it on"
        assert r.json()["definition"]["when"] == {"every": "2h"}
        assert c.put("/v1/automations/nope", json={"definition": every}).status_code == 404
    toml = (daemon.config_dir / "automations" / "weekdays" / "automation.toml").read_text()
    assert 'when = {every = "2h"}' in toml


def test_a_schedule_runs_its_latest_slot_once(daemon: Daemon) -> None:
    folder = write(
        daemon, "hourly", 'when = { every = "1h" }\nrun = "cat $HANDLER_INPUT/event.json"\n'
    )
    assert folder.is_dir()
    view = enable(daemon, "hourly")
    assert view["nextAt"] and runs(daemon, "hourly") == []  # not at once
    state = daemon.config_dir.parent / "state" / "automations" / "hourly" / "state.json"
    data = json.loads(state.read_text())
    since = datetime.fromisoformat(data["since"]) - timedelta(hours=3, minutes=5)
    state.write_text(json.dumps(data | {"since": since.isoformat()}))  # handlerd was off 3 hours
    [run] = wait_runs(daemon, "hourly", 1, timeout=40)  # schedules are looked at every 20 s
    assert run["state"] == "succeeded" and run["missed"] == 2, run
    assert datetime.fromisoformat(run["slot"]) == since + timedelta(hours=3)
    log = (run_folder(daemon, "hourly", run["id"]) / "run.log").read_text()
    assert json.loads(log)["type"] == "schedule" and json.loads(log)["missed"] == 2
    with daemon.http() as c:
        view = c.get("/v1/automations/hourly").json()
    assert datetime.fromisoformat(view["nextAt"]) == since + timedelta(hours=4)
