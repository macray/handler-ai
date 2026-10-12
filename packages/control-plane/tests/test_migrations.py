"""Migrations: the user's files brought to the current format at handlerd's start, once each."""

from pathlib import Path

import pytest

from handler_control import migrations
from handler_control.settings import Settings


def settings(tmp_path: Path) -> Settings:
    return Settings(
        port=0,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path / "config" / "bindings",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
    )


def test_each_migration_runs_once_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    monkeypatch.setattr(
        migrations, "MIGRATIONS", [lambda s: ran.append("a"), lambda s: ran.append("b")]
    )
    s = settings(tmp_path)
    migrations.run(s)
    assert ran == ["a", "b"] and migrations.current(s) == 2
    migrations.run(s)
    assert ran == ["a", "b"]


def test_only_the_new_ones_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    s = settings(tmp_path)
    migrations.write_version(s, 1)
    monkeypatch.setattr(
        migrations, "MIGRATIONS", [lambda s: ran.append("a"), lambda s: ran.append("b")]
    )
    migrations.run(s)
    assert ran == ["b"] and migrations.current(s) == 2


def test_a_failure_stops_and_keeps_the_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(s: Settings) -> None:
        raise ValueError("bad file")

    monkeypatch.setattr(migrations, "MIGRATIONS", [lambda s: None, broken])
    s = settings(tmp_path)
    with pytest.raises(migrations.MigrationError, match="migration 2 failed: bad file"):
        migrations.run(s)
    assert migrations.current(s) == 1


def test_files_of_a_newer_handler_are_refused(tmp_path: Path) -> None:
    s = settings(tmp_path)
    migrations.write_version(s, len(migrations.MIGRATIONS) + 1)
    with pytest.raises(migrations.MigrationError, match="newer Handler"):
        migrations.run(s)
