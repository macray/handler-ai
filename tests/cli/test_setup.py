"""`handler setup` against a real handlerd (the systemd step left out: tests do not install
services)."""

import argparse
import sys
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from handler_cli import cli, daemon_commands, runtime_commands, setup
from handler_cli.client import ClientError
from handler_cli.client import Daemon as Client
from handler_control import __version__

from ..support.daemon import Daemon, _free_port


@pytest.mark.rule("runtime.check-starts-nothing-and-says-why")
def test_setup_reports_the_runtime_and_the_toolbox(
    daemon: Daemon, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HANDLER_URL", daemon.base_url)
    monkeypatch.setenv("HANDLER_CONFIG_DIR", str(daemon.config_dir))
    monkeypatch.setattr(daemon_commands, "install", lambda dry_run: 0)
    code = setup.dispatch(
        argparse.Namespace(
            no_build=True, yes=False, runtime=None, engine=None, program=None, verbose=False
        )
    )
    out = capsys.readouterr().out
    assert f"handlerd {__version__} is running at" in out
    assert "podman" in out  # the runtime check (A.8), whatever this machine has
    if code == 0:
        assert f"Your toolbox (the system every agent works in): {daemon.config_dir}/toolbox" in out
        assert "system packages: podman, wl-clipboard" in out
        assert "handler ui" in out
    else:
        assert "FAIL" in out and "run `handler setup` again" in out


def test_the_engine_of_agents_that_run_containers_is_chosen(
    daemon: Daemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B.6, Q4: the system packages giving an engine, podman first (the default); choosing docker
    turns podman off. `handler setup` asks it before the first build only."""
    monkeypatch.setenv("HANDLER_URL", daemon.base_url)
    monkeypatch.setenv("HANDLER_CONFIG_DIR", str(daemon.config_dir))
    d = Client()
    assert setup.engines(d) == ["podman", "docker"]
    on = ["podman", "wl-clipboard"]
    try:
        chosen = setup._engine(d, argparse.Namespace(engine="docker", yes=False), on)
        assert chosen == ["wl-clipboard", "docker"]  # one already on keeps its place (B.7)
        kept = setup._engine(d, argparse.Namespace(engine=None, yes=True), chosen)
        assert kept == chosen  # nothing asked, nothing changed
    finally:  # the module's daemon: the default again
        d.call("PUT", "/v1/toolbox/system-packages", {"systemPackages": on})


def test_setup_without_systemd_goes_on_with_the_running_handlerd(
    daemon: Daemon, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No systemd user session (a server, `su`, a container): the handlerd started by hand."""

    def no_systemctl(dry_run: bool) -> int:
        raise FileNotFoundError("systemctl")

    monkeypatch.setenv("HANDLER_URL", daemon.base_url)
    monkeypatch.setenv("HANDLER_CONFIG_DIR", str(daemon.config_dir))
    monkeypatch.setattr(daemon_commands, "install", no_systemctl)
    monkeypatch.setattr(daemon_commands, "macos", lambda: False)
    setup.dispatch(
        argparse.Namespace(
            no_build=True, yes=False, runtime=None, engine=None, program=None, verbose=False
        )
    )
    out = capsys.readouterr().out
    assert "systemd failed" in out and f"handlerd {__version__} is running at" in out
    assert "podman" in out  # the machine check
    assert out.rstrip().endswith("Keep `handlerd` running: sessions live as long as it does.")


def test_setup_without_launchd_goes_on_with_the_running_handlerd(
    daemon: Daemon, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Mac whose launchd refuses the agent: the setup goes on through the handlerd started by
    hand, as without systemd, instead of stopping before the check and the images."""
    reached: list[str] = []

    def rest_of_setup(d: Client, args: argparse.Namespace) -> int:
        reached.append(d.call("GET", "/v1/health")["version"])
        return 0

    monkeypatch.setenv("HANDLER_URL", daemon.base_url)
    monkeypatch.setenv("HANDLER_CONFIG_DIR", str(daemon.config_dir))
    monkeypatch.setattr(daemon_commands, "install", lambda dry_run: 1)
    monkeypatch.setattr(daemon_commands, "macos", lambda: True)
    monkeypatch.setattr(setup, "_setup", rest_of_setup)
    code = setup.dispatch(
        argparse.Namespace(
            no_build=True, yes=False, runtime=None, engine=None, program=None, verbose=False
        )
    )
    out = capsys.readouterr().out
    assert code == 0 and reached == [__version__]
    assert "launchd failed: it only keeps handlerd running as a user service." in out
    assert out.rstrip().endswith("Keep `handlerd` running: sessions live as long as it does.")


@pytest.mark.rule("runtime.check-starts-nothing-and-says-why")
def test_setup_without_systemd_checks_through_a_handlerd_of_its_own(
    daemon: Daemon,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No handlerd running: one started for the machine check alone, stopped after it."""
    port = _free_port()
    own = {k: str(tmp_path / k) for k in ("config", "state", "data", "cache", "run")}
    env = daemon.env | {
        "HANDLER_PORT": str(port),
        "HANDLER_CONFIG_DIR": own["config"],
        "HANDLER_STATE_DIR": own["state"],
        "HANDLER_DATA_DIR": own["data"],
        "HANDLER_CACHE_DIR": own["cache"],
        "HANDLER_RUNTIME_DIR": own["run"],
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("HANDLER_URL", raising=False)
    monkeypatch.setattr(daemon_commands, "install", lambda dry_run: 1)
    monkeypatch.setattr(daemon_commands, "macos", lambda: False)
    monkeypatch.setattr(daemon_commands, "wsl", lambda: False)
    assert (
        setup.dispatch(
            argparse.Namespace(
                no_build=True, yes=False, runtime=None, engine=None, program=None, verbose=False
            )
        )
        == 1
    )
    out = capsys.readouterr().out
    assert "Starting handlerd for the machine check" in out
    assert "podman" in out  # the machine check
    assert "Start `handlerd` yourself and keep it running" in out
    with pytest.raises(httpx.ConnectError):  # stopped after the check
        httpx.get(f"http://127.0.0.1:{port}/v1/health")


def test_setup_says_how_to_turn_systemd_on_in_wsl(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(daemon_commands, "install", lambda dry_run: 1)
    monkeypatch.setattr(daemon_commands, "macos", lambda: False)
    monkeypatch.setattr(daemon_commands, "wsl", lambda: True)
    monkeypatch.setattr(setup, "_without_service", lambda args: 1)
    assert (
        setup.dispatch(
            argparse.Namespace(
                no_build=True, yes=False, runtime=None, engine=None, program=None, verbose=False
            )
        )
        == 1
    )
    assert "systemd=true" in capsys.readouterr().out


def test_runtime_list_says_why_sandboxes_cannot_run(capsys: pytest.CaptureFixture[str]) -> None:
    """`handler runtime list`: the required items failing, not a pointer to `handler setup`."""
    item = {"name": "network", "ok": False, "required": True, "detail": "install passt"}
    warned = {"name": "display", "ok": False, "required": False, "detail": "no Wayland"}
    runtime_commands.print_supports({"runtime": "podman", "ok": False, "items": [item, warned]})
    assert capsys.readouterr().out == "it cannot run sandboxes here:\n  network: install passt\n"


class FakeBuilds:
    """handlerd's side of a first setup, in memory: nothing built; each build started goes
    through its stages, a few log lines each, then succeeds."""

    PROGRAMS = [
        ("claude-code", "Claude Code"),
        ("codex", "Codex"),
        ("pi", "pi"),
        ("vibe", "Mistral Vibe"),
    ]

    def __init__(self) -> None:
        self.started: list[str] = []
        self.built: set[str] = set()
        self.builds: dict[str, dict[str, Any]] = {}
        self.read: dict[str, int] = {}

    def stages(self, target: str) -> list[str]:
        return ["build toolbox", "check toolbox", "switch"] if target == "toolbox" else [
            f"build {target}", f"check {target}", "switch"
        ]  # fmt: skip

    def call(self, method: str, path: str, body: Any = None) -> Any:
        answers = {
            "/v1/runtime": {"runtime": "podman", "ok": True, "items": []},
            "/v1/runtimes": [{"name": "podman", "current": True, "check": None}],
            "/v1/network-filter": {"imagePresent": True},
            "/v1/toolbox": {
                "imagePresent": "toolbox" in self.built,
                "directory": "/t",
                "systemPackages": [{"name": "podman"}],
            },
            "/v1/toolbox/system-packages": [],
            "/v1/harnesses": [
                {"name": n, "product": p, "imagePresent": n in self.built} for n, p in self.PROGRAMS
            ],
        }
        if path in answers:
            return answers[path]
        if method == "POST" and path.endswith("/rebuild"):
            target = path.removeprefix("/v1/").removesuffix("/rebuild").removeprefix("harnesses/")
            self.started.append(target)
            build: dict[str, Any] = {
                "id": f"b{len(self.started)}",
                "target": target,
                "state": "running",
            }
            build |= {"harnesses": [] if target == "toolbox" else [target], "addons": []}
            self.builds[build["id"]] = build
            self.read[build["id"]] = 0
            return build
        build_id = path.split("/")[3].split("?", maxsplit=1)[0]
        build = self.builds[build_id]
        stages = self.stages(build["target"])
        if path.endswith(f"/{build_id}"):
            return build
        n = self.read[build_id]  # a log read: the next stage's lines
        self.read[build_id] = n + 1
        build["stage"] = stages[min(n, len(stages) - 1)]
        complete = n + 1 >= len(stages)
        if complete:
            build |= {"state": "succeeded", "stage": None}
            self.built.add(build["target"])
        text = f"STEP 1/2: {stages[n]} for {build['target']}\nnpm warn using --force\n"
        return {"text": text, "nextOffset": n + 1, "complete": complete}


def _first_setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *flags: str) -> FakeBuilds:
    fake = FakeBuilds()
    monkeypatch.setenv("HANDLER_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail(f"asked: {prompt}"))
    args = cli.parser().parse_args(["setup", *flags])
    code = setup._setup(cast(Client, fake), args)
    assert code == 0
    return fake


def test_setup_builds_the_toolbox_and_the_program_chosen_quietly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D.4: a first setup builds the toolbox, then the agent program chosen, and no other; one
    line per image with its time estimate, the log in the file it names, not on the terminal.

    If this fails: a newcomer waits for (and stores) four agent programs to use one, or reads a
    thousand lines of build log to learn it worked."""
    fake = _first_setup(monkeypatch, tmp_path, "--yes", "--program", "codex")
    out = capsys.readouterr().out
    assert fake.started == ["toolbox", "codex"]
    assert "toolbox 1/2 · ~3 min\n" in out and "Codex 2/2 · ~2 min\n" in out
    assert "STEP" not in out and "npm warn" not in out
    logs = sorted((tmp_path / "build-logs").iterdir())
    assert [p.name for p in logs] == ["b1.log", "b2.log"]
    assert f"The full log: {logs[0]}" in out
    assert "STEP 1/2: build codex for codex" in logs[1].read_text()
    assert "Codex is ready. The other agent programs are built when an agent needs one" in out


def test_setup_builds_claude_code_with_yes_and_streams_with_verbose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = _first_setup(monkeypatch, tmp_path, "--yes", "--verbose")
    out = capsys.readouterr().out
    assert fake.started == ["toolbox", "claude-code"]
    assert "STEP 1/2: build toolbox for toolbox" in out and "npm warn using --force" in out
    assert "1/2 ·" not in out and not (tmp_path / "build-logs").exists()


def test_setup_asks_which_program_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """On a terminal without --yes: the program asked (by its name or the vendor's product
    name), then the build with its size."""
    fake = FakeBuilds()
    asked: list[str] = []
    answers = iter(["mistral vibe", ""])
    monkeypatch.setenv("HANDLER_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or next(answers))
    assert setup._setup(cast(Client, fake), cli.parser().parse_args(["setup"])) == 0
    assert "Which agent program first? Claude Code (claude-code), Codex (codex)" in asked[0]
    assert "The toolbox, then Mistral Vibe: about 1 GB" in asked[1]
    assert fake.started == ["toolbox", "vibe"]
    fake.started.clear()
    assert setup._setup(cast(Client, fake), cli.parser().parse_args(["setup"])) == 0
    assert fake.started == [] and "agent programs built: Mistral Vibe" in capsys.readouterr().out


def test_setup_says_what_it_leaves_to_other_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Once the toolbox and a program are built, setup builds nothing more: --program and
    --engine are not ignored without a word, setup names the commands that do them.

    If this fails: `handler setup --program codex --engine docker` after a setup says "Done."
    and nothing changed."""

    class WithEngines(FakeBuilds):
        def call(self, method: str, path: str, body: Any = None) -> Any:
            if path == "/v1/toolbox/system-packages":
                return [{"name": n, "provides": [n]} for n in ("podman", "docker")]
            return super().call(method, path, body)

    fake = WithEngines()
    fake.built = {"toolbox", "claude-code"}
    _ = setup._setup(
        cast(Client, fake),
        cli.parser().parse_args(["setup", "--program", "codex", "--engine", "docker"]),
    )
    out = capsys.readouterr().out
    assert fake.started == []
    assert (
        "--engine docker: the toolbox is built, setup leaves it as it is: "
        "`handler toolbox add docker`, then `handler toolbox rm podman`." in out
    )
    assert "--program codex: setup builds the first one only; " in out
    assert "`handler image rebuild codex` builds Codex." in out
    # a program built already, the engine already the only one: nothing to say
    _ = setup._setup(
        cast(Client, fake),
        cli.parser().parse_args(["setup", "--program", "claude-code", "--engine", "podman"]),
    )
    assert "--program" not in (out := capsys.readouterr().out) and "--engine" not in out


class FakeRuntimes:
    """handlerd's side of the runtime's choice, in memory: a fresh Mac with Apple container in use
    (not started), Docker running, and a runtime whose check fails; `busy` PUTs refused while
    handlerd's own build of the network filter runs."""

    def __init__(self, busy: int = 0) -> None:
        self.current = "apple"
        self.busy = busy
        self.calls: list[tuple[str, str]] = []

    def call(self, method: str, path: str, body: Any = None) -> Any:
        self.calls.append((method, path))
        if path == "/v1/toolbox":
            return {"imagePresent": False}
        if path == "/v1/builds":  # running until asked `busy` times
            running = self.busy > 0
            self.busy -= running
            return [{"target": "network-filter", "state": "running" if running else "succeeded"}]
        if path == "/v1/runtimes":
            stopped = {"name": "container service", "ok": False, "required": True,
                       "detail": "not running: `container system start`"}  # fmt: skip
            vm = {"isolation": "a container in the virtual machine Docker runs"}
            return [
                {"name": "apple", "current": self.current == "apple",
                 "check": {"ok": False, "items": [stopped]}},
                {"name": "docker", "current": self.current == "docker",
                 "check": {"ok": True, "items": [], "supports": vm}},
                {"name": "other", "current": False, "check": {"ok": False, "items": []}},
            ]  # fmt: skip
        assert (method, path) == ("PUT", "/v1/runtime")
        if self.busy:
            raise ClientError("sandboxes running", status=409)
        self.current = body["name"]
        return {}


def _choose(
    monkeypatch: pytest.MonkeyPatch, fake: FakeRuntimes, answer: str | None, *flags: str
) -> list[str]:
    """`handler setup`'s runtime step on a Mac's terminal; the questions asked."""
    asked: list[str] = []

    def reply(prompt: str) -> str:
        asked.append(prompt)
        assert answer is not None, f"asked: {prompt}"
        return answer

    monkeypatch.setattr(daemon_commands, "macos", lambda: True)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", reply)
    monkeypatch.setattr(setup.time, "sleep", lambda s: None)
    setup._choose_runtime(cast(Client, fake), cli.parser().parse_args(["setup", *flags]))
    return asked


@pytest.mark.rule("runtime.proposed-by-setup-on-macos")
def test_a_mac_s_first_setup_asks_where_agents_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Before the first build: the runtime in use first (Enter keeps it), then each other one
    whose check passes, each with what a sandbox is there or why it cannot run yet.

    If this fails: a Mac user's first setup fails on a runtime they never chose, or they must know
    `handler runtime use` first."""
    fake = FakeRuntimes()
    assert _choose(monkeypatch, fake, "") == ["[apple/docker] (apple) "]
    out = capsys.readouterr().out
    assert "  apple: not ready here (not running: `container system start`)\n" in out
    assert "  docker: each sandbox is a container in the virtual machine Docker runs\n" in out
    assert "other" not in out and fake.current == "apple"
    assert _choose(monkeypatch, fake, "docker") and fake.current == "docker"
    fake.current = "apple"
    with pytest.raises(ClientError, match="'other' is not offered here"):
        _choose(monkeypatch, fake, "other")


@pytest.mark.rule("runtime.proposed-by-setup-on-macos")
def test_a_runtime_chosen_waits_for_handlerd_s_first_build(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """handlerd builds the network filter as it starts; another runtime is used once that build
    ends (a runtime changes only while nothing runs)."""
    fake = FakeRuntimes(busy=2)
    _choose(monkeypatch, fake, "docker")
    assert fake.current == "docker" and fake.calls.count(("PUT", "/v1/runtime")) == 3
    assert capsys.readouterr().out.count("Waiting for the build running now to end") == 1


@pytest.mark.rule("runtime.proposed-by-setup-on-macos")
def test_the_runtime_is_asked_only_on_a_mac_s_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """--yes keeps the one in use, --runtime chooses without asking (on any system), and Linux
    is never asked."""
    fake = FakeRuntimes()
    _choose(monkeypatch, fake, None, "--yes")
    assert fake.current == "apple" and fake.calls == []
    _choose(monkeypatch, fake, None, "--runtime", "docker")
    assert fake.current == "docker" and fake.calls == [("PUT", "/v1/runtime")]
    fake.current, fake.calls = "apple", []
    monkeypatch.setattr(daemon_commands, "macos", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail(f"asked: {prompt}"))
    setup._choose_runtime(cast(Client, fake), cli.parser().parse_args(["setup"]))
    assert fake.current == "apple" and fake.calls == []
