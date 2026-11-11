"""G.5 through the Control API: preview, install (its image built afterwards), remove. The test
daemon has the official source's fake-browser and fake-shop installed (D.26: test_sources.py)."""

from pathlib import Path

import pytest

from ..support.daemon import Daemon

MANIFEST = 'apiVersion = "handler.tool/v1"\nname = "notes"\negress = ["notes.example.com:443"]\n'


def test_an_installed_addon_says_where_it_came_from(daemon: Daemon) -> None:
    with daemon.http() as c:
        c.get("/v1/sources")  # read once
        listed = {a["name"]: a for a in c.get("/v1/addons").json()}
    assert listed["fake-shop"]["source"] == "source:official/fake-shop"
    assert not listed["fake-shop"]["updateAvailable"]  # what the source holds
    assert listed["app-builder"]["builtin"] and "source" not in listed["app-builder"]


@pytest.mark.rule("tool.installed-as-previewed")
def test_preview_install_and_remove_from_a_folder(daemon: Daemon, tmp_path: Path) -> None:
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "tool.toml").write_text(MANIFEST)
    with daemon.http() as c:
        seen = c.post("/v1/addons/preview", json={"source": str(folder)}).json()
        assert seen["egress"] == ["notes.example.com:443"] and "image" not in seen
        body = {"source": str(folder), "digest": seen["digest"]}
        installed = c.post("/v1/addons/install", json=body).json()
        assert installed["addon"]["source"] == str(folder) and "build" not in installed
        assert "notes" in [a["name"] for a in c.get("/v1/addons").json()]
        assert c.delete("/v1/addons/notes").status_code == 204
        assert "notes" not in [a["name"] for a in c.get("/v1/addons").json()]


@pytest.mark.rule(
    "tool.installed-as-previewed",
    "tool.an-install-stays-in-its-folder",
    "tool.yours-is-never-replaced",
)
def test_what_cannot_be_installed_or_removed(daemon: Daemon) -> None:
    with daemon.http() as c:
        bad = c.post("/v1/addons/preview", json={"source": "relative/notes"})
        assert bad.status_code == 422 and "absolute path" in bad.json()["detail"]
        stale = {"source": "source:official/fake-shop", "digest": "0" * 64}
        assert c.post("/v1/addons/install", json=stale).status_code == 422
        used = c.delete("/v1/addons/fake-browser")  # the daemon's `browser` binding uses it
        assert used.status_code == 409 and "browser" in used.json()["detail"]
        assert c.delete("/v1/addons/app-builder").status_code == 409  # built-in
