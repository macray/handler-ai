"""`handler run`, `handler attach`, `handler session …` and `handler acp AGENT`
against a real handlerd: sessions held by the daemon, used from the terminal, the stdio bridge, or
another client."""

import argparse
import asyncio
import contextlib
import io
import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from handler_cli.client import ClientError
from handler_cli.session_commands import acknowledge_outside, flag_changes, settle_flags
from handler_cli.terminal import Terminal
from handler_harness.render import FILTERED_NETWORK

from ..support.acp_client import AcpClient
from ..support.daemon import Daemon
from .test_cli import HANDLER, env, handler


def sessions(daemon: Daemon) -> list[dict[str, Any]]:
    with daemon.http() as c:
        return c.get("/v1/sessions").json()


def session_id(output: str) -> str:
    return next(w for w in output.split() if w.startswith("s_"))


def events(daemon: Daemon, sid: str, want: str, timeout: float = 30) -> str:
    """The session's event log, once it contains `want`."""
    log = daemon.config_dir.parent / "state" / "sessions" / sid / "events.ndjson"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = log.read_text() if log.exists() else ""
        if want in text:
            return text
        time.sleep(0.1)
    raise AssertionError(f"{want!r} never in {log}")


def project(daemon: Daemon, folder: Path) -> dict[str, Any]:
    agents = [
        {"model": {"account": "fake"}, "name": "dev"},
        {"model": {"account": "fake"}, "name": "review", "instructions": "Be brief."},
    ]
    with daemon.http() as c:
        r = c.post("/v1/projects", json={"folder": str(folder), "agents": agents})
        assert r.status_code == 201, r.text
        return r.json()


def test_run_is_an_ad_hoc_session_here(daemon: Daemon) -> None:
    here = daemon.make_scope()
    r = handler(daemon, "run", "fake", "-p", "report", "--name", "cli", "--detach", cwd=here)
    assert r.returncode == 0, r.stderr
    sid = session_id(r.stdout)
    assert f"/#/sessions/{sid}" in r.stdout
    events(daemon, sid, '\\"mode\\": \\"yolo\\"')  # the request was answered
    session = next(s for s in sessions(daemon) if s["id"] == sid)
    assert (session["scope"], session["title"], session.get("projectId")) == (
        str(here),
        "report",
        None,
    )
    listed = handler(daemon, "session", "list").stdout
    assert sid in listed and str(here) in listed
    shown = handler(daemon, "session", "show", sid).stdout
    assert "fake · account fake" in shown and str(here) in shown and f"/#/sessions/{sid}" in shown
    # no account or provider named, several ready: which one?
    r = handler(daemon, "run", "--detach", cwd=here)
    assert r.returncode != 0 and "which account or provider?" in r.stderr


@pytest.mark.rule("cli.the-folder-decides-the-project")
def test_run_names_an_agent_of_the_project_of_the_folder(daemon: Daemon) -> None:
    folder = daemon.make_scope()
    p = project(daemon, folder)
    inside = folder / "src"
    inside.mkdir()
    r = handler(daemon, "run", "Review", "-p", "report", "--detach", cwd=inside)
    assert r.returncode == 0, r.stderr
    sid = session_id(r.stdout)
    # the agent's instructions, what its filtered network means, then the request
    events(daemon, sid, json.dumps(f"Be brief.\n\n{FILTERED_NETWORK}\n\nreport")[1:-1])
    assert next(s for s in sessions(daemon) if s["id"] == sid)["projectId"] == p["id"]
    assert "review" in handler(daemon, "session", "list").stdout
    r = handler(daemon, "run", "nope", cwd=folder)
    assert r.returncode == 1 and "no agent, account or provider 'nope'" in r.stderr
    assert "(its agents: dev, review)" in r.stderr


@pytest.mark.rule("cli.the-folder-decides-the-project")
def test_a_project_with_no_agent_yet_refuses(daemon: Daemon) -> None:
    """In the folder of a project with no agent, nothing runs: it says where to add one."""
    folder = daemon.make_scope()
    with daemon.http() as c:
        r = c.post("/v1/projects", json={"folder": str(folder), "name": "empty"})
        assert r.status_code == 201, r.text
    empty = r.json()["id"]
    r = handler(daemon, "run", "--detach", cwd=folder)
    assert r.returncode == 1
    assert "the project empty has no agent yet: add one on its page in the web UI" in r.stderr
    assert not [s for s in sessions(daemon) if s.get("projectId") == empty]


