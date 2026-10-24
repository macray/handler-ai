"""Unit tests: projects and the resolution of their agents."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from handler_control.agents import AgentRecord, AgentRegistry, CheckedSettings, RunsAs
from handler_control.projects import ProjectRecord, ProjectRegistry


def at(minutes: int) -> datetime:
    return datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=minutes)


def agent(settings: CheckedSettings, name: str, **fields: object) -> AgentRecord:
    return AgentRecord(**settings.model_dump(), name=name, **fields)


def test_agents_follow_their_project(tmp_path: Path) -> None:
    registry = AgentRegistry(tmp_path)
    projects = ProjectRegistry(tmp_path, registry)
    project = projects.add(
        ProjectRecord(id=projects.new_id(), name="shop", folder="/code/shop", skills=["a"])
    )
    follows = agent(
        CheckedSettings(model=RunsAs(harness="claude", account="a"), scope="/code/shop"),
        "coder",
        description="writes code",
    )
    projects.add_agent(project, follows)
    own = agent(
        CheckedSettings(
            model=RunsAs(harness="codex", account="a"),
            scope="/code/shop",
            bindings=["b"],
            allow=["b.org:443"],
        ),
        "review",
        instructions="review only",
    )
    projects.add_agent(project, own)
    assert project.default_agent == follows.id  # the first one
    assert (follows.bindings, own.bindings) == ([], ["b"])  # its own, nothing followed
    assert follows.project_skills == own.project_skills == ["a"]  # the project's skills

    projects.update(project, skills=["c", "a"], folder="/code/shop2", caches="off")
    assert follows.project_skills == ["a", "c"] and own.bindings == ["b"]
    assert own.allow == ["b.org:443"]
    assert follows.scope == own.scope == "/code/shop2"
    assert follows.caches == own.caches == "off"

    registry.delete(follows.id)
    projects.agent_gone(project, follows.id)
    assert project.default_agent == own.id
    loaded = ProjectRegistry(tmp_path, AgentRegistry(tmp_path))
    found = loaded.agents(loaded.projects[project.id])[0]
    assert (found.name, found.instructions, found.scope) == ("review", "review only", "/code/shop2")

    projects.delete(project)
    assert not ProjectRegistry(tmp_path, registry).projects


def test_agents_take_their_project_s_area_again_when_loaded(tmp_path: Path) -> None:
    """An agent's copy of its project's area is taken again at start: one saved without it
    (agents.json written before projects had areas) never lets another area's account run."""
    registry = AgentRegistry(tmp_path)
    projects = ProjectRegistry(tmp_path, registry)
    project = projects.add(
        ProjectRecord(id=projects.new_id(), name="news", folder="/code/news", area="Personal")
    )
    analyzer = agent(
        CheckedSettings(model=RunsAs(harness="claude", account="perso"), scope="/code/news"),
        "analyzer",
    )
    projects.add_agent(project, analyzer)
    analyzer.area = None  # a stale copy, as an older version saved it
    registry.save()
    reloaded = AgentRegistry(tmp_path)
    ProjectRegistry(tmp_path, reloaded)
    assert reloaded.agents[analyzer.id].area == "Personal"
