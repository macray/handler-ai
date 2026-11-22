"""Unit tests: the knowledge tool (D.29): what its build context holds, and an agent with a
knowledge use getting it."""

import tomllib
from importlib import metadata
from pathlib import Path

import pytest

from handler_contracts import AddonUse
from handler_control import knowledge_tool
from handler_control.agents import KNOWLEDGE_TOOL, with_knowledge_tool
from handler_harness import addons

SMD_PYPROJECT = Path(__file__).parents[2] / "smd" / "pyproject.toml"


@pytest.mark.rule("image.built-only-from-what-is-on-disk")
def test_its_context_is_the_tool_a_copy_of_the_format_and_its_pinned_dependencies(
    tmp_path: Path,
) -> None:
    tool = addons.get("knowledge")
    assert tool.builtin and tool.manifest.commands == ["handler-smd", "smd"]
    folder = knowledge_tool.write_context(tmp_path, tool.directory)
    assert (folder / "Containerfile").is_file() and (folder / "tool.toml").is_file()
    assert (folder / "handler_smd" / "cli.py").is_file()
    assert not list(folder.rglob("__pycache__"))
    pinned = (folder / "requirements.txt").read_text().splitlines()
    assert pinned == [f"{n}=={metadata.version(n)}" for n in knowledge_tool.DEPENDENCIES]
    declared = tomllib.loads(SMD_PYPROJECT.read_text())["project"]["dependencies"]
    names = {d.split(">")[0].split("=")[0].split("<")[0].strip().lower() for d in declared}
    assert names == {n.lower() for n in knowledge_tool.DEPENDENCIES}
    knowledge_tool.write_context(tmp_path, tool.directory)  # made again, not merged
    assert (folder / "requirements.txt").read_text() == "\n".join(pinned) + "\n"


@pytest.mark.rule("tool.each-start-gets-what-it-gives")
@pytest.mark.parametrize(
    ("uses", "has_schemas", "expected"),
    [
        ([], False, []),
        ([], True, [KNOWLEDGE_TOOL]),
        (["app-builder"], True, ["app-builder", KNOWLEDGE_TOOL]),
        ([KNOWLEDGE_TOOL], True, [KNOWLEDGE_TOOL]),  # picked already: once
        ([KNOWLEDGE_TOOL], False, [KNOWLEDGE_TOOL]),  # any agent may pick it
    ],
)
def test_a_knowledge_use_brings_the_tool(
    uses: list[str], has_schemas: bool, expected: list[str]
) -> None:
    given = [AddonUse(addon=u) for u in uses]
    assert [u.addon for u in with_knowledge_tool(given, has_schemas)] == expected
