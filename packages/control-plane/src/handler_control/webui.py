"""Serving the web UI (a static client of C and D) and the folder picker it needs.

The UI is built separately (packages/web-ui → dist/); the daemon only serves files, with a strict
Content-Security-Policy: scripts, styles and connections only from the daemon itself, so agent
output rendered in the page cannot load or send anything elsewhere.
"""

import os
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from handler_contracts import DirectoryEntry, DirectoryListing, is_within

from .settings import Settings

MAX_ENTRIES = 500


class OutsideRootsError(ValueError):
    pass


class DirectoryExistsError(ValueError):
    pass


def list_directories(roots: list[str], path: str | None) -> DirectoryListing:
    """`roots`: the work folders (folders.roots), resolved."""
    if path is None:
        entries = [DirectoryEntry(name=r, path=r) for r in roots if Path(r).is_dir()]
        return DirectoryListing(path=None, parent=None, entries=entries)
    resolved = os.path.realpath(path)
    if not any(is_within(resolved, r) for r in roots) or not Path(resolved).is_dir():
        raise OutsideRootsError(f"{resolved} is not a directory inside the work folders")
    children = sorted(
        (
            e
            for e in os.scandir(resolved)
            if e.is_dir(follow_symlinks=False) and not e.name.startswith(".")
        ),
        key=lambda e: e.name.lower(),
    )[:MAX_ENTRIES]
    parent = None if resolved in roots else os.path.dirname(resolved)
    return DirectoryListing(
        path=resolved,
        parent=parent,
        entries=[
            DirectoryEntry(name=e.name, path=os.path.join(resolved, e.name)) for e in children
        ],
    )


def create_directory(roots: list[str], parent: str, name: str) -> DirectoryListing:
    """Create `parent/name` (one level, not hidden) and return its (empty) listing."""
    if name in (".", "..") or name.startswith(".") or "/" in name or "\0" in name:
        raise OutsideRootsError(f"invalid folder name {name!r}")
    listing = list_directories(roots, parent)  # checks parent is a directory inside the roots
    assert listing.path is not None
    target = Path(listing.path) / name
    try:
        target.mkdir()
    except FileExistsError:
        raise DirectoryExistsError(f"{target} already exists") from None
    return list_directories(roots, str(target))


def content_security_policy(settings: Settings) -> str:
    ws = f"ws://127.0.0.1:{settings.port} ws://localhost:{settings.port}"
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",  # Svelte transitions set inline styles
            "img-src 'self' data:",
            f"connect-src 'self' {ws}",
            "frame-ancestors 'none'",
            "base-uri 'none'",
            "form-action 'none'",
        ]
    )


class SecurityHeaders(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, csp: str) -> None:
        super().__init__(app)
        self.csp = csp

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if not request.url.path.startswith("/v1/"):
            response.headers["Content-Security-Policy"] = self.csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


def mount(app: FastAPI, settings: Settings) -> None:
    """Serve the built UI at / if present (after every API route, so /v1 always wins)."""
    app.add_middleware(SecurityHeaders, csp=content_security_policy(settings))
    if (settings.web_ui_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.web_ui_dir, html=True), name="web-ui")
