"""I.3 on the real sandbox: an automation run's sandbox, as handlerd composes it, keeps its
definition and its input read-only, lets it write its output only, has no network, and has
`handler-llm` on its PATH. Skipped without podman or without the toolbox (`handler image rebuild
toolbox`)."""

import subprocess
from pathlib import Path

import pytest

from handler_control import compose, runtime, sandbox_process
from handler_control.automations import BIN
from handler_harness import images

from ..sandbox.conftest import podman_usable
from ..support import dev_env

TOOLBOX = images.ref(images.TOOLBOX, images.LATEST)

pytestmark = [
    pytest.mark.skipif(
        not podman_usable() or not runtime.exists(TOOLBOX), reason=f"podman or {TOOLBOX} missing"
    ),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]

SCRIPT = """
set -u
try() { if "$@" 2>/dev/null; then echo "yes: $*"; else echo "no: $*"; fi; }
try touch "$PWD/written"
try touch "$HANDLER_INPUT/written"
try touch "$HANDLER_OUTPUT/written"
try curl -s -m 5 -o /dev/null https://example.com
try command -v handler-llm
cat "$HANDLER_INPUT/given"
echo "try=$HANDLER_TRY run=$HANDLER_RUN"
"""


def test_a_runs_sandbox_is_confined() -> None:
    root = dev_env.make_scope()
    try:
        folders = {n: root / n for n in ("definition", "input", "output")}
        for folder in folders.values():
            folder.mkdir()
        (folders["input"] / "given").write_text("the conversation\n")
        spec = compose.automation_run_spec(
            name="handler-run-a-test",
            run_id="a_test",
            toolbox=TOOLBOX,
            run=SCRIPT,
            definition=str(folders["definition"]),
            input_dir=str(folders["input"]),
            output=str(folders["output"]),
            bin_dir=str(BIN),
            services=None,
            trial=True,
        )
        proc = sandbox_process.start(spec, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        out, _ = proc.communicate(timeout=120)
        lines = out.decode().splitlines()
        assert f"no: touch {folders['definition']}/written" in lines
        assert f"no: touch {folders['input']}/written" in lines
        assert f"yes: touch {folders['output']}/written" in lines
        assert "no: curl -s -m 5 -o /dev/null https://example.com" in lines
        assert "yes: command -v handler-llm" in lines
        assert "the conversation" in lines and "try=1 run=a_test" in lines
        assert (folders["output"] / "written").exists()
    finally:
        dev_env.remove_scope(Path(root))
