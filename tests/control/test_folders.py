"""D.13 through a real handlerd: the work folders, owned by this computer, and what they allow."""

import pytest

from ..support.daemon import Daemon


@pytest.mark.rule("folders.agents-work-only-inside-them", "folders.never-handler-s-own")
def test_work_folders(daemon: Daemon) -> None:
    """Replaced as written; never the daemon's own folders; a folder outside them cannot be
    an ad-hoc agent's or a project's."""
    root = str(daemon.scope_root)
    outside = daemon.scope_root.parent / f"{daemon.scope_root.name}-outside"
    outside.mkdir()
    with daemon.http() as c:
        assert [f["root"] for f in c.get("/v1/folders").json()["folders"]] == [root]
        body = {"model": {"account": "fake"}, "scope": str(outside)}
        r = c.post("/v1/agents", json=body)
        assert r.status_code == 403 and "outside the work folders" in r.json()["detail"]
        try:
            missing = f"{outside}-missing"
            r = c.put("/v1/folders", json={"roots": [root, str(outside), root, missing]})
            assert r.status_code == 200
            assert [f["root"] for f in r.json()["folders"]] == [root, str(outside), missing]
            assert c.post("/v1/agents", json=body).status_code == 201
            project = {
                "folder": str(outside / "shop"),
                "agents": [{"model": {"account": "fake"}, "name": "dev"}],
            }
            (outside / "shop").mkdir()
            made = c.post("/v1/projects", json=project | {"name": "shop-in-outside"})
            assert made.status_code == 201, made.text
            shown = {f["root"]: f for f in c.get("/v1/folders").json()["folders"]}
            assert shown[str(outside)]["projects"] == ["shop-in-outside"]
            assert shown[str(outside)]["exists"] and not shown[missing]["exists"]
            c.delete(f"/v1/projects/{made.json()['id']}").raise_for_status()
            for refused in (str(daemon.config_dir), str(daemon.config_dir.parent), "relative"):
                r = c.put("/v1/folders", json={"roots": [refused]})
                assert r.status_code == 403, refused
            assert c.put("/v1/folders", json={"roots": []}).status_code == 422
        finally:
            c.put("/v1/folders", json={"roots": [root]}).raise_for_status()
