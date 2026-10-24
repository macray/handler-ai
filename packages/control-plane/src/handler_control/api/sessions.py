"""Session routes: daemon-held chats created, listed, stopped, shared, their folders read (F)."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    CreateSessionRequest,
    RevealRequest,
    SessionAppDraft,
    SessionInput,
    SessionSubject,
    SetSessionRemoteRequest,
)

from .. import desktop, interfaces, save_rules, session_files, skills
from ..agents import AgentRecord
from ..sessions import SessionError, SessionRecord
from .common import (
    Context,
    ProblemError,
    check_problems,
    dump,
    parse_body,
)


def add_session_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    def out(record: SessionRecord, status: int = 200) -> Response:
        return dump(ctx.sessions.to_contract(record), status=status)

    @app.post("/v1/sessions", dependencies=authed)
    async def create_session(request: Request) -> Response:  # async: it starts on the event loop
        body = parse_body(CreateSessionRequest, await request.body())
        agent = ctx.get_agent(body.agent_id)
        if agent.app is not None:  # H.14: its app starts it (an ask, its screen, its schedule)
            why = f"{agent.name or agent.id} is one of the app {agent.app}'s parts: ask the app"
            raise ProblemError(409, "started by its app only", why)
        if body.prompt is not None and body.acp_session_id is not None:
            raise ProblemError(400, "a resumed session has its conversation", "no prompt")
        with check_problems():
            runs = save_rules.session_model(ctx.settings, agent, body.model)
        run, subject = checked_input(ctx, agent, body)
        check_from_skill(ctx, agent, body.from_skill)
        draft = app_draft(ctx, agent, body)
        record = ctx.sessions.create(
            agent,
            runs,
            body.acp_session_id,
            body.prompt,
            origin=body.origin,
            run=run,
            subject=subject,
            from_skill=body.from_skill,
            app_draft=draft,
        )
        return out(record, 202)

    @app.get("/v1/sessions", dependencies=authed)
    def list_sessions(agentId: str | None = None, subject: str | None = None) -> Response:  # noqa: N803 — query parameter name
        records = ctx.sessions.list(agentId)
        if subject is not None:
            records = [r for r in records if subject_of(r) == subject]
        return dump([ctx.sessions.to_contract(r) for r in records])

    @app.get("/v1/sessions/{session_id}", dependencies=authed)
    def inspect_session(session_id: str) -> Response:
        return out(ctx.get_session(session_id))

    @app.post("/v1/sessions/{session_id}/stop", dependencies=authed)
    async def stop_session(session_id: str) -> Response:
        record = ctx.get_session(session_id)
        await ctx.sessions.stop(session_id, "stopped", "explicit")
        return out(record)

    @app.post("/v1/sessions/{session_id}/cancel", dependencies=authed)
    async def cancel_turn(session_id: str) -> Response:
        record = ctx.get_session(session_id)
        await ctx.sessions.cancel(session_id)
        return out(record)

    @app.delete("/v1/sessions/{session_id}", dependencies=authed)
    async def delete_session(session_id: str) -> Response:
        ctx.get_session(session_id)
        if (opened := ctx.apps.preview_of(session_id)) is not None:
            await ctx.apps.close_draft(opened)  # a draft thrown away: its opened copy too
        await ctx.sessions.delete(session_id)
        return Response(status_code=204)

    @app.put("/v1/sessions/{session_id}/remote", dependencies=authed)
    async def share_session(session_id: str, request: Request) -> Response:
        record = ctx.get_session(session_id)
        body = parse_body(SetSessionRemoteRequest, await request.body())
        try:
            ctx.sessions.set_remote(session_id, body.enabled)
        except SessionError as e:
            raise ProblemError(409, "cannot share this session", str(e)) from None
        return out(record)

    add_folder_routes(app, ctx)


def add_folder_routes(app: FastAPI, ctx: Context) -> None:
    """A session's folder and what else its sandbox sees (F.8), read-only."""
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/sessions/{session_id}/changes", dependencies=authed)
    def session_changes(session_id: str) -> Response:
        record = ctx.get_session(session_id)
        baseline = ctx.sessions.baseline(session_id)
        return dump(session_files.changes(Path(record.scope), baseline, record.created_at))

    @app.get("/v1/sessions/{session_id}/mounts", dependencies=authed)
    def session_mounts(session_id: str) -> Response:
        record = ctx.get_session(session_id)
        return dump(session_files.mounts(ctx.sessions.mounts(session_id), record.scope))

    @app.get("/v1/sessions/{session_id}/folder", dependencies=authed)
    def session_folder(session_id: str, path: str = "", mount: str | None = None) -> Response:
        record = ctx.get_session(session_id)
        recorded = ctx.sessions.mounts(session_id)
        with shown_path():
            root, _ = session_files.mount_root(recorded, record.scope, mount)
            return dump(session_files.folder(root, path))

    @app.get("/v1/sessions/{session_id}/find", dependencies=authed)
    def session_find(session_id: str, q: str = "") -> Response:
        record = ctx.get_session(session_id)
        return dump(session_files.find(Path(record.scope), q))

    @app.get("/v1/sessions/{session_id}/file", dependencies=authed)
    def session_file(session_id: str, path: str, mount: str | None = None) -> Response:
        record = ctx.get_session(session_id)
        recorded = ctx.sessions.mounts(session_id)
        with shown_path():
            root, own = session_files.mount_root(recorded, record.scope, mount)
            baseline = ctx.sessions.baseline(session_id) if own else None
            return dump(session_files.read(root, path, baseline))

    @app.post("/v1/sessions/{session_id}/reveal", dependencies=authed)
    async def reveal(session_id: str, request: Request) -> Response:
        record = ctx.get_session(session_id)
        body = parse_body(RevealRequest, await request.body())
        recorded = ctx.sessions.mounts(session_id)
        with shown_path():
            root, _ = session_files.mount_root(recorded, record.scope, body.mount)
            path, is_folder = session_files.host_path(root, body.path)
        if not await asyncio.to_thread(desktop.reveal, path, is_folder):
            detail = "no file manager answered (org.freedesktop.FileManager1, xdg-open)"
            raise ProblemError(409, "cannot show it", detail)
        return Response(status_code=204)


