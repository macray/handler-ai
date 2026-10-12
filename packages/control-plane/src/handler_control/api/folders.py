"""Work folder routes (D.13)."""

import os
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    WorkFolderInfo,
    WorkFolders,
    WorkFoldersInfo,
    is_within,
)

from .. import (
    folders,
)
from .common import Context, ProblemError, dump, log, parse_body


def add_folder_routes(app: FastAPI, ctx: Context) -> None:
    """D.13: the work folders, owned by this computer."""
    authed = [Depends(ctx.require_auth)]

    def info(written: list[str]) -> WorkFoldersInfo:
        """Each folder as written, where it is, whether it exists, and its projects."""
        found = []
        for root in written:
            path = os.path.realpath(os.path.expanduser(root))
            inside = [p.name for p in ctx.projects.projects.values() if is_within(p.folder, path)]
            found.append(
                WorkFolderInfo(root=root, path=path, exists=Path(path).is_dir(), projects=inside)
            )
        return WorkFoldersInfo(folders=found)

    @app.get("/v1/folders", dependencies=authed)
    def get_folders() -> Response:
        return dump(info(folders.written(ctx.settings)))

    @app.put("/v1/folders", dependencies=authed)
    async def put_folders(request: Request) -> Response:
        """The folders are the point of the call: no confirmation, but never the daemon's own
        (invariant 5). Applies to new sessions; a project outside them can no longer start one."""
        body = parse_body(WorkFolders, await request.body())
        try:
            saved = folders.save(ctx.settings, body.roots)
        except folders.FoldersError as e:
            raise ProblemError(403, "folder not allowed", str(e)) from None
        log.info("work folders set through the API: %s", saved)
        return dump(info(saved))