@pytest.mark.rule(
    "cli.the-folder-decides-the-project", "cli.another-area-runs-only-outside-once-confirmed"
)
def test_the_project_s_folder_decides_the_agent(daemon: Daemon) -> None:
    """In a project's folder, `handler run` uses its agents and their settings; another account runs
    its default agent, unless it is not made for the project's area (D.19): refused, and
    --anyway (then ad hoc, outside the project) needs it confirmed in a terminal."""
    folder = daemon.make_scope()
    p = project(daemon, folder)
    default = next(a for a in p["agents"] if a["id"] == p["defaultAgent"])
    r = handler(daemon, "run", "--detach", cwd=folder)  # no name needed: the default agent
    assert r.returncode == 0, r.stderr
    session = next(s for s in sessions(daemon) if s["id"] == session_id(r.stdout))
    assert (session["agentId"], session.get("projectId")) == (default["id"], p["id"])

    r = handler(daemon, "run", "echo-box", "--detach", cwd=folder)  # not one of its agents'
    assert r.returncode == 0, r.stderr
    session = next(s for s in sessions(daemon) if s["id"] == session_id(r.stdout))
    assert (session["agentId"], session["account"]) == (default["id"], "echo-box")

    with daemon.http() as c:
        assert c.post("/v1/areas", json={"name": "Job", "color": "blue"}).status_code == 201
        body = {"name": "fake", "harness": "fake", "areas": ["Job"]}
        assert c.put("/v1/accounts/fake", json=body).status_code == 200
        work = {"folder": str(folder), "area": "Job"}
        assert c.put(f"/v1/projects/{p['id']}", json=work).status_code == 200
    try:
        for command in ("run", "terminal"):
            r = handler(daemon, command, "echo-box", cwd=folder)
            assert r.returncode != 0, r.stderr
            assert f"echo-box is for no area; {p['name']} is a Job project" in r.stderr
            assert f"handler {command} echo-box --anyway" in r.stderr
        r = handler(daemon, "run", "echo-box", "--anyway", "--detach", cwd=folder)
        assert r.returncode != 0 and "confirm it in a terminal" in r.stderr  # no terminal here

        r = handler(daemon, "run", "fake", "--anyway", "--network", "none", "--detach", cwd=folder)
        assert r.returncode == 0, r.stderr  # made for the project's area: nothing to confirm
        sid = session_id(r.stdout)
        assert next(s for s in sessions(daemon) if s["id"] == sid).get("projectId") is None
    finally:
        with daemon.http() as c:
            c.put(f"/v1/projects/{p['id']}", json={"folder": str(folder)})
            c.put("/v1/accounts/fake", json={"name": "fake", "harness": "fake"})


@pytest.mark.rule("cli.a-flag-is-never-ignored")
def test_a_flag_that_differs_from_the_project_s_agent_is_saved_never_ignored(
    daemon: Daemon,
) -> None:
    """--save without a terminal (in one, handler asks); then it is the agent's setting."""
    folder = daemon.make_scope()
    p = project(daemon, folder)
    default = next(a for a in p["agents"] if a["id"] == p["defaultAgent"])
    r = handler(daemon, "run", "fake", "--containers", "--detach", cwd=folder)
    assert r.returncode != 0 and not r.stdout  # no terminal to ask: nothing started
    assert "agent dev: confinement strict → nested" in r.stderr and "--save" in r.stderr
    r = handler(daemon, "run", "fake", "--containers", "--save", "--detach", cwd=folder)
    assert r.returncode == 0, r.stderr
    assert "this agent gets it runs containers" in r.stderr  # what it widens, said
    sid = session_id(r.stdout)
    assert next(s for s in sessions(daemon) if s["id"] == sid)["agentId"] == default["id"]
    with daemon.http() as c:
        saved = c.get(f"/v1/agents/{default['id']}").json()
    assert (saved["confinement"], saved["name"], saved.get("instructions")) == (
        "nested",
        "dev",
        None,
    )
    with daemon.http() as c:
        assert c.get(f"/v1/projects/{p['id']}").json()["defaultAgent"] == default["id"]
    r = handler(daemon, "run", "fake", "--containers", "--detach", cwd=folder)
    assert r.returncode == 0, r.stderr  # now its setting: nothing differs
    r = handler(daemon, "run", "--name", "x", "--detach", cwd=folder)
    assert r.returncode != 0 and "name one of its agents: handler run AGENT" in r.stderr


