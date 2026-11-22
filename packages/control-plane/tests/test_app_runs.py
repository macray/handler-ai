"""Unit tests: what an app's backend asks of its runs on handler.sock (H.11), and the folders the
person gives its needs (H.2), without sandboxes: the sessions its jobs' runs start are recorded,
not run. A job's run itself (who runs it, its folders, its turns, its `then`): test_app_jobs.py."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import WhoWorks
from handler_control import app_jobs, app_runs
from handler_control import apps as apps_module
from handler_control.agents import AgentRegistry, RunsAs
from handler_control.app_runs import AppRuns
from handler_control.apps import AppError, AppRecord, AppStore, Deployment
from handler_control.inbox import Inbox
from handler_control.sessions import SessionStore
from handler_control.settings import Settings

RESULT_TOML = (
    '{ type = "object", required = ["status", "summary"], properties = { status = { enum = '
    '["ok", "attention", "failed"] }, summary = { type = "string" } } }'
)
HEAD = """apiVersion = "handler.app/v1"
name = "planner"
version = "1.0.0"
"""
MANIFEST = (
    HEAD
    + f"""[jobs.plan]
description = "Tells you what to do next"
result = {RESULT_TOML}
[jobs.plan.fields]
type = "object"
required = ["request"]
properties = {{ request = {{ type = "string" }} }}
[jobs.today]
description = "Says what today holds"
result = {RESULT_TOML}
[actions.today]
description = "What about today?"
job = "today"
"""
)


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
        monkeypatch.setattr(
            app_jobs,
            "runs_as",
            lambda _s, who: RunsAs(**who.model_access.model_dump() | {"harness": who.program}),
        )
        monkeypatch.setattr(self.sessions, "spawn", lambda coro: coro.close())  # nothing starts
        monkeypatch.setattr(app_runs, "WATCH_POLL", 0.01)

    def deployed(self, manifest: str = MANIFEST) -> Path:
        """The app installed (version 1), its jobs' instructions there, run by a fake program."""
        version = self.store.version_dir("planner", 1)
        (version / "jobs").mkdir(parents=True)
        (version / "app.toml").write_text(manifest)
        for job in ("plan", "today"):
            (version / "jobs" / f"{job}.md").write_text("Do it.\n")
        self.store.records["planner"] = AppRecord(
            name="planner",
            deployments=[Deployment(1, "1.0.0", datetime.now(UTC))],
            who_works=WhoWorks(program="fake", account="fake"),
        )
        return version

    async def call(self, method: str, path: str, body: Any = None) -> tuple[int, dict[str, Any]]:
        return await self.store.from_app("planner", method, path, body)


