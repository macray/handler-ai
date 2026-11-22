"""Contract H.1, H.2, H.11: an app's jobs run by the Who works you chose for it, each run a session
with no agent, with the test app tests/fixtures/app-jobs (its backend in a real sandbox, its jobs
on the fake harness: the fake sandbox keeps the spec handlerd composed for each run)."""

import json
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from handler_control.secrets import SecretStore
from handler_harness import addons

from ..support.daemon import FAKE_SECRET, Daemon, start_daemon
from .conftest import AppClient, add_app, api, copy_fixture, real_sandbox_env, requires_app_runtime

pytestmark = requires_app_runtime

RESULT = {"status": "attention", "summary": "Your CV is written."}


@pytest.fixture(scope="module")
def daemon(data_root: Path) -> Iterator[Daemon]:
    # its own data folder: the fake account's login goes there too (who works on its jobs)
    SecretStore(data_root / "handler").put("accounts/fake/token", FAKE_SECRET)
    env = {"HANDLER_DATA_DIR": str(data_root / "handler")}
    yield from start_daemon(extra_env=env | real_sandbox_env())


@pytest.fixture(scope="module")
def folders(data_root: Path) -> dict[str, Path]:
    """The person's folders, inside the home: their CV (a git repository) and their notes."""
    cv, notes = data_root / "cv", data_root / "notes"
    (cv / ".git").mkdir(parents=True)
    notes.mkdir()
    (notes / "today.md").write_text("Met Bob.\n")
    return {"cv": cv, "notes": notes}


@pytest.fixture(scope="module")
def deployed(daemon: Daemon, data_root: Path, folders: dict[str, Path]) -> dict[str, Any]:
    """The app installed: its folders given, who works chosen (the fake harness), deployed."""
    assert add_app(daemon, copy_fixture("app-jobs", data_root)).status_code == 201
    for need, path in folders.items():
        r = api(daemon, "PUT", f"/v1/apps/cv/files/{need}", {"path": str(path)})
        assert r.status_code == 200, r.text
    r = api(daemon, "PUT", "/v1/apps/cv/who-works", {"program": "fake", "account": "fake"})
    assert r.status_code == 200, r.text
    r = api(daemon, "POST", "/v1/apps/cv/deploy")
    assert r.status_code == 200, api(daemon, "GET", "/v1/apps/cv/log").json()["text"]
    return r.json()


def ran_spec(daemon: Daemon, session_id: str) -> dict[str, Any]:
    """The sandbox spec handlerd composed for that session's run (the fake sandbox keeps it)."""
    ran = daemon.config_dir.parent / "fake-ran"
    (found,) = [p for p in ran.iterdir() if p.name.endswith(session_id)]
    return json.loads(found.read_text())


@pytest.mark.rule("app-job.runs-as-its-who-works")
def test_who_works_is_chosen_per_app_and_per_job(daemon: Daemon, deployed: dict[str, Any]) -> None:
    """The app's Who works runs every job; a job's own is refused when it cannot run it (the
    model alone for a job reaching folders), and each job says who runs it.

    If this fails: a job runs on a model nobody chose for it, or one that cannot run it."""
    assert deployed["whoWorks"] == {"program": "fake", "account": "fake"}
    jobs = {j["name"]: j for j in deployed["jobs"]}
    assert jobs["write"]["canDo"]["files"] == {"cv": "write", "notes": "read"}
    assert (jobs["write"]["whoWorks"], jobs["write"]["own"]) == (deployed["whoWorks"], False)
    assert jobs["summarize"].get("problem") is None
    alone = {"provider": "somewhere", "model": "m"}
    r = api(daemon, "PUT", "/v1/apps/cv/jobs/summarize/who-works", alone)
    assert r.status_code == 409 and "the model alone cannot run it" in r.json()["detail"]
    r = api(daemon, "PUT", "/v1/apps/cv/who-works", {"program": "fake", "account": "nobody"})
    assert r.status_code == 409


