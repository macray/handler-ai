"""Skill library routes: skills, their files, archives out and in (D.17)."""

import asyncio
import binascii
import contextlib
from base64 import b64decode
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    MAX_SKILL_ARCHIVE_BYTES,
    CreateSkillRequest,
    SkillFile,
    SkillFileRequest,
    SkillInfo,
    SkillRequest,
    SkillUrlRequest,
)

from .. import (
    skill_scan,
    skill_sources,
    skills,
)
from ..projects import ProjectRecord
from .common import (
    Context,
    ProblemError,
    dump,
    log,
    parse_body,
)


def skill_info(ctx: Context, skill: skills.LoadedSkill, content: bool = False) -> SkillInfo:
    used_by = []
    for user in ctx.projects.skill_users(skill.name):
        if user.project_id is None:
            used_by.append(f"ad-hoc/{user.name or user.id}")
            continue
        project = ctx.projects.get(user.project_id)
        used_by.append(f"agents/{project.name if project else '?'}/{user.name}")
    return SkillInfo(
        name=skill.name,
        description=skill.description,
        projects=[p.id for p in ctx.projects.skill_projects(skill.name)],
        files=[SkillFile(path=f.path, size=f.size, executable=f.executable) for f in skill.files],
        error=skill.error,
        used_by=sorted(used_by),
        content=skills.content(ctx.settings.skills_dir, skill.name) if content else None,
        digest=skills.digest(skill.path) if content else None,
        scan=skill_scan.scan(skill.path) if content else None,
    )


def giver(ctx: Context, project_id: str) -> ProjectRecord:
    """A project that is to give a skill to all its agents."""
    if (project := ctx.projects.get(project_id)) is None:
        raise ProblemError(400, "unknown project", project_id)
    return project


def existing_skill(ctx: Context, name: str) -> skills.LoadedSkill:
    if not skills.exists(ctx.settings.skills_dir, name):
        raise ProblemError(404, "skill not found", name)
    return skills.get(ctx.settings.skills_dir, name)


def add_skill_routes(app: FastAPI, ctx: Context) -> None:
    """The library's skills (skills.py), offered to every agent; projects give some to all their
    agents. Every change is allowed while agents use a skill: they follow a rename, and lose it
    when it is deleted (their running sandboxes keep what they mounted)."""
    authed = [Depends(ctx.require_auth)]
    directory = ctx.settings.skills_dir

    def info(skill: skills.LoadedSkill, content: bool = False) -> SkillInfo:
        return skill_info(ctx, skill, content)

    def existing(name: str) -> skills.LoadedSkill:
        return existing_skill(ctx, name)

    def parsed(body: SkillRequest) -> tuple[str, list[ProjectRecord]]:
        """The skill's name (its SKILL.md's) and the projects that give it to all their agents."""
        try:
            name, _ = skills.parse(body.content)
        except skills.SkillError as e:
            raise ProblemError(422, "invalid SKILL.md", str(e)) from None
        return name, [giver(ctx, p) for p in body.projects]

    @app.get("/v1/skills", dependencies=authed)
    def list_skills() -> Response:
        return dump([info(s) for s in skills.load_all(directory)])

    @app.get("/v1/skills/{name}", dependencies=authed)
    def read_skill(name: str) -> Response:
        return dump(info(existing(name), content=True))

    @app.post("/v1/skills", dependencies=authed)
    async def create_skill(request: Request) -> Response:
        """A new skill, from its SKILL.md; `copyOf`: with the other files of that skill."""
        body = parse_body(CreateSkillRequest, await request.body())
        name, givers = parsed(body)
        if body.copy_of is not None:
            existing(body.copy_of)
        if skills.exists(directory, name):
            raise ProblemError(409, "skill exists", name)
        if body.copy_of is not None:
            (directory / name).mkdir(parents=True)
            skills.copy(directory / body.copy_of, directory / name)
        skills.save(directory, body.content)
        ctx.projects.give_skill(None, name, givers)
        log.info("skill %s created%s", name, f" from {body.copy_of}" if body.copy_of else "")
        return dump(info(skills.get(directory, name), content=True), status=201)

    @app.put("/v1/skills/{name}", dependencies=authed)
    async def replace_skill(name: str, request: Request) -> Response:
        """Its SKILL.md and the projects giving it; a new name in the SKILL.md renames it."""
        existing(name)
        body = parse_body(SkillRequest, await request.body())
        new, givers = parsed(body)
        if new != name and skills.exists(directory, new):
            raise ProblemError(409, "skill exists", new)
        skills.save(directory, body.content, old=name)
        ctx.projects.give_skill(name, new, givers)
        log.info("skill %s saved", new)
        return dump(info(skills.get(directory, new), content=True))

    @app.delete("/v1/skills/{name}", dependencies=authed)
    def delete_skill(name: str) -> Response:
        """Its folder; the agents using it lose it."""
        existing(name)
        skills.delete(directory, name)
        ctx.projects.drop_skill(name)
        log.info("skill %s deleted", name)
        return Response(status_code=204)


