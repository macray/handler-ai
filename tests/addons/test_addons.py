"""Contract G conformance, through a real handlerd: addons and bindings listed, an addon image
rebuilt, extracted into its folder and checked (G.4), bindings selected by an agent (G3) and given
to a live agent (G4, A.1), and an addon's folder kept while an agent mounts it.

Needs podman and the toolbox image (the test addon is built in it, like real ones). The agent is
the echo-box test harness (a container that only echoes), inspected from outside.
"""

import json
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from handler_control import runtime

from ..support import dev_env
from ..support.daemon import Daemon, start_daemon

TOOLBOX = "localhost/handler-ai-toolbox:latest"
REPO = "localhost/handler-ai-test-addon"
TARGET = "/opt/tools/handler-test"
TOKEN = "addon-s3cr3t-for-redaction"

MANIFEST = f"""
apiVersion = "handler.tool/v1"
name = "handler-test"
image = "{REPO}"
commands = ["handler-hello"]
check = ["handler-hello"]
egress = ["example.net:443"]
[env]
HANDLER_TEST_STATIC = "static"
[settings.greeting]
env = "HANDLER_TEST_GREETING"
required = true
[secretSlots.token]
env = "HANDLER_TEST_ADDON_TOKEN"
"""

# --no-cache rebuilds give a new image each time (the version records when)
CONTAINERFILE = f"""
ARG TOOLBOX_IMAGE={TOOLBOX}
FROM ${{TOOLBOX_IMAGE}} AS build
RUN mkdir -p {TARGET}/bin \\
    && printf '#!/bin/sh\\necho "hello $HANDLER_TEST_GREETING"\\n' > {TARGET}/bin/handler-hello \\
    && chmod 755 {TARGET}/bin/handler-hello \\
    && echo "handler-test $(date +%s%N)" > {TARGET}/version
FROM scratch
COPY --from=build {TARGET} /
"""


def podman_ok() -> bool:
    try:
        return subprocess.run(["podman", "image", "exists", TOOLBOX], check=False).returncode == 0
    except OSError:
        return False


