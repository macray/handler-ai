"""The `handler-ai` wheel (packaging/) ships exactly the workspace's packages, their third-party
dependencies and their commands: nothing added there, nothing forgotten."""

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGING = tomllib.loads((REPO / "packaging" / "pyproject.toml").read_text())


def members() -> list[dict]:
    return [
        tomllib.loads(p.read_text())["project"]
        for p in sorted(REPO.glob("packages/*/pyproject.toml"))
    ]


def test_the_wheel_has_every_package() -> None:
    included = PACKAGING["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    sources = {
        f"../{src.relative_to(REPO)}": src.name
        for src in REPO.glob("packages/*/src/handler_*")
        if src.is_dir()
    }
    assert included == sources


def test_the_wheel_depends_on_what_the_packages_depend_on() -> None:
    third_party = {
        d for p in members() for d in p.get("dependencies", []) if not d.startswith("handler-")
    }
    assert sorted(PACKAGING["project"]["dependencies"]) == sorted(third_party)


def test_the_wheel_installs_every_command() -> None:
    commands = {name: target for p in members() for name, target in p.get("scripts", {}).items()}
    assert PACKAGING["project"]["scripts"] == commands
