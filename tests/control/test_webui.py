"""Web UI serving and the folder picker (contract D additions for the UI)."""

import os
import re
from pathlib import Path

import httpx
import pytest

from handler_control.settings import WEB_UI

from ..support.daemon import Daemon

UI_BUILT = (WEB_UI / "index.html").is_file()


@pytest.mark.skipif(not UI_BUILT, reason="web UI not built (scripts/build-web-ui.sh)")
def test_ui_is_served_with_security_headers(daemon: Daemon) -> None:
    r = httpx.get(f"{daemon.base_url}/")
    assert r.status_code == 200 and '<div id="app">' in r.text
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert f"ws://127.0.0.1:{daemon.base_url.rsplit(':', 1)[1]}" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    asset = next(
        part.split('"')[1] for part in r.text.split("src=")[1:] if part.startswith('"/assets/')
    )
    assert httpx.get(f"{daemon.base_url}{asset}").status_code == 200


@pytest.mark.skipif(not UI_BUILT, reason="web UI not built (scripts/build-web-ui.sh)")
def test_the_ui_s_styles_load_nothing_its_csp_refuses() -> None:
    """The CSP lets in `data:` images only: a font inlined as a data: URL is refused (the
    browser's console says so on every page) and falls back to another font."""
    inlined = {
        url.split(";", 1)[0].split(",", 1)[0]
        for css in (WEB_UI / "assets").glob("*.css")
        for url in re.findall(r"url\(\s*[\"']?(data:[^)\"']{0,80})", css.read_text())
    }
    assert all(kind.startswith("data:image/") for kind in inlined), inlined


def test_api_routes_win_over_static_files(daemon: Daemon) -> None:
    assert httpx.get(f"{daemon.base_url}/v1/health").json()["status"] == "ok"
    assert httpx.get(f"{daemon.base_url}/v1/accounts").status_code == 401


def test_directories(daemon: Daemon) -> None:
    project = daemon.make_scope()
    (project / "src").mkdir()
    (project / ".git").mkdir()
    with daemon.http() as c:
        roots = c.get("/v1/directories").json()
        assert roots.get("path") is None  # omitted = null (exclude_none)
        assert [e["path"] for e in roots["entries"]] == [str(daemon.scope_root)]
        inside = c.get("/v1/directories", params={"path": str(project)}).json()
        assert inside["path"] == str(project) and inside["parent"] == str(daemon.scope_root)
        assert [e["name"] for e in inside["entries"]] == ["src"]  # no dot-folders
        at_root = c.get("/v1/directories", params={"path": str(daemon.scope_root)}).json()
        assert at_root.get("parent") is None


def test_recent_directories(daemon: Daemon) -> None:
    """New project's list: the work folders' folders changed last first, with their git branch."""
    old, new = daemon.make_scope(), daemon.make_scope()
    (new / ".git").mkdir()
    (new / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    os.utime(old, (1_000_000_000, 1_000_000_000))
    with daemon.http() as c:
        entries = c.get("/v1/directories/recent").json()["entries"]
    paths = [e["path"] for e in entries]
    assert str(new) in paths and str(old) not in paths[: paths.index(str(new)) + 1]
    found = next(e for e in entries if e["path"] == str(new))
    assert found["branch"] == "main" and found["changedAt"]


def test_directories_are_confined_to_the_work_folders(daemon: Daemon, tmp_path: Path) -> None:
    escape = daemon.make_scope() / "escape"
    escape.symlink_to(tmp_path)
    with daemon.http() as c:
        for path in ("/etc", str(tmp_path), str(escape), f"{daemon.scope_root}/../"):
            r = c.get("/v1/directories", params={"path": path})
            assert r.status_code == 403, path


def test_create_directory(daemon: Daemon, tmp_path: Path) -> None:
    project = daemon.make_scope()
    url = "/v1/directories"
    with daemon.http() as c:
        r = c.post(url, json={"parent": str(project), "name": "new project"})
        assert r.status_code == 201, r.text
        assert r.json()["path"] == str(project / "new project") and r.json()["entries"] == []
        assert (project / "new project").is_dir()
        assert c.post(url, json={"parent": str(project), "name": "new project"}).status_code == 409
        for name in ("..", ".hidden", "a/b"):
            r = c.post(url, json={"parent": str(project), "name": name})
            assert r.status_code in (400, 403, 422), name
        assert c.post(url, json={"parent": str(tmp_path), "name": "x"}).status_code == 403
    assert not (tmp_path / "x").exists()
