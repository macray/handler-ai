"""`launch.run`: its exit code is its program's, unless its engine's start failed for a reason
the runtime can tell the person; on a terminal (`tty`), that start is `attach`'s, which says it
there too.

Spec: contract A.1 (`launch`'s exit codes, SETUP_FAILED before the sandboxed process starts)."""

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import SandboxExit, SandboxSpec
from handler_sandbox_kit import launch


class Engine:
    """A runtime whose start is `sh -c 'exit CODE'`, saying `why` when it did not start."""

    prog = "handler-sandbox-test"

    def __init__(self, code: int, why: str | None) -> None:
        self.code, self.why = code, why

    def start(self, name: str) -> subprocess.Popen[bytes]:
        return subprocess.Popen(["sh", "-c", f"exit {self.code}"])

    def start_failed(self, instance: launch.Instance) -> str | None:
        return self.why


def instance(tmp_path: Any, **more: Any) -> launch.Instance:
    spec = SandboxSpec.model_validate(
        {
            "apiVersion": "handler.sandbox/v2",
            "name": "handler-test-run",
            "image": "x",
            "argv": ["true"],
            "env": {},
            "workdir": str(tmp_path),
            "home": "/home/agent",
            "workFolder": {"path": str(tmp_path)},
            "network": {"mode": "none"},
        }
        | more
    )
    return launch.Instance(spec)


@pytest.mark.rule("sandbox.stdio-is-the-agent-s-stream")
@pytest.mark.parametrize(
    ("engine", "exits", "said"),
    [
        pytest.param(Engine(3, None), 3, "", id="the-program-s-code"),
        pytest.param(Engine(0, "never asked"), 0, "", id="ended-well"),
        pytest.param(
            Engine(1, "a folder refused"),
            SandboxExit.SETUP_FAILED,
            "a folder refused",
            id="not-started",
        ),
    ],
)
def test_launch_exits_with_the_program_s_code_or_says_why_it_did_not_start(
    tmp_path: Any, capsys: pytest.CaptureFixture[str], engine: Engine, exits: int, said: str
) -> None:
    """If this fails: a sandbox that never ran is shown as an agent that exited (1), with no word
    of why, or a program's own failure is taken for a start that failed."""
    assert launch.run(engine, instance(tmp_path)) == exits  # ty: ignore[invalid-argument-type]
    err = capsys.readouterr().err
    assert (f"handler-sandbox-test: {said}" in err) if said else err == ""


class Refused(Engine):
    """A `tty` sandbox whose start, by `attach`, fails before it runs."""

    def status(self, name: str) -> str:
        return "waiting"  # created, never run

    def attached(self, folder: Path, code: int) -> None:
        pass

    def stop(self, name: str) -> None:
        pass


@pytest.mark.rule("sandbox.stdio-is-the-agent-s-stream")
@pytest.mark.parametrize(
    ("why", "said"),
    [
        pytest.param("a folder refused", "a folder refused", id="the-runtime-s-reason"),
        pytest.param(None, "the sandbox did not start (exit 1)", id="no-reason-known"),
    ],
)
def test_a_terminal_whose_start_failed_says_why_on_it_at_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    why: str | None,
    said: str,
) -> None:
    """If this fails: `handler terminal` refused a folder shows only the engine's words, and its
    launcher waits a minute for an attach that already came."""
    monkeypatch.setattr(launch, "_instances_dir", lambda: tmp_path / "instances")
    monkeypatch.setattr(launch.signal, "signal", lambda *_: None)  # both here, one not main
    sandbox = instance(tmp_path, tty=True)
    sandbox.dir.mkdir(parents=True)
    engine = Refused(1, why)
    ended: list[int] = []
    launcher = threading.Thread(target=lambda: ended.append(launch.run(engine, sandbox)))  # ty: ignore[invalid-argument-type]
    began = time.monotonic()
    launcher.start()
    attached = launch.attach(engine, sandbox.spec.name)  # ty: ignore[invalid-argument-type]
    launcher.join(timeout=10)
    assert ended == [attached] == [SandboxExit.SETUP_FAILED]
    assert time.monotonic() - began < launch.START_REASON_TIMEOUT
    # said twice: by the launcher (handlerd's log) and by attach (the person's terminal)
    assert capsys.readouterr().err.count(f"handler-sandbox-test: {said}") == 2