@pytest.mark.rule("cli.the-folder-decides-the-project")
def test_an_account_picks_the_agent_whose_model_it_is(daemon: Daemon) -> None:
    """D.1: naming an account runs the project's agent on it, the default agent first."""
    folder = daemon.make_scope()
    agents = [
        {"name": "dev", "model": {"account": "fake"}, "default": True},
        {"name": "review", "model": {"account": "echo-box"}},
    ]
    with daemon.http() as c:
        r = c.post("/v1/projects", json={"folder": str(folder), "agents": agents})
        assert r.status_code == 201, r.text
    ids = {a["name"]: a["id"] for a in r.json()["agents"]}
    for name, agent, harness in (
        (None, "dev", "fake"),
        ("echo-box", "review", "echo-box"),
        ("review", "review", "echo-box"),
    ):
        r = handler(daemon, "run", *([name] if name else []), "--detach", cwd=folder)
        assert r.returncode == 0, r.stderr
        session = next(s for s in sessions(daemon) if s["id"] == session_id(r.stdout))
        assert session["agentId"] == ids[agent], name
        assert (session["harness"], session.get("account")) == (harness, harness), name


def test_terminal_client(daemon: Daemon) -> None:
    """The built-in client: the replay, a prompt and its answer, a permission request answered
    with a number, then Ctrl-D detaches and the agent keeps running."""
    here = daemon.make_scope()
    sid = session_id(handler(daemon, "run", "fake", "-p", "hello", "--detach", cwd=here).stdout)
    events(daemon, sid, '"ok"')
    proc = subprocess.Popen(
        [HANDLER, "attach"], cwd=here, env=env(daemon), text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )  # fmt: skip
    assert proc.stdin is not None and proc.stdout is not None
    out: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: [out.put(line) for line in proc.stdout], daemon=True).start()  # ty: ignore[not-iterable]
    seen: list[str] = []

    def expect(text: str) -> None:
        deadline = time.monotonic() + 30
        while not any(text in line for line in seen):
            assert time.monotonic() < deadline, f"{text!r} not in {seen}"
            with contextlib.suppress(queue.Empty):
                seen.append(out.get(timeout=0.5))

    try:
        expect("> Your network goes through Handler's network filter")  # replayed: its first
        expect("hello")  # prompt, what its filtered network means before the request
        proc.stdin.write("report\n")
        proc.stdin.flush()
        expect('"mode": "yolo"')
        proc.stdin.write("permission\n")
        proc.stdin.flush()
        expect("1) Allow")
        proc.stdin.write("1\n")
        proc.stdin.flush()
        expect('"optionId": "yes"')
        proc.stdin.close()
        assert proc.wait(timeout=30) == 0
        expect("detached")
    finally:
        proc.kill()
    assert next(s for s in sessions(daemon) if s["id"] == sid)["state"] == "running"


def test_run_says_why_a_session_did_not_start_and_ends(daemon: Daemon) -> None:
    """A session that cannot start (its account's token in an environment variable handlerd does
    not have): `handler run -p` says why in full, a line and no traceback, and exits 1 instead
    of waiting. Its why is the session's error: the WebSocket close's reason is cut at 120
    characters."""
    here = daemon.make_scope()
    var = "HANDLER_TEST_" + "NOT_SET_" * 16  # long: past what a close's reason can say
    added = handler(daemon, "account", "add", "unset-env", "fake", "--area", "any",
                    "--token-env", var)  # fmt: skip
    assert added.returncode == 0, added.stderr
    try:
        r = subprocess.run(
            [HANDLER, "run", "unset-env", "-p", "hi"], cwd=here, env=env(daemon),
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False,
        )  # fmt: skip
        assert r.returncode == 1, (r.stdout, r.stderr)
        assert f"environment variable {var} is not set" in r.stdout
        assert "Traceback" not in r.stderr, r.stderr
    finally:
        handler(daemon, "account", "rm", "unset-env")


class _Daemon:
    """What the terminal client asks handlerd over HTTP: the session, its error."""

    def __init__(self, error: str | None) -> None:
        self.error = error

    def call(self, method: str, path: str, json: Any = None) -> dict[str, Any]:
        return {"id": "s_1", "error": self.error}


