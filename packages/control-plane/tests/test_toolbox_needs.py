"""Unit tests of toolbox.py (B.6, B.7): the needs in use, what provides each, turning system
packages on and off. No image: the record is written by hand."""

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from handler_contracts import HANDLER_TOOLBOX_NEEDS, AddonUse, ToolboxRecord
from handler_control import toolbox
from handler_control.agents import AgentRecord, AgentRegistry, RunsAs
from handler_control.settings import Settings
from handler_harness import catalog

RUNS = RunsAs(harness="codex", provider="local")


def settings(tmp_path: Path) -> Settings:
    (tmp_path / "state").mkdir()
    return Settings(
        port=0,
        config_dir=tmp_path,
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path,
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )


@pytest.fixture
def mine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A toolbox folder of the test's, holding the default toolbox.toml; no toolbox image."""
    monkeypatch.setattr(toolbox.runtime, "inspect", lambda ref: None)
    folder = tmp_path / "toolbox"
    folder.mkdir()
    shutil.copyfile(catalog.DEFAULT_TOOLBOX / "toolbox.toml", folder / "toolbox.toml")
    monkeypatch.setenv("HANDLER_TOOLBOX_DIR", str(folder))
    return folder


def registry(tmp_path: Path, *agents: AgentRecord) -> AgentRegistry:
    found = AgentRegistry(tmp_path / "state")
    for agent in agents:
        found.agents[agent.id] = agent
    return found


def nested(agent_id: str = "a1") -> AgentRecord:
    return AgentRecord(id=agent_id, model=RUNS, scope="/code/x", confinement="nested")


@pytest.mark.rule("toolbox.gives-every-need-in-use")
def test_what_is_in_use_needs(tmp_path: Path) -> None:
    agents = registry(
        tmp_path,
        nested(),
        AgentRecord(id="a2", model=RUNS, scope="/code/y", display=True),
        AgentRecord(id="a3", model=RUNS, scope="/code/z"),
    )
    by = toolbox.grouped(toolbox.needs_in_use(agents))
    assert by[("python3",)] == ["handler"]
    assert by[("node",)] == ["harness:claude-code", "harness:codex", "harness:pi"]
    assert by[("uv",)] == ["harness:vibe"]
    assert by[("podman", "docker")] == ["agent:a1"]
    assert by[("wl-paste",)] == ["agent:a2"]


@pytest.mark.rule("toolbox.gives-every-need-in-use")
def test_the_addons_in_use_need_what_they_declare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G.1 `needs`: an addon an agent uses, or its project gives, needs them; a model alone
    uses none; every addon's are recorded by a build."""
    root = tmp_path / "addons"
    for name in ("web", "unused"):
        (root / name).mkdir(parents=True)
        (root / name / "tool.toml").write_text(
            f'apiVersion = "handler.tool/v1"\nname = "{name}"\nneeds = ["chromium-{name}"]\n'
        )
    monkeypatch.setenv("HANDLER_TOOLS_DIR", str(root))
    own = AgentRecord(id="a1", model=RUNS, scope="/x", addons=[AddonUse(addon="web")])
    given = AgentRecord(id="a2", model=RUNS, scope="/y", project_addons=[AddonUse(addon="web")])
    by = toolbox.grouped(toolbox.needs_in_use(registry(tmp_path, own, given)))
    assert by[("chromium-web",)] == ["addon:web"]
    assert ("chromium-unused",) not in by
    known = toolbox.known_commands(catalog.toolbox())
    assert "chromium-web" in known and "chromium-unused" in known


@pytest.mark.rule("toolbox.gives-every-need-in-use")
def test_each_need_says_what_provides_it(tmp_path: Path, mine: Path) -> None:
    s = settings(tmp_path)
    agents = registry(tmp_path, nested())
    info = toolbox.info(s, agents)
    assert info.distro == "fedora" and info.problem is None
    assert [p.name for p in info.system_packages] == ["podman", "wl-clipboard"]
    assert info.system_packages[0].version == 1 and info.system_packages[0].built_version is None
    assert info.system_packages[0].needed_by == ["agent:a1"]
    provided = {tuple(n.commands): n.provided_by for n in info.needs}
    assert provided[("node",)] == "base"
    assert provided[("podman", "docker")] == "system-package:podman"
    assert info.commands == {}  # no toolbox built yet

    record = ToolboxRecord(
        image_id="sha256:1",
        built_at=datetime.now(UTC),
        distro="fedora",
        system_packages={"podman": 1},
        commands={"node": "/usr/bin/node", "docker": "/usr/bin/docker"},
    )
    toolbox.write_record(s, record)
    assert toolbox.read_record(s) == record
    (mine / "toolbox.toml").write_text('distro = "fedora"\n')
    info = toolbox.info(s, agents)
    provided = {tuple(n.commands): n.provided_by for n in info.needs}
    assert provided[("podman", "docker")] == "lines"  # not declared, but found in the toolbox
    (mine / "toolbox.toml").write_text('distro = "fedora"\n[systemPackages.nope]\n')
    assert toolbox.info(s, agents).problem == "unknown system package 'nope'"