@contextmanager
def shown_path() -> Iterator[None]:
    """F.8: a path of a session's folder that cannot be shown."""
    try:
        yield
    except session_files.PathError as e:
        if e.missing:
            raise ProblemError(404, "not found", str(e)) from None
        raise ProblemError(400, "path not shown", str(e)) from None


def checked_input(
    ctx: Context, agent: AgentRecord, body: CreateSessionRequest
) -> tuple[SessionInput | None, SessionSubject | None]:
    """D.18: an agent with an interface is started with an input, never a request; with the
    skill its skill field names, the run's subject."""
    if agent.interface is None:
        if body.input is not None:
            raise ProblemError(400, "input invalid", "this agent has no interface")
        return None, None
    if body.input is None or body.prompt is not None or body.acp_session_id is not None:
        raise ProblemError(
            400, "input invalid", "an agent with an interface is started with an input only"
        )
    try:
        subject = interfaces.check_input(agent.interface, body.input, ctx.settings.skills_dir)
    except interfaces.InterfaceError as e:
        raise ProblemError(400, "input invalid", str(e)) from None
    return body.input, subject


def check_from_skill(ctx: Context, agent: AgentRecord, name: str | None) -> None:
    """D.18: a folderless agent's session may start as a copy of a skill of the library."""
    if name is None:
        return
    if agent.scope is not None:
        raise ProblemError(400, "a folderless agent's only", "its sessions work in its folder")
    if (skill := skills.get(ctx.settings.skills_dir, name)).error:
        raise ProblemError(400, "skill unusable", f"{name}: {skill.error}")


def app_draft(
    ctx: Context, agent: AgentRecord, body: CreateSessionRequest
) -> tuple[SessionAppDraft, Path | None] | None:
    """H.15: a folderless agent's session may work on a draft of an app's code: a copy of an
    app's (one draft of it at a time), or an empty folder for a new app."""
    draft = body.app_draft
    if draft is None:
        return None
    if agent.scope is not None:
        raise ProblemError(400, "a folderless agent's only", "its sessions work in its folder")
    if body.from_skill is not None:
        raise ProblemError(400, "one folder", "a skill's copy or an app's draft, not both")
    if draft.app is None:
        return draft, None
    if draft.app not in ctx.apps.records:
        raise ProblemError(404, "app not found", draft.app)
    for other in ctx.sessions.list():
        if (other.app_draft or {}).get("app") == draft.app:
            why = f"continue it ({other.title or other.id}), use it or throw it away"
            raise ProblemError(409, f"a draft of {draft.app} is waiting", why)
    return draft, ctx.apps.source(draft.app)


def subject_of(record: SessionRecord) -> str | None:
    """ "skill:<name>": what a run worked on (D.18)."""
    return f"skill:{record.subject['skill']}" if record.subject else None
