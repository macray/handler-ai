"""B.6, G.1: the user's toolbox folder and addons, as handlerd shows and edits them (no image)."""

import asyncio
import subprocess
from pathlib import Path

from handler_control import image_check
from handler_control.settings import Settings
from handler_harness import catalog

from ..sandbox.conftest import requires_podman
from ..support import dev_env
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
    builder = addons["app-builder"]
    assert builder["builtin"] and not builder["overridesBuiltin"]
    assert builder["directory"] == str(catalog.DATA / "addons" / "app-builder")


def test_the_runtime_check_is_shown(daemon: Daemon) -> None:
    """A.8 through D: what `handler setup` and Settings → Images show."""
    with daemon.http() as c:
        check = c.get("/v1/runtime").json()
    assert check["runtime"].startswith("podman") and check["items"]


@requires_podman
def test_the_toolbox_check_finds_no_bun(tmp_path: Path) -> None:
    """B.6 through the sandbox, on an image with a shell and no Bun: a warning, not an error."""
    image = "docker.io/curlimages/curl:8.11.1"
    subprocess.run(["podman", "pull", "-q", image], capture_output=True, check=False)
    settings = Settings(
        port=0,
        config_dir=tmp_path / "config",
        state_dir=dev_env.make_scope(),  # its scratch folder must be outside /tmp (A.1)
        bindings_dir=tmp_path / "bindings",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        accounts_dir=tmp_path / "accounts",
        providers_dir=tmp_path / "providers",
        skills_dir=tmp_path / "skills",
        knowledge_dir=tmp_path / "knowledge",
    )
    lines: list[str] = []
    try:
        warnings = asyncio.run(image_check.check_toolbox(settings, image, lines.append))
    finally:
        dev_env.remove_scope(settings.state_dir)
    assert warnings == [image_check.NO_BUN], "\n".join(lines)
    assert f"warning: {image_check.NO_BUN}" in lines
