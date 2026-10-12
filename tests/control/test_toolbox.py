"""B.6, G.1: the user's toolbox folder and addons, as handlerd shows and edits them (no image)."""

from handler_harness import catalog

from ..support.daemon import Daemon


def test_the_toolbox_is_the_users_copy_of_the_default(daemon: Daemon) -> None:
    folder = daemon.config_dir / "toolbox"
    with daemon.http() as c:
        assert c.get("/v1/toolbox").json()["directory"] == str(folder)
        file = c.get("/v1/toolbox/containerfile").json()
    default = (catalog.DEFAULT_TOOLBOX / "Containerfile").read_text()
    assert file == {"content": default, "defaultContent": default}  # seeded on first start
    assert (folder / "toolbox.toml").is_file()


def test_the_toolbox_containerfile_is_saved_whole(daemon: Daemon) -> None:
    path = daemon.config_dir / "toolbox" / "Containerfile"
    before = path.read_text()
    mine = before + "RUN pacman -S --noconfirm htop\n"
    try:
        with daemon.http() as c:
            saved = c.put("/v1/toolbox/containerfile", json={"content": mine}).json()
            assert saved["content"] == mine and saved["defaultContent"] == before
            assert c.put("/v1/toolbox/containerfile", json={"content": ""}).status_code == 422
            too_big = {"content": "x" * (256 * 1024 + 1)}
            assert c.put("/v1/toolbox/containerfile", json=too_big).status_code == 422
        assert path.read_text() == mine
    finally:
        path.write_text(before)


def test_addons_say_where_they_come_from(daemon: Daemon) -> None:
    with daemon.http() as c:
        addons = {a["name"]: a for a in c.get("/v1/addons").json()}
    miniapp = addons["miniapp"]
    assert miniapp["builtin"] and not miniapp["overridesBuiltin"]
    assert miniapp["directory"] == str(catalog.DATA / "addons" / "miniapp")


def test_the_runtime_check_is_shown(daemon: Daemon) -> None:
    """A.8 through D: what `handler setup` and Settings → Images show."""
    with daemon.http() as c:
        check = c.get("/v1/runtime").json()
    assert check["runtime"].startswith("podman") and check["items"]