def add_skill_file_routes(app: FastAPI, ctx: Context) -> None:
    """A skill's other files, one at a time (its SKILL.md: add_skill_routes)."""
    authed = [Depends(ctx.require_auth)]
    directory = ctx.settings.skills_dir

    def info(skill: skills.LoadedSkill, content: bool = False) -> SkillInfo:
        return skill_info(ctx, skill, content)

    def existing(name: str) -> skills.LoadedSkill:
        return existing_skill(ctx, name)

    @app.get("/v1/skills/{name}/files/{path:path}", dependencies=authed)
    def read_skill_file(name: str, path: str) -> Response:
        existing(name)
        try:
            data, is_executable = skills.read_file(directory, name, path)
        except FileNotFoundError:
            raise ProblemError(404, "file not found", path) from None
        except skills.SkillError as e:
            raise ProblemError(400, "invalid path", str(e)) from None
        text = None
        if b"\x00" not in data:
            with contextlib.suppress(UnicodeDecodeError):
                text = data.decode()
        return dump(SkillFile(path=path, size=len(data), executable=is_executable, text=text))

    @app.put("/v1/skills/{name}/files/{path:path}", dependencies=authed)
    async def write_skill_file(name: str, path: str, request: Request) -> Response:
        """Create or replace one of its files (its SKILL.md: PUT /v1/skills/{name})."""
        existing(name)
        body = parse_body(SkillFileRequest, await request.body())
        try:
            data = body.text.encode() if body.text is not None else b64decode(body.base64 or "")
            skills.write_file(directory, name, path, data, body.executable)
        except binascii.Error:
            raise ProblemError(422, "invalid request", "base64: not base64") from None
        except skills.SkillError as e:
            raise ProblemError(422, "invalid file", str(e)) from None
        log.info("skill %s: %s saved", name, path)
        return dump(info(skills.get(directory, name)))

    @app.delete("/v1/skills/{name}/files/{path:path}", dependencies=authed)
    def delete_skill_file(name: str, path: str) -> Response:
        existing(name)
        try:
            skills.delete_file(directory, name, path)
        except FileNotFoundError:
            raise ProblemError(404, "file not found", path) from None
        except skills.SkillError as e:
            raise ProblemError(422, "invalid file", str(e)) from None
        log.info("skill %s: %s deleted", name, path)
        return dump(info(skills.get(directory, name)))


def add_skill_archive_routes(app: FastAPI, ctx: Context) -> None:
    """Whole skills as zip archives, out and in."""
    authed = [Depends(ctx.require_auth)]
    directory = ctx.settings.skills_dir

    @app.get("/v1/skills/{name}/archive", dependencies=authed)
    def export_skill(name: str) -> Response:
        """The skill as a zip archive, its folder inside (as a `.skill` file is)."""
        existing_skill(ctx, name)
        disposition = f'attachment; filename="{name}.zip"'
        return Response(
            skills.pack(directory, name),
            media_type="application/zip",
            headers={"Content-Disposition": disposition},
        )

    @app.post("/v1/skills/import", dependencies=authed)
    async def import_skill(
        request: Request, project: str | None = None, replace: bool = False
    ) -> Response:
        """A skill from a zip archive (the body). A new one is given to `project`'s agents (absent:
        to none yet); `replace` puts it over the skill of its name, which keeps its projects and
        agents (409 without it)."""
        if int(request.headers.get("content-length") or 0) > MAX_SKILL_ARCHIVE_BYTES:
            raise ProblemError(413, "archive too large", f"at most {MAX_SKILL_ARCHIVE_BYTES} bytes")
        data = await request.body()
        if len(data) > MAX_SKILL_ARCHIVE_BYTES:
            raise ProblemError(413, "archive too large", f"at most {MAX_SKILL_ARCHIVE_BYTES} bytes")
        try:
            name, files = skills.unpack(data)
        except skills.SkillError as e:
            raise ProblemError(422, "not a skill archive", str(e)) from None
        return imported(name, files, project, replace)

    @app.post("/v1/skills/import-session/{session_id}", dependencies=authed)
    async def import_skill_session(
        session_id: str, project: str | None = None, replace: bool = False
    ) -> Response:
        """A folderless agent's session's folder as a skill (D.18); then as an archive's
        import."""
        record = ctx.get_session(session_id)
        if Path(record.scope) != ctx.sessions.work_folder(record.id):
            raise ProblemError(409, "a session with a scope", "only a folderless agent's session")
        try:
            name, files = await asyncio.to_thread(skills.from_folder, Path(record.scope))
        except skills.SkillError as e:
            raise ProblemError(422, "not a skill", str(e)) from None
        return imported(name, files, project, replace)

    @app.post("/v1/skills/import-url", dependencies=authed)
    async def import_skill_url(
        request: Request, project: str | None = None, replace: bool = False
    ) -> Response:
        """A skill from a URL (skill_sources: a GitHub repository's folder, or a skill's https://
        archive), downloaded by handlerd; then as an archive's import."""
        body = parse_body(SkillUrlRequest, await request.body())
        try:
            name, files = await asyncio.to_thread(skill_sources.fetch, body.url)
        except skills.SkillError as e:
            raise ProblemError(422, "not a skill", str(e)) from None
        return imported(name, files, project, replace)

    def imported(
        name: str, files: dict[str, tuple[bytes, bool]], project: str | None, replace: bool
    ) -> Response:
        """Into the library: a new one given to `project`'s agents (None: to none yet), or over the
        skill of its name when `replace` (it keeps its projects and agents; 409 without it)."""
        givers = [] if project is None else [giver(ctx, project)]
        replaced = skills.exists(directory, name)
        if replaced and not replace:
            raise ProblemError(409, "skill exists", name)
        skills.install(directory, name, files)
        if not replaced:
            ctx.projects.give_skill(None, name, givers)
        log.info("skill %s imported (%d files)", name, len(files))
        imported = skill_info(ctx, skills.get(directory, name), content=True)
        return dump(imported, status=200 if replaced else 201)