@pytest.fixture
def f(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fixture:
    return Fixture(tmp_path, monkeypatch)


@pytest.mark.rule(
    "app-origin.handlerd-says-who-asks",
    "app-job.its-code-starts-one-only-while-answering-the-owner",
)
def test_a_run_starts_only_while_answering_the_owner(f: Fixture) -> None:
    """Only the owner's request in progress carries a start token: never another person's,
    another app's, or one answered already."""
    f.deployed()

    async def go() -> None:
        body = {"job": "plan", "fields": {"request": "what now?"}}
        status, answer = await f.call("POST", "/runs", body | {"start": "made-up"})
        assert status == 403 and "request of the owner's" in answer["error"]
        assert f.store.issue_start("planner", "alice") is None  # a family member's: none
        other = f.store.issue_start("other-app", "owner")
        assert other is not None
        assert (await f.call("POST", "/runs", body | {"start": other}))[0] == 403
        token = f.store.issue_start("planner", "owner")
        assert token is not None
        status, run = await f.call("POST", "/runs", body | {"start": token})
        assert status == 202, run
        assert (run["job"], run["state"]) == ("plan", "running")
        f.store.end_start(token)
        status, answer = await f.call("POST", "/runs", body | {"start": token})
        assert status == 403  # answered: spent
        await f.runs.close()

    asyncio.run(go())


@pytest.mark.rule("app-sock.answers-only-what-the-app-declares")
def test_a_run_is_of_a_job_with_a_valid_input(f: Fixture) -> None:
    f.deployed()

    async def go() -> None:
        token = f.store.issue_start("planner", "owner")
        status, answer = await f.call("POST", "/runs", {"job": "plan", "start": token})
        assert status == 400 and answer["error"].startswith("input invalid")
        status, answer = await f.call("POST", "/runs", {"job": "plan"})
        assert status == 400 and "start" in answer["error"]
        status, answer = await f.call("POST", "/runs", {"agent": "plan", "start": token})
        assert status == 400  # an app has no agents: a run is of one of its jobs
        status, answer = await f.call("GET", "/runs/r_nope")
        assert status == 404
        assert f.runs.recent("planner") == []

    asyncio.run(go())


@pytest.mark.rule("app-sock.answers-only-what-the-app-declares")
def test_the_app_lists_its_runs_newest_first_with_what_started_and_asked_each(
    f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    f.deployed()
    monkeypatch.setattr(apps_module, "ACTION_WAIT", 0)  # answered as running at once
    monkeypatch.setattr(f.store, "nudge_of", lambda *_: None)  # an open nudge of this action
    monkeypatch.setattr(f.store.nudges, "running", lambda *_: None)

    async def go() -> None:
        assert await f.call("GET", "/runs") == (200, {"runs": []})
        token = f.store.issue_start("planner", "owner")
        body = {"job": "plan", "fields": {"request": "now"}, "start": token}
        status, run = await f.call("POST", "/runs", body)
        assert status == 202 and run["startedBy"] == {"by": "code"}
        await f.store.act("planner", "today", {})
        await f.store.act("planner", "today", {}, asked=True)
        await f.store.act("planner", "today", {}, "m_1")
        status, listed = await f.call("GET", "/runs")
        assert status == 200
        assert [r["startedBy"] for r in listed["runs"]] == [
            {"by": "action", "action": "today", "via": via} for via in ("nudge", "ask", "try")
        ] + [{"by": "code"}]
        assert [r["job"] for r in listed["runs"]] == ["today", "today", "today", "plan"]
        assert listed["runs"][-1] == run  # as `POST /runs` answered it
        # what each was asked: its fields, as its run got them (so the app keeps no list of its
        # own requests), also from `GET /runs/{id}`
        assert run["fields"] == {"request": "now"}
        assert [r["fields"] for r in listed["runs"][:3]] == [{}, {}, {}]
        assert await f.call("GET", f"/runs/{run['id']}") == (200, run)
        await f.runs.close()

    asyncio.run(go())


@pytest.mark.rule("app-sock.answers-only-what-the-app-declares")
def test_the_app_lists_only_the_last_runs_kept(f: Fixture, monkeypatch: pytest.MonkeyPatch) -> None:
    f.deployed()
    monkeypatch.setattr(app_runs, "KEEP", 3)

    async def go() -> None:
        token = f.store.issue_start("planner", "owner")
        body = {"job": "today", "start": token}
        started = [(await f.call("POST", "/runs", body))[1]["id"] for _ in range(4)]
        _, listed = await f.call("GET", "/runs")
        assert [r["id"] for r in listed["runs"]] == started[:0:-1]  # the first one is gone
        await f.runs.close()

    asyncio.run(go())


@pytest.mark.rule("app-sock.answers-only-what-the-app-declares")
def test_runs_need_jobs_in_the_manifest(f: Fixture) -> None:
    f.deployed(HEAD + "[needs]\nnotify = true\n")

    async def go() -> None:
        status, answer = await f.call("POST", "/runs", {"job": "plan", "start": "x"})
        assert status == 403 and "[jobs.<name>]" in answer["error"]
        assert (await f.call("GET", "/elsewhere"))[0] == 404

    asyncio.run(go())


@pytest.mark.rule("app-run.its-end-reaches-the-inbox")
def test_a_cancelled_run_tells_nothing(f: Fixture) -> None:
    f.deployed()

    async def go() -> None:
        token = f.store.issue_start("planner", "owner")
        _, run = await f.call("POST", "/runs", {"job": "today", "start": token})
        assert (await f.call("POST", f"/runs/{run['id']}/cancel"))[0] == 200
        f.sessions.records[run["sessionId"]].state = "stopped"
        for _ in range(20):
            await asyncio.sleep(0.02)
        assert (await f.call("GET", f"/runs/{run['id']}"))[1]["state"] == "cancelled"
        assert f.inbox.messages == []
        await f.runs.close()

    asyncio.run(go())


@pytest.mark.rule(
    "app-need.a-folder-in-your-home-never-handler-s", "app-need.a-file-given-is-that-file"
)
def test_a_folder_given_is_checked_made_and_set_up(f: Fixture) -> None:
    source = f.store.source("planner")
    (source / "format").mkdir(parents=True)
    (source / "format" / "README.md").write_text("The folder's format.\n")
    (source / "app.toml").write_text(
        HEAD + '[needs.files.tasks]\nmode = "rw"\ninit = ["format/README.md"]\n'
    )
    f.store.records["planner"] = AppRecord(name="planner")

    async def go() -> None:
        folder = f.home / "planner"
        with pytest.raises(AppError, match="does not exist"):
            await f.store.set_file("planner", "tasks", str(folder), create=False)
        app = await f.store.set_file("planner", "tasks", str(folder), create=True)
        assert app.files[0].path == str(folder) and not app.files[0].file
        assert (folder / "README.md").read_text() == "The folder's format.\n"
        (folder / "README.md").write_text("Mine.\n")
        await f.store.set_file("planner", "tasks", str(folder), create=False)
        assert (folder / "README.md").read_text() == "Mine.\n"  # never overwritten
        for bad, why in [
            ("/etc", "inside your home"),
            (str(f.home), "inside your home"),
            (str(f.home / ".ssh"), "never given"),
        ]:
            with pytest.raises(AppError, match=why):
                await f.store.set_file("planner", "tasks", bad, create=True)
        with pytest.raises(AppError, match="needs no folder notes"):
            await f.store.set_file("planner", "notes", str(folder), create=False)
        # a file: said (the app's page tells how an editor's save reaches it, a restart)
        app = await f.store.set_file("planner", "tasks", str(folder / "README.md"), create=False)
        assert app.files[0].file

    asyncio.run(go())


@pytest.mark.rule("app.nothing-is-read-through-a-link-out")
def test_links_out_of_the_app_are_never_read(f: Fixture) -> None:
    """An agent writes the app's folder: a link there to a file of the person's must not make
    handler read it for the agent (into the folder given)."""
    secret = f.home / ".ssh" / "id_ed25519"
    secret.parent.mkdir(parents=True)
    secret.write_text("PRIVATE KEY\n")
    source = f.store.source("planner")
    (source / "format").mkdir(parents=True)
    (source / "format" / "README.md").symlink_to(secret)
    (source / "app.toml").write_text(
        HEAD + '[needs.files.tasks]\nmode = "rw"\ninit = ["format/README.md"]\n'
    )
    f.store.records["planner"] = AppRecord(name="planner")

    async def go() -> None:
        with pytest.raises(AppError, match=r"format/README\.md is a link to outside the app"):
            await f.store.set_file("planner", "tasks", str(f.home / "planner"), create=True)
        assert not (f.home / "planner" / "README.md").exists()

    asyncio.run(go())


@pytest.mark.rule("app-need.yours-kept-by-handler")
def test_only_the_next_version_s_needs_are_asked_for(f: Fixture) -> None:
    """A need the installed version has and the source dropped (a migrated `file-1`) is not
    asked for: the next deploy drops it."""
    f.deployed(HEAD + "[needs.files.file-1]\n")
    assert [n.name for n in f.store.view("planner").files] == ["file-1"]  # no source: installed
    source = f.store.source("planner")
    source.mkdir(parents=True)
    (source / "app.toml").write_text(HEAD + '[needs.files.tasks]\nmode = "rw"\n')
    assert [n.name for n in f.store.view("planner").files] == ["tasks"]
