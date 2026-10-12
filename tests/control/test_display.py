"""An agent's display (contracts D, A.6), through a real handlerd: only an agent that asks for a
display gives its agent one, and asking for one without a display is refused.

The agent is the fake agent on the host (the fake sandbox): it reports the WAYLAND_DISPLAY it got.
"""

import json
import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from ..support.daemon import Daemon, start_daemon

SOCKET_DIR = Path(tempfile.mkdtemp(prefix="handler-display-"))
SOCKET = SOCKET_DIR / "wayland-0"


@pytest.fixture(scope="module")
def display() -> Iterator[socket.socket]:
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(SOCKET))
    yield server
    server.close()


@pytest.fixture(scope="module")
def daemon(display: socket.socket) -> Iterator[Daemon]:
    yield from start_daemon(extra_env={"HANDLER_WAYLAND_SOCKET": str(SOCKET)})


def seen_display(daemon: Daemon, ad_hoc: dict[str, Any], scope: Path) -> str | None:
    client = daemon.connect(ad_hoc["acpUrl"])
    try:
        client.initialize()
        session = client.new_session(str(scope))["sessionId"]
        client.prompt(session, "report")
        return json.loads(client.text())["display"]
    finally:
        client.close()


def test_display_only_for_agents_that_ask(daemon: Daemon, display: socket.socket) -> None:
    assert httpx.get(f"{daemon.base_url}/v1/health").json()["display"] is True
    scope = daemon.make_scope()
    plain = daemon.create_ad_hoc("fake", scope)
    shown = daemon.create_ad_hoc("fake", scope, display=True, name="shown")
    assert plain["display"] is False and shown["display"] is True
    assert plain["id"] != shown["id"]
    assert seen_display(daemon, plain, scope) is None
    assert seen_display(daemon, shown, scope) == str(SOCKET)

    display.close()
    SOCKET.unlink()  # the Wayland session ended
    assert httpx.get(f"{daemon.base_url}/v1/health").json()["display"] is False
    with daemon.http() as c:
        r = c.post(
            "/v1/agents",
            json={"models": [{"account": "fake"}], "scope": str(scope), "display": True},
        )
    assert r.status_code == 409 and "no Wayland display" in r.json()["detail"]
