"""Unit tests: the skill library (D.17) and the projects and agents that follow its changes."""

import io
import zipfile
from pathlib import Path

import pytest

from handler_control import skill_sources, skills
from handler_control.agents import AgentRecord, AgentRegistry, CheckedSettings, RunsAs
from handler_control.projects import ProjectRecord, ProjectRegistry


def skill_md(name: str, description: str = "Does things. Use when asked to.") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"


def test_parse_follows_the_format() -> None:
    assert skills.parse(skill_md("pdf-tools")) == ("pdf-tools", "Does things. Use when asked to.")
    folded = "---\nname: x\ndescription: >\n  on two\n  lines\nlicense: MIT\n---\nbody"
    assert skills.parse(folded) == ("x", "on two lines")
    for bad in (
        "# no frontmatter",
        "---\nname: [unclosed\n---\n",
        "---\n- a list\n---\n",
        skill_md("PDF"),
        skill_md("a--b"),
        skill_md("-a"),
        skill_md("a" * 65),
        "---\nname: x\n---\n",
        skill_md("x", "y" * 1025),
    ):
        with pytest.raises(skills.SkillError):
            skills.parse(bad)


def test_load_save_rename_delete(tmp_path: Path) -> None:
    assert skills.save(tmp_path, skill_md("one")) == "one"
    (tmp_path / "one" / "scripts").mkdir()
    (tmp_path / "one" / "scripts" / "run.sh").write_text("echo")
    loaded = skills.get(tmp_path, "one")
    assert (loaded.description, loaded.files, loaded.error) == (
        "Does things. Use when asked to.",
        [skills.SkillFile("scripts/run.sh", 4, False)],
        None,
    )
    # renamed with its other files
    assert skills.save(tmp_path, skill_md("two"), old="one") == "two"
    assert not (tmp_path / "one").exists()
    assert [f.path for f in skills.get(tmp_path, "two").files] == ["scripts/run.sh"]
    assert skills.paths(tmp_path, ["two"]) == [str(tmp_path / "two")]

    # by hand: a folder whose SKILL.md says another name, or none, is listed with its error
    (tmp_path / "three").mkdir()
    (tmp_path / "three" / "SKILL.md").write_text(skill_md("other"))
    (tmp_path / "four").mkdir()
    (tmp_path / ".hidden").mkdir()
    listed = {s.name: s.error for s in skills.load_all(tmp_path)}
    assert set(listed) == {"two", "three", "four"} and listed["two"] is None
    assert "named 'other'" in (listed["three"] or "") and "no SKILL.md" in (listed["four"] or "")
    with pytest.raises(skills.SkillError, match="three"):
        skills.paths(tmp_path, ["two", "three"])
    assert skills.get(tmp_path, "../etc").error and not skills.exists(tmp_path, "../etc")

    skills.delete(tmp_path, "two")
    assert skills.get(tmp_path, "two").error


def test_files_stay_in_their_skill(tmp_path: Path) -> None:
    skills.save(tmp_path, skill_md("tool"))
    skills.write_file(tmp_path, "tool", "scripts/run.sh", b"#!/bin/sh\necho hi\n", True)
    skills.write_file(tmp_path, "tool", "references/api.md", b"# API", False)
    assert skills.read_file(tmp_path, "tool", "scripts/run.sh") == (b"#!/bin/sh\necho hi\n", True)
    assert [(f.path, f.executable) for f in skills.get(tmp_path, "tool").files] == [
        ("references/api.md", False),
        ("scripts/run.sh", True),
    ]
    for bad in ("../escape", "/abs", "a//b", ".hidden", "a/../b", "a\\b", "SKILL.md"):
        with pytest.raises(skills.SkillError):
            skills.write_file(tmp_path, "tool", bad, b"x", False)
    # a symbolic link made by hand is never written through
    (tmp_path / "outside").mkdir()
    (tmp_path / "tool" / "linked").symlink_to(tmp_path / "outside")
    with pytest.raises(skills.SkillError, match="symbolic link"):
        skills.write_file(tmp_path, "tool", "linked/x", b"x", False)
    assert not (tmp_path / "outside" / "x").exists()
    assert "linked" not in [f.path for f in skills.get(tmp_path, "tool").files]

    skills.delete_file(tmp_path, "tool", "references/api.md")
    assert not (tmp_path / "tool" / "references").exists()  # left empty: removed
    with pytest.raises(FileNotFoundError):
        skills.delete_file(tmp_path, "tool", "references/api.md")
    with pytest.raises(skills.SkillError):
        skills.delete_file(tmp_path, "tool", "SKILL.md")


