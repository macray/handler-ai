"""Cache routes (D.8): the toolbox's caches, their folders and sizes, emptying them."""

import contextlib
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import CacheSizes, CachesRequest

from .. import caches, runtime
from .common import Context, ProblemError, dump, log, parse_body


def add_cache_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    def info() -> Response:
        return dump(caches.info(ctx.settings, ctx.projects.projects.values()))

    @app.get("/v1/caches", dependencies=authed)
    def get_caches() -> Response:
        return info()

    @app.put("/v1/caches", dependencies=authed)
    async def put_caches(request: Request) -> Response:
        """The user's own, written to the toolbox's toolbox.toml; applies to new sessions. A
        removed cache's folders stay (emptied first if wanted, with DELETE below)."""
        body = parse_body(CachesRequest, await request.body())
        try:
            caches.save(body.caches)
        except caches.CacheError as e:
            raise ProblemError(400, "caches refused", str(e)) from None
        log.info("caches set through the API: %s", ", ".join(c.target for c in body.caches))
        return info()

    @app.get("/v1/caches/sizes", dependencies=authed)
    def cache_sizes() -> Response:
        """Measured on each call (it may take seconds: GET /v1/caches does not wait for it)."""
        listed = caches.info(ctx.settings, ctx.projects.projects.values())
        folders = [
            f
            for x in (listed.global_, *listed.own)
            for f in (*x.caches.values(), *x.removed.values())
        ]
        try:
            return dump(CacheSizes(sizes=runtime.cache_sizes(folders)))
        except RuntimeError as e:
            raise ProblemError(502, "cannot measure the caches", str(e)) from None

    def clear(folder: Path, what: str) -> Response:
        if reason := runtime.clear_cache(folder):
            raise ProblemError(409, "cache in use", reason)
        log.info("%s emptied through the API", what)
        return Response(status_code=204)

    def clear_one(root: Path, name: str, what: str) -> Response:
        """A declared cache's folder emptied; what a removed one left emptied, then its folder
        removed: no longer listed."""
        declared = caches.declared()
        if name in declared:
            return clear(root / name, what)
        if name not in caches.left(root, declared):
            raise ProblemError(404, "cache not found", name)
        response = clear(root / name, f"what {what} left")
        with contextlib.suppress(OSError):
            (root / name).rmdir()
        return response

    @app.delete("/v1/caches/files", dependencies=authed)
    def clear_global() -> Response:
        return clear(ctx.settings.cache_dir, "global caches")

    @app.delete("/v1/caches/{name}/files", dependencies=authed)
    def clear_global_cache(name: str) -> Response:
        return clear_one(ctx.settings.cache_dir, name, f"global cache {name}")

    @app.delete("/v1/projects/{project_id}/caches", dependencies=authed)
    def clear_project(project_id: str) -> Response:
        project = ctx.get_project(project_id)
        return clear(caches.project_dir(ctx.settings, project.id), f"caches of {project.name}")

    @app.delete("/v1/projects/{project_id}/caches/{name}/files", dependencies=authed)
    def clear_project_cache(project_id: str, name: str) -> Response:
        project = ctx.get_project(project_id)
        root = caches.project_dir(ctx.settings, project.id)
        return clear_one(root, name, f"cache {name} of {project.name}")
