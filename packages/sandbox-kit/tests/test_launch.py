"""`launch.launch` and `launch.create`: what the kit refuses before anything is made, and what it
gives the runtime's `create` to make the sandbox, here its environment (secrets among it, a
provider's key when it cannot be injected).

Spec: contract A.1 (`launch`'s exit codes; B3: the environment through `--env-file`, never in a
command line)."""

import stat
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import SandboxExit, SandboxSpec
from handler_sandbox_kit import launch

SECRET = "sk-test-" + "s3cr3t" * 6


class Engine:
    """A runtime giving nothing of its own: each need is no argument, and `create` records the
    arguments it is given and the env file as it is then."""

    prog = "handler-sandbox-test"

    def __init__(self) -> None:
        self.args: list[str] = []
        self.env_file: tuple[int, str] | None = None  # its mode and content at create

    def __getattr__(self, need: str) -> Any:
        return lambda *_: []

    def abilities(self) -> frozenset[str]:
        return frozenset()

    def create(self, instance: launch.Instance, args: list[str]) -> None:
        self.args = args
        path = Path(args[args.index("--env-file") + 1])
        self.env_file = (stat.S_IMODE(path.stat().st_mode), path.read_text())


def spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SandboxSpec:
    """A sandbox given a secret in its environment, its instance folders in `tmp_path`."""
    monkeypatch.setattr(launch, "_instances_dir", lambda: tmp_path / "sandboxes")
    (tmp_path / "sandboxes").mkdir()
    return SandboxSpec.model_validate(
        {
            "apiVersion": "handler.sandbox/v2",
            "name": "handler-test-env",
            "image": "x",
            "argv": ["true"],
            "env": {"OPENAI_API_KEY": SECRET},
            "workdir": str(tmp_path),
            "home": "/home/agent",
            "workFolder": {"path": str(tmp_path)},
            "network": {"mode": "none"},
        }
    )


@pytest.mark.rule("sandbox.a-name-in-use-is-refused")
def test_a_name_in_use_is_refused_and_its_folder_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """If this fails: a second launch of one name mounts over the first sandbox's files, and
    its cleanup removes what the first still uses."""
    doc = spec(tmp_path, monkeypatch)
    used = tmp_path / "sandboxes" / doc.name
    used.mkdir()
    (used / "env").write_text("the first sandbox's\n")
    engine = Engine()
    assert launch.launch(engine, doc) == SandboxExit.SETUP_FAILED  # ty: ignore[invalid-argument-type]
    assert "sandbox name in use: handler-test-env" in capsys.readouterr().err
    assert engine.env_file is None  # nothing created
    assert (used / "env").read_text() == "the first sandbox's\n"


@pytest.mark.rule("sandbox.its-environment-never-on-a-command-line")
def test_the_environment_reaches_the_engine_in_a_file_of_the_user_s_removed_after_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The environment goes to the engine in a 0600 file, gone once the sandbox is created; no
    value of it is an argument.
    If this fails: a secret in the environment is readable by every user of the computer, in the
    engine's command line (`ps`), or in a file left behind."""
    engine, instance = Engine(), launch.Instance(spec(tmp_path, monkeypatch))
    launch.create(engine, instance)  # ty: ignore[invalid-argument-type]
    assert engine.env_file is not None
    mode, content = engine.env_file
    assert mode == 0o600
    assert f"OPENAI_API_KEY={SECRET}\n" in content
    assert not any(SECRET in a for a in engine.args)
    assert not Path(engine.args[engine.args.index("--env-file") + 1]).exists()