def zipped(files: dict[str, bytes], modes: dict[str, int] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, data in files.items():
            info = zipfile.ZipInfo(path)
            info.external_attr = (modes or {}).get(path, 0o100644) << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def test_archives_out_and_in(tmp_path: Path) -> None:
    library, other = tmp_path / "a", tmp_path / "b"
    skills.save(library, skill_md("tool"))
    skills.write_file(library, "tool", "scripts/run.sh", b"echo", True)
    name, files = skills.unpack(skills.pack(library, "tool"))
    assert name == "tool" and files == {
        "SKILL.md": (skill_md("tool").encode(), False),
        "scripts/run.sh": (b"echo", True),
    }
    skills.install(other, name, files)
    assert skills.get(other, "tool").error is None
    assert skills.read_file(other, "tool", "scripts/run.sh") == (b"echo", True)

    # a repository's archive: the skill in a folder, its other files and junk around it
    repo = zipped(
        {
            "repo-main/README.md": b"# repo",
            "repo-main/skill/SKILL.md": skill_md("audit").encode(),
            "repo-main/skill/run.py": b"print()",
            "repo-main/skill/.gitignore": b"*.pyc",
            "repo-main/skill/examples/SKILL.md": skill_md("nested").encode(),
            "__MACOSX/repo-main/skill/._run.py": b"junk",
            "repo-main/skill/link": b"/etc/passwd",
        },
        {"repo-main/skill/link": 0o120777},
    )
    name, files = skills.unpack(repo)
    assert name == "audit" and set(files) == {"SKILL.md", "run.py", "examples/SKILL.md"}
    skills.install(other, "tool", {"SKILL.md": (skill_md("tool", "New.").encode(), False)})
    assert skills.get(other, "tool").files == []  # replaced as a whole

    for archive, error in (
        (b"not a zip", "not a zip"),
        (zipped({"x.md": b"x"}), "no SKILL.md"),
        (zipped({"a/SKILL.md": skill_md("a").encode(), "b/SKILL.md": b""}), "several skills"),
        (zipped({"SKILL.md": b"no frontmatter"}), "frontmatter"),
    ):
        with pytest.raises(skills.SkillError, match=error):
            skills.unpack(archive)


def test_agents_follow_their_skills(tmp_path: Path) -> None:
    registry = AgentRegistry(tmp_path)
    projects = ProjectRegistry(tmp_path, registry)
    shop = projects.add(ProjectRecord(id="p_shop", name="shop", folder="/code/shop"))
    blog = projects.add(ProjectRecord(id="p_blog", name="blog", folder="/code/blog"))

    def agent(project: ProjectRecord, chosen: list[str]) -> AgentRecord:
        settings = CheckedSettings(model=RunsAs(harness="claude", account="a"), scope=None)
        record = AgentRecord(**settings.model_dump(), name="a", skills=chosen)
        projects.add_agent(project, record)
        return record

    in_shop, in_blog = agent(shop, ["deploy", "review"]), agent(blog, ["deploy"])
    projects.give_skill(None, "deploy", [])  # a new skill, given by no project
    assert projects.skill_projects("deploy") == []

    projects.give_skill("deploy", "ship", [])  # renamed: its agents follow
    assert (in_shop.skills, in_blog.skills) == (["review", "ship"], ["ship"])

    projects.give_skill("ship", "ship", [shop])  # shop gives it: its agents' picks are dropped
    assert projects.skill_projects("ship") == [shop] and shop.skills == ["ship"]
    assert (in_shop.skills, in_blog.skills) == (["review"], ["ship"])  # blog's agent keeps it
    assert (in_shop.project_skills, in_blog.project_skills) == (["ship"], [])

    projects.give_skill("ship", "ship", [shop, blog])  # given by both
    assert (shop.skills, blog.skills) == (["ship"], ["ship"]) and in_blog.skills == []
    assert (in_shop.project_skills, in_blog.project_skills) == (["ship"], ["ship"])

    projects.give_skill("ship", "ship", [blog])  # shop no longer gives it
    assert (shop.skills, in_shop.project_skills, in_shop.skills) == ([], [], ["review"])

    projects.drop_skill("review")
    assert in_shop.skills == []
    projects.drop_skill("ship")
    assert in_blog.project_skills == [] and blog.skills == []
    projects.give_skill(None, "ship", [blog])  # a new skill blog gives
    loaded = ProjectRegistry(tmp_path, AgentRegistry(tmp_path))
    assert loaded.projects["p_blog"].skills == ["ship"]
    assert [a.skills for a in loaded.agents(loaded.projects["p_shop"])] == [[]]


def test_a_skill_from_a_repository_folder() -> None:
    """D.17 import from a URL: one folder of a repository holding several skills."""
    repo = zipped(
        {
            "skills-main/README.md": b"# skills",
            "skills-main/skills/pdf/SKILL.md": skill_md("pdf").encode(),
            "skills-main/skills/pdf/scripts/fill.py": b"print()",
            "skills-main/skills/docx/SKILL.md": skill_md("docx").encode(),
        }
    )
    name, files = skills.unpack(repo, "skills/pdf")
    assert name == "pdf" and set(files) == {"SKILL.md", "scripts/fill.py"}
    with pytest.raises(skills.SkillError, match="no folder 'skills/xlsx'"):
        skills.unpack(repo, "skills/xlsx")
    with pytest.raises(skills.SkillError, match="the URL of one skill's folder"):
        skills.unpack(repo, "")  # the repository's root: two skills


def test_skill_urls_name_an_archive_and_a_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    github = "https://github.com/acme/skills"
    assert skill_sources.locate(f"{github}/tree/main/skills/pdf") == (
        f"{github}/archive/main.zip",
        "skills/pdf",
    )
    assert skill_sources.locate(f"{github}/blob/v2/pdf/SKILL.md") == (
        f"{github}/archive/v2.zip",
        "pdf",
    )
    assert skill_sources.locate(f"{github}.git") == (f"{github}/archive/HEAD.zip", "")
    assert skill_sources.locate("https://x.test/pdf.skill") == ("https://x.test/pdf.skill", None)
    for url, error in (
        ("http://x.test/a.zip", "https:// only"),
        (f"{github}/blob/main/README.md", "must be a SKILL.md"),
    ):
        with pytest.raises(skills.SkillError, match=error):
            skill_sources.locate(url)

    archive = zipped({"skills-main/pdf/SKILL.md": skill_md("pdf").encode()})
    monkeypatch.setattr(skill_sources, "_download", lambda url: archive)
    assert skill_sources.fetch(f"{github}/tree/main/pdf")[0] == "pdf"