@pytest.mark.rule(
    "app-job.its-code-starts-one-only-while-answering-the-owner",
    "app-job.reads-are-read-only",
    "app-run.its-end-reaches-the-inbox",
    "app-sock.answers-only-what-the-app-declares",
)
def test_the_app_s_code_runs_its_job_with_no_agent(
    daemon: Daemon, deployed: dict[str, Any], folders: dict[str, Path]
) -> None:
    """The app's code starts its job while answering you: a session with no agent, of the app
    and the job, in the folder it writes (its .git read-only over it), the folder it reads
    read-only; its result reaches the inbox, and the app lists the run.

    If this fails: a job's run is no app's, reaches more than it declares, or its end is lost."""
    browser = AppClient(daemon, "cv")
    browser.login(api(daemon, "POST", "/v1/apps/cv/open").json()["url"])
    asked = browser.request_json("POST", "/api/write", {"fake": "valid", "answer": RESULT})
    assert isinstance(asked, dict) and asked["status"] == 202, asked
    run = asked["run"]
    assert (run["job"], run["startedBy"], run.get("agent")) == ("write", {"by": "code"}, None)
    deadline = time.monotonic() + 60
    while run["state"] in ("waiting", "running"):
        assert time.monotonic() < deadline
        time.sleep(0.5)
        run = browser.request_json("GET", f"/api/run?id={run['id']}", None)
        assert isinstance(run, dict)
    assert run["state"] == "succeeded", run.get("error")
    assert run["result"] == RESULT
    session = api(daemon, "GET", f"/v1/sessions/{run['sessionId']}").json()
    assert (session["origin"], session["app"], session["job"]) == ("app", "cv", "write")
    assert session.get("agentId") is None and session["unattended"] is True
    spec = ran_spec(daemon, session["id"])
    cv, notes = str(folders["cv"]), str(folders["notes"])
    assert spec["workFolder"]["path"] == cv == session["scope"]
    mounted = {f["target"]: (f["source"], f["writable"]) for f in spec["folders"]}
    assert mounted[notes] == (notes, False)
    assert mounted[f"{cv}/.git"] == (f"{cv}/.git", False)
    assert spec["labels"]["handler.agent"] == "app-cv"
    listed = browser.request_json("GET", "/api/runs", None)
    assert isinstance(listed, dict) and listed["runs"][0]["id"] == run["id"]
    deadline = time.monotonic() + 10
    while not (
        notes_ := [
            n for n in api(daemon, "GET", "/v1/inbox").json() if n.get("sessionId") == session["id"]
        ]
    ):
        assert time.monotonic() < deadline
        time.sleep(0.2)
    (note,) = notes_
    assert (note["source"], note["app"], note["title"], note.get("agent")) == (
        "app",
        "cv",
        "write",
        None,
    )
    assert (note["status"], note["summary"]) == ("attention", "Your CV is written.")


@pytest.mark.rule("action.done-by-its-code-or-its-job", "app-job.reads-are-read-only")
def test_an_action_done_by_its_job(
    daemon: Daemon, deployed: dict[str, Any], folders: dict[str, Path]
) -> None:
    """An action done by a job: its form the job's, a run of it answered with its result; a job
    reading only works in a folder of its own, what it reads read-only.

    If this fails: Ask or the app's page cannot do what the app declares, or a reading job may
    change your folder."""
    (action,) = deployed["actions"]
    assert (action["name"], action["by"]) == ("summarize", "job")
    assert set(action["fields"]["properties"]) == {"fake", "answer"}
    answer = {"status": "ok", "summary": "Bob."}
    body = {"fields": {"fake": "valid", "answer": answer}}
    done = api(daemon, "POST", "/v1/apps/cv/actions/summarize", body).json()
    deadline = time.monotonic() + 60
    while done["state"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.5)
        path = f"/v1/apps/cv/actions/summarize/runs/{done['runId']}"
        done = api(daemon, "GET", path).json()
    assert done["state"] == "succeeded", done
    assert done["result"]["summary"] == "Bob."
    session = api(daemon, "GET", f"/v1/sessions/{done['sessionId']}").json()
    spec = ran_spec(daemon, session["id"])
    notes = str(folders["notes"])
    assert spec["workFolder"]["path"] != notes and spec["workFolder"]["path"] == session["scope"]
    assert {f["target"]: f["writable"] for f in spec["folders"]}[notes] is False
    # its page lists the run (D: GET /v1/apps/{name}/runs, H.11's AppRun), what started it,
    # when it started and ended
    listed = {r["sessionId"]: r for r in api(daemon, "GET", "/v1/apps/cv/runs").json()}
    run = listed[done["sessionId"]]
    assert (run["job"], run["state"], run["result"]["summary"]) == (
        "summarize",
        "succeeded",
        "Bob.",
    )
    assert run["startedBy"] == {"by": "action", "action": "summarize", "via": "try"}
    assert run["endedAt"] >= run["at"]
    assert api(daemon, "GET", "/v1/apps/nope/runs").status_code == 404


