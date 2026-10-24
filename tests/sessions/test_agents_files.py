"""D.23 conformance: a project's agents exported as a file (what is yours left out, their checks
kept), the file read again and its agents set up in a new project (their checks and skills come
with them), on a real handlerd, the job on the model alone with a stub provider (no image
needed)."""

import io
import tomllib
import zipfile
from collections.abc import Iterator
from typing import Any

import pytest

from ..support.daemon import Daemon, start_daemon
from ..support.stub_llm import StubLlm
from .test_checks import FIELDS, RESULT, answer
from .test_runs import skill_md, wait_output
from .test_sessions import create_session


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


JUDGE = {
    "name": "Judge",
    "modelAlone": True,
    "model": {"provider": "stub"},
    "instructions": "Judge {{draft}}.",
    "interface": {"fields": FIELDS, "result": RESULT},
}


def a_project_with_a_checked_job(daemon: Daemon) -> dict[str, Any]:
    with daemon.http() as c:
        assert c.post("/v1/skills", json={"content": skill_md("tidy")}).status_code == 201
        dev = {"name": "Dev", "model": {"account": "fake"}, "bindings": ["browser"]}
        body = {"folder": str(daemon.make_scope()), "skills": ["tidy"], "agents": [JUDGE, dev]}
        r = c.post("/v1/projects", json=body)
        assert r.status_code == 201, r.text
        project = r.json()
    judge = next(a for a in project["agents"] if a["name"] == "Judge")
    started = create_session(daemon, judge, input={"fields": {"draft": "Hi"}})
    run = wait_output(daemon, started["id"])
    with daemon.http() as c:
        r = c.post(f"/v1/agents/{judge['id']}/checks", json={"fromRun": run["id"], "name": "a no"})
        assert r.status_code == 201, r.text
    return project


def test_exported_from_a_project_then_set_up_again(daemon: Daemon) -> None:
    project = a_project_with_a_checked_job(daemon)
    ids = [a["id"] for a in project["agents"]]
    export = {"name": "tone-shop", "description": "Judges drafts", "projectId": project["id"]}
    with daemon.http() as c:
        r = c.post("/v1/agents-files/export", json=export | {"agentIds": ids, "dryRun": True})
        assert r.status_code == 200, r.text
        draft = r.json()
        assert draft["file"]["version"] == 1
        said = "\n".join(draft["replaced"])
        assert "account fake" in said and "provider stub" in said and project["folder"] in said
        assert "addon configuration browser" in said and "skill tidy, given by its project" in said
        assert "provider stub → a provider, chosen at set-up" in said  # Judge, on the model alone
        assert said.count(project["folder"]) == 1  # Dev's: the model alone has no folder

        r = c.post("/v1/agents-files/export", json=export | {"agentIds": ids})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
        assert 'filename="tone-shop-agents.zip"' in r.headers["content-disposition"]
        data = r.content
        assert c.get("/v1/agents-files/tone-shop").status_code == 404  # nothing kept
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        meta = tomllib.loads(zf.read("agents.toml").decode())
        assert meta["name"] == "tone-shop" and meta["description"] == "Judges drafts"
        assert "agents/dev/skills/tidy/SKILL.md" in zf.namelist()  # its skills come with it

    with daemon.http() as c:  # the file read again: its agents, ready to be set up
        r = c.post("/v1/agents-files/import", content=data)
        assert r.status_code == 201, r.text
        read = r.json()
        assert c.get("/v1/agents-files/tone-shop").json() == read
    assert (read["name"], read["version"], read["place"]) == ("tone-shop", 1, "project")
    assert read["description"] == "Judges drafts" and "handler" not in read
    dev, judge = read["agents"]
    assert (dev["part"], judge["part"]) == ("dev", "judge")
    assert "model" not in judge["definition"] and judge["definition"]["modelAlone"]
    assert dev["definition"]["skills"] == ["tidy"] and dev["definition"]["addons"]
    [check] = judge["checks"]
    assert check["input"] == {"draft": "Hi"} and check["answer"]["verdict"] == "send"
    assert "id" not in check and "fromRun" not in check

    with daemon.http() as c:
        origin = {"kind": "agents-file", "name": "tone-shop", "version": 1, "agent": "judge"}
        body = {"folder": str(daemon.make_scope()), "agents": [JUDGE | {"origin": origin}]}
        r = c.post("/v1/projects", json=body)
        assert r.status_code == 201, r.text
        [made] = r.json()["agents"]
        assert made["origin"] == origin
        [copied] = c.get(f"/v1/agents/{made['id']}/checks").json()["checks"]
        assert copied["input"] == {"draft": "Hi"} and "fromRun" not in copied

        # set up, the file is forgotten: the agents stay as they are
        assert c.delete("/v1/agents-files/tone-shop").status_code == 204
        assert c.get("/v1/agents-files/tone-shop").status_code == 404
        assert c.get(f"/v1/agents/{made['id']}").json()["origin"] == origin


def test_refusals(daemon: Daemon) -> None:
    with daemon.http() as c:
        folder = str(daemon.make_scope())
        one = c.post("/v1/projects", json={"folder": folder, "agents": [JUDGE]}).json()
        other = c.post("/v1/projects", json={"folder": str(daemon.make_scope()), "agents": [JUDGE]})
        mixed = {"name": "mixed", "projectId": one["id"]}
        mixed["agentIds"] = [one["agents"][0]["id"], other.json()["agents"][0]["id"]]
        r = c.post("/v1/agents-files/export", json=mixed)
        assert r.status_code == 400 and r.json()["title"] == "not one project"
        r = c.post("/v1/agents-files/import", content=b"not a zip")
        assert r.status_code == 400 and r.json()["title"] == "not an agents file"
        assert c.delete("/v1/agents-files/nope").status_code == 404
        assert c.get("/v1/agents-files/skill-review").status_code == 404  # a need's: no file