@pytest.mark.parametrize("when", ["at-once", "after-initialize"])
def test_the_terminal_client_ends_when_handlerd_closes_before_the_session_runs(
    when: str,
) -> None:
    """handlerd closes the WebSocket of a session that failed to start (1011, its reason cut at
    120 characters), before or after the client's `initialize`: the client says the session's
    error and returns 1; before, a traceback (the close came first) or a wait until killed."""

    async def refuse(ws: ServerConnection) -> None:
        if when == "after-initialize":
            await ws.recv()
        await ws.close(1011, "environment variable NOPE is n")

    out = io.StringIO()

    async def attach() -> int:
        async with serve(refuse, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            daemon = _Daemon("environment variable NOPE is not set")
            terminal = Terminal(daemon, {"id": "s_1"}, out)  # ty: ignore[invalid-argument-type]
            return await asyncio.wait_for(terminal.run(f"ws://127.0.0.1:{port}", "t"), 10)

    assert asyncio.run(attach()) == 1
    assert "[session closed: environment variable NOPE is not set]" in out.getvalue()


def test_attach_stdio_and_acp_agent_bridge_a_session(daemon: Daemon) -> None:
    """A plain ACP client: session/new is answered with the session's own conversation; the
    daemon's _handler notifications stay out. `handler acp AGENT` does the same with a new session
    of the folder's project, listed like any other."""
    folder = daemon.make_scope()
    project(daemon, folder)
    before = {s["id"] for s in sessions(daemon)}
    proc = subprocess.Popen(
        [HANDLER, "acp", "review"], cwd=folder, env=env(daemon),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )  # fmt: skip
    client = AcpClient.over_process(proc)
    try:
        client.initialize()
        new = client.new_session(str(folder))
        assert new["sessionId"].startswith("s") and new["modes"]["currentModeId"] == "yolo"
        client.prompt(new["sessionId"], "report")
        # the agent's instructions go with the first prompt (F.3)
        assert json.loads(client.text())["prompt"] == [f"Be brief.\n\n{FILTERED_NETWORK}\n\nreport"]
        assert not [u for u in client.updates if str(u.get("method", "")).startswith("_handler/")]
    finally:
        client.close()
    added = [s for s in sessions(daemon) if s["id"] not in before]
    assert len(added) == 1 and added[0].get("projectId")

    proc = subprocess.Popen(
        [HANDLER, "attach", "--stdio", added[0]["id"]], env=env(daemon),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )  # fmt: skip
    client = AcpClient.over_process(proc)
    try:
        client.initialize()
        again = client.new_session(str(folder))
        assert again["sessionId"] == new["sessionId"]
        assert "report" in json.dumps(client.updates)  # the conversation so far, replayed
    finally:
        client.close()

    sid = added[0]["id"]
    assert "shared with your paired devices" in handler(daemon, "session", "share", sid).stdout
    assert next(s for s in sessions(daemon) if s["id"] == sid)["remote"]
    assert "not shared" in handler(daemon, "session", "share", sid, "--off").stdout
    r = handler(daemon, "session", "stop", sid)
    assert r.returncode == 0 and f"handler attach {sid} resumes it" in r.stdout
    assert next(s for s in sessions(daemon) if s["id"] == sid)["state"] == "stopped"
    assert sid not in handler(daemon, "session", "list").stdout
    assert sid in handler(daemon, "session", "list", "--all").stdout
    assert f"handler attach {sid}" in handler(daemon, "session", "show", sid).stdout
    # a stopped session is resumed: restarted with its conversation
    proc = subprocess.Popen(
        [HANDLER, "attach", "--stdio"], cwd=folder, env=env(daemon),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )  # fmt: skip
    client = AcpClient.over_process(proc)
    try:
        client.initialize()
        assert client.new_session(str(folder))["sessionId"] == new["sessionId"]
        assert "report" in json.dumps(client.updates)
    finally:
        client.close()
    assert next(s for s in sessions(daemon) if s["id"] == sid)["state"] == "running"


@pytest.mark.rule("cli.another-area-runs-only-outside-once-confirmed")
def test_anyway_with_an_account_not_for_the_area_is_typed_yes(monkeypatch: Any) -> None:
    """D.19: --anyway in a Work project's folder with a Personal account: the person types yes in
    a terminal; anything else, and no terminal at all, does not start it."""

    class FakeDaemon:
        def call(self, _method: str, path: str) -> list[dict[str, Any]]:
            found = {"/v1/accounts": [{"name": "perso", "areas": ["Personal"]}]}
            return found.get(path, [])

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    project = {"name": "acme", "folder": "/code/acme", "area": "Work"}
    args = argparse.Namespace(cmd="run")
    d: Any = FakeDaemon()
    monkeypatch.setattr("sys.stdin", Terminal())
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    acknowledge_outside(d, project, "perso", args)  # confirmed
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    with pytest.raises(ClientError, match="not started"):
        acknowledge_outside(d, project, "perso", args)
    monkeypatch.setattr("sys.stdin", io.StringIO())
    with pytest.raises(ClientError, match="confirm it in a terminal"):
        acknowledge_outside(d, project, "perso", args)
    acknowledge_outside(d, project | {"area": "Personal"}, "perso", args)  # nothing to confirm


@pytest.mark.rule("cli.a-flag-is-never-ignored")
def test_a_flag_that_differs_is_saved_once_the_person_says_yes(monkeypatch: Any) -> None:
    """In a terminal, handler asks "Save this to the agent?": yes saves it (the lists added to),
    with the agent's other settings and own fields; anything else starts nothing."""
    saved: list[tuple[str, dict[str, Any]]] = []

    class FakeDaemon:
        def call(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
            saved.append((f"{method} {path}", body))
            return body | {"id": "a1"}

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    agent = {
        "id": "a1", "name": "tests", "scope": "/code/x", "model": {"account": "fake",
        "harness": "fake", "requiredHosts": []}, "network": "filtered", "egress": "enforce",
        "allow": ["a.test:443"], "confinement": "strict", "permissions": "bypass",
        "addons": [], "knowledge": [], "display": False, "skills": ["s"],
        "acpUrl": "ws://x", "connections": [],
    }  # fmt: skip
    flags: dict[str, Any] = {"network": None, "log_only": True, "containers": False}
    flags["permissions"] = None
    flags |= {"display": False, "allow": ["b.test:443", "a.test:443"], "tool": None}
    flags["keep_blocked"] = None
    args = argparse.Namespace(**flags, notes=None, save=False)
    d: Any = FakeDaemon()
    monkeypatch.setattr("sys.stdin", Terminal())
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    with pytest.raises(ClientError, match="not started"):
        settle_flags(d, agent, args, None)
    assert saved == []
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    settle_flags(d, agent, args, None)
    [(call, body)] = saved
    assert call == "PUT /v1/agents/a1"
    assert (body["egress"], body["allow"]) == ("log-only", ["a.test:443", "b.test:443"])
    assert body["model"] == {"account": "fake", "harness": "fake"}
    assert (body["name"], body["scope"], body["skills"]) == ("tests", "/code/x", ["s"])
    saved.clear()
    same = argparse.Namespace(**flags | {"log_only": False}, notes=None, save=False)
    assert settle_flags(d, agent | {"allow": ["a.test:443", "b.test:443"]}, same, None)
    assert saved == []  # nothing differs: nothing asked, nothing saved


@pytest.mark.rule("save.a-host-is-allowed-or-kept-blocked")
def test_keep_blocked_and_allow_take_a_host_off_the_other_list() -> None:
    """--keep-blocked adds to the hosts kept blocked and takes them off the allowed ones;
    --allow the reverse (A.3: never both)."""
    agent = {"allow": ["a.test:443", "b.test:443"], "blocked": ["c.test:443"]}
    none = {"network": None, "log_only": False, "containers": False, "permissions": None}
    none |= {"display": False, "tool": None, "notes": None}
    args = argparse.Namespace(**none, allow=None, keep_blocked=["a.test:443"])
    assert flag_changes(agent, args) == (
        {"blocked": ["a.test:443", "c.test:443"], "allow": ["b.test:443"]},
        ["kept blocked + a.test:443"],
    )
    args = argparse.Namespace(**none, allow=["c.test:443"], keep_blocked=None)
    assert flag_changes(agent, args) == (
        {"allow": ["a.test:443", "b.test:443", "c.test:443"], "blocked": []},
        ["allow + c.test:443"],
    )