def wait_run(daemon: Daemon, name: str) -> dict[str, Any]:
    deadline = time.monotonic() + 60
    while True:
        runs = api(daemon, "GET", f"/v1/automations/{name}/runs").json()
        if runs and runs[0]["state"] not in ("queued", "running"):
            return runs[0]
        assert time.monotonic() < deadline, runs
        time.sleep(0.5)


@pytest.mark.rule(
    "automation.unattended-only-where-the-terms-allow",
    "app-job.runs-as-its-who-works",
    "app-run.its-end-reaches-the-inbox",
)
def test_an_automation_runs_a_job_by_its_who_works(
    daemon: Daemon, deployed: dict[str, Any]
) -> None:
    """`run = { app, job }`: a run of the app's job, unattended, by its Who works, whose terms
    decide whether it may (an account refusing unattended use: a problem; one to check: a
    warning); its result reaches the inbox once, as the automation's, opening the app.

    If this fails: an automation runs a job on a subscription whose terms refuse it, or its
    result is lost or told twice."""
    answer = {"status": "ok", "summary": "Bob."}
    definition = {
        "apiVersion": "handler.automation/v1",
        "when": {"every": "1h"},
        "run": {
            "app": "cv",
            "job": "summarize",
            "input": {"fields": {"fake": "valid", "answer": answer}},
        },
    }
    nope = definition | {"run": {"app": "cv", "job": "nope"}}
    check = api(daemon, "POST", "/v1/automations/check", {"definition": nope}).json()
    assert check["problems"] == ["run.job: cv has no job nope"]
    r = api(daemon, "POST", "/v1/automations", {"name": "notes-daily", "definition": definition})
    assert r.status_code == 201, r.text
    view = r.json()
    assert view["problems"] == [] and view["warnings"] == []
    assert "Runs the job summarize of the app cv unattended" in view["permissions"][1]
    assert api(daemon, "POST", "/v1/automations/notes-daily/try", {}).status_code == 202
    run = wait_run(daemon, "notes-daily")
    assert run["state"] == "succeeded", run
    session = api(daemon, "GET", f"/v1/sessions/{run['agentSessionId']}").json()
    assert (session["origin"], session["app"], session["job"]) == ("automation", "cv", "summarize")
    time.sleep(1.5)  # the app's watcher would have told it by now
    told = [
        m for m in api(daemon, "GET", "/v1/inbox").json() if m.get("sessionId") == session["id"]
    ]
    assert [(m["source"], m["app"], m["summary"]) for m in told] == [("automation", "cv", "Bob.")]
    browser = AppClient(daemon, "cv")
    browser.login(api(daemon, "POST", "/v1/apps/cv/open").json()["url"])
    listed = browser.request_json("GET", "/api/runs", None)
    assert isinstance(listed, dict)
    assert listed["runs"][0]["startedBy"] == {"by": "automation", "automation": "notes-daily"}
    try:
        for account, expected in (("echo-box", "warnings"), ("login-box", "problems")):
            who = {"program": account, "account": account}
            r = api(daemon, "PUT", "/v1/apps/cv/jobs/summarize/who-works", who)
            assert r.status_code == 200, r.text
            view = api(daemon, "GET", "/v1/automations/notes-daily").json()
            said = " ".join(view[expected])
            assert ("refused" if expected == "problems" else "Check your") in said, view
    finally:
        api(daemon, "DELETE", "/v1/apps/cv/jobs/summarize/who-works")
        api(daemon, "DELETE", "/v1/automations/notes-daily")


def until(what: Any, timeout: float = 60) -> Any:
    deadline = time.monotonic() + timeout
    while not (found := what()):
        assert time.monotonic() < deadline
        time.sleep(0.3)
    return found


