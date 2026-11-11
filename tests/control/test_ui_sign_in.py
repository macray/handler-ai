"""The web UI's sign-in (D.2): `handler ui` opens a one-time link, the browser keeps a cookie, and
the cookie is taken only on requests from the UI's own pages (rules connect.only-with-the-token,
connect.the-ui-cookie-only-from-its-own-pages)."""

import subprocess
from typing import Any

import httpx
import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from handler_contracts import ACP_SUBPROTOCOL

from ..cli.test_cli import HANDLER, env
from ..support.daemon import UI_ORIGIN, Daemon

SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


def signed_in(daemon: Daemon, then: str | None = None) -> tuple[str, httpx.Response]:
    """The UI's cookie, as a browser gets it from a link of `handler ui`; and the login's answer."""
    with daemon.http() as c:
        url = c.post("/v1/ui/open", json={"then": then} if then else {}).json()["url"]
    login = httpx.get(url, follow_redirects=False)
    return login.cookies["handler-ui"], login


def as_browser(daemon: Daemon, cookie: str, **headers: str) -> httpx.Client:
    return httpx.Client(
        base_url=daemon.base_url, cookies={"handler-ui": cookie}, headers=headers, timeout=30
    )


@pytest.mark.rule("connect.only-with-the-token")
def test_handler_ui_opens_a_one_time_link(daemon: Daemon) -> None:
    r = subprocess.run(
        [HANDLER, "ui", "--print"], env=env(daemon), capture_output=True, text=True, check=True
    )
    url = r.stdout.strip()
    assert url.startswith(f"{daemon.base_url}/v1/ui/login?code=") and daemon.token not in url
    login = httpx.get(url, follow_redirects=False)
    assert login.status_code == 303 and login.headers["location"] == "/#/"
    set_cookie = login.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie
    assert daemon.token not in set_cookie
    assert httpx.get(url, follow_redirects=False).status_code == 403  # once only


def test_a_link_opens_the_page_asked_for(daemon: Daemon) -> None:
    _, login = signed_in(daemon, then="/setup/review")
    assert login.headers["location"] == "/#/setup/review"
    with daemon.http() as c:
        assert c.post("/v1/ui/open", json={"then": "//evil.test"}).status_code == 422


@pytest.mark.rule("connect.only-with-the-token", "connect.the-ui-cookie-only-from-its-own-pages")
def test_the_cookie_opens_the_ui_from_its_own_pages(daemon: Daemon) -> None:
    cookie, _ = signed_in(daemon)
    with as_browser(daemon, cookie, **SAME_ORIGIN) as c:  # the UI's own fetches
        assert c.get("/v1/ui/signed-in").status_code == 204
        assert c.get("/v1/accounts").status_code == 200
    with as_browser(daemon, cookie, Origin=UI_ORIGIN) as c:  # an allowed origin
        assert c.get("/v1/accounts").status_code == 200
    with as_browser(daemon, "0" * 64, **SAME_ORIGIN) as c:
        assert c.get("/v1/ui/signed-in").status_code == 401
    with httpx.Client(base_url=daemon.base_url, headers=SAME_ORIGIN) as c:
        assert c.get("/v1/ui/signed-in").status_code == 401


@pytest.mark.rule("connect.the-ui-cookie-only-from-its-own-pages")
def test_the_cookie_from_elsewhere_is_refused(daemon: Daemon) -> None:
    """Another port's page (same site for the browser), a page renamed to 127.0.0.1 (DNS
    rebinding), a request saying nothing of where it comes from."""
    cookie, _ = signed_in(daemon)
    port = daemon.base_url.rsplit(":", 1)[1]
    cases: list[dict[str, Any]] = [
        {"Sec-Fetch-Site": "same-site"},
        {"Sec-Fetch-Site": "same-site", "Origin": "http://127.0.0.1:5173"},
        {"Sec-Fetch-Site": "cross-site"},
        {},
        {"Sec-Fetch-Site": "same-origin", "Host": f"evil.test:{port}"},
    ]
    for headers in cases:
        with as_browser(daemon, cookie, **headers) as c:
            status = c.get("/v1/accounts").status_code
            assert status in (401, 403), headers
            assert c.delete("/v1/agents/nope").status_code in (401, 403), headers


@pytest.mark.rule("connect.the-ui-cookie-only-from-its-own-pages")
def test_a_websocket_takes_the_cookie_from_an_allowed_origin(daemon: Daemon) -> None:
    cookie, _ = signed_in(daemon)
    agent = daemon.create_ad_hoc("fake", daemon.make_scope())
    with connect(
        agent["acpUrl"],
        subprotocols=[ACP_SUBPROTOCOL],  # ty: ignore[invalid-argument-type]
        additional_headers={"Cookie": f"handler-ui={cookie}", "Origin": UI_ORIGIN},
    ) as ws:
        assert ws.subprotocol == ACP_SUBPROTOCOL
    with pytest.raises(InvalidStatus) as refused:
        connect(
            agent["acpUrl"],
            subprotocols=[ACP_SUBPROTOCOL],  # ty: ignore[invalid-argument-type]
            additional_headers={"Cookie": f"handler-ui={cookie}"},
        )
    assert refused.value.response.status_code == 401
