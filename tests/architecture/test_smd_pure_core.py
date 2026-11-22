"""The format's pure core (smd.pure-core): only `scanner` and `cli` touch files, folders or the
environment; the rest of `handler_smd` takes text and gives back text or data.

Read from the source, as `test_boundaries` reads imports.
"""

import ast
from pathlib import Path

import pytest

SMD = Path(__file__).resolve().parents[2] / "packages/smd/src/handler_smd"
DOES_IO = {"scanner", "cli"}
IO_MODULES = {"os", "pathlib", "subprocess", "shutil", "io", "sys", "tempfile", "glob"}


def core_modules() -> list[str]:
    return sorted(p.stem for p in SMD.glob("*.py") if p.stem not in DOES_IO)


def io_of(name: str) -> list[str]:
    tree = ast.parse((SMD / f"{name}.py").read_text())
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] in IO_MODULES]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.split(".")[0] in IO_MODULES:
                found.append(node.module)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"open", "input", "print"}
        ):
            found.append(f"{node.func.id}()")
    return found


@pytest.mark.rule("smd.pure-core")
def test_the_core_does_no_io() -> None:
    assert {"parser", "schema", "resolver", "validator", "renderer", "agent"} <= set(core_modules())
    assert {name: io_of(name) for name in core_modules() if io_of(name)} == {}


@pytest.mark.rule("smd.pure-core")
def test_the_check_would_see_a_module_doing_io() -> None:
    assert io_of("scanner")  # the test reads what it claims to read
