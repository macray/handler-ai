"""`handler daemon install`: handlerd as a user service, systemd's on Linux, launchd's on macOS
(here only written and read back: tests do not install services)."""

import os
import plistlib
import pwd
from pathlib import Path

import pytest

from handler_cli import daemon_commands


@pytest.mark.rule("service.starts-with-your-session")
def test_a_systemd_unit_on_linux(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(daemon_commands.sys, "platform", "linux")
    assert daemon_commands.install(dry_run=True) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"# {daemon_commands.unit_path()}")
    assert "ExecStart=" in out and "Restart=on-failure" in out


def _fake_systemctl(folder: Path) -> Path:
    """A `systemctl` that answers `--user show-environment` with $MANAGER_ENV (systemd's user
    manager's own environment) and records every other call in `calls`."""
    folder.mkdir()
    calls = folder / "calls"
    script = folder / "systemctl"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$2" = show-environment ]; then printf %s "$MANAGER_ENV"; exit 0; fi\n'
        f'echo "$@" >> {calls}\n'
    )
    script.chmod(0o755)
    return calls


@pytest.mark.rule(
    "service.starts-with-your-session",
    "service.is-the-handlerd-this-shell-talks-to",
    "service.installed-again-replaces-it",
)
def test_the_unit_goes_where_systemds_user_manager_looks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The user manager has its own environment, not this shell's: the unit goes under its
    XDG_CONFIG_HOME, or its home's `.config`, never under a custom one of this shell (where
    `systemctl --user enable` would not find it); that one is still carried into the unit."""
    monkeypatch.setattr(daemon_commands.sys, "platform", "linux")
    shells = tmp_path / "shells-config"
    managers = tmp_path / "managers config"  # a space: systemctl quotes it $'…'
    calls = _fake_systemctl(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(shells))
    monkeypatch.setenv("MANAGER_ENV", f"HOME={tmp_path}\nXDG_CONFIG_HOME=$'{managers}'\n")

    unit = managers / "systemd" / "user" / "handler-ai.service"
    assert daemon_commands.unit_path() == unit
    assert daemon_commands.install(dry_run=False) == 0
    assert unit.is_file() and not shells.exists()
    assert f'Environment="XDG_CONFIG_HOME={shells}"' in unit.read_text()
    assert daemon_commands.uninstall() == 0
    assert not unit.exists()
    assert calls.read_text().splitlines() == [
        "--user daemon-reload",
        "--user enable --now handler-ai.service",
        "--user disable --now handler-ai.service",
        "--user daemon-reload",
    ]
    capsys.readouterr()

    monkeypatch.setenv("MANAGER_ENV", f"HOME={tmp_path}\nPATH=/usr/bin\n")  # none of its own
    assert daemon_commands.unit_path() == tmp_path / ".config/systemd/user/handler-ai.service"


@pytest.mark.rule("service.starts-with-your-session")
def test_a_launch_agent_on_macos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(daemon_commands.sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert daemon_commands.install(dry_run=True) == 0
    out = capsys.readouterr().out
    path = tmp_path / "Library" / "LaunchAgents" / "ai.handler.handlerd.plist"
    assert out.startswith(f"# {path}\n")
    agent = plistlib.loads(out.split("\n", 1)[1].encode())
    assert agent["Label"] == "ai.handler.handlerd"
    assert agent["ProgramArguments"][0].endswith("handlerd")
    assert agent["RunAtLoad"] and agent["KeepAlive"] == {"SuccessfulExit": False}
    assert "/opt/homebrew/bin" in agent["EnvironmentVariables"]["PATH"]  # brew's podman, docker
    assert agent["StandardErrorPath"] == str(tmp_path / "Library/Logs/handler-ai/handlerd.log")


def _fake_launchctl(folder: Path) -> Path:
    """A `launchctl` that unloads as launchd does: `bootout` returns at once but the job stays
    known (`print` succeeds) until its handlerd has exited, here 0.5 s later; `bootstrap` of a job
    still known fails with launchd's `5: Input/output error`. Each call is recorded in `calls`."""
    folder.mkdir()
    loaded, calls = folder / "loaded", folder / "calls"
    script = folder / "launchctl"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$1" >> {calls}\n'
        "case $1 in\n"
        f"  print) [ -e {loaded} ];;\n"
        f"  bootout) if [ -e {loaded} ]; then (sleep 0.5; rm -f {loaded}) >/dev/null 2>&1 & fi;;\n"
        f"  bootstrap) if [ -e {loaded} ]; then echo 'Bootstrap failed: 5: Input/output error'"
        f" >&2; exit 5; fi; touch {loaded};;\n"
        "esac\n"
    )
    script.chmod(0o755)
    return calls


