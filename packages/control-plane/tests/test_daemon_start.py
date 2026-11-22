"""handlerd's start, before it serves: the runtime's engine started, then the sweep."""

import logging
import subprocess
from pathlib import Path
from typing import Any

import pytest

from handler_control import daemon


@pytest.mark.rule("runtime.apple-service-started-with-handlerd")
def test_handlerd_starts_the_runtime_s_engine_then_sweeps_and_logs_what_it_said(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """`start-engine` first (Apple's service, gone after a restart, started before anything
    asks for it), then `sweep` (which needs it); what the runtime said is in handlerd's log."""
    binary = str(tmp_path / "handler-sandbox-apple")
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        said = "handler-sandbox-apple: Apple's container service started\n"
        return subprocess.CompletedProcess(argv, 0, "", said if argv[1] == "start-engine" else "")

    monkeypatch.setattr(daemon.sandbox_process, "binary", lambda: binary)
    monkeypatch.setattr(daemon.subprocess, "run", run)
    with caplog.at_level(logging.INFO, logger="handler.daemon"):
        daemon.prepare_runtime()
    assert calls == [[binary, "start-engine"], [binary, "sweep"]]
    assert "Apple's container service started" in caplog.text
