"""Contract F conformance: a session's folder and what changed in it since it started (§F.8)."""

import os
import time
from typing import Any

from ..support.daemon import Daemon
from .test_projects import create_project


def running(daemon: Daemon, session_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while True:
        with daemon.http() as c:
            state = c.get(f"/v1/sessions/{session_id}").json()
        if state["state"] == "running":
            return state
        assert time.monotonic() < deadline, state
        time.sleep(0.1)


def test_session_folder_and_changes(daemon: Daemon) -> None:
    scope = daemon.make_scope()
    (scope / "src").mkdir()
    (scope / "src" / "app.py").write_text("print('hi')\n")
    agent = create_project(daemon, scope)["agents"][0]
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"]})
        assert r.status_code == 202, r.text
        sid = r.json()["id"]
    running(daemon, sid)

    (scope / "notes.md").write_text("# plan\n")  # what the agent would write
    app = scope / "src" / "app.py"
    app.write_text("print('bye')\n")
    st = app.stat()
    os.utime(app, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    with daemon.http() as c:
        r = c.get(f"/v1/sessions/{sid}/changes")
        assert r.status_code == 200, r.text
        changes = r.json()
        assert changes["git"] is False and "notFollowed" not in changes
        assert sorted((f["path"], f["change"]) for f in changes["files"]) == [
            ("notes.md", "added"),
            ("src/app.py", "modified"),
        ]

        listing = c.get(f"/v1/sessions/{sid}/folder").json()
        assert [(e["name"], e["kind"]) for e in listing["entries"]] == [
            ("src", "folder"),
            ("notes.md", "file"),
        ]
        file = c.get(f"/v1/sessions/{sid}/file", params={"path": "src/app.py"}).json()
        assert (file["text"], file["change"]) == ("print('bye')\n", "modified")
        found = c.get(f"/v1/sessions/{sid}/find", params={"q": "app"}).json()
        assert found == {"paths": ["src/app.py"]}
        recent = c.get(f"/v1/sessions/{sid}/find").json()  # no query: the latest changed first
        assert recent["paths"][0] == "src/app.py"

        out = c.get(f"/v1/sessions/{sid}/file", params={"path": "../x"})
        assert out.status_code == 400 and out.json()["title"] == "path not shown"
        gone = c.get(f"/v1/sessions/{sid}/folder", params={"path": "nope"})
        assert gone.status_code == 404
        assert c.get("/v1/sessions/s_nope/changes").status_code == 404
        outside = c.post(f"/v1/sessions/{sid}/reveal", json={"path": "../x"})
        assert outside.status_code == 400
        missing = c.post(f"/v1/sessions/{sid}/reveal", json={"path": "nope"})
        assert missing.status_code == 404
        assert c.delete(f"/v1/sessions/{sid}").status_code == 204


def test_what_the_sandbox_sees(daemon: Daemon) -> None:
    """Every mount of its last start listed; knowledge read like its folder, never caches."""
    root = daemon.make_scope()
    (root / "notes").mkdir()
    (root / "notes" / "me.md").write_text("# me\n")
    scope = daemon.make_scope()
    with daemon.http() as c:
        c.put("/v1/knowledge/root", json={"root": str(root)}).raise_for_status()
        agent = {"models": [{"account": "fake"}], "name": "dev", "knowledge": ["notes"]}
        agent = create_project(daemon, scope, agents=[agent])["agents"][0]
        sid = c.post("/v1/sessions", json={"agentId": agent["id"]}).json()["id"]
    running(daemon, sid)
    with daemon.http() as c:
        seen = c.get(f"/v1/sessions/{sid}/mounts").json()
        assert seen["startedAt"]
        by_kind = {m["kind"]: m for m in seen["mounts"]}
        assert by_kind["scope"] | {"readOnly": False, "browsable": True} == by_kind["scope"]
        knowledge = by_kind["knowledge"]
        assert (knowledge["target"], knowledge["readOnly"]) == ("/knowledge/notes", True)
        assert knowledge["browsable"] and knowledge["source"] == str(root / "notes")
        cache = by_kind["cache"]  # the fake harness has no state of its own
        assert not cache["browsable"]

        query = {"mount": "/knowledge/notes", "path": "me.md"}
        note = c.get(f"/v1/sessions/{sid}/file", params=query).json()
        assert (note["text"], note.get("change")) == ("# me\n", None)
        listing = c.get(f"/v1/sessions/{sid}/folder", params={"mount": "/knowledge/notes"})
        assert [e["name"] for e in listing.json()["entries"]] == ["me.md"]
        hidden = c.get(f"/v1/sessions/{sid}/folder", params={"mount": cache["target"]})
        assert hidden.status_code == 404
        assert c.delete(f"/v1/sessions/{sid}").status_code == 204