pytestmark = [
    pytest.mark.skipif(not podman_ok(), reason=f"podman or {TOOLBOX} missing"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


@pytest.fixture(scope="module")
def addons_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("addons")
    (root / "handler-test").mkdir()
    (root / "handler-test" / "tool.toml").write_text(MANIFEST)
    (root / "handler-test" / "Containerfile").write_text(CONTAINERFILE)
    return root


@pytest.fixture(scope="module")
def daemon(addons_dir: Path) -> Iterator[Daemon]:
    env = {"HANDLER_TOOLS_DIR": str(addons_dir), "HANDLER_TEST_ADDON_TOKEN_SOURCE": TOKEN}
    yield from start_daemon(extra_env=env)


@pytest.fixture(scope="module")
def bindings(daemon: Daemon) -> Path:
    root = daemon.config_dir / "connections"
    root.mkdir(exist_ok=True)
    (root / "test.toml").write_text(
        'apiVersion = "handler.connection/v1"\ntool = "handler-test"\n'
        'settings = { greeting = "from the binding" }\n'
        'secrets = { token = { env = "HANDLER_TEST_ADDON_TOKEN_SOURCE" } }\n'
    )
    (root / "incomplete.toml").write_text(
        'apiVersion = "handler.connection/v1"\ntool = "handler-test"\n'
    )
    return root


def rebuild(c: httpx.Client, name: str = "handler-test") -> dict[str, Any]:
    r = c.post(f"/v1/addons/{name}/rebuild")
    assert r.status_code == 202, r.text
    build_id = r.json()["id"]
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        build: dict[str, Any] = c.get(f"/v1/builds/{build_id}").json()
        if build["state"] != "running":
            build["log"] = c.get(f"/v1/builds/{build_id}/log").json()["text"]
            return build
        time.sleep(0.5)
    raise TimeoutError(build_id)


def folders(daemon: Daemon) -> Path:
    return daemon.data_dir / "addons" / "handler-test"


def current(daemon: Daemon) -> Path | None:
    """The folder agents get (its image's id), None before the first build."""
    marker = folders(daemon) / "current"
    return folders(daemon) / marker.read_text().strip() if marker.exists() else None


def wait_gone(path: Path, timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while path.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    return not path.exists()


def addon(c: httpx.Client) -> dict[str, Any]:
    found: dict[str, Any] = next(
        a for a in c.get("/v1/addons").json() if a["name"] == "handler-test"
    )
    return found


# ── catalog (G.1, G.2) ──────────────────────────────────────────────────


@pytest.mark.rule("access.its-status-says-what-is-missing", "secrets.never-read-back")
def test_addons_and_bindings_are_listed(daemon: Daemon, bindings: Path) -> None:
    with daemon.http() as c:
        a = addon(c)
        assert a["commands"] == ["handler-hello"] and a["egress"] == ["example.net:443"]
        assert a["settings"] == [{"name": "greeting", "required": True}]
        assert a["secretSlots"] == [{"name": "token", "required": False}]
        listed = {b["name"]: b for b in c.get("/v1/bindings").json()}
    assert "error" not in listed["test"]
    assert listed["test"]["secrets"] == ["token"]
    assert "HANDLER_TEST_ADDON_TOKEN_SOURCE" not in json.dumps(listed)  # references stay private
    assert "required setting greeting" in listed["incomplete"]["error"]


def test_unknown_addon_cannot_be_rebuilt(daemon: Daemon) -> None:
    with daemon.http() as c:
        assert c.post("/v1/addons/nope/rebuild").status_code == 404


# ── images and folders (G.4) ────────────────────────────────────────────────────────


@pytest.mark.rule("tool.runs-from-a-read-only-folder", "tool.checked-against-its-manifest")
def test_rebuild_builds_checks_and_switches(daemon: Daemon) -> None:
    before = current(daemon)
    with daemon.http() as c:
        build = rebuild(c)
        assert build["state"] == "succeeded", build["log"][-2000:]
        assert build["target"] == "addon:handler-test"
        assert build["versions"]["addon:handler-test"].startswith("handler-test ")
        assert "commands, version and check ok" in build["log"]
        a = addon(c)
    assert a["imagePresent"] and a["version"] == build["versions"]["addon:handler-test"]
    now = current(daemon)
    assert now is not None and now != before and (now / "bin" / "handler-hello").is_file()
    assert not (now / "version").stat().st_mode & 0o222  # read-only
    assert runtime.inspect(now.name) is None  # the image is removed once extracted
    assert before is None or wait_gone(before)  # the replaced folder too, no sandbox mounts it


@pytest.mark.rule("tool.checked-against-its-manifest")
def test_check_refuses_an_image_that_does_not_match_its_manifest(
    daemon: Daemon, addons_dir: Path
) -> None:
    toml = addons_dir / "handler-test" / "tool.toml"
    original = toml.read_text()
    with daemon.http() as c:
        if not addon(c)["imagePresent"]:
            assert rebuild(c)["state"] == "succeeded"
    before = current(daemon)
    toml.write_text(original.replace('commands = ["handler-hello"]', 'commands = ["other"]'))
    try:
        with daemon.http() as c:
            build = rebuild(c)
    finally:
        toml.write_text(original)
    assert build["state"] == "failed"
    assert "bin/ holds handler-hello; the manifest declares other" in build["error"]
    assert before is not None and current(daemon) == before  # agents keep the folder they had
    failed = [p for p in folders(daemon).iterdir() if p.name not in ("current", before.name)]
    assert all(wait_gone(p) for p in failed)  # removed once the build ended


# ── selection (G3) and agents (G4, A.1) ──────────────────────────────────


@pytest.mark.rule("tool.its-use-is-checked-when-saved")
def test_g3_agent_selection_is_checked(daemon: Daemon, bindings: Path) -> None:
    scope = daemon.make_scope()
    with daemon.http() as c:
        for account, selected, detail in (
            ("echo-box", "missing", "unknown connection"),
            ("echo-box", "incomplete", "required setting greeting"),
        ):
            uses = [{"addon": "handler-test", "binding": selected}]
            r = c.post(
                "/v1/agents",
                json={"model": {"account": account}, "scope": str(scope), "addons": uses},
            )
            assert r.status_code == 400, r.text
            assert detail in r.json()["detail"]


@pytest.mark.rule("tool.each-start-gets-what-it-gives")
def test_g4_agent_gets_the_addon(daemon: Daemon, bindings: Path) -> None:
    with daemon.http() as c:
        if not addon(c)["imagePresent"]:
            assert rebuild(c)["state"] == "succeeded"
    folder = current(daemon)
    uses = [{"addon": "handler-test", "binding": "test"}]
    ad_hoc = daemon.create_ad_hoc("echo-box", daemon.make_scope(), addons=uses)
    assert ad_hoc["addons"] == uses
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        container = wait_for_container(ad_hoc["id"])
        config = inspect(container)
        env = dict(e.split("=", 1) for e in config["Config"]["Env"])
        assert env["HANDLER_TEST_GREETING"] == "from the binding"
        assert env["HANDLER_TEST_STATIC"] == "static"
        phantom = env["HANDLER_TEST_ADDON_TOKEN"]  # the proxy swaps it back (A.3)
        assert phantom != TOKEN and len(phantom) == len(TOKEN)
        assert env["PATH"].endswith(f":{TARGET}/bin")
        mount = next(m for m in config["Mounts"] if m["Destination"] == TARGET)
        assert mount["Source"] == str(folder) and not mount["RW"]
        hello = subprocess.run(
            ["podman", "exec", container, "handler-hello"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert hello.stdout.strip() == "hello from the binding", hello.stderr
        write = subprocess.run(
            ["podman", "exec", container, "touch", f"{TARGET}/x"], capture_output=True, check=False
        )
        assert write.returncode != 0  # read-only
    finally:
        client.close()


@pytest.mark.rule("tool.runs-from-a-read-only-folder")
def test_rebuild_keeps_a_folder_an_agent_mounts(daemon: Daemon, bindings: Path) -> None:
    """A rebuild switches agents to the new folder; the one a running sandbox mounts stays until
    that sandbox ends."""
    with daemon.http() as c:
        if not addon(c)["imagePresent"]:
            assert rebuild(c)["state"] == "succeeded"
        mounted = current(daemon)
        assert mounted is not None
        uses = [{"addon": "handler-test", "binding": "test"}]
        ad_hoc = daemon.create_ad_hoc("echo-box", daemon.make_scope(), addons=uses)
        client = daemon.connect(ad_hoc["acpUrl"])
        try:
            container = wait_for_container(ad_hoc["id"])
            build = rebuild(c)
            assert build["state"] == "succeeded", build["log"][-2000:]
            assert current(daemon) != mounted and mounted.is_dir()
            hello = subprocess.run(
                ["podman", "exec", container, "handler-hello"],
                capture_output=True,
                text=True,
                check=False,
            )
            assert hello.stdout.strip() == "hello from the binding"
        finally:
            client.close()
    assert wait_gone(mounted)  # removed once its sandbox ended


# ── helpers ─────────────────────────────────────────────────────────────


def wait_for_container(agent_id: str, timeout: float = 60) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        names = subprocess.run(
            [
                "podman",
                "ps",
                "--format",
                "{{.Names}}",
                "--filter",
                f"label=handler.agent={agent_id}",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
        agents = [n for n in names if not n.endswith("-proxy")]  # an filtered network adds a proxy
        if agents:
            return agents[0]
        time.sleep(0.2)
    raise TimeoutError(f"no container for agent {agent_id}")


def inspect(container: str) -> dict[str, Any]:
    out = subprocess.run(
        ["podman", "inspect", container], capture_output=True, text=True, check=True
    ).stdout
    found: dict[str, Any] = json.loads(out)[0]
    return found
