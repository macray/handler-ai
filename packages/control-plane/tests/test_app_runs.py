"""Unit tests: the agents an app needs, given by the person (H.2), and the runs it starts of
them on handler.sock (H.11), without sandboxes: the sessions they start are recorded, not run."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import AgentInterface, AgentOrigin, AppManifest, SessionOutput
from handler_control import app_runs, interfaces, save_rules
from handler_control.agents import AgentRecord, AgentRegistry, CheckedSettings, RunsAs
from handler_control.app_runs import AppRuns
from handler_control.apps import AppError, AppRecord, AppStore, DeployError, Deployment
from handler_control.inbox import Inbox
from handler_control.projects import ProjectRegistry
from handler_control.sessions import SessionRecord, SessionStore
from handler_control.settings import Settings

RESULT: dict[str, Any] = {
    "type": "object",
    "required": ["status", "summary"],
    "properties": {
        "status": {"enum": ["ok", "attention", "failed"]},
        "summary": {"type": "string"},
    },
}
FIELDS = {"type": "object", "properties": {"request": {"type": "string"}}, "required": ["request"]}
OPTIONAL = {**FIELDS, "required": []}  # the request may be left out
MANIFEST = """apiVersion = "handler.app/v1"
name = "planner"
version = "1.0.0"
[needs.agents.planner]
description = "Tells you what to do next"
from = "agent"
"""
DEFINITION = '[agent]\nname = "Planner"\n'


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
        projects = ProjectRegistry(self.settings.state_dir, self.registry)
        self.runs = AppRuns(self.settings, self.sessions, projects, self.inbox)
        self.store = AppStore(self.settings, "t0ken", self.inbox, self.runs)
        self.created: list[dict[str, Any]] = []
        runs_as = RunsAs(harness="fake", account="fake")
        monkeypatch.setattr(save_rules, "session_model", lambda *_: runs_as)
        monkeypatch.setattr(self.sessions, "create", self.create)
        monkeypatch.setattr(app_runs, "WATCH_POLL", 0.01)

    def create(self, agent: AgentRecord, runs: RunsAs, **kw: Any) -> SessionRecord:
        """What SessionStore.create would record, without starting it."""
        now = datetime.now(UTC)
        rec = SessionRecord(
            id=f"s_{len(self.created)}",
            agent_id=agent.id,
            harness=runs.harness,
            scope="/code/planner",
            created_at=now,
            last_activity_at=now,
            agents_model=True,
            origin=kw["origin"],
            app=kw["app"],
            input=kw["run"].model_dump(),
        )
        self.sessions.records[rec.id] = rec
        self.created.append(kw)
        return rec

    def agent(
        self, name: str = "Planner", scope: str = "/code/planner", **interface: Any
    ) -> AgentRecord:
        settings = CheckedSettings(
            scope=scope,
            model=RunsAs(harness="fake", account="fake"),
            interface=AgentInterface.model_validate(interface or {"result": RESULT}),
        )
        return self.registry.add(AgentRecord(**settings.model_dump(), name=name))

    def deployed(
        self,
        manifest: str = MANIFEST,
        interface: dict[str, Any] | None = None,
        given: AgentRecord | None = None,
    ) -> Path:
        """The app installed (version 1), its definition's interface `interface` (default: a form
        with an optional request, the result RESULT), `given` given for its need."""
        version = self.store.version_dir("planner", 1)
        version.mkdir(parents=True)
        (version / "app.toml").write_text(manifest)
        definition = version / "agent"
        definition.mkdir()
        (definition / "agent.toml").write_text(DEFINITION)
        wanted = interface or {"fields": OPTIONAL, "result": RESULT}
        (definition / "interface.json").write_text(json.dumps(wanted))
        self.store.records["planner"] = AppRecord(
            name="planner",
            deployments=[Deployment(1, "1.0.0", datetime.now(UTC))],
            agents={"planner": given.id} if given else {},
        )
        return version

    async def call(self, method: str, path: str, body: Any = None) -> tuple[int, dict[str, Any]]:
        return await self.store.from_app("planner", method, path, body)


@pytest.fixture
def f(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fixture:
    return Fixture(tmp_path, monkeypatch)


def test_a_run_starts_only_while_answering_the_owner(f: Fixture) -> None:
    strict: dict[str, Any] = {"fields": FIELDS, "result": RESULT}  # the app always sends a request
    f.deployed(interface=strict, given=f.agent(fields=FIELDS, result=RESULT))

    async def go() -> None:
        body = {"agent": "planner", "fields": {"request": "what now?"}}
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
        assert (run["agent"], run["state"]) == ("planner", "running")
        assert f.created[0]["origin"] == "app" and f.created[0]["app"] == "planner"
        f.store.end_start(token)
        status, answer = await f.call("POST", "/runs", body | {"start": token})
        assert status == 403  # answered: spent
        await f.runs.close()

    asyncio.run(go())


def test_a_run_is_of_a_need_with_a_valid_input(f: Fixture) -> None:
    strict: dict[str, Any] = {"fields": FIELDS, "result": RESULT}  # the app always sends a request
    f.deployed(interface=strict, given=f.agent(fields=FIELDS, result=RESULT))

    async def go() -> None:
        token = f.store.issue_start("planner", "owner")
        status, answer = await f.call("POST", "/runs", {"agent": "other", "start": token})
        assert status == 403 and "not in its needs.agents" in answer["error"]
        status, answer = await f.call("POST", "/runs", {"agent": "planner", "start": token})
        assert status == 400 and answer["error"].startswith("input invalid")
        status, answer = await f.call("POST", "/runs", {"agent": "planner"})
        assert status == 400 and "start" in answer["error"]
        status, answer = await f.call("GET", "/runs/r_nope")
        assert status == 404
        assert f.created == []

    asyncio.run(go())


def test_a_run_needs_an_agent_given_that_still_fits(f: Fixture) -> None:
    f.deployed()
    planner = f.agent(result=RESULT)

    async def go() -> None:
        token = f.store.issue_start("planner", "owner")
        status, answer = await f.call("POST", "/runs", {"agent": "planner", "start": token})
        assert status == 409 and "not given" in answer["error"]
        f.store.records["planner"].agents["planner"] = planner.id
        f.registry.delete(planner.id)
        status, answer = await f.call("POST", "/runs", {"agent": "planner", "start": token})
        assert status == 409 and "deleted" in answer["error"]

    asyncio.run(go())


def test_runs_need_agents_in_the_manifest(f: Fixture) -> None:
    f.deployed(MANIFEST.split("[needs.agents.planner]", maxsplit=1)[0] + "[needs]\nnotify = true\n")

    async def go() -> None:
        status, answer = await f.call("POST", "/runs", {"agent": "planner", "start": "x"})
        assert status == 403 and "[needs.agents" in answer["error"]
        assert (await f.call("GET", "/elsewhere"))[0] == 404

    asyncio.run(go())


def test_its_end_goes_to_the_inbox_opening_the_app(f: Fixture) -> None:
    f.deployed(given=f.agent("My planner", fields=OPTIONAL, result=RESULT))

    async def go() -> None:
        token = f.store.issue_start("planner", "owner")
        status, run = await f.call("POST", "/runs", {"agent": "planner", "start": token})
        assert status == 202
        rec = f.sessions.records[run["sessionId"]]
        result = {"status": "attention", "summary": "Call the bank before 10."}
        rec.state = "stopped"
        rec.output = SessionOutput(valid=True, value=result).model_dump()
        for _ in range(100):
            if f.inbox.messages:
                break
            await asyncio.sleep(0.02)
        (message,) = f.inbox.messages
        assert (message.source, message.name, message.app) == ("app", "planner", "planner")
        assert (message.title, message.status, message.summary) == (
            "My planner",  # the agent given, by its name
            "attention",
            "Call the bank before 10.",
        )
        status, done = await f.call("GET", f"/runs/{run['id']}")
        assert (status, done["state"], done["result"]) == (200, "succeeded", result)
        assert (await f.call("POST", f"/runs/{run['id']}/cancel"))[0] == 409
        await f.runs.close()

    asyncio.run(go())


def test_a_cancelled_run_tells_nothing(f: Fixture) -> None:
    f.deployed(given=f.agent(fields=OPTIONAL, result=RESULT))

    async def go() -> None:
        token = f.store.issue_start("planner", "owner")
        _, run = await f.call("POST", "/runs", {"agent": "planner", "start": token})
        assert (await f.call("POST", f"/runs/{run['id']}/cancel"))[0] == 200
        f.sessions.records[run["sessionId"]].state = "stopped"
        for _ in range(20):
            await asyncio.sleep(0.02)
        assert (await f.call("GET", f"/runs/{run['id']}"))[1]["state"] == "cancelled"
        assert f.inbox.messages == []
        await f.runs.close()

    asyncio.run(go())


def test_deploy_checks_the_agent_given(f: Fixture) -> None:
    version = f.deployed()
    manifest = AppManifest.from_toml(MANIFEST)
    with pytest.raises(DeployError, match="agent planner not given"):
        f.store.check_agents("planner", manifest, version)
    brief = f.agent("Brief", fields=FIELDS)
    f.store.records["planner"].agents["planner"] = brief.id
    with pytest.raises(DeployError, match="it is not a job"):
        f.store.check_agents("planner", manifest, version)
    strict = f.agent("Strict", fields=FIELDS, result=RESULT)  # requires a request
    f.store.records["planner"].agents["planner"] = strict.id
    with pytest.raises(DeployError, match="requires request, which the app may leave out"):
        f.store.check_agents("planner", manifest, version)
    fits = f.agent(fields=OPTIONAL, result=RESULT)
    f.store.records["planner"].agents["planner"] = fits.id
    f.store.check_agents("planner", manifest, version)


def test_deploy_checks_the_definition_is_a_job(f: Fixture) -> None:
    version = f.deployed(interface={"fields": FIELDS})
    manifest = AppManifest.from_toml(MANIFEST)
    with pytest.raises(AppError, match="a job's, with a result"):
        f.store.check_agents("planner", manifest, version)
    (version / "agent" / "agent.toml").write_text('description = "x"\n' + DEFINITION)
    with pytest.raises(AppError, match="only \\[agent\\]"):
        f.store.check_agents("planner", manifest, version)


def test_the_agents_that_fit_are_offered(f: Fixture) -> None:
    f.deployed(MANIFEST + 'worksIn = "tasks"\n[needs.files.tasks]\nmode = "rw"\n')
    here = f.agent(fields=OPTIONAL, result=RESULT)
    elsewhere = f.agent("Elsewhere", scope="/code/other", fields=OPTIONAL, result=RESULT)
    f.agent("Brief", fields=FIELDS)
    (need,) = f.store.view("planner").agents
    assert (need.name, need.works_in) == ("planner", "tasks")
    assert need.origin == AgentOrigin(kind="app", name="planner", agent="planner")
    assert need.definition is not None and need.definition.agent_name == "Planner"
    assert set(need.fits) == {here.id, elsewhere.id}  # no folder given yet: any folder
    f.store.records["planner"].files["tasks"] = "/code/planner"
    (need,) = f.store.view("planner").agents
    assert need.fits == [here.id]
    with pytest.raises(AppError, match="it works in /code/other, not in /code/planner"):
        f.store.set_agent("planner", "planner", elsewhere.id)
    assert f.store.set_agent("planner", "planner", here.id).agents[0].agent_id == here.id
    with pytest.raises(AppError, match="needs no agent other"):
        f.store.set_agent("planner", "other", here.id)


def test_a_folder_given_is_checked_made_and_set_up(f: Fixture) -> None:
    source = f.store.source("planner")
    (source / "agent").mkdir(parents=True)
    (source / "agent" / "README.md").write_text("The folder's format.\n")
    (source / "app.toml").write_text(
        MANIFEST.split("[needs.agents.planner]", maxsplit=1)[0]
        + '[needs.files.tasks]\nmode = "rw"\ninit = ["agent/README.md"]\n'
    )
    f.store.records["planner"] = AppRecord(name="planner")

    async def go() -> None:
        folder = f.home / "planner"
        with pytest.raises(AppError, match="does not exist"):
            await f.store.set_file("planner", "tasks", str(folder), create=False)
        app = await f.store.set_file("planner", "tasks", str(folder), create=True)
        assert app.files[0].path == str(folder)
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

    asyncio.run(go())


def test_an_agent_is_set_up_from_the_source_definition(f: Fixture) -> None:
    source = f.store.source("planner")
    (source / "agent").mkdir(parents=True)
    (source / "app.toml").write_text(MANIFEST)
    (source / "agent" / "agent.toml").write_text(DEFINITION)
    (source / "agent" / "interface.json").write_text(json.dumps({"result": RESULT}))
    f.store.records["planner"] = AppRecord(name="planner")
    assert (
        f.store.definition_dir(
            AgentOrigin.model_validate({"kind": "app", "name": "planner", "agent": "planner"})
        )
        == source / "agent"
    )
    with pytest.raises(AppError, match="no app planner needing an agent other"):
        f.store.definition_dir(
            AgentOrigin.model_validate({"kind": "app", "name": "planner", "agent": "other"})
        )


def test_added_agents_are_shown() -> None:
    manifest = AppManifest.from_toml(MANIFEST)
    assert manifest.added_needs(None) == ["agent planner"]
    assert manifest.added_needs(manifest.needs) == []


def test_a_need_names_one_need() -> None:
    with pytest.raises(ValueError, match="names one need: planner"):
        AppManifest.from_toml(MANIFEST + "[needs.files.planner]\n")
    with pytest.raises(ValueError, match="no files need tasks"):
        AppManifest.from_toml(MANIFEST + 'worksIn = "tasks"\n')


def test_misfit_compares_properties_types_and_required() -> None:
    wanted = AgentInterface.model_validate({"fields": OPTIONAL, "result": RESULT})

    def why(**interface: Any) -> str | None:
        return interfaces.misfit(wanted, AgentInterface.model_validate(interface))

    assert why(fields=OPTIONAL, result=RESULT) is None
    extra = {"type": "object", "properties": {**RESULT["properties"], "more": {"type": "string"}}}
    assert why(fields=OPTIONAL, result={**RESULT, **extra}) is None
    assert why(result=RESULT) == "its form has no field request"
    number = {"type": "object", "properties": {"request": {"type": "number"}}}
    assert why(fields=number, result=RESULT) == "its form's request is not a string"
    loose = {**RESULT, "required": ["status"]}
    assert why(fields=OPTIONAL, result=loose) == ("its result does not always give summary")
    assert interfaces.misfit(wanted, None) == "it is not a job"


def test_links_out_of_the_app_are_never_read(f: Fixture) -> None:
    """An agent writes the app's folder: a link there to a file of the person's must not make
    handler read it for the agent (into a definition, into the folder given)."""
    secret = f.home / ".ssh" / "id_ed25519"
    secret.parent.mkdir(parents=True)
    secret.write_text("PRIVATE KEY\n")
    source = f.store.source("planner")
    (source / "agent").mkdir(parents=True)
    (source / "agent" / "agent.toml").write_text(DEFINITION)
    (source / "agent" / "interface.json").write_text(json.dumps({"result": RESULT}))
    (source / "agent" / "instructions.md").symlink_to(secret)
    (source / "agent" / "README.md").symlink_to(secret)
    (source / "app.toml").write_text(
        MANIFEST + '[needs.files.tasks]\nmode = "rw"\ninit = ["agent/README.md"]\n'
    )
    f.store.records["planner"] = AppRecord(name="planner")
    (need,) = f.store.view("planner").agents
    assert need.definition is None
    assert need.problem is not None and need.problem.endswith("is a link to outside the app")
    with pytest.raises(AppError, match="a link to outside the app"):
        f.store.definition_dir(
            AgentOrigin.model_validate({"kind": "app", "name": "planner", "agent": "planner"})
        )

    async def go() -> None:
        with pytest.raises(AppError, match=r"agent/README\.md is a link to outside the app"):
            await f.store.set_file("planner", "tasks", str(f.home / "planner"), create=True)
        assert not (f.home / "planner" / "README.md").exists()

    asyncio.run(go())


def test_only_the_next_version_s_needs_are_asked_for(f: Fixture) -> None:
    """A need the installed version has and the source dropped (a migrated `file-1`) is not
    asked for: the next deploy drops it."""
    head = MANIFEST.partition("[needs.agents.planner]")[0]
    f.deployed(head + "[needs.files.file-1]\n")
    assert [n.name for n in f.store.view("planner").files] == ["file-1"]  # no source: installed
    source = f.store.source("planner")
    source.mkdir(parents=True)
    (source / "app.toml").write_text(head + '[needs.files.tasks]\nmode = "rw"\n')
    assert [n.name for n in f.store.view("planner").files] == ["tasks"]
