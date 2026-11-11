"""Contract A.8: `check` says whether this host can run sandboxes, and why not."""

import subprocess

import pytest

from handler_contracts import RuntimeCheck

from ...support.runtimes import Runtime


@pytest.mark.rule("runtime.check-starts-nothing-and-says-why")
def test_check_prints_a_runtime_check_and_exits_with_it(runtime: Runtime) -> None:
    result = subprocess.run(
        [runtime.binary, "check"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    check = RuntimeCheck.model_validate_json(result.stdout)
    assert check.runtime
    assert check.ok == all(i.ok for i in check.items if i.required)
    assert result.returncode == (0 if check.ok else 1)
    assert all(i.detail for i in check.items)
    # what it gives here (A.8): with every runtime that can run sandboxes
    assert (check.supports is not None) == check.ok
    if check.supports is not None:
        assert check.supports.isolation
