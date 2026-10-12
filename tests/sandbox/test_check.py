"""Contract A.8: `check` says whether this host can run sandboxes, and why not."""

import subprocess

from handler_contracts import RuntimeCheck


def test_check_prints_a_runtime_check_and_exits_with_it() -> None:
    result = subprocess.run(
        ["handler-sandbox-podman", "check"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    check = RuntimeCheck.model_validate_json(result.stdout)
    assert check.runtime.startswith("podman")
    assert check.ok == all(i.ok for i in check.items if i.required)
    assert result.returncode == (0 if check.ok else 1)
    assert all(i.detail for i in check.items)
