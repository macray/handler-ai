"""Contract A.6 conformance, every runtime: a display is only the Wayland socket of the session it
runs in (A7), found by the runtime."""

from pathlib import Path

import pytest

from ...support.runtimes import Runtime
from ..conftest import gives_display, on_display, run, spec

PROBE = (
    'echo "${WAYLAND_DISPLAY:+set} ${DISPLAY-unset}";'
    ' curl -s -o /dev/null -w "%{http_code}" --unix-socket "$WAYLAND_DISPLAY" http://display/'
)


@pytest.mark.rule("display.only-the-wayland-socket")
def test_display_is_the_wayland_socket(runtime: Runtime, scope: Path, display_socket: str) -> None:
    """The process reaches that socket through WAYLAND_DISPLAY, with network none: the display
    is not egress."""
    doc = spec(scope, ["sh", "-c", PROBE], display=True)
    r = run(runtime.binary, doc, env=on_display(display_socket))
    if not gives_display(runtime.binary, display_socket):
        assert r.returncode == 64, r.stderr  # refused, never started without it (A1)
        return
    assert r.returncode == 0, r.stderr
    assert r.stdout.decode().splitlines() == ["set unset", "200"]


@pytest.mark.rule("display.only-when-asked")
def test_no_display_unless_asked(runtime: Runtime, scope: Path, display_socket: str) -> None:
    script = 'echo "${WAYLAND_DISPLAY-unset} ${DISPLAY-unset}"'
    r = run(runtime.binary, spec(scope, ["sh", "-c", script]), env=on_display(display_socket))
    assert r.stdout.decode().split() == ["unset", "unset"]


@pytest.mark.rule("sandbox.refuses-what-it-cannot-enforce")
def test_refused_where_no_display_is_found(runtime: Runtime, scope: Path, tmp_path: Path) -> None:
    doc = spec(scope, ["true"], display=True)
    r = run(runtime.binary, doc, env=on_display(str(tmp_path / "none")))
    assert r.returncode == 64
    assert b"display" in r.stderr


@pytest.mark.rule("display.only-the-wayland-socket", "sandbox.an-invalid-spec-is-refused")
def test_display_env_is_the_implementation_s(runtime: Runtime, scope: Path) -> None:
    doc = spec(scope, ["true"], display=True, env={"WAYLAND_DISPLAY": "wayland-1"})
    assert run(runtime.binary, doc).returncode == 65
