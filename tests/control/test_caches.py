"""Contract D.8: the toolbox's caches as Settings → Caches shows and edits them; sizes and
emptying through the sandbox's `cache` verbs (A.9), on the test daemon's own folders."""

import shutil
import tomllib

import pytest

from ..sandbox.conftest import requires_podman
from ..support.daemon import Daemon
from .test_projects import create_project

# the fake sandbox hands the `cache` verbs to handler-sandbox-podman (tests/support/fake_sandbox.py):
# Podman must answer (on a Mac, a Podman machine running)


def test_caches_with_their_folders_and_who_uses_them(daemon: Daemon) -> None:
    own = create_project(daemon, daemon.make_scope(), name="own-caches", caches="project")
    create_project(daemon, daemon.make_scope(), name="no-caches", caches="off")
    create_project(daemon, daemon.make_scope(), name="sharing", caches="global")
    with daemon.http() as c:
        info = c.get("/v1/caches").json()
    names = ["npm", "cache", "local", "local-share-containers-storage", "bun"]
    assert [x["name"] for x in info["caches"]] == names  # the base's, podman's, app-builder's
    npm = next(x for x in info["caches"] if x["name"] == "npm")
    assert npm["target"] == "~/.npm" and npm["about"] and not npm["general"]
    assert npm["declaredBy"] == ["base"]
    assert info["caches"][-2]["declaredBy"] == ["system-package:podman"]
    assert info["caches"][-1]["declaredBy"] == ["addon:app-builder"]
    assert next(x for x in info["caches"] if x["name"] == "cache")["general"]
    shared = info["global"]
    assert shared["folder"] == str(daemon.cache_dir)
    assert shared["caches"]["npm"] == str(daemon.cache_dir / "npm")
    assert list(shared["caches"]) == names
    assert "sharing" in shared["projects"] and "own-caches" not in shared["projects"]
    folder = daemon.data_dir / "caches" / own["id"]
    mine = next(p for p in info["own"] if p["projectId"] == own["id"])
    assert mine["name"] == "own-caches" and mine["folder"] == str(folder)
    assert mine["caches"]["npm"] == str(folder / "npm")
    assert "no-caches" in info["off"]


def test_the_cache_list_is_written_to_the_toolbox(daemon: Daemon) -> None:
    path = daemon.config_dir / "toolbox" / "toolbox.toml"
    before = path.read_text()
    try:
        with daemon.http() as c:
            mine = [
                {"target": "~/.cargo", "about": "Rust crates"},
                {"target": "~/.gradle", "about": "Gradle's packages", "general": True},
            ]
            saved = c.put("/v1/caches", json={"caches": mine}).json()["caches"]
            assert [(x["name"], x["target"], x["general"]) for x in saved[-2:]] == [
                ("cargo", "~/.cargo", False),
                ("gradle", "~/.gradle", True),
            ]
            assert saved[-1]["declaredBy"] == ["user"] and saved[0]["declaredBy"] == ["base"]
            written = [
                {"target": "~/.cargo", "about": "Rust crates"},
                {"target": "~/.gradle", "about": "Gradle's packages", "general": True},
            ]
            assert tomllib.loads(path.read_text())["caches"] == written
            for invalid in (
                [{"target": "~", "about": "home"}],  # it would hide the harness's home
                [{"target": "~/.x", "about": "x"}, {"target": "~/.x", "about": "y"}],
                [{"target": "~/.m2", "about": "x"}, {"target": "~/m2", "about": "y"}],  # one folder
                [{"target": "~/.x"}],  # what it holds is said
                [{"target": "relative", "about": "x"}],
                ["~/.x"],
            ):
                assert c.put("/v1/caches", json={"caches": invalid}).status_code == 422
            # the base's at the same place: shared, said by both
            same = [{"target": "~/.npm", "about": "my npm"}]
            npm = c.put("/v1/caches", json={"caches": same}).json()["caches"][0]
            assert npm["declaredBy"] == ["base", "user"] and npm["about"] == "npm packages"
            r = c.put("/v1/caches", json={"caches": [{"target": "~/npm", "about": "x"}]})
            assert r.status_code == 400 and "share the folder of ~/.npm" in r.json()["detail"]
            assert c.put("/v1/caches", json={"caches": mine}).status_code == 200
        assert tomllib.loads(path.read_text())["caches"] == written
    finally:
        path.write_text(before)


