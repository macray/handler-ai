"""Contract D.8: the toolbox's caches as Settings → Caches shows and edits them; sizes and
emptying through the sandbox's `cache` verbs (A.9), on the test daemon's own folders."""

import tomllib

from handler_harness import catalog

from ..support.daemon import Daemon
from .test_projects import create_project


def test_caches_with_their_folders_and_who_uses_them(daemon: Daemon) -> None:
    own = create_project(daemon, daemon.make_scope(), name="own-caches", caches="project")
    create_project(daemon, daemon.make_scope(), name="no-caches", caches="off")
    create_project(daemon, daemon.make_scope(), name="sharing", caches="global")
    with daemon.http() as c:
        info = c.get("/v1/caches").json()
    declared = tomllib.loads((catalog.DEFAULT_TOOLBOX / "toolbox.toml").read_text())["caches"]
    assert [x["name"] for x in info["caches"]] == list(declared)
    cargo = next(x for x in info["caches"] if x["name"] == "cargo")
    assert cargo["target"] == "~/.cargo" and cargo["about"] and not cargo["general"]
    assert next(x for x in info["caches"] if x["name"] == "cache")["general"]
    shared = info["global"]
    assert shared["folder"] == str(daemon.cache_dir)
    assert shared["caches"]["cargo"] == str(daemon.cache_dir / "cargo")
    assert list(shared["caches"]) == list(declared)
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
            mine = {
                "cargo": {"target": "~/.cargo", "about": "Rust crates"},
                "gradle": {"target": "~/.gradle", "about": "", "general": True},
            }
            saved = c.put("/v1/caches", json={"caches": mine}).json()
            assert [(x["name"], x["target"], x["general"]) for x in saved["caches"]] == [
                ("cargo", "~/.cargo", False),
                ("gradle", "~/.gradle", True),
            ]
            written = {
                "cargo": {"target": "~/.cargo", "about": "Rust crates"},
                "gradle": {"target": "~/.gradle", "general": True},
            }
            assert tomllib.loads(path.read_text())["caches"] == written
            for refused in ({"home": "~"}, {"a": "~/.x", "b": "~/.x"}):
                body = {n: {"target": t} for n, t in refused.items()}
                r = c.put("/v1/caches", json={"caches": body})
                assert r.status_code == 400 and r.json()["title"] == "caches refused"
            for invalid in (
                {"Bad Name": {"target": "~/.x"}},
                {"x": {"target": "relative"}},
                {"x": "~/.x"},
            ):
                assert c.put("/v1/caches", json={"caches": invalid}).status_code == 422
        assert tomllib.loads(path.read_text())["caches"] == written
    finally:
        path.write_text(before)


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
        assert c.delete("/v1/caches/files").status_code == 204
        assert list(daemon.cache_dir.iterdir()) == []


def test_a_projects_own_caches_emptied_then_removed_with_it(daemon: Daemon) -> None:
    project = create_project(daemon, daemon.make_scope(), name="kept-apart", caches="project")
    folder = daemon.data_dir / "caches" / project["id"]
    for name in ("cargo", "npm"):
        (folder / name).mkdir(parents=True)
        (folder / name / "file").write_text("x")
    with daemon.http() as c:
        sizes = c.get("/v1/caches/sizes").json()["sizes"]
        assert sizes[str(folder / "cargo")] > 0 and sizes[str(folder / "npm")] > 0
        assert c.delete(f"/v1/projects/{project['id']}/caches/cargo/files").status_code == 204
        assert list((folder / "cargo").iterdir()) == [] and list((folder / "npm").iterdir())
        assert c.delete(f"/v1/projects/{project['id']}/caches/nope/files").status_code == 404
        assert c.delete(f"/v1/projects/{project['id']}/caches").status_code == 204
        assert folder.is_dir() and list(folder.iterdir()) == []
        (folder / "cargo").mkdir()
        assert c.delete(f"/v1/projects/{project['id']}").status_code == 204
    assert not folder.exists()