@pytest.mark.rule("service.installed-again-replaces-it")
def test_setup_run_again_on_macos_leaves_the_launch_agent_loaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`handler setup` run a second time: the new launch agent is bootstrapped once launchd has
    let go of the old one, not while its handlerd is still shutting down (which failed, and left
    no service at all)."""
    monkeypatch.setattr(daemon_commands.sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    calls = _fake_launchctl(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")

    assert daemon_commands.install(dry_run=False) == 0  # the first setup
    assert daemon_commands.install(dry_run=False) == 0  # and again, the old one loaded
    assert (tmp_path / "bin" / "loaded").exists()
    second = calls.read_text().splitlines()[calls.read_text().splitlines().index("bootstrap") + 1 :]
    assert second[0] == "bootout" and second[-1] == "bootstrap"
    assert second.count("print") >= 2  # it waited for launchd
    capsys.readouterr()


@pytest.mark.parametrize("command", ["status", "log"])
def test_without_systemd_a_sentence_not_a_traceback(
    command: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No `systemctl` nor `journalctl` (a container, WSL without systemd), handlerd not running."""
    monkeypatch.setattr(daemon_commands.sys, "platform", "linux")
    monkeypatch.setattr(daemon_commands.shutil, "which", lambda name: None)
    monkeypatch.setenv("HANDLER_URL", "http://127.0.0.1:9")  # nothing listens there
    run = daemon_commands.status if command == "status" else lambda: daemon_commands.log(False)
    assert run() == 1
    assert daemon_commands.NO_SYSTEMD in capsys.readouterr().out


@pytest.mark.rule(
    "service.is-the-handlerd-this-shell-talks-to", "service.never-gets-test-credentials"
)
def test_the_service_gets_the_environment_of_the_shell_that_installs_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A service gets none of the shell's environment: what says where Handler keeps its files
    and listens is written in it, so that it is the handlerd this shell's `handler` talks to;
    the tests' variables (credentials among them) and the CLI's own are not."""
    monkeypatch.setattr(daemon_commands.sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HANDLER_PORT", "7499")
    monkeypatch.setenv("HANDLER_TERMINAL", "kgx --")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HANDLER_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("HANDLER_TEST_OPENAI_API_KEY", "sk-test")
    assert daemon_commands.install(dry_run=True) == 0
    env = plistlib.loads(capsys.readouterr().out.split("\n", 1)[1].encode())["EnvironmentVariables"]
    assert env["HANDLER_PORT"] == "7499" and env["HANDLER_TERMINAL"] == "kgx --"
    assert env["XDG_CONFIG_HOME"] == str(tmp_path / "config")
    assert env["HOME"] == str(tmp_path)  # not the account's home
    assert "HANDLER_URL" not in env and "HANDLER_TEST_OPENAI_API_KEY" not in env

    monkeypatch.setattr(daemon_commands.sys, "platform", "linux")
    monkeypatch.setenv("HOME", pwd.getpwuid(os.getuid()).pw_dir)
    monkeypatch.setenv("HANDLER_TERMINAL", 'my "term" --at 100%')
    assert daemon_commands.install(dry_run=True) == 0
    unit = capsys.readouterr().out
    assert 'Environment="HANDLER_PORT=7499"' in unit
    assert 'Environment="HANDLER_TERMINAL=my \\"term\\" --at 100%%"' in unit
    assert 'Environment="HOME=' not in unit  # the account's own: the service has it


@pytest.mark.rule("service.is-the-handlerd-this-shell-talks-to")
def test_the_service_finds_the_engine_this_shell_finds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Docker Desktop's `docker` only on this shell's PATH (its own folder): on handlerd's too."""
    folder = tmp_path / "Docker.app" / "bin"
    folder.mkdir(parents=True)
    (folder / "docker").write_text("#!/bin/sh\n")
    (folder / "docker").chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}:/usr/bin:/bin")
    path = daemon_commands.service_path("/opt/handler/bin").split(":")
    assert path[0] == "/opt/handler/bin" and str(folder) in path
    assert len(path) == len(set(path))
