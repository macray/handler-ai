"""Migrations: the only code that knows an older format of Handler's files.

Everything else reads and writes the current format only. When a release changes the format of
something a user keeps (config in `~/.config/handler-ai/`, state, data), it adds one module here,
`m<NNNN>_<what>.py` with `migrate(settings)` that rewrites the old format into the new one, and
appends it to MIGRATIONS. handlerd runs the ones not run yet before anything reads those files.

    <state_dir>/format-version   how many migrations this computer's files have had (absent: 0)

A migration runs once per computer, in order, and must not fail on files that are not there (a
fresh install runs them all, on nothing). One that fails stops handlerd with its reason: nothing
reads files half in the old format. Files written by a newer Handler (a version above
len(MIGRATIONS)) stop it too, rather than being read wrong.

Format 0: the files as they were on 2026-10-21; those of 0.1 are not migrated.
"""

import logging
from collections.abc import Callable

from ..files import write_private
from ..settings import Settings
from . import (
    m0001_agent_home,
    m0002_no_app_shortcuts,
    m0003_chat_and_handler_needs,
    m0004_apps,
    m0005_sources,
    m0006_file_slots_in_folders,
    m0007_addon_uses,
    m0008_toolbox_manifest,
    m0009_kept_blocked,
    m0010_pins,
    m0011_notes_default,
    m0012_push_keys,
)

log = logging.getLogger("handler.migrations")

# in order; the format version is the number of migrations run
MIGRATIONS: list[Callable[[Settings], None]] = [
    m0001_agent_home.migrate,
    m0002_no_app_shortcuts.migrate,
    m0003_chat_and_handler_needs.migrate,
    m0004_apps.migrate,
    m0005_sources.migrate,
    m0006_file_slots_in_folders.migrate,
    m0007_addon_uses.migrate,
    m0008_toolbox_manifest.migrate,
    m0009_kept_blocked.migrate,
    m0010_pins.migrate,
    m0011_notes_default.migrate,
    m0012_push_keys.migrate,
]

VERSION_FILE = "format-version"


class MigrationError(Exception):
    """handlerd cannot start on these files: the reason, for the person."""


def current(settings: Settings) -> int:
    path = settings.state_dir / VERSION_FILE
    try:
        return int(path.read_text().strip())
    except FileNotFoundError:
        return 0
    except ValueError:
        raise MigrationError(f"{path} is not a number: write the format version in it") from None


def run(settings: Settings) -> None:
    """Bring this computer's files to the current format. MigrationError when it cannot."""
    done = current(settings)
    if done > len(MIGRATIONS):
        raise MigrationError(
            f"these files were written by a newer Handler (format {done}, this one knows "
            f"{len(MIGRATIONS)}): install that version again"
        )
    for number, migrate in enumerate(MIGRATIONS[done:], start=done + 1):
        log.info("migration %d: %s", number, migrate.__module__.rsplit(".", 1)[-1])
        try:
            migrate(settings)
        except Exception as e:
            raise MigrationError(f"migration {number} failed: {e}") from e
        write_version(settings, number)


def write_version(settings: Settings, number: int) -> None:
    write_private(settings.state_dir / VERSION_FILE, f"{number}\n")