@pytest.mark.rule("toolbox.made-of-its-three-parts", "toolbox.gives-every-need-in-use")
def test_turning_system_packages_on_and_off(tmp_path: Path, mine: Path) -> None:
    agents = registry(tmp_path, nested())
    toolbox.set_system_packages(agents, ["chromium", "podman"])
    assert list(catalog.toolbox().system_packages) == [
        "podman",
        "chromium",
    ]  # podman kept its place
    with pytest.raises(toolbox.ToolboxInUseError, match=r"podman or docker \(agent:a1\)"):
        toolbox.set_system_packages(agents, ["chromium"])
    with pytest.raises(toolbox.ToolboxChangeError, match="unknown system package 'nope'"):
        toolbox.set_system_packages(agents, ["podman", "nope"])
    assert list(catalog.toolbox().system_packages) == ["podman", "chromium"]
    toolbox.set_system_packages(registry(tmp_path), [])
    assert catalog.toolbox().system_packages == {}


@pytest.mark.rule("toolbox.gives-every-need-in-use")
def test_a_new_toolbox_lacking_a_need_in_use_says_who_needs_it(tmp_path: Path) -> None:
    needs = toolbox.needs_in_use(registry(tmp_path, nested()))
    commands = dict.fromkeys([*HANDLER_TOOLBOX_NEEDS, "node", "npm", "jq", "uv"], "/x")
    assert toolbox.missing(needs, commands) == ["podman or docker (needed by agent:a1)"]
    assert toolbox.missing(needs, commands | {"docker": "/usr/bin/docker"}) == []


def test_known_commands_are_every_need_and_every_package(mine: Path) -> None:
    known = toolbox.known_commands(catalog.toolbox())
    for command in ("sh", "node", "uv", "podman", "docker", "wl-paste", "chromium", "g++", "rg"):
        assert command in known


def test_what_a_save_needs_is_answered_by_system_packages(
    tmp_path: Path, mine: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B.6: what the toolbox lacks (neither the base, a system package on, nor its record) is
    answered by a system package providing it; what none provides is said."""
    root = tmp_path / "addons"
    (root / "web").mkdir(parents=True)
    (root / "web" / "tool.toml").write_text(
        'apiVersion = "handler.tool/v1"\nname = "web"\nneeds = ["chromium", "nothing-gives"]\n'
    )
    monkeypatch.setenv("HANDLER_TOOLS_DIR", str(root))
    s = settings(tmp_path)
    agent = nested().model_copy(update={"display": True})
    assert toolbox.to_add(s, toolbox.agent_needs(agent, [], "agent:a1")).adds == {}  # on
    needs = toolbox.agent_needs(agent, [AddonUse(addon="web")], "agent:a1")
    lacking = toolbox.to_add(s, needs)
    assert lacking.adds == {"chromium": ["chromium"]}
    assert lacking.unprovided == ["nothing-gives"]
    toolbox.turn_on(registry(tmp_path), ["chromium"])
    assert toolbox.to_add(s, needs).adds == {}  # on, applied by the next build
    (mine / "toolbox.toml").write_text('distro = "fedora"\n')  # no engine on
    assert toolbox.to_add(s, toolbox.agent_needs(nested(), [], "agent:a1")).adds == {
        "podman": ["podman"]  # nested's first engine
    }
    record = ToolboxRecord(
        image_id="x", built_at=datetime.now(UTC), distro="fedora", system_packages={},
        commands={"docker": "/usr/bin/docker"},
    )  # fmt: skip
    toolbox.write_record(s, record)  # the user's lines give docker: nothing to add
    assert toolbox.to_add(s, toolbox.agent_needs(nested(), [], "agent:a1")).adds == {}
    assert toolbox.agent_needs(nested().model_copy(update={"model_alone": True}), [], "x") == []


@pytest.mark.rule("toolbox.a-daemon-only-where-its-ability-is")
def test_the_daemons_are_those_of_the_built_toolbox_s_system_packages(tmp_path: Path) -> None:
    """B.7: what the toolbox `:latest` was built with (its record) starts its daemons."""
    s = settings(tmp_path)
    assert toolbox.daemons(s) == []  # no toolbox built yet
    record = ToolboxRecord(
        image_id="x", built_at=datetime.now(UTC), distro="fedora",
        system_packages={"podman": 1, "docker": 1}, commands={},
    )  # fmt: skip
    toolbox.write_record(s, record)
    assert [d.command for d in toolbox.daemons(s)] == ["handler-dockerd"]
    assert toolbox.daemons(s)[0].abilities == ["nested", "privileged"]
