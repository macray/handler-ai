"""Contract A.8, every runtime: a spec needing an ability its `check` does not declare is refused
(A1, exit 64), and nothing of it is left. What a declared ability gives is tested with its need
(test_display.py, the confinements in test_launch.py)."""

from pathlib import Path
from typing import Any

import pytest

from handler_contracts import ABILITIES, SandboxSpec

from ...support.runtimes import Runtime
from ..conftest import run, spec

NEEDING: dict[str, dict[str, Any]] = {
    "nested": {"isolation": "nested"},
    "privileged": {"isolation": "privileged"},
    "display": {"display": True},
}


@pytest.mark.rule("runtime.declares-only-what-it-gives")
def test_each_ability_has_a_spec_needing_it(scope: Path) -> None:
    assert set(NEEDING) == set(ABILITIES)
    for ability, change in NEEDING.items():
        assert SandboxSpec.model_validate(spec(scope, ["true"], **change)).abilities() == {ability}


@pytest.mark.rule("sandbox.refuses-what-it-cannot-enforce", "runtime.declares-only-what-it-gives")
@pytest.mark.parametrize("ability", sorted(NEEDING))
def test_an_ability_not_declared_is_refused(runtime: Runtime, scope: Path, ability: str) -> None:
    if ability in runtime.abilities:
        pytest.skip(f"{runtime.name} gives {ability} here")
    doc = spec(scope, ["true"], **NEEDING[ability])
    r = run(runtime.binary, doc)
    assert r.returncode == 64, r.stderr
    assert ability.encode() in r.stderr
    assert runtime.leftovers(doc["name"]) == []
