"""Contract A.8, every runtime: a spec's memory limit is applied where the host lets it be
(`check`'s `limits`); where not, the sandbox runs without it and says so on stderr. A runtime
with a minimum (Apple's virtual machines) raises a smaller limit to it and says so."""

import re
from pathlib import Path

import pytest

from ...support.runtimes import Runtime
from ..conftest import run, spec


@pytest.mark.rule("runtime.a-limit-is-applied-or-said")
def test_a_memory_limit_is_applied_or_said(runtime: Runtime, scope: Path) -> None:
    doc = spec(scope, ["cat", "/sys/fs/cgroup/memory.max"], resources={"memory": "64m"})
    r = run(runtime.binary, doc)
    assert r.returncode == 0, r.stderr
    if runtime.limits:
        raised = re.search(rb"--memory 64m raised to (\d+)m", r.stderr)
        mib = int(raised.group(1)) if raised else 64
        assert r.stdout.decode().strip() == str(mib * 1024 * 1024)
    else:
        assert b"--memory 64m not applied" in r.stderr
