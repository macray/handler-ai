"""Pinned (D.28): the projects and apps the person put in the web UI's menu, mixed, in their
order. Kept here rather than in the browser, so the menu is the same on every one.

    <state>/pins.json   [{"kind": "project" | "app", "id": project id | app name}, …], in order

The routes check that each pin names something that exists (api/pins.py); deleting a project or
uninstalling an app takes its pin off (projects.py, apps.py).
"""

import json
from pathlib import Path

from handler_contracts import Pin, PinKind

from .files import write_private

FILE = "pins.json"


def load(state_dir: Path) -> list[Pin]:
    path = state_dir / FILE
    if not path.exists():
        return []
    return [Pin.model_validate(p) for p in json.loads(path.read_text())]


def save(state_dir: Path, pins: list[Pin]) -> None:
    write_private(state_dir / FILE, json.dumps([p.model_dump(mode="json") for p in pins], indent=2))


def add(state_dir: Path, pin: Pin) -> None:
    """Pin it last, unless it is pinned already."""
    pins = load(state_dir)
    if pin not in pins:
        save(state_dir, [*pins, pin])


def forget(state_dir: Path, kind: PinKind, id: str) -> None:
    """What it pinned is gone: its pin goes too."""
    pins = load(state_dir)
    kept = [p for p in pins if (p.kind, p.id) != (kind, id)]
    if kept != pins:
        save(state_dir, kept)
