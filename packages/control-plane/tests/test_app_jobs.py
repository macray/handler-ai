"""Unit tests: an app's jobs run by its Who works (H.1, H.2, H.11), without sandboxes: who may
run a job, the folders its run gets, the stand-in it launches as, and its runs started on
handler.sock or by an action, each a session with no agent (recorded, not started)."""

import asyncio
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from handler_contracts import AppManifest, AppRun, SessionOutput, StartedByCode, WhoWorks
from handler_control import agent_state, app_jobs, app_runs
from handler_control import apps as apps_module
from handler_control import sessions as sessions_module
from handler_control.agents import AgentRegistry, RunsAs
from handler_control.app_runs import AppRunError, AppRuns
from handler_control.apps import AppError, AppRecord, AppStore, Deployment
from handler_control.inbox import Inbox
from handler_control.sessions import SessionStore
from handler_control.settings import Settings

RESULT: dict[str, Any] = {
    "type": "object",
    "required": ["status", "summary"],
    "properties": {
        "status": {"enum": ["ok", "attention", "failed"]},
        "summary": {"type": "string"},
    },
}
RESULT_TOML = (
    '{ type = "object", required = ["status", "summary"], properties = { status = { enum = '
    '["ok", "attention", "failed"] }, summary = { type = "string" } } }'
)
MANIFEST = f"""apiVersion = "handler.app/v1"
name = "cv"
version = "1.0.0"
[needs.files.cv]
mode = "rw"
[needs.files.notes]
[jobs.write]
description = "Writes your CV"
files = {{ cv = "write", notes = "read" }}
worksIn = ["cv"]
result = {RESULT_TOML}
[jobs.write.fields]
type = "object"
properties = {{ request = {{ type = "string" }} }}
[jobs.ask]
description = "Answers a question"
result = {RESULT_TOML}
[actions.write]
description = "Write my CV"
job = "write"
"""
FAKE = WhoWorks(program="fake", account="fake")


def manifest() -> AppManifest:
    return AppManifest.from_toml(MANIFEST)


class Fixture:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.settings = Settings(
            port=7430,
            config_dir=tmp_path / "config",
            state_dir=tmp_path / "state",
            bindings_dir=tmp_path / "bindings",
            allowed_origins=frozenset(),
            web_ui_dir=tmp_path / "ui",
            data_dir=tmp_path / "data",
            skills_dir=tmp_path / "skills",
        )
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        self.home = tmp_path / "home"
        self.registry = AgentRegistry(self.settings.state_dir)
        self.sessions = SessionStore(self.settings, self.registry)
        self.inbox = Inbox(self.settings)
        self.runs = AppRuns(self.settings, self.sessions, self.inbox)
        self.store = AppStore(self.settings, "t0ken", self.inbox, self.runs)
        # a Who works is checked against the person's accounts: here, every one runs
        monkeypatch.setattr(
            app_jobs,
            "runs_as",
            lambda _s, who: RunsAs(**who.model_access.model_dump() | {"harness": who.program}),
        )
        monkeypatch.setattr(self.sessions, "spawn", lambda coro: coro.close())  # nothing starts
        monkeypatch.setattr(app_runs, "WATCH_POLL", 0.01)
        cv, notes = self.home / "cv", self.home / "notes"
        (cv / ".git").mkdir(parents=True)
        notes.mkdir()
        self.folders = {"cv": str(cv), "notes": str(notes)}

    def deployed(self, who: WhoWorks | None = FAKE, text: str = MANIFEST) -> None:
        version = self.store.version_dir("cv", 1)
        (version / "jobs").mkdir(parents=True)
        (version / "app.toml").write_text(text)
        for job in AppManifest.from_toml(text).jobs:
            (version / "jobs" / f"{job}.md").write_text("Do it.\n")
        (version / "jobs" / "write.md").write_text("Write the CV: {{request}}.\n")
        self.store.records["cv"] = AppRecord(
            name="cv",
            deployments=[Deployment(1, "1.0.0", datetime.now(UTC))],
            files=dict(self.folders),
            who_works=who,
        )

    async def call(self, method: str, path: str, body: Any = None) -> tuple[int, dict[str, Any]]:
        return await self.store.from_app("cv", method, path, body)


