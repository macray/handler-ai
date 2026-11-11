"""The menu's Pinned holds projects and apps, mixed, in the person's order (D.28): a project no
longer knows whether it is pinned.

    <state>/projects.json   each project loses `pinned`
    <state>/pins.json       the projects that were pinned, in the menu's order until now: by area
                            (in areas.toml's order, those of no area last), then by name
"""

import contextlib
import json
import tomllib

from ..files import write_private
from ..settings import Settings


def migrate(settings: Settings) -> None:
    path = settings.state_dir / "projects.json"
    if not path.exists():
        return
    projects = json.loads(path.read_text())
    areas: list[str] = []
    with contextlib.suppress(OSError, tomllib.TOMLDecodeError):
        areas = list(tomllib.loads((settings.config_dir / "areas.toml").read_text()))

    def menu_order(p: dict) -> tuple[int, str]:
        area = p.get("area")
        return (areas.index(area) if area in areas else len(areas), p["name"].casefold())

    pinned = sorted((p for p in projects if p.pop("pinned", True)), key=menu_order)
    pins = [{"kind": "project", "id": p["id"]} for p in pinned]
    write_private(settings.state_dir / "pins.json", json.dumps(pins, indent=2))
    write_private(path, json.dumps(projects, indent=2))
