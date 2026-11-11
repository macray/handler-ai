"""D.27 conformance: plan drafts on a real handlerd (made for a project, written, edited with the
digest read, approved into a plan, copied from one, thrown away) and the plan builder's session
(its draft its folder, its project read-only: the spec handlerd composed, run in the real
sandbox when there is one)."""

import json
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from ..sandbox.conftest import CURL_IMAGE, run, spec
from ..support import dev_env, runtimes
from ..support.daemon import Daemon
from .test_plans import PLAN, project, wait_plan


def drafts_root(daemon: Daemon) -> Path:
    return daemon.config_dir.parent / "state" / "plan-drafts"


def new_draft(daemon: Daemon, project_id: str) -> dict[str, Any]:
    with daemon.http() as c:
        r = c.post("/v1/plan-drafts", json={"projectId": project_id})
        assert r.status_code == 201, r.text
        return r.json()


def builder(daemon: Daemon, **body: Any) -> dict[str, Any]:
    """A plan builder: folderless, only its model's sites (the defaults); named apart (one name, one agent)."""
    name = f"Plan builder {uuid.uuid4().hex[:6]}"
    body = {"model": {"account": "fake"}, "name": name, "confirmRisks": True} | body
    with daemon.http() as c:
        r = c.post("/v1/agents", json=body)
        assert r.status_code == 201, r.text
        return r.json()


@pytest.mark.rule("plan.a-draft-is-not-a-plan", "plan.what-runs-is-what-you-approved")
def test_a_draft_is_edited_approved_and_copied(daemon: Daemon) -> None:
    folder, dev = project(daemon)
    draft = new_draft(daemon, dev["projectId"])
    assert draft["folder"] == str(folder) and draft.get("title") is None
    text = drafts_root(daemon) / draft["id"] / "draft" / "plan.md"
    text.write_text(PLAN.format(first=""))  # its builder writes
    with daemon.http() as c:
        draft = c.get(f"/v1/plan-drafts/{draft['id']}").json()
        assert draft["title"] == "two steps"
        found = c.post("/v1/plans/read", json={"draftId": draft["id"]}).json()
        assert found["problems"] == [] and found["agentId"] == dev["id"]
        assert found["digest"] == draft["digest"] and found["path"] == "plan.md"
        both = {"draftId": draft["id"], "agentId": dev["id"]}
        assert c.post("/v1/plans/read", json=both).status_code == 422
        old = {"text": "# Plan: mine\n", "digest": "0" * 64}
        r = c.put(f"/v1/plan-drafts/{draft['id']}", json=old)
        assert r.status_code == 409 and r.json()["title"] == "the draft changed since you read it"
        r = c.post("/v1/plans", json={"draftId": draft["id"], "digest": draft["digest"]})
        assert r.status_code == 201, r.text
        plan = r.json()
        assert plan["draftId"] == draft["id"] and plan.get("source") is None
        assert plan["folder"] == str(folder)
        edited = PLAN.format(first="").replace("The second", "The other")
        body = {"text": edited, "digest": draft["digest"]}
        r = c.put(f"/v1/plan-drafts/{draft['id']}", json=body)
        assert r.status_code == 200 and r.json()["digest"] != draft["digest"]
    plan = wait_plan(daemon, plan["id"], "done")
    assert [s["title"] for s in plan["steps"]] == ["The first", "The second"]  # as approved
    assert (folder / "step-2.md").exists()  # its steps worked in the project's folder
    with daemon.http() as c:
        r = c.post("/v1/plan-drafts", json={"fromPlan": plan["id"]})  # Edit as a new draft
        assert r.status_code == 201, r.text
        copy = r.json()
        assert copy["fromPlan"] == plan["id"] and copy["digest"] == plan["digest"]
        listed = c.get("/v1/plan-drafts", params={"projectId": dev["projectId"]}).json()
        assert {d["id"] for d in listed} == {draft["id"], copy["id"]}
        assert c.delete(f"/v1/plan-drafts/{draft['id']}").status_code == 204
        assert c.get(f"/v1/plan-drafts/{draft['id']}").status_code == 404
        assert c.get(f"/v1/plans/{plan['id']}").status_code == 200  # the plan stays
    assert not (drafts_root(daemon) / draft["id"]).exists()


