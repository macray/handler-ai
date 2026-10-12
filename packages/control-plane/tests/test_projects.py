"""Unit tests: projects and the resolution of their agents."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from handler_control.agents import AgentRegistry, CheckedSettings, RunsAs
from handler_control.projects import ProjectRecord, ProjectRegistry


def at(minutes: int) -> datetime:
    return datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=minutes)


def test_agents_follow_their_project(tmp_path: Path) -> None:
    registry = AgentRegistry(tmp_path)
    projects = ProjectRegistry(tmp_path, registry)
    project = projects.add(
        ProjectRecord(id=projects.new_id(), name="shop", folder="/code/shop", skills=["a"])
    )
    follows = projects.add_agent(
        project,
        CheckedSettings(models=[RunsAs(harness="claude", account="a")], scope="/code/shop"),
        name="coder",
        description="writes code",
        instructions=None,
    )
    own = projects.add_agent(
        project,
        CheckedSettings(
            models=[RunsAs(harness="codex", account="a")],
            scope="/code/shop",
            bindings=["b"],
            allow=["b.org:443"],
        ),
        name="review",
        description=None,
        instructions="review only",
    )
    assert project.default_agent == follows.id  # the first one
    assert (follows.bindings, own.bindings) == ([], ["b"])  # its own, nothing followed
    assert follows.project_skills == own.project_skills == ["a"]  # the project's skills

    projects.update(project, skills=["c", "a"], folder="/code/shop2", caches="off")
    assert follows.project_skills == ["a", "c"] and own.bindings == ["b"]
    assert own.allow == ["b.org:443"]
    assert follows.scope == own.scope == "/code/shop2"
    assert follows.caches == own.caches == "off"

    projects.remove_agent(project, follows)
    assert project.default_agent == own.id
    loaded = ProjectRegistry(tmp_path, AgentRegistry(tmp_path))
    agent = loaded.agents(loaded.projects[project.id])[0]
    assert (agent.name, agent.instructions, agent.scope) == ("review", "review only", "/code/shop2")

    assert projects.delete(project) == [own]
    assert registry.get(own.id) is None and not projects.projects
