"""Unit tests: finding the host's Wayland display for agents that ask for one (A.6). Both copies
of the search, handlerd's and the sandbox runtime's (the boundaries keep them apart), answer the
same cases."""

import socket
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest

from handler_control import display
from handler_sandbox_kit import display as runtime_display

COPIES = {"handlerd": display, "runtime": runtime_display}
ENV = ("HANDLER_WAYLAND_SOCKET", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR")


@pytest.fixture(params=sorted(COPIES))
def copy(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> ModuleType:
    """One copy of the search; WSLg's socket out of the way (these tests may run in WSL)."""
    module = COPIES[request.param]
    monkeypatch.setattr(module, "WSLG_SOCKET", tmp_path / "no-wslg")
    return module


@pytest.fixture
def wayland_socket(copy: ModuleType, monkeypatch: pytest.MonkeyPatch) -> Callable[..., str]:
    """The copy's search in `env`: handlerd's takes it, the runtime's reads its own environment."""

    def find(env: dict[str, str]) -> str:
        if copy is display:
            return display.wayland_socket(env)
        for name in ENV:
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return runtime_display.wayland_socket()

    return find


@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[Path]:
    sockets = []

    def listen(name: str) -> None:
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(tmp_path / name))
        sockets.append(s)

    listen("wayland-1")
    (tmp_path / "wayland-1.lock").touch()  # compositors leave lock files next to their sockets
    yield tmp_path
    for s in sockets:
        s.close()


@pytest.mark.rule("display.found-where-handlerd-runs")
def test_explicit_socket_wins(runtime: Path, wayland_socket: Callable[..., str]) -> None:
    env = {"HANDLER_WAYLAND_SOCKET": str(runtime / "wayland-1"), "WAYLAND_DISPLAY": "wayland-9"}
    assert wayland_socket(env) == str(runtime / "wayland-1")


@pytest.mark.rule("display.found-where-handlerd-runs")
def test_wayland_display_name_or_path(runtime: Path, wayland_socket: Callable[..., str]) -> None:
    env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-1"}
    assert wayland_socket(env) == str(runtime / "wayland-1")
    env = {"XDG_RUNTIME_DIR": "/nowhere", "WAYLAND_DISPLAY": str(runtime / "wayland-1")}
    assert wayland_socket(env) == str(runtime / "wayland-1")


@pytest.mark.rule("display.found-where-handlerd-runs")
def test_the_only_socket_of_the_runtime_dir(
    runtime: Path, wayland_socket: Callable[..., str]
) -> None:
    """handlerd as a systemd user service often has no WAYLAND_DISPLAY."""
    assert wayland_socket({"XDG_RUNTIME_DIR": str(runtime)}) == str(runtime / "wayland-1")


@pytest.mark.rule("display.found-where-handlerd-runs")
def test_several_sockets_need_a_choice(
    runtime: Path, copy: ModuleType, wayland_socket: Callable[..., str]
) -> None:
    second = socket.socket(socket.AF_UNIX)
    second.bind(str(runtime / "wayland-0"))
    try:
        with pytest.raises(
            copy.DisplayError, match=r"several Wayland displays.*HANDLER_WAYLAND_SOCKET"
        ):
            wayland_socket({"XDG_RUNTIME_DIR": str(runtime)})
    finally:
        second.close()


@pytest.mark.rule("display.found-where-handlerd-runs")
@pytest.mark.parametrize(
    "env",
    [
        {"XDG_RUNTIME_DIR": "/nowhere"},
        {"XDG_RUNTIME_DIR": "/nowhere", "WAYLAND_DISPLAY": "wayland-0"},
        {"HANDLER_WAYLAND_SOCKET": "/nowhere/wayland-0"},
    ],
)
def test_no_display_is_an_error(
    env: dict[str, str], copy: ModuleType, wayland_socket: Callable[..., str]
) -> None:
    with pytest.raises(copy.DisplayError, match="no Wayland display"):
        wayland_socket(env)


@pytest.mark.rule("display.found-where-handlerd-runs")
def test_not_a_socket_is_an_error(
    runtime: Path, copy: ModuleType, wayland_socket: Callable[..., str]
) -> None:
    with pytest.raises(copy.DisplayError, match="no Wayland display"):
        wayland_socket({"HANDLER_WAYLAND_SOCKET": str(runtime / "wayland-1.lock")})


@pytest.mark.rule("display.found-where-handlerd-runs")
def test_wslg_s_socket_when_the_runtime_dir_has_none(
    runtime: Path,
    copy: ModuleType,
    wayland_socket: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WSL with systemd: $XDG_RUNTIME_DIR is systemd's, WSLg's socket stays in /mnt/wslg."""
    monkeypatch.setattr(copy, "WSLG_SOCKET", runtime / "wayland-1")
    assert wayland_socket({"XDG_RUNTIME_DIR": "/nowhere"}) == str(runtime / "wayland-1")
    env = {"XDG_RUNTIME_DIR": "/nowhere", "WAYLAND_DISPLAY": "wayland-0"}
    assert wayland_socket(env) == str(runtime / "wayland-1")
    with pytest.raises(
        copy.DisplayError, match="no Wayland display"
    ):  # an explicit one is not replaced
        wayland_socket({"HANDLER_WAYLAND_SOCKET": "/nowhere/wayland-0"})
