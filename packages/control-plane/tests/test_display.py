"""Unit tests: finding the host's Wayland display for agents that ask for one (A.6)."""

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from handler_control.display import DisplayError, wayland_socket


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


def test_explicit_socket_wins(runtime: Path) -> None:
    env = {"HANDLER_WAYLAND_SOCKET": str(runtime / "wayland-1"), "WAYLAND_DISPLAY": "wayland-9"}
    assert wayland_socket(env) == str(runtime / "wayland-1")


def test_wayland_display_name_or_path(runtime: Path) -> None:
    env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-1"}
    assert wayland_socket(env) == str(runtime / "wayland-1")
    env = {"XDG_RUNTIME_DIR": "/nowhere", "WAYLAND_DISPLAY": str(runtime / "wayland-1")}
    assert wayland_socket(env) == str(runtime / "wayland-1")


def test_the_only_socket_of_the_runtime_dir(runtime: Path) -> None:
    """handlerd as a systemd user service often has no WAYLAND_DISPLAY."""
    assert wayland_socket({"XDG_RUNTIME_DIR": str(runtime)}) == str(runtime / "wayland-1")


def test_several_sockets_need_a_choice(runtime: Path) -> None:
    second = socket.socket(socket.AF_UNIX)
    second.bind(str(runtime / "wayland-0"))
    try:
        with pytest.raises(DisplayError, match=r"several Wayland displays.*HANDLER_WAYLAND_SOCKET"):
            wayland_socket({"XDG_RUNTIME_DIR": str(runtime)})
    finally:
        second.close()


@pytest.mark.parametrize(
    "env",
    [
        {"XDG_RUNTIME_DIR": "/nowhere"},
        {"XDG_RUNTIME_DIR": "/nowhere", "WAYLAND_DISPLAY": "wayland-0"},
        {"HANDLER_WAYLAND_SOCKET": "/nowhere/wayland-0"},
    ],
)
def test_no_display_is_an_error(env: dict[str, str]) -> None:
    with pytest.raises(DisplayError, match="no Wayland display"):
        wayland_socket(env)


def test_not_a_socket_is_an_error(runtime: Path) -> None:
    with pytest.raises(DisplayError, match="no Wayland display"):
        wayland_socket({"HANDLER_WAYLAND_SOCKET": str(runtime / "wayland-1.lock")})
