"""Work folders (D.13): the folders agents may work in, owned by this computer. A project's folder
and an ad-hoc session's must be inside one (compose.check_scope). Stored as written (`~/…` kept)
in <config>/folders.toml, `roots = ["~/code"]`, edited in Settings → Folders; ~/code when unset.
Never one of the daemon's own folders, nor one containing them: an agent working there could use
the API as the user (contracts §2, invariant 5).
"""

import json
import os
import tomllib
from pathlib import Path

from handler_contracts import is_within

from .settings import Settings

CONFIG_FILE = "folders.toml"
DEFAULT = ["~/code"]


class FoldersError(ValueError):
    """Work folders that cannot be saved (not absolute, the daemon's own)."""


def daemon_folders(settings: Settings) -> list[Path]:
    """The daemon's own folders (its token, config, state and data): never given to an agent
    through the API (contracts §2, invariant 5)."""
    return [
        settings.config_dir,
        settings.bindings_dir,
        settings.accounts_dir,
        settings.providers_dir,
        settings.state_dir,
        settings.data_dir,
    ]


def written(settings: Settings) -> list[str]:
    """As saved, else the default. Read on every call: a change applies to the next check."""
    try:
        roots = tomllib.loads((settings.config_dir / CONFIG_FILE).read_text()).get("roots")
    except (OSError, tomllib.TOMLDecodeError):
        return list(DEFAULT)
    return [r for r in roots if isinstance(r, str)] if isinstance(roots, list) else list(DEFAULT)


def roots(settings: Settings) -> list[str]:
    """Absolute, symbolic links resolved."""
    return [os.path.realpath(os.path.expanduser(r)) for r in written(settings)]


def save(settings: Settings, entries: list[str]) -> list[str]:
    """Replace them (duplicates dropped, as written); FoldersError when one is not absolute or
    is, contains or is inside one of the daemon's folders."""
    guarded = [os.path.realpath(d) for d in daemon_folders(settings)]
    kept = list(dict.fromkeys(e.strip() for e in entries))
    for entry in kept:
        if not os.path.isabs(os.path.expanduser(entry)):
            raise FoldersError(f"{entry}: an absolute path, or one starting with ~/")
        real = os.path.realpath(os.path.expanduser(entry))
        if any(is_within(real, d) or is_within(d, real) for d in guarded):
            raise FoldersError(f"{entry} holds or is inside the daemon's own files")
    config = settings.config_dir / CONFIG_FILE
    config.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.with_suffix(".tmp")
    tmp.write_text(f"roots = {json.dumps(kept)}\n")  # a JSON array of strings is a TOML one
    tmp.replace(config)
    return kept
