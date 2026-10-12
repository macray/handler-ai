"""G.5 through the Control API: the catalog, preview, install (its image built afterwards),
remove. The test daemon has the catalog's playwright and shopify installed."""

from pathlib import Path

from ..support.daemon import Daemon

MANIFEST = 'apiVersion = "handler.addon/v1"\nname = "notes"\negress = ["notes.example.com:443"]\n'


def test_the_catalog_says_what_is_installed(daemon: Daemon) -> None:
    with daemon.http() as c:
        entries = {e["name"]: e for e in c.get("/v1/addon-catalog").json()}
        listed = {a["name"]: a for a in c.get("/v1/addons").json()}
    assert entries["shopify"]["installed"] and entries["shopify"]["description"]
    assert listed["shopify"]["source"] == "catalog:shopify"
    assert not listed["shopify"]["updateAvailable"]  # what handler ships
    assert listed["miniapp"]["builtin"] and "source" not in listed["miniapp"]


def test_preview_install_and_remove_from_a_folder(daemon: Daemon, tmp_path: Path) -> None:
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "addon.toml").write_text(MANIFEST)
    with daemon.http() as c:
        seen = c.post("/v1/addons/preview", json={"source": str(folder)}).json()
        assert seen["egress"] == ["notes.example.com:443"] and "image" not in seen
        body = {"source": str(folder), "digest": seen["digest"]}
        installed = c.post("/v1/addons/install", json=body).json()
        assert installed["addon"]["source"] == str(folder) and "build" not in installed
        assert "notes" in [a["name"] for a in c.get("/v1/addons").json()]
        assert c.delete("/v1/addons/notes").status_code == 204
        assert "notes" not in [a["name"] for a in c.get("/v1/addons").json()]


def test_what_cannot_be_installed_or_removed(daemon: Daemon) -> None:
    with daemon.http() as c:
        bad = c.post("/v1/addons/preview", json={"source": "relative/notes"})
        assert bad.status_code == 422 and "absolute path" in bad.json()["detail"]
        stale = {"source": "catalog:shopify", "digest": "0" * 64}
        assert c.post("/v1/addons/install", json=stale).status_code == 422
        used = c.delete("/v1/addons/playwright")  # the daemon's `browser` binding uses it
        assert used.status_code == 409 and "browser" in used.json()["detail"]
        assert c.delete("/v1/addons/miniapp").status_code == 409  # built-in
