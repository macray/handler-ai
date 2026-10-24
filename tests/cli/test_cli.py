"""The `handler` CLI against a real handlerd — including `handler acp`, the stdio bridge editors
use."""

import contextlib
import fcntl
import json
import os
import pty
import struct
import subprocess
import sys
import termios
import tomllib
from pathlib import Path

from ..support.acp_client import AcpClient
from ..support.daemon import Daemon

HANDLER = str(Path(sys.executable).parent / "handler")


def env(daemon: Daemon) -> dict[str, str]:
    return os.environ | {
        "HANDLER_URL": daemon.base_url,
        "HANDLER_CONFIG_DIR": str(daemon.config_dir),
    }


def handler(
    daemon: Daemon, *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [HANDLER, *args],
        env=env(daemon),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_daemon_status_and_images(daemon: Daemon) -> None:
    assert "up at" in handler(daemon, "daemon", "status").stdout
    listed = handler(daemon, "image", "list").stdout
    names = [line.split()[0] for line in listed.splitlines()[1:]]
    assert names[0] == "toolbox" and "claude-code" in names and names[-1] == "network-filter"


def test_image_commands_report_errors(daemon: Daemon) -> None:
    """The real rebuild flow is covered by tests/harness/test_rebuild.py."""
    r = handler(daemon, "image", "rebuild", "nope")
    assert r.returncode == 1 and "404 harness not found" in r.stderr


def run(daemon: Daemon, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """`handler run … --detach` in `cwd`: an ad-hoc agent there, and a session on it."""
    return handler(daemon, "run", *args, "--detach", cwd=cwd)


def agent_row(daemon: Daemon, scope: Path) -> str:
    """The line of `handler agent list` of the agent working in `scope`."""
    listed = handler(daemon, "agent", "list").stdout.splitlines()
    return next(line for line in listed if line.rstrip().endswith(str(scope)))


def test_run_makes_an_ad_hoc_agent_in_the_current_directory(daemon: Daemon) -> None:
    scope = daemon.make_scope()
    r = run(daemon, "fake", cwd=scope)
    assert r.returncode == 0, r.stderr
    row = agent_row(daemon, scope)
    assert "outside projects" in row and "fake · account fake" in row
    agent_id = row.split()[0]
    shown = handler(daemon, "agent", "show", agent_id).stdout
    assert agent_id in shown and "fake · account fake" in shown and str(scope) in shown
    assert handler(daemon, "agent", "rm", agent_id).returncode == 0
    assert agent_id not in handler(daemon, "agent", "list").stdout


def test_agent_options_and_list(daemon: Daemon) -> None:
    scope = daemon.make_scope()
    r = run(
        daemon, "fake", "--name", "api",
        "--allow", "a.test:443", "--containers", "--permissions", "ask", "--log-only", cwd=scope,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    # the flags that widen it confirm it (D.8), said on stderr
    assert "this agent gets log only" in r.stderr and "runs containers" in r.stderr
    row = agent_row(daemon, scope)
    assert "api" in row and "network=filtered/log-only +1 hosts" in row and "containers" in row
    assert "permissions=ask" in row


def test_agent_network_lists_connections_and_switches_live(daemon: Daemon) -> None:
    agent_id = daemon.create_ad_hoc("fake", daemon.make_scope())["id"]  # filtered, enforced
    assert handler(daemon, "agent", "network", agent_id).stdout.startswith(
        "network filtered, enforce"
    )
    r = handler(daemon, "agent", "network", agent_id, "log-only")
    assert r.stdout.strip() == f"agent {agent_id}: network filtered, log-only"
    assert handler(daemon, "agent", "network", agent_id).stdout.startswith(
        "network filtered, log-only"
    )


def test_the_same_command_in_the_same_folder_gives_the_same_agent(daemon: Daemon) -> None:
    """Outside projects an agent is its folder and --name (D.1): another account is that
    agent's model this time, never another agent; a flag that differs from its settings is
    saved to it (--save without a terminal) or nothing starts; --name makes another agent."""
    scope = daemon.make_scope()
    assert run(daemon, "fake", cwd=scope).returncode == 0
    agent_id = agent_row(daemon, scope).split()[0]
    r = run(daemon, "echo-box", cwd=scope)
    assert r.returncode == 0, r.stderr
    with daemon.http() as c:
        sid = next(w for w in r.stdout.split() if w.startswith("s_"))
        session = c.get(f"/v1/sessions/{sid}").json()
    assert (session["agentId"], session["account"]) == (agent_id, "echo-box")
    r = run(daemon, "fake", "--network", "open", cwd=scope)
    assert r.returncode == 1 and "network filtered → open" in r.stderr
    r = run(daemon, "fake", "--network", "open", "--save", cwd=scope)
    assert r.returncode == 0, r.stderr
    assert "this agent gets an open network" in r.stderr
    assert run(daemon, "fake", cwd=scope).returncode == 0  # no flag: its settings, as saved
    assert run(daemon, "fake", "--name", "try", cwd=scope).returncode == 0
    listed = handler(daemon, "agent", "list").stdout.splitlines()
    rows = [line for line in listed if str(scope) in line]
    assert len(rows) == 2 and any(row.startswith(agent_id) and "open" in row for row in rows)


def test_a_provider_runs_the_harness_that_speaks_it(daemon: Daemon) -> None:
    """A provider: --harness, or the only harness speaking its protocol; --model one of its."""
    (daemon.providers_dir / "local.toml").write_text(
        'apiVersion = "handler.provider/v1"\n[endpoints]\nopenai-chat = "http://127.0.0.1:3000/v1"\n'
        '[[models]]\nid = "m1"\n'
    )
    scope = daemon.make_scope()
    r = run(daemon, "local", cwd=scope)
    assert r.returncode == 1 and "which harness for provider 'local'?" in r.stderr
    r = run(daemon, "local", "--harness", "pi", "--model", "m1", cwd=scope)
    assert r.returncode == 0, r.stderr
    assert "pi · provider local · m1" in agent_row(daemon, scope)
    r = run(daemon, "nope", cwd=scope)
    assert r.returncode == 1 and "no account or provider 'nope'" in r.stderr
    (daemon.providers_dir / "local.toml").unlink()


def test_errors_are_readable(daemon: Daemon, tmp_path: Path) -> None:
    r = run(daemon, "fake", cwd=tmp_path)
    assert r.returncode == 1 and "403 scope not allowed" in r.stderr
    bad = subprocess.run(
        [HANDLER, "image", "list"], env=env(daemon) | {"HANDLER_URL": "http://127.0.0.1:1"},
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert bad.returncode == 1 and "not reachable" in bad.stderr


def test_acp_bridge_behaves_like_an_agent_on_stdio(daemon: Daemon) -> None:
    scope = daemon.make_scope()
    proc = subprocess.Popen(
        [HANDLER, "acp", "fake"], cwd=scope, env=env(daemon),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )  # fmt: skip
    client = AcpClient.over_process(proc)
    try:
        client.initialize({"fs": {"readTextFile": True, "writeTextFile": True}, "terminal": True})
        session = client.new_session(str(scope))
        assert session["modes"]["currentModeId"] == "yolo"  # P7 through the bridge
        client.prompt(session["sessionId"], "report")
    finally:
        client.close()
    seen = json.loads(client.text())
    assert seen["capabilities"]["terminal"] is False  # P1 through the bridge
    assert proc.returncode == 0


def test_service_unit(daemon: Daemon) -> None:
    unit = handler(daemon, "daemon", "install", "--dry-run").stdout
    assert "ExecStart=" in unit and unit.rstrip().endswith("WantedBy=default.target")
    # handlerd finds handler-sandbox-* next to itself
    assert str(Path(sys.executable).parent) in unit


def test_addons_bindings_and_selection(daemon: Daemon) -> None:
    """The official source's addons (fake-shop) through the CLI; images: tests/addons."""
    assert "fake-shop" in handler(daemon, "addon", "list").stdout
    bindings = daemon.config_dir / "bindings"
    bindings.mkdir(exist_ok=True)
    (bindings / "shop.toml").write_text(
        'apiVersion = "handler.binding/v1"\naddon = "fake-shop"\n'
        'settings = { store = "dev.shop.example.com" }\n'
        'secrets = { theme_token = { env = "HANDLER_TEST_UNUSED" } }\n'
    )
    (bindings / "broken.toml").write_text('apiVersion = "handler.binding/v1"\naddon = "nope"\n')
    listed = handler(daemon, "binding", "list").stdout
    assert "store=dev.shop.example.com" in listed and "theme_token" in listed
    assert "unknown addon 'nope'" in listed

    scope = daemon.make_scope()
    r = run(daemon, "fake", "--binding", "nope", cwd=scope)
    assert r.returncode == 1 and "400 bindings unusable" in r.stderr and "unknown" in r.stderr
    r = run(daemon, "fake", "--binding", "shop", cwd=scope)
    assert r.returncode == 0, r.stderr
    assert "bindings=shop" in agent_row(daemon, scope)

    r = handler(daemon, "image", "rebuild", "addon:nope")
    assert r.returncode == 1 and "404 addon image not found" in r.stderr


def test_project_list_and_show(daemon: Daemon) -> None:
    folder = daemon.make_scope()
    agents = [
        {"model": {"account": "fake"}, "name": "dev"},
        {"model": {"account": "fake"}, "name": "review", "default": True},
    ]
    with daemon.http() as c:
        body = {"folder": str(folder), "name": "shop", "agents": agents}
        assert c.post("/v1/projects", json=body).status_code == 201
    listed = handler(daemon, "project", "list").stdout
    row = next(line.split() for line in listed.splitlines() if line.startswith("shop "))
    assert row[1:] == ["-", "review,", "dev", str(folder)]  # no area; the default agent first
    out = handler(daemon, "project", "show", "shop").stdout
    assert out.splitlines()[0] == f"shop · {folder}"
    rows = [line.split() for line in out.splitlines()[2:] if line.startswith(("review", "dev"))]
    assert [r[0] for r in rows] == ["review", "dev"] and rows[0][1] == "*"
    r = handler(daemon, "project", "show", "nope")
    assert r.returncode == 1 and "no project 'nope'" in r.stderr


def test_project_agents_exported_and_imported(daemon: Daemon, tmp_path: Path) -> None:
    """D.23: a project's agents written as a file (what of yours is left out said), then read
    again: the address of the web UI's set-up page printed."""
    folder = daemon.make_scope()
    agents = [{"model": {"account": "fake"}, "name": "dev", "bindings": ["browser"]}]
    with daemon.http() as c:
        body = {"folder": str(folder), "name": "My kit", "agents": agents}
        assert c.post("/v1/projects", json=body).status_code == 201
    out = tmp_path / "kit.zip"
    r = handler(daemon, "project", "export-agents", "My kit", "-o", str(out))
    assert r.returncode == 0, r.stderr
    assert f"wrote {out}: dev" in r.stdout
    assert "account fake" in r.stdout and "addon configuration browser" in r.stdout
    r = handler(daemon, "project", "import-agents", str(out))
    assert r.returncode == 0, r.stderr
    assert "&then=/setup/my-kit" in r.stdout
    with daemon.http() as c:
        assert c.get("/v1/agents-files/my-kit").json()["agents"][0]["part"] == "dev"
    r = handler(daemon, "project", "import-agents", str(tmp_path / "nope.zip"))
    assert r.returncode == 1 and "no such file" in r.stderr


def test_secret_set_list_rm(daemon: Daemon) -> None:
    """D.14: the value is read from stdin and never printed back."""
    path, value = "bindings/demo/token", "tok-not-a-real-one"
    r = subprocess.run(
        [HANDLER, "secret", "set", path, "--description", "demo"],
        input=value + "\n",
        env=env(daemon),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert f"{path}: set" in r.stdout
    listed = handler(daemon, "secret", "list")
    assert path in listed.stdout and "demo" in listed.stdout and value not in listed.stdout
    assert handler(daemon, "secret", "rm", path).returncode == 0
    assert handler(daemon, "secret", "rm", path).returncode != 0  # 404


def test_provider_from_a_template_and_areas(daemon: Daemon) -> None:
    templates = handler(daemon, "provider", "templates").stdout
    assert "llamacpp" in templates and "openrouter" in templates
    with daemon.http() as c:
        assert c.post("/v1/areas", json={"name": "Lab", "color": "blue"}).status_code == 201
    r = handler(
        daemon, "provider", "add", "local", "--from", "llamacpp", "--model", "tiny",
        "--endpoint", "openai-chat=http://host.containers.internal:8080/v1", "--area", "Lab",
    )  # fmt: skip
    assert r.returncode == 0 and "local: created" in r.stdout, r.stderr
    with daemon.http() as c:
        made = next(p for p in c.get("/v1/providers").json() if p["name"] == "local")
    assert [m["id"] for m in made["models"]] == ["tiny"] and made["areas"] == ["Lab"]
    assert made["endpoints"]["openai-chat"] == "http://host.containers.internal:8080/v1"
    assert "codex" in made["files"]  # the template's config files come with it
    row = next(line for line in handler(daemon, "provider", "list").stdout.splitlines()
               if line.startswith("local "))  # fmt: skip
    assert "tiny" in row and "Lab" in row
    r = handler(daemon, "provider", "add", "router", "--from", "openrouter")
    assert r.returncode == 1 and "openrouter needs a key: add --key" in r.stderr
    assert handler(daemon, "provider", "rm", "local").returncode == 0
    assert "local " not in handler(daemon, "provider", "list").stdout

    r = handler(daemon, "account", "add", "lab", "codex", "--area", "Lab")
    assert r.returncode == 0, r.stderr
    row = next(line for line in handler(daemon, "account", "list").stdout.splitlines()
               if line.startswith("lab "))  # fmt: skip
    assert "Lab" in row
    assert handler(daemon, "account", "rm", "lab").returncode == 0


def test_account_add_import_rm(daemon: Daemon, tmp_path: Path) -> None:
    """D.9: a file login imported from this machine; a token login given by the person: read from
    stdin, or where they keep it (a file, a command); handler never runs a token login."""
    assert handler(daemon, "account", "add", "plus", "codex").returncode == 0
    auth = tmp_path / "auth.json"
    auth.write_text('{"tokens": {}}')
    r = handler(daemon, "account", "import", "plus", str(auth))
    assert r.returncode == 0 and "plus: logged in" in r.stdout, r.stderr
    assert "plus" in handler(daemon, "account", "list").stdout
    r = handler(daemon, "account", "add", "perso", "claude-code", "--plan", "max")
    assert r.returncode == 0, r.stderr
    assert "run `claude setup-token`, then: handler account token perso" in r.stdout
    assert "claude-code  max   not logged in" in handler(daemon, "account", "list").stdout
    r = handler(daemon, "account", "login", "perso")
    assert r.returncode == 1 and "run `claude setup-token`" in r.stdout  # not run by handler
    r = subprocess.run(
        [HANDLER, "account", "token", "perso"],
        input="sk-ant-oat01-not-real\n",
        env=env(daemon),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0 and "perso: logged in" in r.stdout, r.stderr
    assert "token in handler, until 20" in handler(daemon, "account", "list").stdout  # a year
    kept = tmp_path / "token"
    kept.write_text("sk-ant-oat01-kept-by-me\n")
    r = handler(daemon, "account", "add", "pro", "claude-code", "--token-file", str(kept))
    assert r.returncode == 0 and "pro: logged in" in r.stdout, r.stderr
    pro = tomllib.loads((daemon.accounts_dir / "pro.toml").read_text())
    assert pro["token"] == {"file": str(kept)}
    r = handler(daemon, "account", "token", "perso", "--command", "pass show claude-perso")
    assert r.returncode == 0, r.stderr
    perso = tomllib.loads((daemon.accounts_dir / "perso.toml").read_text())
    assert perso["token"] == {"command": ["pass", "show", "claude-perso"]}
    store = json.loads((daemon.data_dir / "secrets.json").read_text())
    assert "accounts/perso/token" not in store  # the pasted one is forgotten
    assert "token from a command" in handler(daemon, "account", "list").stdout
    for name in ("plus", "perso", "pro"):
        assert handler(daemon, "account", "rm", name).returncode == 0


def test_account_login_runs_on_this_computer(daemon: Daemon) -> None:
    """D.9: `handler account login` runs the harness's login here, on a terminal of its own (it
    checks), relayed to this one; the file it leaves in its folder becomes the account's login."""
    r = subprocess.run(
        [HANDLER, "account", "login", "login-box"],
        input="cli-code\n",
        env=env(daemon),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "code?" in r.stdout and "login-box: logged in" in r.stdout
    assert (daemon.data_dir / "accounts" / "login-box" / "credential").read_text() == "cli-code\n"


def test_terminal_runs_the_harness_s_terminal_program(daemon: Daemon) -> None:
    """D.16: what follows `--` goes to the program, after its settings' flags; its exit code is
    handler's. Stdin is piped here: its lines still reach the program (the terminal itself:
    tests/control/test_terminal_endpoint.py)."""
    scope = daemon.make_scope()
    r = subprocess.run(
        [HANDLER, "terminal", "fake", "--model", "big-model", "--", "--resume", "x"],
        env=env(daemon) | {"TERM": "xterm-test"},
        cwd=scope,
        input="hello\nquit\n",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 3, r.stdout + r.stderr
    # who it runs as, said before it starts: the harness's terminal cannot tell
    assert "handler: fake · account fake" in r.stderr
    assert "subscription, plan not set in the account" in r.stderr
    assert "TERM=xterm-test" in r.stdout
    assert "args:--yolo --model big-model --resume x" in r.stdout
    assert "got:hello" in r.stdout


def test_terminal_reports_what_cannot_run(daemon: Daemon) -> None:
    r = handler(daemon, "terminal", "echo-box", str(daemon.make_scope()))
    assert r.returncode == 1 and "has no terminal program" in r.stderr


def test_account_login_on_a_terminal(daemon: Daemon) -> None:
    """The same from a terminal (raw while the login runs): what is typed reaches the login's
    own terminal, which has this one's size."""
    pid, master = pty.fork()
    if pid == 0:
        os.execve(HANDLER, [HANDLER, "account", "login", "login-box"], env(daemon))
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 90, 0, 0))
    output = b""
    with contextlib.suppress(OSError):  # EIO once it is gone
        while chunk := os.read(master, 4096):
            output += chunk
            if output.endswith(b"code? "):
                os.write(master, b"tty-code\r")
    _, status = os.waitpid(pid, 0)
    os.close(master)
    assert os.waitstatus_to_exitcode(status) == 0, output
    assert b"login-box: logged in" in output
    kept = daemon.data_dir / "accounts" / "login-box" / "credential"
    assert kept.read_text() == "tty-code\n"
