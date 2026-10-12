"""Shared by the mini app suites: a daemon with its own data folder, a browser on an app's
origin, the Control API."""

import json
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from ..sandbox.conftest import podman_usable
from ..support import dev_env
from ..support.daemon import Daemon, start_daemon

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
IDLE_TIMEOUT = 6

requires_podman = pytest.mark.skipif(not podman_usable(), reason="podman not usable")


@pytest.fixture(scope="module")
def data_root() -> Iterator[Path]:
    path = dev_env.scope_root() / f"apps-{uuid.uuid4().hex[:8]}"  # not under /tmp (A.1)
    path.mkdir()
    yield path
    dev_env.remove_scope(path)


GNOME_SCHEMA = (
    Path(__file__).resolve().parents[2] / "packages" / "control-plane" / "tests" / "fixtures"
    / "org.gnome.settings-daemon.plugins.media-keys.gschema.xml"
)  # fmt: skip


def gnome_env(root: Path) -> dict[str, str]:
    """gsettings on a keyfile under `root`, with the part of GNOME's schema handler uses: the daemon
    sets keyboard shortcuts there, not in the desktop running the tests."""
    schemas = root / "gnome" / "schemas"
    schemas.mkdir(parents=True)
    shutil.copy(GNOME_SCHEMA, schemas)
    if shutil.which("glib-compile-schemas"):
        subprocess.run(["glib-compile-schemas", str(schemas)], check=True)
    return {
        "GSETTINGS_SCHEMA_DIR": str(schemas),
        "GSETTINGS_BACKEND": "keyfile",
        "XDG_CONFIG_HOME": str(root / "gnome" / "config"),
    }


@pytest.fixture(scope="module")
def daemon(data_root: Path) -> Iterator[Daemon]:
    env = {"HANDLER_DATA_DIR": str(data_root), "HANDLER_APP_IDLE_TIMEOUT": str(IDLE_TIMEOUT)}
    yield from start_daemon(extra_env=env | gnome_env(data_root))


def copy_fixture(name: str, data_root: Path) -> Path:
    path = data_root / "src" / name
    shutil.copytree(FIXTURES / name, path)
    return path


class AppClient:
    """A browser on the app's origin: Host header, its cookie, its Origin."""

    def __init__(self, daemon: Daemon, name: str) -> None:
        self.port = daemon.base_url.rsplit(":", 1)[1]
        self.origin = f"http://{name}.localhost:{self.port}"
        self.http = httpx.Client(base_url=daemon.base_url, timeout=90)
        self.cookie: str | None = None

    def request(self, method: str, path: str, **headers: str) -> httpx.Response:
        h = {"Host": self.origin.removeprefix("http://")} | headers
        if self.cookie:
            h["Cookie"] = f"handler_app={self.cookie}; other=1"
        return self.http.request(method, path, headers=h)

    def request_json(self, method: str, path: str, body: object) -> object:
        """A JSON call from the app's own page (its Origin)."""
        h = {"Origin": self.origin, "Content-Type": "application/json"}
        r = self.request_body(method, path, json.dumps(body).encode(), **h)
        assert r.status_code == 200, r.text
        return r.json()

    def request_body(
        self, method: str, path: str, content: bytes, **headers: str
    ) -> httpx.Response:
        h = {"Host": self.origin.removeprefix("http://")} | headers
        if self.cookie:
            h["Cookie"] = f"handler_app={self.cookie}"
        return self.http.request(method, path, headers=h, content=content)

    def login(self, link: str) -> httpx.Response:
        assert link.startswith(f"{self.origin}/_handler/login?code=")
        r = self.request("GET", link.removeprefix(self.origin))
        if r.status_code == 200:
            self.cookie = r.cookies["handler_app"]
        self.http.cookies.clear()  # sent by hand (request), so that tests can drop it
        return r


def api(daemon: Daemon, method: str, path: str, json: object = None) -> httpx.Response:
    with daemon.http() as c:  # a deploy may pull the runtime image: long timeout
        return c.request(method, path, json=json, timeout=600)


def set_version(source: Path, version: str) -> None:
    manifest = source / "app.toml"
    text = manifest.read_text()
    old = text.split('version = "')[1].split('"')[0]
    manifest.write_text(text.replace(f'version = "{old}"', f'version = "{version}"'))


def call_app(daemon: Daemon, name: str, app: str, call: str) -> dict[str, object]:
    """An automation `name` calling `app`'s route (I.3), tried now; its run once it ended."""
    folder = daemon.config_dir / "automations" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "automation.toml").write_text(
        'apiVersion = "handler.automation/v1"\nwhen = { at = "08:30", days = ["mon", "fri"] }\n'
        f'run = {{ app = "{app}", call = "{call}" }}\n'
    )
    r = api(daemon, "POST", f"/v1/automations/{name}/try", {})
    assert r.status_code == 202, r.text
    run = r.json()
    deadline = time.monotonic() + 120
    while run["state"] in ("queued", "running"):
        assert time.monotonic() < deadline, run
        time.sleep(0.3)
        run = api(daemon, "GET", f"/v1/automations/{name}/runs/{run['id']}").json()
    return run