@pytest.mark.rule("cache.measured-and-emptied-whoever-wrote-it")
@requires_podman
def test_sizes_and_emptying_global_caches(daemon: Daemon) -> None:
    npm, left = daemon.cache_dir / "npm", daemon.cache_dir / "removed-cache"
    for folder in (npm, left):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "pkg.tgz").write_bytes(b"x" * 50_000)
    with daemon.http() as c:
        removed = c.get("/v1/caches").json()["global"]["removed"]
        assert removed == {"removed-cache": str(left)}  # what a removed cache left
        sizes = c.get("/v1/caches/sizes").json()["sizes"]
        assert sizes[str(npm)] >= 50_000 and sizes[str(left)] >= 50_000
        assert c.delete("/v1/caches/npm/files").status_code == 204
        assert npm.is_dir() and list(npm.iterdir()) == []
        assert left.is_dir() and list(left.iterdir())
        assert c.delete("/v1/caches/nope/files").status_code == 404
        # what a removed cache left, freed alone: no longer listed
        assert c.delete("/v1/caches/removed-cache/files").status_code == 204
        assert not left.exists() and c.get("/v1/caches").json()["global"]["removed"] == {}
        assert c.delete("/v1/caches/files").status_code == 204
        assert list(daemon.cache_dir.iterdir()) == []


@pytest.mark.rule(
    "cache.measured-and-emptied-whoever-wrote-it", "project.deleting-it-never-touches-its-folder"
)
@requires_podman
def test_a_projects_own_caches_emptied_then_removed_with_it(daemon: Daemon) -> None:
    project = create_project(daemon, daemon.make_scope(), name="kept-apart", caches="project")
    folder = daemon.data_dir / "caches" / project["id"]
    for name in ("bun", "npm"):
        (folder / name).mkdir(parents=True)
        (folder / name / "file").write_text("x")
    with daemon.http() as c:
        sizes = c.get("/v1/caches/sizes").json()["sizes"]
        assert sizes[str(folder / "bun")] > 0 and sizes[str(folder / "npm")] > 0
        assert c.delete(f"/v1/projects/{project['id']}/caches/bun/files").status_code == 204
        assert list((folder / "bun").iterdir()) == [] and list((folder / "npm").iterdir())
        assert c.delete(f"/v1/projects/{project['id']}/caches/nope/files").status_code == 404
        (folder / "gone").mkdir()
        (folder / "gone" / "file").write_text("x")
        assert c.delete(f"/v1/projects/{project['id']}/caches/gone/files").status_code == 204
        assert not (folder / "gone").exists()
        assert c.delete(f"/v1/projects/{project['id']}/caches").status_code == 204
        assert folder.is_dir() and list(folder.iterdir()) == []
        (folder / "bun").mkdir()
        assert c.delete(f"/v1/projects/{project['id']}").status_code == 204
    assert not folder.exists()


def test_a_project_choosing_otherwise_keeps_its_own_listed_until_emptied(daemon: Daemon) -> None:
    project = create_project(daemon, daemon.make_scope(), name="moved", caches="project")
    folder = daemon.data_dir / "caches" / project["id"]
    (folder / "npm").mkdir(parents=True)
    (folder / "npm" / "file").write_text("x")
    with daemon.http() as c:
        body = {"name": "moved", "folder": project["folder"], "caches": "global"}
        assert c.put(f"/v1/projects/{project['id']}", json=body).status_code == 200
        info = c.get("/v1/caches").json()
        assert "moved" in info["global"]["projects"]
        assert any(p["projectId"] == project["id"] for p in info["own"])  # its files still there
        shutil.rmtree(folder / "npm")
        info = c.get("/v1/caches").json()
        assert not any(p["projectId"] == project["id"] for p in info["own"])
