import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from ..support.daemon import Daemon, start_daemon
from ..support.stub_llm import StubLlm

FINDING = '{"findings": [{"kind": "missing-tool", "what": "npm: command not found"}]}'
STUB_KEY = "sk-stub-secret-value"


@pytest.fixture(scope="module")
def stub() -> Iterator[StubLlm]:
    s = StubLlm(FINDING)
    yield s
    s.close()


@pytest.fixture(scope="module")
def knowledge() -> Path:
    root = Path(tempfile.mkdtemp(prefix="handler-knowledge-"))
    (root / "handler").mkdir()
    return root


@pytest.fixture(scope="module")
def daemon(stub: StubLlm, knowledge: Path) -> Iterator[Daemon]:
    yield from start_daemon(
        extra_env={
            "HANDLER_NOTES_DIR": str(knowledge),
            "HANDLER_TEST_FAKE_TOOLBOX": "1",
            "HANDLER_TEST_STUB_KEY": STUB_KEY,
        },
        extra_providers={"stub": stub.provider()},
    )
