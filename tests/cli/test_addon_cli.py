"""`handler addon …` (G.5) against a real handlerd."""

from pathlib import Path

from ..support.daemon import Daemon
from .test_cli import handler

MANIFEST = 'apiVersion = "handler.addon/v1"\nname = "memo"\negress = ["memo.example.com:443"]\n'


def test_sources_list_what_they_offer(daemon: Daemon) -> None:
    out = handler(daemon, "source", "list").stdout
    assert "official ·" in out and "Handler's" in out
    assert "fake-shop" in out and "fake-browser" in out and "journal" in out
    # where the installed one came from
    assert "source:official/fake-shop" in handler(daemon, "addon", "list").stdout
    added = handler(daemon, "source", "add", "https://example.invalid/acme")  # asked: no terminal
    assert added.returncode == 1 and "Handler does not check" in added.stdout


def test_add_shows_what_it_brings_then_installs(daemon: Daemon, tmp_path: Path) -> None:
    folder = tmp_path / "memo"
    folder.mkdir()
    (folder / "addon.toml").write_text(MANIFEST)
    asked = handler(daemon, "addon", "add", str(folder))  # no terminal to answer: nothing installed
    assert asked.returncode == 1 and "hosts   memo.example.com:443" in asked.stdout
    assert "memo" not in handler(daemon, "addon", "list").stdout
    added = handler(daemon, "addon", "add", str(folder), "--yes")
    assert added.returncode == 0 and "installed memo" in added.stdout
    assert str(folder) in handler(daemon, "addon", "list").stdout
    assert handler(daemon, "addon", "rm", "memo").returncode == 0
    assert "memo" not in handler(daemon, "addon", "list").stdout
