"""The notes history's routes (D.5): the changes of a folder others write (a read-write notes
folder, an app's), one change's files and lines, undo. Web UI only (no CLI)."""

import asyncio
import contextlib
from collections.abc import Iterator

from fastapi import Depends, FastAPI, Request, Response

from handler_contracts import NotesUndoRequest

from ..notes_history import NotesHistoryConflictError, NotesHistoryError, NotesHistoryMissingError
from .common import Context, ProblemError, dump, parse_body


@contextlib.contextmanager
def history_problems() -> Iterator[None]:
    try:
        yield
    except NotesHistoryMissingError as e:
        raise ProblemError(404, "no such history", str(e)) from None
    except NotesHistoryConflictError as e:
        raise ProblemError(409, "cannot undo", str(e)) from None
    except NotesHistoryError as e:
        raise ProblemError(400, "notes unusable", str(e)) from None


def add_notes_history_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/knowledge/history", dependencies=authed)
    def notes_history(folder: str) -> Response:
        with history_problems():
            return dump(ctx.notes.history(folder))

    @app.get("/v1/knowledge/history/{commit_id}", dependencies=authed)
    def notes_change(folder: str, commit_id: str) -> Response:
        with history_problems():
            return dump(ctx.notes.commit(folder, commit_id))

    @app.post("/v1/knowledge/history/undo", dependencies=authed)
    async def undo_notes_change(request: Request) -> Response:
        body = parse_body(NotesUndoRequest, await request.body())
        with history_problems():
            return dump(await asyncio.to_thread(ctx.notes.undo, body.folder, body.commit))