@pytest.mark.rule("app-job.writers-of-a-folder-take-turns", "app-job.then-called-once")
def test_writers_of_a_folder_take_turns_and_then_is_called(
    daemon: Daemon, deployed: dict[str, Any]
) -> None:
    """Two runs of the job writing the CV: the second waits for the first (`waiting`, its
    session saying which), while a job reading only the notes runs at once; each one's end calls
    the job's `then` once, as the owner, with no start token, the run's state and result.

    If this fails: two runs write your CV at once, or the app is not told when a run ended."""
    browser = AppClient(daemon, "cv")
    browser.login(api(daemon, "POST", "/v1/apps/cv/open").json()["url"])

    def app(method: str, path: str, body: Any = None) -> dict[str, Any]:
        answer = browser.request_json(method, path, body)
        assert isinstance(answer, dict)
        return answer

    def session(run: dict[str, Any]) -> dict[str, Any]:
        return api(daemon, "GET", f"/v1/sessions/{run['sessionId']}").json()

    first = app("POST", "/api/write", {"fake": "sleep"})["run"]
    until(lambda: session(first)["busy"])
    second = app("POST", "/api/write", {"fake": "valid", "answer": RESULT})["run"]
    until(lambda: "waitingFor" in session(second))
    assert (session(second)["waitingFor"], session(second)["state"]) == (
        first["sessionId"],
        "starting",
    )
    assert app("GET", f"/api/run?id={second['id']}")["state"] == "waiting"
    # a job reading only the notes runs while the CV is written
    body = {"fields": {"fake": "valid", "answer": {"status": "ok", "summary": "Bob."}}}
    done = api(daemon, "POST", "/v1/apps/cv/actions/summarize", body).json()
    path = f"/v1/apps/cv/actions/summarize/runs/{done['runId']}"
    until(lambda: api(daemon, "GET", path).json()["state"] == "succeeded")
    assert "waitingFor" in session(second)
    assert api(daemon, "POST", f"/v1/sessions/{first['sessionId']}/cancel").status_code == 200

    def calls() -> list[dict[str, Any]] | None:
        ours = {c["body"]["runId"]: c for c in app("GET", "/api/ended")["ended"]}
        return [ours[r["id"]] for r in (first, second)] if second["id"] in ours else None

    ended = until(calls)
    assert [(c["person"], c["start"]) for c in ended] == [("owner", None)] * 2
    assert ended[0]["body"]["state"] == "failed" and ended[0]["body"]["result"] is None
    assert ended[1]["body"] == {
        "runId": second["id"],
        "job": "write",
        "state": "succeeded",
        "fields": {"fake": "valid", "answer": RESULT},
        "result": RESULT,
    }
    run = app("GET", f"/api/run?id={second['id']}")
    assert run["state"] == "succeeded" and "thenError" not in run


def test_the_app_builder_s_template_deploys_and_its_job_s_then_saves_its_result(
    daemon: Daemon, data_root: Path
) -> None:
    """The template the app-builder skill starts every app from (its job `draft`, the action done
    by it, its `then`) deploys with its tests passing, and a run of its job ends in a note saved
    by its `then` (contract H.1, H.11, H.12).

    If this fails: an agent writing an app starts from a template that does not deploy, or that
    teaches a job, an action or a `then` Handler no longer runs."""
    template = addons.BUILTIN_DIR / "app-builder" / "skills" / "app-builder" / "template"
    source = data_root / "src" / "template"
    shutil.copytree(template, source, ignore=shutil.ignore_patterns("node_modules"))
    (source / "ui" / "dist").mkdir()
    (source / "ui" / "dist" / "index.html").write_text("<!doctype html><title>Notes</title>\n")
    assert add_app(daemon, source).status_code == 201
    r = api(daemon, "PUT", "/v1/apps/notes/who-works", {"program": "fake", "account": "fake"})
    assert r.status_code == 200, r.text
    r = api(daemon, "POST", "/v1/apps/notes/deploy")
    assert r.status_code == 200, api(daemon, "GET", "/v1/apps/notes/log").json()["text"]
    assert {a["name"]: a["by"] for a in r.json()["actions"]} == {"add": "code", "draft": "job"}
    answer = {"status": "ok", "summary": "On the kettle.", "note": "Descale it monthly"}
    fields = {"request": "the kettle", "fake": "valid", "answer": answer}
    done = api(daemon, "POST", "/v1/apps/notes/actions/draft", {"fields": fields}).json()
    if done["state"] == "running":
        path = f"/v1/apps/notes/actions/draft/runs/{done['runId']}"
        done = until(lambda: (d := api(daemon, "GET", path).json())["state"] != "running" and d)
    assert done["state"] == "succeeded", done
    browser = AppClient(daemon, "notes")
    browser.login(api(daemon, "POST", "/v1/apps/notes/open").json()["url"])

    def saved() -> bool:
        notes = browser.request_json("GET", "/api/notes", None)
        return isinstance(notes, list) and [n["text"] for n in notes] == ["Descale it monthly"]

    until(saved)
    assert api(daemon, "DELETE", "/v1/apps/notes").status_code == 204
