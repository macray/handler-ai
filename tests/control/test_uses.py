"""D.22 conformance: what uses what, on a real handlerd: an agent's skills (its own and its
project's), knowledge, addon configuration and model access, each seen from both ends."""

import tempfile
from pathlib import Path
from typing import Any

from ..support.daemon import Daemon

SKILL = "---\nname: {name}\ndescription: Does {name} things.\n---\n\nDo it.\n"


def uses(daemon: Daemon, kind: str, ident: str) -> dict[str, Any]:
    with daemon.http() as c:
        r = c.get(f"/v1/uses/{kind}/{ident}")
        assert r.status_code == 200, r.text
        return r.json()


def pairs(refs: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(r["kind"], r["how"]) for r in refs}


def test_what_an_agent_uses_and_what_uses_it(daemon: Daemon) -> None:
    root = Path(tempfile.mkdtemp(prefix="knowledge-"))
    (root / "acme").mkdir()
    with daemon.http() as c:
        c.put("/v1/knowledge/root", json={"root": str(root)}).raise_for_status()
        for name in ("own-skill", "shared-skill"):
            c.post("/v1/skills", json={"content": SKILL.format(name=name)}).raise_for_status()
        r = c.post(
            "/v1/projects",
            json={
                "name": "used",
                "folder": str(daemon.make_scope()),
                "skills": ["shared-skill"],
                "agents": [
                    {
                        "name": "dev",
                        "model": {"account": "fake"},
                        "skills": ["own-skill"],
                        "knowledge": ["acme"],
                        "bindings": ["browser"],
                    }
                ],
            },
        )
        assert r.status_code == 201, r.text
        project = r.json()
        [agent] = project["agents"]
    seen = uses(daemon, "agent", agent["id"])
    assert {("skill", "own-skill"), ("skill", "shared-skill")} <= {
        (r["kind"], r["id"]) for r in seen["uses"]
    }
    assert pairs(seen["uses"]) >= {
        ("skill", "picks it"),
        ("skill", "given by its project"),
        ("knowledge", "reads it"),
        ("addon", "uses it"),
        ("account", "runs on it"),
    }
    shared = uses(daemon, "skill", "shared-skill")["usedBy"]
    assert pairs(shared) == {
        ("agent", "given by its project"),
        ("project", "gives it to all its agents"),
    }
    assert [r["label"] for r in shared if r["kind"] == "agent"] == ["used · dev"]
    assert pairs(uses(daemon, "knowledge", "acme")["usedBy"]) == {("agent", "reads it")}
    assert pairs(uses(daemon, "account", "fake")["usedBy"]) >= {("agent", "runs on it")}
    assert uses(daemon, "skill", "nobody")["usedBy"] == []
    with daemon.http() as c:
        assert c.get("/v1/uses/nonsense/x").status_code == 404
