"""`handler setup` against a real handlerd (the systemd step left out: tests do not install
services)."""

import argparse

import pytest

from handler_cli import daemon_commands, setup
from handler_control import __version__

from ..support.daemon import Daemon


def test_setup_reports_the_runtime_and_the_toolbox(
    daemon: Daemon, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HANDLER_URL", daemon.base_url)
    monkeypatch.setenv("HANDLER_CONFIG_DIR", str(daemon.config_dir))
    monkeypatch.setattr(daemon_commands, "install", lambda dry_run: 0)
    code = setup.dispatch(argparse.Namespace(no_build=True, yes=False))
    out = capsys.readouterr().out
    assert f"handlerd {__version__} is running at" in out
    assert "podman" in out  # the runtime check (A.8), whatever this machine has
    if code == 0:
        assert f"Your toolbox (the tools every agent gets): {daemon.config_dir}/toolbox" in out
        assert "handler ui" in out
    else:
        assert "FAIL" in out and "run `handler setup` again" in out


def test_setup_stops_when_the_service_cannot_be_installed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_systemctl(dry_run: bool) -> int:
        raise FileNotFoundError("systemctl")

    monkeypatch.setattr(daemon_commands, "install", no_systemctl)
    assert setup.dispatch(argparse.Namespace(no_build=True, yes=False)) == 1
    assert "run `handlerd` yourself" in capsys.readouterr().out