@pytest.mark.rule("plan.builder-reads-the-project-only", "plan.builder-has-no-secret")
def test_a_plan_builder_writes_its_draft_and_sees_the_project_read_only(daemon: Daemon) -> None:
    folder, dev = project(daemon)
    draft = new_draft(daemon, dev["projectId"])
    plans_builder = builder(daemon)
    start = {"agentId": plans_builder["id"], "planDraft": draft["id"], "prompt": "write"}
    with daemon.http() as c:
        r = c.post("/v1/sessions", json=start)
        assert r.status_code == 202, r.text
        session = r.json()
        work = drafts_root(daemon) / draft["id"] / "draft"
        assert session["scope"] == str(work)
        assert session["planDraft"] == {
            "id": draft["id"],
            "projectId": dev["projectId"],
            "folder": str(folder),
        }
        deadline = time.monotonic() + 30
        while not (work / "notes.md").exists():  # the fake writes in its folder: the draft
            assert time.monotonic() < deadline
            time.sleep(0.2)
        assert c.get(f"/v1/plan-drafts/{draft['id']}").json()["sessionId"] == session["id"]
        seen = c.get(f"/v1/sessions/{session['id']}/mounts").json()["mounts"]
        assert {"kind": "scope", "source": str(work), "readOnly": False} in [
            {k: m.get(k) for k in ("kind", "source", "readOnly")} for m in seen
        ]
        project_seen = [m for m in seen if m.get("source") == str(folder)]
        assert [m["readOnly"] for m in project_seen] == [True]
        assert not any(m.get("source", "").endswith("draft.json") for m in seen)
        r = c.post("/v1/sessions", json=start)
        assert r.status_code == 409 and r.json()["title"] == "the draft has its builder session"
        assert not (folder / "notes.md").exists()
    # the spec handlerd composed, its folders run in the real sandbox
    composed = json.loads(
        (daemon.config_dir.parent / "fake-ran" / f"handler-{plans_builder['id']}-{session['id']}")
        .read_text()
    )  # fmt: skip
    assert composed["workFolder"] == {"path": str(work)} and composed["workdir"] == str(work)
    folders = [f for f in composed["folders"] if f["source"] == str(folder)]
    assert folders == [{"source": str(folder), "target": str(folder), "writable": False}]
    assert composed.get("addons", []) == []
    found = runtimes.available()
    if not found:
        pytest.skip("no sandbox runtime here: its folders are checked, not run")
    dev_env.ensure_image(CURL_IMAGE, found[0].binary)
    script = (
        f"cat {folder}/plans/p.md >/dev/null && echo reads; "
        f"echo x > {folder}/plans/p.md 2>/dev/null && echo project-written || echo project-ro; "
        f"echo '# Plan: x' > {work}/plan.md && echo draft-written"
    )
    r = run(found[0].binary, spec(work, ["sh", "-c", script], folders=folders))
    assert r.stdout.decode().split() == ["reads", "project-ro", "draft-written"]
    assert (folder / "plans" / "p.md").read_text() == PLAN.format(first="")
    assert (work / "plan.md").read_text() == "# Plan: x\n"


@pytest.mark.rule("plan.builder-has-no-secret")
def test_a_builder_with_more_rights_is_refused(daemon: Daemon) -> None:
    _, dev = project(daemon)
    draft = new_draft(daemon, dev["projectId"])
    given = builder(daemon, addons=[{"addon": "fake-browser", "binding": "browser"}])
    opened = builder(daemon, network="open")
    with daemon.http() as c:
        for agent, why in ((given, "has tools"), (opened, "reaches more than")):
            body = {"agentId": agent["id"], "planDraft": draft["id"]}
            r = c.post("/v1/sessions", json=body)
            assert r.status_code == 409 and r.json()["title"] == "it cannot build plans"
            assert why in r.json()["detail"]
        r = c.post("/v1/sessions", json={"agentId": dev["id"], "planDraft": draft["id"]})
        assert r.status_code == 409 and "has a folder" in r.json()["detail"]
        assert c.get(f"/v1/plan-drafts/{draft['id']}").json().get("sessionId") is None
