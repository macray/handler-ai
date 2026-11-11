"""`handler daemon install`: handlerd as a user service, systemd's on Linux, launchd's on macOS
(here only written and read back: tests do not install services)."""

import os
import plistlib
import pwd
from pathlib import Path

import pytest

from handler_cli import daemon_commands


def test_a_systemd_unit_on_linux(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(daemon_commands.sys, "platform", "linux")
    assert daemon_commands.install(dry_run=True) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"# {daemon_commands.unit_path()}")
    assert "ExecStart=" in out and "Restart=on-failure" in out


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
