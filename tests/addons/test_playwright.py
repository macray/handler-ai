"""The playwright addon (browser design), end to end through handler-sandbox-podman: its
MCP server, started from the addon's folder the way a harness starts it (stdio), in a `strict`
sandbox.

- a local preview on the sandbox's 127.0.0.1 opens, whatever the network;
- with a filtered network the browser goes through the sandbox's proxy: an allowed host loads,
  another one does not;
- headless without a display; Wayland only when the sandbox is given one (A.6).

Needs podman, the toolbox and the addon built (`handler image rebuild addon:playwright`: its
folder, under Handler's data, mounted read-only here); the filtered network test needs the
internet.
"""

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import ADDONS_ROOT
from handler_control import addon_folders
from handler_control.settings import Settings

from ..sandbox.conftest import (  # noqa: F401 — display_socket: a fixture
    display_socket,
    on_display,
    requires_internet,
    run,
)
from ..support import dev_env

TOOLBOX = "localhost/handler-ai-toolbox:latest"
ADDON = addon_folders.folder(Settings.from_env(), "playwright")
TARGET = f"{ADDONS_ROOT}/playwright"
PROBE = (Path(__file__).parent / "mcp_probe.py").read_text()
LOCAL = "http://127.0.0.1:9292/"


def built() -> bool:
    try:
        toolbox = subprocess.run(["podman", "image", "exists", TOOLBOX], check=False)
    except OSError:
        return False
    return toolbox.returncode == 0 and ADDON.is_dir()


pytestmark = [
    pytest.mark.skipif(not built(), reason=f"{TOOLBOX} or {ADDON} missing"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


@pytest.fixture
def scope() -> Iterator[Path]:
    path = dev_env.make_scope()
    yield path
    dev_env.remove_scope(path)


def probe(
    scope: Path, urls: list[str], env: dict[str, str] | None = None, **overrides: Any
) -> dict[str, Any]:
    """Run the addon's MCP server (its manifest's `mcp.command`) under the probe, in a sandbox
    composed as G4 does: the addon's folder mounted, its bin/ on PATH."""
    doc: dict[str, Any] = {
        "apiVersion": "handler.sandbox/v2",
        "name": f"handler-test-pw-{scope.name[-8:].lower().replace('_', '-')}",
        "image": TOOLBOX,
        "argv": ["python3", "/opt/handler/probe.py", *urls, "--", "playwright-mcp"],
        "env": {},
        "workdir": str(scope),
        "home": "/home/agent",
        "workFolder": {"path": str(scope)},
        "addons": [{"source": str(ADDON), "target": TARGET, "path": f"{TARGET}/bin"}],
        "tools": [{"target": "/opt/handler/probe.py", "content": PROBE}],
        "network": {"mode": "none"},
    } | overrides
    r = run("handler-sandbox-podman", doc, timeout=240, env=env)
    assert r.returncode == 0, r.stderr.decode()[-3000:]
    return json.loads(r.stdout.decode().splitlines()[-1])


def main_browsers(report: dict[str, Any]) -> list[str]:
    """The browser process Playwright drives (over --remote-debugging-pipe), not its renderers,
    GPU… processes (`--type=…`) or crash handler."""
    return [b for b in report["browsers"] if "--remote-debugging-pipe" in b and "--type=" not in b]


def test_local_preview_headless_without_display(scope: Path) -> None:
    report = probe(scope, [LOCAL])
    local = report["navigations"][LOCAL]
    assert not local["error"] and "handler preview" in local["text"]
    main = main_browsers(report)
    assert main and all("--headless" in b for b in main)
    assert not any("--ozone-platform=wayland" in b for b in report["browsers"])


@requires_internet
def test_filtered_goes_through_the_sandbox_proxy(scope: Path) -> None:
    allowed, denied = "https://example.com/", "https://example.org/"
    network = {"mode": "filtered", "allow": ["example.com:443"], "enforcement": "enforce"}
    report = probe(scope, [LOCAL, allowed, denied], network=network)
    nav = report["navigations"]
    assert not nav[LOCAL]["error"], nav[LOCAL]  # loopback bypasses the proxy
    assert not nav[allowed]["error"] and "Example Domain" in nav[allowed]["text"], nav[allowed]
    assert nav[denied]["error"], nav[denied]
    assert all("--proxy-server" in b for b in main_browsers(report))


def test_display_makes_it_headed_on_wayland(scope: Path, display_socket: str) -> None:  # noqa: F811
    """Given a display, the browser is started for Wayland (here a fake socket, so it cannot draw:
    the launch fails, and Playwright's error shows how it was started)."""
    report = probe(scope, [LOCAL], env=on_display(display_socket), display=True)
    local = report["navigations"][LOCAL]
    assert local["error"] and "--ozone-platform=wayland" in local["text"], local
    assert "--headless" not in local["text"]
