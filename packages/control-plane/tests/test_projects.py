"""Unit tests: projects and the resolution of their agents."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from handler_contracts import AddonUse
from handler_control.agents import AgentRecord, AgentRegistry, CheckedSettings, RunsAs
from handler_control.projects import ProjectRecord, ProjectRegistry, branch_of


def at(minutes: int) -> datetime:
    return datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=minutes)


def agent(settings: CheckedSettings, name: str, **fields: object) -> AgentRecord:
    return AgentRecord(**settings.model_dump(), name=name, **fields)


@pytest.mark.rule("project.agents-take-only-what-it-gives")
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
            addons=[AddonUse(addon="b")],
            allow=["b.org:443"],
        ),
        "review",
        instructions="review only",
    )
    projects.add_agent(project, own)
    assert project.default_agent == follows.id  # the first one
    assert (follows.addons, own.addons) == ([], [AddonUse(addon="b")])  # its own
    assert follows.project_skills == own.project_skills == ["a"]  # the project's skills

    projects.update(project, skills=["c", "a"], folder="/code/shop2", caches="off")
    assert follows.project_skills == ["a", "c"] and own.addons == [AddonUse(addon="b")]
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


def test_the_branch_is_read_from_its_git_head(tmp_path: Path) -> None:
    folder = tmp_path / "repo"
    (folder / ".git").mkdir(parents=True)
    assert branch_of(str(tmp_path)) is None  # not a git folder
    (folder / ".git" / "HEAD").write_text("ref: refs/heads/feature/cart\n")
    assert branch_of(str(folder)) == "feature/cart"
    (folder / ".git" / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n")
    assert branch_of(str(folder)) is None  # detached
    # a worktree: its .git a file pointing to its own folder of the repository's
    worktree, own = tmp_path / "wt", folder / ".git" / "worktrees" / "wt"
    own.mkdir(parents=True)
    worktree.mkdir()
    (own / "HEAD").write_text("ref: refs/heads/main\n")
    (worktree / ".git").write_text(f"gitdir: {own}\n")
    assert branch_of(str(worktree)) == "main"
