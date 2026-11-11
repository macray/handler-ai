"""The web UI's sign-in (contract D.2): `handler ui` asks a one-time link, the browser opening it
gets the UI's cookie, kept a year; from then on a bookmark opens the UI (auth.py says which
requests the cookie is taken on)."""

from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from handler_contracts import UiLink, UiOpenRequest

from .. import auth
from .common import Context, dump, parse_body

EXPIRED = """<!doctype html><meta charset="utf-8"><title>Handler</title>
<p>This link has been used or is too old. Run <code>handler ui</code> on this computer to open
Handler again.</p>"""


def add_ui_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.post("/v1/ui/open", dependencies=authed)
    async def open_ui(request: Request) -> Response:
        body = parse_body(UiOpenRequest, await request.body() or b"{}")
        query = f"code={ctx.ui_links.new()}"
        if body.then:
            query += f"&then={quote(body.then)}"
        base = str(request.base_url).rstrip("/")  # the address the client reached handlerd at
        return dump(UiLink(url=f"{base}/v1/ui/login?{query}"))

    @app.get("/v1/ui/login")
    def login(code: str = "", then: str = "/") -> Response:
        """Not authenticated: the code is. Opens the page asked for, with the cookie set."""
        if not ctx.ui_links.redeem(code):
            return HTMLResponse(EXPIRED, status_code=403)
        page = then if then.startswith("/") and not then.startswith("//") else "/"
        response = RedirectResponse(f"/#{page}", status_code=303)
        response.set_cookie(
            auth.UI_COOKIE,
            auth.ui_cookie(ctx.token),
            max_age=auth.UI_COOKIE_MAX_AGE,
            path="/",
            httponly=True,
            samesite="strict",
        )
        return response

    @app.get("/v1/ui/signed-in", dependencies=authed)
    def signed_in() -> Response:
        """204 when the browser's cookie opens the UI; 401 otherwise."""
        return Response(status_code=204)
