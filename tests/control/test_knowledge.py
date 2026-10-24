"""D.5 through a real handlerd: knowledge folders listed, checked when an agent selects
them, and mounted read-only in a live container agent (echo-box)."""

import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from ..support import dev_env
from ..support.daemon import Daemon, require_echo_box, start_daemon


@pytest.fixture(scope="module")
def root() -> Iterator[Path]:
    base = dev_env.scope_root() / f"knowledge-{uuid.uuid4().hex[:8]}"
    (base / "me").mkdir(parents=True)
    (base / "me" / "_index.md").write_text("---\nsummary: My preferences.\n---\n# me\n")
    (base / "projects" / "shop").mkdir(parents=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture(scope="module")
def daemon(root: Path) -> Iterator[Daemon]:
    yield from start_daemon(extra_env={"HANDLER_KNOWLEDGE_DIR": str(root)})


def test_listing(daemon: Daemon, root: Path) -> None:
    with daemon.http() as c:
        listing = c.get("/v1/knowledge").json()
    folders = ["me", "projects", "projects/shop"]
    assert listing == {"root": str(root), "source": "env", "exists": True, "folders": folders}


def test_selection_is_checked(daemon: Daemon) -> None:
    scope = daemon.make_scope()
    with daemon.http() as c:
        body = {"model": {"account": "echo-box"}, "scope": str(scope), "knowledge": ["../x"]}
        r = c.post("/v1/agents", json=body)
        assert r.status_code == 400 and "outside the knowledge root" in r.text

    ad_hoc = daemon.create_ad_hoc("echo-box", scope, knowledge=["projects/shop", "me"])
    assert ad_hoc["knowledge"] == ["me", "projects/shop"]
    assert daemon.create_ad_hoc("echo-box", scope, name="none")["knowledge"] == []


def test_agent_reads_knowledge_read_only(daemon: Daemon) -> None:
    require_echo_box()
    ad_hoc = daemon.create_ad_hoc("echo-box", daemon.make_scope(), knowledge=["me"])
    client = daemon.connect(ad_hoc["acpUrl"])  # `cat` agent: nothing to initialize
    try:
        container = wait_for_container(ad_hoc["id"])
        read = podman_exec(container, "cat", "/knowledge/me/_index.md")
        assert "summary: My preferences." in read.stdout, read.stderr
        assert podman_exec(container, "ls", "/knowledge").stdout.split() == ["me"]
        assert podman_exec(container, "touch", "/knowledge/me/x").returncode != 0
    finally:
        client.close()


def podman_exec(container: str, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["podman", "exec", container, *argv], capture_output=True, text=True, check=False
    )


def wait_for_container(agent_id: str, timeout: float = 60) -> str:
    deadline = time.monotonic() + timeout
    label = f"label=handler.agent={agent_id}"
    ps = ["podman", "ps", "--format", "{{.Names}}", "--filter", label]
    while time.monotonic() < deadline:
        names = subprocess.run(ps, capture_output=True, text=True, check=False).stdout.split()
        agents = [n for n in names if not n.endswith("-proxy")]  # an filtered network adds a proxy
        if agents:
            return agents[0]
        time.sleep(0.2)
    raise TimeoutError(f"no container for agent {agent_id}")


@pytest.fixture(scope="module")
def configurable() -> Iterator[Daemon]:
    """A daemon without HANDLER_KNOWLEDGE_DIR: the root is set through the API."""
    yield from start_daemon()


def test_root_forced_by_env_cannot_be_changed(daemon: Daemon, tmp_path: Path) -> None:
    with daemon.http() as c:
        assert c.get("/v1/knowledge").json()["source"] == "env"
        assert c.put("/v1/knowledge/root", json={"root": str(tmp_path)}).status_code == 409


def test_configure_create_browse_read(configurable: Daemon, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    with configurable.http() as c:
        r = c.put("/v1/knowledge/root", json={"root": str(vault)})
        assert r.status_code == 400 and "not a folder" in r.text
        r = c.put("/v1/knowledge/root", json={"root": str(vault), "create": True})
        assert r.status_code == 200, r.text
        assert r.json() == {"root": str(vault), "source": "config", "exists": True, "folders": []}

        assert c.post("/v1/knowledge/folders", json={"path": "me"}).json()["folders"] == ["me"]
        assert c.post("/v1/knowledge/folders", json={"path": "me"}).status_code == 409
        assert c.post("/v1/knowledge/folders", json={"path": "../x"}).status_code == 400

        (vault / "me" / "_index.md").write_text("---\nsummary: Me.\n---\n# me\n")
        (vault / "me" / "tools.md").write_text("Zed.\n")
        view = c.get("/v1/knowledge/browse", params={"path": "me"}).json()
        assert view["notes"] == ["tools.md"] and "summary: Me." in view["index"]
        note = c.get("/v1/knowledge/note", params={"path": "me/tools.md"}).json()
        assert note == {"path": "me/tools.md", "text": "Zed.\n"}
        assert c.get("/v1/knowledge/note", params={"path": "../etc.md"}).status_code == 400

        # the new root applies at once to agents
        scope = configurable.make_scope()
        body = {"model": {"account": "echo-box"}, "scope": str(scope), "knowledge": ["me"]}
        assert c.post("/v1/agents", json=body).status_code == 201

        assert c.put("/v1/knowledge/root", json={"root": None}).json()["source"] == "default"