@pytest.fixture
def f(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fixture:
    return Fixture(tmp_path, monkeypatch)


# ── who runs a job ──────────────────────────────────────────────────────


@pytest.mark.rule("app-job.runs-as-its-who-works")
def test_who_may_run_a_job() -> None:
    """Nobody chosen runs nothing; the model alone runs only a job reaching no folder, schema or
    host (it has no sandbox).

    If this fails: a job runs with no one chosen for it, or on the model alone without the
    folders it needs."""
    jobs = manifest().jobs
    alone = WhoWorks(provider="mistral", model="small")
    assert "nobody is chosen" in (app_jobs.cannot_run(jobs["write"], None) or "")
    assert "the model alone cannot run it" in (app_jobs.cannot_run(jobs["write"], alone) or "")
    assert app_jobs.cannot_run(jobs["ask"], alone) is None
    assert app_jobs.cannot_run(jobs["write"], FAKE) is None
    with pytest.raises(ValueError, match="the model alone runs on a provider"):
        WhoWorks(account="claude-pro")


@pytest.mark.rule("app-job.runs-as-its-who-works")
def test_who_works_is_kept_per_app_and_per_job(f: Fixture) -> None:
    """The app's Who works and a job's own are kept (apps.json), each job saying who runs it and
    why it cannot; a job's own the model alone cannot run is refused.

    If this fails: what you chose is lost at the next start, or a job's own is one that fails
    each time it runs."""
    f.deployed(who=None)
    view = {j.name: j for j in f.store.view("cv").jobs}
    assert view["write"].who_works is None and "nobody" in (view["write"].problem or "")
    f.store.set_who_works("cv", FAKE)
    other = WhoWorks(program="fake", account="other", model="big")
    f.store.set_job_who_works("cv", "ask", other)
    with pytest.raises(AppError, match="the model alone cannot run it"):
        f.store.set_job_who_works("cv", "write", WhoWorks(provider="mistral"))
    with pytest.raises(AppError, match="has no job"):
        f.store.set_job_who_works("cv", "nope", other)
    again = AppStore(f.settings, "t0ken", f.inbox, f.runs)  # handlerd started again
    jobs = {j.name: j for j in again.view("cv").jobs}
    assert again.view("cv").who_works == FAKE
    assert (jobs["write"].who_works, jobs["write"].own, jobs["write"].problem) == (
        FAKE,
        False,
        None,
    )
    assert (jobs["ask"].who_works, jobs["ask"].own) == (other, True)
    assert jobs["write"].can_do.files == {"cv": "write", "notes": "read"}
    again.set_job_who_works("cv", "ask", None)  # the app's again
    assert {j.name: j.own for j in again.view("cv").jobs}["ask"] is False


@pytest.mark.rule("app-job.runs-as-its-who-works")
def test_a_job_nobody_runs_is_refused_with_why(f: Fixture) -> None:
    f.deployed(who=None)

    async def go() -> None:
        token = f.store.issue_start("cv", "owner")
        status, answer = await f.call("POST", "/runs", {"job": "write", "start": token})
        assert status == 409 and "nobody is chosen to run it" in answer["error"]
        f.store.records["cv"].who_works = WhoWorks(provider="mistral")
        status, answer = await f.call("POST", "/runs", {"job": "write", "start": token})
        assert status == 409 and "the model alone cannot run it" in answer["error"]
        assert f.sessions.records == {}

    asyncio.run(go())


@pytest.mark.rule("app-job.can-do-is-the-app-s")
def test_what_a_job_reaches_is_its_declaration_s(f: Fixture) -> None:
    """Its Can do, on the app's page, is its declaration's: choosing who works for it changes
    nothing of it, and a version that adds to it says so before it is deployed.

    If this fails: a job reaches more than its app declared, or a new version widens it unsaid."""
    f.deployed()
    jobs = {j.name: j for j in f.store.view("cv").jobs}
    write = manifest().jobs["write"]
    assert jobs["write"].can_do.files == write.files == {"cv": "write", "notes": "read"}
    assert (jobs["write"].can_do.works_in, jobs["ask"].can_do.files) == (["cv"], {})
    f.store.set_job_who_works("cv", "write", WhoWorks(program="fake", account="other"))
    assert {j.name: j for j in f.store.view("cv").jobs}["write"].can_do == jobs["write"].can_do
    source = f.store.source("cv")
    source.mkdir(parents=True)
    wider = MANIFEST.replace('version = "1.0.0"', 'version = "1.1.0"').replace(
        '[jobs.ask]\ndescription = "Answers a question"',
        '[jobs.ask]\ndescription = "Answers a question"\nfiles = { notes = "read" }\n'
        'egress = ["api.example.com:443"]',
    )
    (source / "app.toml").write_text(wider)
    view = f.store.view("cv")
    assert view.source.added_needs == [
        "job ask: egress api.example.com:443",
        "job ask: file notes (read)",
    ]
    asks = {j.name: j for j in view.jobs}["ask"].can_do
    assert (asks.files, asks.egress) == ({"notes": "read"}, ["api.example.com:443"])


# ── what its run gets ───────────────────────────────────────────────────


@pytest.mark.rule("app-job.reads-are-read-only")
def test_a_job_s_folders_read_only_where_it_reads(tmp_path: Path) -> None:
    """A folder it reads is read-only; the folder it writes and works in is its own folder, its
    .git read-only over it; every folder named in its request.

    If this fails: a job meant to read your notes changes them, or rewrites your history."""
    cv, notes = tmp_path / "cv", tmp_path / "notes"
    (cv / ".git").mkdir(parents=True)
    (notes / ".git").mkdir(parents=True)
    place, said = app_jobs.place(manifest().jobs["write"], {"cv": str(cv), "notes": str(notes)})
    assert place.work == str(cv)
    mounted = {f.target: (f.source, f.writable) for f in place.folders}
    assert mounted == {f"{cv}/.git": (f"{cv}/.git", False), str(notes): (str(notes), False)}
    assert f"`cv`: `{cv}` (read-write; you work in it)" in said
    assert f"`notes`: `{notes}` (read-only)" in said


@pytest.mark.rule("app-job.reads-are-read-only")
def test_a_written_folder_whose_git_is_a_link_is_refused(tmp_path: Path) -> None:
    """A `.git` that is a link (or a worktree's file) cannot be kept read-only: no run.

    If this fails: a job writes through the link into a git history it was never given."""
    cv, notes, elsewhere = tmp_path / "cv", tmp_path / "notes", tmp_path / "elsewhere"
    for folder in (cv, notes, elsewhere):
        folder.mkdir()
    (cv / ".git").symlink_to(elsewhere)
    with pytest.raises(AppRunError, match=r"its \.git is not a folder"):
        app_jobs.place(manifest().jobs["write"], {"cv": str(cv), "notes": str(notes)})
    (cv / ".git").unlink()
    file = tmp_path / "cv.md"
    file.write_text("")
    with pytest.raises(AppRunError, match=r"worksIn cv: .* is a file"):
        app_jobs.place(manifest().jobs["write"], {"cv": str(file), "notes": str(notes)})


@pytest.mark.rule("app-job.runs-as-its-who-works")
def test_its_stand_in_runs_as_its_who_works_with_the_app_s_harness_state(tmp_path: Path) -> None:
    """A run launches as a stand-in nobody registers: the Who works' model, the job's form,
    result and hosts, unattended; its harness state the app's, one per app.

    If this fails: a job runs on another model, or its harness state is another's."""
    job = manifest().jobs["write"]
    runs = RunsAs(harness="fake", account="fake", model="big")
    agent = app_jobs.stand_in("cv", "write", job, runs, "Write the CV.")
    assert (agent.model, agent.permissions, agent.instructions) == (runs, "bypass", "Write the CV.")
    assert agent.interface is not None and agent.interface.result == RESULT
    root = agent_state.root(tmp_path, agent, runs)
    assert root == tmp_path / "agent-state" / "app-cv" / "fake@fake"
    assert agent_state.app_folder(tmp_path, "cv") == root.parent
    alone = app_jobs.stand_in(
        "cv", "ask", manifest().jobs["ask"], RunsAs(harness=None, provider="m"), ""
    )
    assert alone.model_alone


# ── its runs ────────────────────────────────────────────────────────────


@pytest.mark.rule(
    "app-job.its-code-starts-one-only-while-answering-the-owner",
    "app-sock.answers-only-what-the-app-declares",
    "app-job.reads-are-read-only",
)
def test_the_app_s_code_starts_a_job_s_run_with_no_agent(f: Fixture) -> None:
    """`POST /runs {job}` while answering the owner: a session of the app and the job, no
    agent, in the folder it writes, its request naming its folders; never without the start
    token, never a job it does not declare.

    If this fails: an app runs its jobs when nobody asked, or a job's run is an agent's."""
    f.deployed()

    async def go() -> None:
        body = {"job": "write", "fields": {"request": "for a job ad"}}
        status, answer = await f.call("POST", "/runs", body | {"start": "made-up"})
        assert status == 403 and "request of the owner's" in answer["error"]
        token = f.store.issue_start("cv", "owner")
        status, answer = await f.call("POST", "/runs", {"job": "nope", "start": token})
        assert status == 403 and "has no job nope" in answer["error"]
        status, answer = await f.call(
            "POST", "/runs", {"job": "write", "agent": "x", "start": token}
        )
        assert status == 400
        status, run = await f.call("POST", "/runs", body | {"start": token})
        assert status == 202, run
        assert (run["job"], run["startedBy"], run.get("agent")) == ("write", {"by": "code"}, None)
        rec = f.sessions.records[run["sessionId"]]
        assert (rec.agent_id, rec.app, rec.job, rec.origin) == (None, "cv", "write", "app")
        assert rec.scope == f.folders["cv"] and rec.harness == "fake"
        job = f.sessions.jobs[rec.id]
        assert job.agent.id == "app-cv" and job.place.work == f.folders["cv"]
        session = f.sessions.to_contract(rec)
        assert (session.agent_id, session.job, session.unattended) == (None, "write", True)
        status, listed = await f.call("GET", "/runs")
        assert [r["job"] for r in listed["runs"]] == ["write"]
        await f.runs.close()

    asyncio.run(go())


@pytest.mark.rule("action.done-by-its-code-or-its-job")
def test_an_action_done_by_its_job(f: Fixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """An action done by a job: its form the job's, a run of it started by the action."""
    f.deployed()
    (action,) = f.store.view("cv").actions
    assert (action.by, action.fields) == ("job", manifest().jobs["write"].fields)

    async def go() -> None:
        done = await f.store.act("cv", "write", {"request": "short"}, asked=True)
        assert done.state == "running" and done.run_id is not None
        run = f.runs.get("cv", done.run_id)
        assert run.job == "write"
        assert run.started_by.model_dump() == {"by": "action", "action": "write", "via": "ask"}
        await f.runs.close()

    monkeypatch.setattr(apps_module, "ACTION_WAIT", 0.0)  # answered as running
    asyncio.run(go())


@pytest.mark.rule("app-run.its-end-reaches-the-inbox")
def test_a_job_s_run_s_end_reaches_the_inbox(f: Fixture) -> None:
    f.deployed()

    async def go() -> None:
        token = f.store.issue_start("cv", "owner")
        _, run = await f.call("POST", "/runs", {"job": "write", "start": token})
        rec = f.sessions.records[run["sessionId"]]
        result = {"status": "ok", "summary": "Written."}
        rec.state = "stopped"
        rec.output = SessionOutput(valid=True, value=result).model_dump()
        for _ in range(100):
            if f.inbox.messages:
                break
            await asyncio.sleep(0.02)
        (message,) = f.inbox.messages
        assert (message.source, message.app, message.title, message.agent) == (
            "app",
            "cv",
            "write",
            None,
        )
        assert (message.status, message.summary) == ("ok", "Written.")
        await f.runs.close()

    asyncio.run(go())


@pytest.mark.rule("app.uninstalled-leaves-nothing-of-it")
def test_uninstalled_its_jobs_runs_and_harness_state_go(f: Fixture) -> None:
    """Its jobs' runs (their sessions) and the harness state they share go with the app.

    If this fails: an app installed later under its name finds the runs and history of the one
    you removed."""
    f.deployed()
    state = agent_state.app_folder(f.settings.data_dir, "cv") / "fake@fake"
    state.mkdir(parents=True)

    async def go() -> None:
        token = f.store.issue_start("cv", "owner")
        _, run = await f.call("POST", "/runs", {"job": "write", "start": token})
        await f.store.remove("cv")
        assert run["sessionId"] not in f.sessions.records
        assert not state.parent.exists()
        await f.runs.close()

    asyncio.run(go())


@pytest.mark.rule("app-job.runs-as-its-who-works")
def test_a_job_s_run_does_not_start_again_after_a_restart(f: Fixture) -> None:
    """What it ran with is kept in memory only: once handlerd stopped, its session refuses to
    start again (its app runs the job again).

    If this fails: a job's run starts with what nobody gave it any more."""
    f.deployed()

    async def go() -> None:
        token = f.store.issue_start("cv", "owner")
        _, run = await f.call("POST", "/runs", {"job": "write", "start": token})
        rec = f.sessions.records[run["sessionId"]]
        f.sessions.jobs.clear()  # as after a restart
        rec.state = "stopped"
        with pytest.raises(Exception, match="a job's run does not start again"):
            await f.sessions.ensure_running(rec.id)
        await f.runs.close()

    asyncio.run(go())


# ── writers of a folder take turns, `then` (H.11) ───────────────────────

TURNS = f"""apiVersion = "handler.app/v1"
name = "cv"
version = "1.0.0"
[needs.files.cv]
mode = "rw"
[needs.files.notes]
mode = "rw"
[jobs.write]
description = "Writes your CV"
files = {{ cv = "write", notes = "read" }}
worksIn = ["cv"]
result = {RESULT_TOML}
then = "POST /api/ended"
[jobs.write.fields]
type = "object"
properties = {{ request = {{ type = "string" }} }}
[jobs.read]
description = "Reads your CV"
files = {{ cv = "read" }}
result = {RESULT_TOML}
[jobs.note]
description = "Writes your notes"
files = {{ notes = "write" }}
result = {RESULT_TOML}
[jobs.both]
description = "Writes both"
files = {{ notes = "write", cv = "write" }}
result = {RESULT_TOML}
"""
OK = {"status": "ok", "summary": "Done."}


class Runs:
    """Runs that really take their turns, each going on until it is let end (its sandbox
    replaced by an event), ending with OK."""

    def __init__(self, f: Fixture, monkeypatch: pytest.MonkeyPatch) -> None:
        self.f = f
        self.going: list[str] = []  # the runs that started, in order
        self.ends: dict[str, asyncio.Event] = {}
        self.tasks: list[asyncio.Task[Any]] = []
        monkeypatch.setattr(sessions_module, "RUN_POLL", 0.005)
        monkeypatch.setattr(f.sessions, "spawn", self.spawn)
        monkeypatch.setattr(f.sessions, "_go", self.go)

    def spawn(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self.tasks.append(task)
        return task

    async def go(self, session_id: str, _prompt: Any, _timeout: Any) -> None:
        self.going.append(session_id)
        await self.ends.setdefault(session_id, asyncio.Event()).wait()
        rec = self.f.sessions.records[session_id]
        rec.state = "stopped"
        rec.output = SessionOutput(valid=True, value=OK).model_dump()

    def start(self, job: str) -> str:
        """A run of that job, started by the app's code: its session's id."""
        return self.f.store.job_run("cv", job, {}, StartedByCode()).session_id

    def end(self, session_id: str) -> None:
        self.ends.setdefault(session_id, asyncio.Event()).set()

    async def settle(self) -> None:
        for _ in range(20):
            await asyncio.sleep(0.005)

    def waiting_for(self, session_id: str) -> str | None:
        return self.f.sessions.records[session_id].waiting_for


async def _no_then(*_args: Any) -> None:
    raise AssertionError("no `then` called in this test")


@pytest.mark.rule("app-job.writers-of-a-folder-take-turns")
def test_runs_writing_a_folder_take_turns_readers_never_wait(
    f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two runs writing a folder go one after the other, the second showing the run it waits
    for; one reading it starts at once while it is written; one writing another folder too; one
    writing both waits for each, in the order they were started.

    If this fails: two runs write your CV at once, or a run only reading it waits for nothing."""
    f.deployed(text=TURNS)
    monkeypatch.setattr(f.runs, "then", _no_then)
    runs = Runs(f, monkeypatch)

    async def go() -> None:
        first = runs.start("write")
        await runs.settle()
        second = runs.start("write")
        reader = runs.start("read")
        other = runs.start("note")
        both = runs.start("both")
        await runs.settle()
        assert runs.going == [first, reader, other]  # the reader and the other folder: at once
        assert runs.waiting_for(second) == first and runs.waiting_for(both) == first
        assert runs.waiting_for(reader) is None
        (waiting,) = [r for r in f.runs.recent("cv") if r.session_id == second]
        assert waiting.state == "waiting"
        with pytest.raises(Exception, match="waits for the run writing its folder"):
            await f.sessions.ensure_running(second)
        runs.end(first)
        await runs.settle()
        assert runs.going[-1] == second and runs.waiting_for(second) is None
        assert runs.waiting_for(both) == second  # behind it on the CV
        runs.end(second)
        await runs.settle()
        assert both not in runs.going and runs.waiting_for(both) == other  # and on the notes
        runs.end(other)
        await runs.settle()
        assert runs.going[-1] == both and runs.waiting_for(both) is None
        for sid in (reader, both):
            runs.end(sid)
        await runs.settle()
        assert f.sessions.running_runs == {}
        assert all(not queue for queue in f.sessions.run_queues.values())
        await f.runs.close()

    asyncio.run(go())


@pytest.mark.rule("app-job.writers-of-a-folder-take-turns")
def test_the_turn_is_the_folder_s_by_its_real_path(tmp_path: Path) -> None:
    """A run takes its turn on each folder it writes, by its real path (a link to it is that
    folder), on none it only reads.

    If this fails: two runs write one folder at once through two of its names."""
    cv, link, notes = tmp_path / "cv", tmp_path / "link", tmp_path / "notes"
    cv.mkdir()
    notes.mkdir()
    link.symlink_to(cv)
    jobs = AppManifest.from_toml(TURNS).jobs
    given = {"cv": str(link), "notes": str(notes)}
    assert app_jobs.place(jobs["write"], given)[0].writes == (str(cv),)
    assert app_jobs.place(jobs["read"], given)[0].writes == ()
    assert app_jobs.place(jobs["both"], given)[0].writes == tuple(sorted((str(cv), str(notes))))


@pytest.mark.rule("app-job.writers-of-a-folder-take-turns")
def test_a_run_waiting_for_a_folder_gives_up_past_its_limit(
    f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past `run_wait_timeout`, a run still waiting fails, saying which folder it waited for.

    If this fails: a run waits forever behind one that never ends."""
    f.deployed(text=TURNS)
    monkeypatch.setattr(f.runs, "then", _no_then)
    monkeypatch.setattr(f.sessions, "settings", replace(f.settings, run_wait_timeout=0.05))
    runs = Runs(f, monkeypatch)

    async def go() -> None:
        first = runs.start("write")
        await runs.settle()
        late = runs.start("both")
        for _ in range(100):
            if f.sessions.records[late].state == "failed":
                break
            await asyncio.sleep(0.01)
        rec = f.sessions.records[late]
        assert rec.state == "failed" and rec.waiting_for is None and late not in runs.going
        assert rec.error is not None and rec.error.startswith("waited ")
        assert f"a run writing {os.path.realpath(f.folders['cv'])} was still running" in rec.error
        runs.end(first)
        await runs.settle()
        await f.runs.close()

    asyncio.run(go())


def backend(monkeypatch: pytest.MonkeyPatch, store: AppStore, answer: int) -> list[httpx.Request]:
    """The app's backend, answering `answer` to every call: the calls it got."""
    got: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        got.append(request)
        return httpx.Response(answer, json={"error": "it broke"} if answer >= 400 else {})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://app")

    async def running(_name: str) -> Any:
        return SimpleNamespace(client=client)

    monkeypatch.setattr(store, "ensure_running", running)
    return got


async def told(f: Fixture, run_id: str) -> AppRun:
    """The run once its end was told (after its `then`)."""
    for _ in range(300):
        if (record := f.runs.find("cv", run_id)).told:
            return f.runs.view(record)
        await asyncio.sleep(0.01)
    raise AssertionError("its end was never told")


@pytest.mark.rule("app-job.then-called-once")
def test_then_is_called_once_as_the_owner_with_no_start_token(
    f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a run of a job with `then` ends, its route is called once: the run, its job, state,
    fields and result, as the owner, with no start token; then the inbox is told.

    If this fails: the app never learns a run ended, learns it twice, or could start a job from
    it (a loop)."""
    f.deployed(text=TURNS)
    got = backend(monkeypatch, f.store, 200)
    runs = Runs(f, monkeypatch)

    async def go() -> None:
        token = f.store.issue_start("cv", "owner")
        body = {"job": "write", "fields": {"request": "short"}, "start": token}
        status, run = await f.call("POST", "/runs", body)
        assert status == 202
        runs.end(run["sessionId"])
        done = await told(f, run["id"])
        await runs.settle()
        (call,) = got
        assert (call.method, call.url.path) == ("POST", "/api/ended")
        assert call.headers["x-handler-person"] == "owner" and "x-handler-start" not in call.headers
        assert json.loads(call.content) == {
            "runId": run["id"],
            "job": "write",
            "state": "succeeded",
            "fields": {"request": "short"},
            "result": OK,
        }
        assert done.then_error is None
        (message,) = f.inbox.messages
        assert (message.status, message.summary) == ("ok", "Done.")
        await f.runs.close()

    asyncio.run(go())


@pytest.mark.rule("app-job.then-called-once")
def test_a_failed_then_is_shown_on_the_run_never_retried(
    f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its route answering an error: said on the run (`GET /runs`) and in its inbox message,
    the result kept; never called again, not after a restart either.

    If this fails: a failed `then` is lost silently, or called again and again."""
    f.deployed(text=TURNS)
    got = backend(monkeypatch, f.store, 500)
    runs = Runs(f, monkeypatch)

    async def go() -> None:
        run = f.store.job_run("cv", "write", {}, StartedByCode())
        runs.end(run.session_id)
        done = await told(f, run.id)
        assert (done.state, done.result, done.then_error) == ("succeeded", OK, "it broke")
        _, listed = await f.call("GET", "/runs")
        assert listed["runs"][0]["thenError"] == "it broke"
        (message,) = f.inbox.messages
        assert message.summary == "Done.\n\nPOST /api/ended failed: it broke"
        f.runs.update("cv", run.id, told=False)  # as if handlerd stopped before telling it
        again = AppRuns(f.settings, f.sessions, f.inbox)
        again.call_then = f.store.call_then
        again.start_watching(["cv"])
        await told(f, run.id)
        assert len(got) == 1
        await again.close()
        await f.runs.close()

    asyncio.run(go())


@pytest.mark.rule("app-job.then-called-once")
def test_at_a_restart_then_is_called_once_or_said_cut(
    f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At handlerd's start, a run that ended without its `then` called gets it now, once; one
    whose `then` was being called when handlerd stopped is not called again, and says so.

    If this fails: a run's end is lost for the app at a restart, or told to it twice."""
    f.deployed(text=TURNS)
    got = backend(monkeypatch, f.store, 200)

    async def go() -> None:
        monkeypatch.setattr(f.runs, "watch", lambda *_: None)  # handlerd stops before they end
        ended_off = f.store.job_run("cv", "write", {}, StartedByCode()).id
        cut = f.store.job_run("cv", "write", {}, StartedByCode()).id
        f.runs.update("cv", cut, then_called=True, then_error=app_runs.THEN_CUT)
        for run in f.runs.recent("cv"):
            f.sessions.records[run.session_id].state = "failed"  # as handlerd's start leaves them
        again = AppRuns(f.settings, f.sessions, f.inbox)
        again.call_then = f.store.call_then
        again.start_watching(["cv"])
        first = await told(f, ended_off)
        second = await told(f, cut)
        (call,) = got
        assert json.loads(call.content)["runId"] == ended_off
        assert json.loads(call.content)["state"] == "failed"
        assert first.then_error is None and second.then_error == app_runs.THEN_CUT
        await again.close()

    asyncio.run(go())


@pytest.mark.rule("app-job.then-called-once")
def test_then_is_not_called_for_a_run_the_app_cancelled(
    f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run its app cancelled ends with no `then`: the app knows it."""
    f.deployed(text=TURNS)
    got = backend(monkeypatch, f.store, 200)
    runs = Runs(f, monkeypatch)

    async def go() -> None:
        first = runs.start("write")
        await runs.settle()
        waiting = f.store.job_run("cv", "write", {}, StartedByCode())
        await runs.settle()
        await f.runs.cancel("cv", waiting.id)
        assert (await told(f, waiting.id)).state == "cancelled"
        assert got == []
        runs.end(first)
        await runs.settle()
        await f.runs.close()

    asyncio.run(go())
