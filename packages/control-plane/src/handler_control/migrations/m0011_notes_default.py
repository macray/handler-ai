"""The default notes root moves from ~/notes to <data>/notes (made by Handler, so there is
nothing to set up): someone who used ~/notes keeps it, as the root they chose.

    <config>/notes.toml   written as `root = "<home>/notes"` when it is absent and ~/notes is a folder
"""

import json
import os
from pathlib import Path

from ..settings import Settings


def migrate(settings: Settings) -> None:
    config = settings.config_dir / "notes.toml"
    old = Path.home() / "notes"
    if config.exists() or not old.is_dir():
        return
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f"root = {json.dumps(os.path.realpath(old))}\n")  # JSON string = TOML one
