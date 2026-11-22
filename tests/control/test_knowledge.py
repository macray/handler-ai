"""D.5 through a real handlerd: knowledge folders listed, checked when an agent selects
them, and mounted read-only in a live container agent (echo-box)."""

import shutil
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

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
    yield from start_daemon(extra_env={"HANDLER_NOTES_DIR": str(root)})


@pytest.mark.rule("notes.follows-its-root")
def test_listing(daemon: Daemon, root: Path) -> None:
    with daemon.http() as c:
        listing = c.get("/v1/knowledge").json()
    folders = ["me", "projects", "projects/shop"]
    assert listing == {"root": str(root), "source": "env", "exists": True, "folders": folders}


@pytest.mark.rule("notes.only-inside-its-root")
def test_selection_is_checked(daemon: Daemon) -> None:
    scope = daemon.make_scope()
    with daemon.http() as c:
        body = {
            "model": {"account": "echo-box"},
            "scope": str(scope),
            "knowledge": [{"folder": "../x"}],
        }
        r = c.post("/v1/agents", json=body)
        assert r.status_code == 400 and "outside the notes root" in r.text

    given = [{"folder": "projects/shop", "access": "write"}, {"folder": "me"}]
    ad_hoc = daemon.create_ad_hoc("echo-box", scope, knowledge=given)
    assert ad_hoc["knowledge"] == [
        {"folder": "me", "access": "read"},
        {"folder": "projects/shop", "access": "write"},
    ]
    assert daemon.create_ad_hoc("echo-box", scope, name="none")["knowledge"] == []


@pytest.mark.rule("notes.read-only-at-its-name")
def test_agent_reads_knowledge_read_only(daemon: Daemon) -> None:
    require_echo_box()
    ad_hoc = daemon.create_ad_hoc("echo-box", daemon.make_scope(), knowledge=[{"folder": "me"}])
    client = daemon.connect(ad_hoc["acpUrl"])  # `cat` agent: nothing to initialize
    try:
        container = wait_for_container(ad_hoc["id"])
        read = podman_exec(container, "cat", "/notes/me/_index.md")
        assert "summary: My preferences." in read.stdout, read.stderr
        assert podman_exec(container, "ls", "/notes").stdout.split() == ["me"]
        assert podman_exec(container, "touch", "/notes/me/x").returncode != 0
    finally:
        client.close()


@pytest.mark.rule(
    "notes.read-only-at-its-name",
    "notes.agents-never-reach-the-history",
    "save.widening-is-confirmed",
)
def test_agent_writes_a_folder_given_read_write_never_its_git(daemon: Daemon, root: Path) -> None:
    """A folder given read-write: the agent's writes land in it at once; its own `.git` (a
    vault's history) stays read-only.

    If this fails: an agent given write access rewrites the vault's git history, or its
    writes never reach your notes."""
    require_echo_box()
    name = f"rw-{uuid.uuid4().hex[:6]}"
    (root / name / ".git").mkdir(parents=True)
    (root / name / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    with daemon.http() as c:
        body = {
            "model": {"account": "echo-box"},
            "scope": str(daemon.make_scope()),
            "knowledge": [{"folder": name, "access": "write"}],
        }
        r = c.post("/v1/agents", json=body)
        assert r.status_code == 409 and r.json()["title"] == "risks not confirmed", r.text
        assert f"notes {name} read-write" in r.json()["detail"]
        ad_hoc = c.post("/v1/agents", json=body | {"confirmRisks": True}).json()
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        container = wait_for_container(ad_hoc["id"])
        wrote = podman_exec(container, "sh", "-c", f"echo hi > /notes/{name}/new.md")
        assert wrote.returncode == 0, wrote.stderr
        assert (root / name / "new.md").read_text() == "hi\n"
        assert podman_exec(container, "touch", f"/notes/{name}/.git/HEAD").returncode != 0
        assert podman_exec(container, "rm", "-rf", f"/notes/{name}/.git").returncode != 0
        assert (root / name / ".git" / "HEAD").read_text() == "ref: refs/heads/main\n"
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
def configurable(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Daemon]:
    """A daemon without HANDLER_NOTES_DIR: the root is set through the API, else ~/notes (in a
    home of its own)."""
    home = tmp_path_factory.mktemp("home")
    yield from start_daemon(extra_env={"HANDLER_NOTES_DIR": "", "HOME": str(home)})


@pytest.mark.rule("notes.follows-its-root")
def test_root_forced_by_env_cannot_be_changed(daemon: Daemon, tmp_path: Path) -> None:
    with daemon.http() as c:
        assert c.get("/v1/knowledge").json()["source"] == "env"
        assert c.put("/v1/knowledge/root", json={"root": str(tmp_path)}).status_code == 409


@pytest.mark.rule("notes.only-inside-its-root", "notes.follows-its-root")
def test_configure_create_browse_read(configurable: Daemon, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    with configurable.http() as c:
        start = c.get("/v1/knowledge").json()  # nothing to set up: the default is made
        assert (start["source"], start["exists"]) == ("default", True)
        assert start["root"].endswith("/notes") and "handlerd-" not in start["root"]
        check = c.get("/v1/knowledge/check", params={"path": str(vault)})
        assert check.json() == {"root": str(vault), "state": "missing"}
        assert c.get("/v1/knowledge/check", params={"path": "vault"}).status_code == 400
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
        body = {
            "model": {"account": "echo-box"},
            "scope": str(scope),
            "knowledge": [{"folder": "me"}],
        }
        assert c.post("/v1/agents", json=body).status_code == 201

        assert c.put("/v1/knowledge/root", json={"root": None}).json()["source"] == "default"


def _start_fails(daemon: Daemon, agent: dict[str, Any]) -> str:
    """Its next session's error, once it failed."""
    with daemon.http() as c:
        r = c.post("/v1/sessions", json={"agentId": agent["id"]})
        assert r.status_code == 202, r.text
        url = f"/v1/sessions/{r.json()['id']}"
        deadline = time.monotonic() + 30
        while (session := c.get(url).json())["state"] == "starting":
            assert time.monotonic() < deadline
            time.sleep(0.1)
    assert session["state"] == "failed", session
    return session["error"]


@pytest.mark.rule("notes.only-inside-its-root")
@pytest.mark.parametrize(
    "replace",
    [
        pytest.param(lambda folder: folder.rmdir(), id="removed"),
        pytest.param(
            lambda folder: folder.rmdir() or folder.symlink_to("/etc"), id="a-link-out-of-the-root"
        ),
    ],
)
def test_a_folder_changed_since_the_save_fails_the_start(
    daemon: Daemon, root: Path, replace: Callable[[Path], None]
) -> None:
    """An agent saved with a notes folder that is then removed, or replaced by a link out of
    the root: its next session does not start, and says which folder.

    If this fails: an agent given "my notes" reads `/etc` or `~/.ssh` through a link made after
    its save."""
    name = f"notes-{uuid.uuid4().hex[:6]}"
    (root / name).mkdir()
    agent = daemon.create_ad_hoc("fake", daemon.make_scope(), knowledge=[{"folder": name}])
    replace(root / name)
    error = _start_fails(daemon, agent)
    assert name in error
