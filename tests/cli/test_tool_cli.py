"""`handler tool …` (G.5) against a real handlerd."""

from pathlib import Path

import pytest

from ..support.daemon import Daemon
from .test_cli import handler

MANIFEST = 'apiVersion = "handler.tool/v1"\nname = "memo"\negress = ["memo.example.com:443"]\n'


def test_sources_list_what_they_offer(daemon: Daemon) -> None:
    out = handler(daemon, "source", "list").stdout
    assert "official ·" in out and "Handler's" in out
    assert "fake-shop" in out and "fake-browser" in out and "journal" in out
    # where the installed one came from
    assert "source:official/fake-shop" in handler(daemon, "tool", "list").stdout
    added = handler(daemon, "source", "add", "https://example.invalid/acme")  # asked: no terminal
    assert added.returncode == 1 and "Handler does not check" in added.stdout


@pytest.mark.rule("tool.installed-as-previewed")
def test_add_shows_what_it_brings_then_installs(daemon: Daemon, tmp_path: Path) -> None:
    folder = tmp_path / "memo"
    folder.mkdir()
    (folder / "tool.toml").write_text(MANIFEST)
    asked = handler(daemon, "tool", "add", str(folder))  # no terminal to answer: nothing installed
    assert asked.returncode == 1 and "hosts   memo.example.com:443" in asked.stdout
    assert "memo" not in handler(daemon, "tool", "list").stdout
    added = handler(daemon, "tool", "add", str(folder), "--yes")
    assert added.returncode == 0 and "installed memo" in added.stdout
    assert str(folder) in handler(daemon, "tool", "list").stdout
    assert handler(daemon, "tool", "rm", "memo").returncode == 0
    assert "memo" not in handler(daemon, "tool", "list").stdout


@pytest.mark.rule("tool.installed-as-previewed")
def test_add_says_what_it_adds_to_the_toolbox(daemon: Daemon, tmp_path: Path) -> None:
    """B.6: the system packages it adds (their scripts run as root), what nothing provides."""
    folder = tmp_path / "web"
    folder.mkdir()
    (folder / "tool.toml").write_text(
        'apiVersion = "handler.tool/v1"\nname = "web"\nneeds = ["chromium", "nothing-gives"]\n'
    )
    asked = handler(daemon, "tool", "add", str(folder))  # no terminal: nothing installed
    assert asked.returncode == 1
    assert "adds    chromium to the toolbox, for chromium (installed)" in asked.stdout
    assert "lacks   nothing-gives: no system package gives it" in asked.stdout
