"""Mini apps are apps, and an app's asks are its actions (H, H.12): the manifest is
`handler.app/v1`, its `[asks.<name>]` are `[actions.<name>]`; the addon that builds apps is
`app-builder` (was `miniapp`); the Ask router reads and gives actions (its definition, version 2).

    <data>/apps/<app>/source/app.toml, versions/<n>/app.toml   Handler's copies of each app's code
    <state>/sessions/<id>/work/app.toml                       a draft of an app's code
                     apiVersion "handler.miniapp/v2" → "handler.app/v1"; [asks.…] → [actions.…]
                     (the routes keep their paths: they are the app's own)
    <config>/bindings/*.toml   `addon = "miniapp"` → "app-builder"; the one named miniapp is named
                               app-builder (when that name is free), and so in agents' `bindings`
    <state>/agents.json        an agent set up for the Ask router (origin handler-need ask-router):
                               its form's `asks` → `actions`, its result's `ask` → `action`, the
                               same words in its instructions; its origin's version 2
"""

import json
import re
from pathlib import Path

from ..files import write_private
from ..settings import Settings

API = re.compile(r'^(\s*apiVersion\s*=\s*)"handler\.miniapp/v2"', re.M)
ASKS_TABLE = re.compile(r"^(\s*\[+\s*)asks(\s*[.\]])", re.M)
ASKS_KEY = re.compile(r"^(\s*)asks(\s*[.=])", re.M)
# the Ask router's instructions as Handler wrote them: their words for an action
ROUTER_WORDS = [
    ("{{asks}}", "{{actions}}"),
    ("which ask of which app does it, and fill that ask's form.",
     "which action of which app does it, and fill that action's form."),
    ("each of its asks:", "each of its actions:"),
    ("one ask clearly does it. Give `app` and `ask`",
     "one action clearly does it. Give `app` and `action`"),
    ("an ask fits but", "an action fits but"),
    ("no ask does it.", "no action does it."),
    ("never invent an app, an ask or a field. When two asks could do it,",
     "never invent an app, an action or a field. When two actions could do it,"),
]  # fmt: skip


def manifest(path: Path) -> None:
    text = path.read_text()
    new = ASKS_KEY.sub(
        r"\1actions\2", ASKS_TABLE.sub(r"\1actions\2", API.sub(r'\1"handler.app/v1"', text))
    )
    if new != text:
        path.write_text(new)


def migrate(settings: Settings) -> None:
    for found in [
        *(settings.data_dir / "apps").glob("*/source/app.toml"),
        *(settings.data_dir / "apps").glob("*/versions/*/app.toml"),
        *(settings.state_dir / "sessions").glob("*/work/app.toml"),
    ]:
        manifest(found)
    renamed = bindings(settings.bindings_dir)
    path = settings.state_dir / "agents.json"
    if not path.exists():
        return
    agents = json.loads(path.read_text())
    for agent in agents:
        if renamed and "miniapp" in agent.get("bindings", []):
            agent["bindings"] = sorted({*agent["bindings"], "app-builder"} - {"miniapp"})
        origin = agent.get("origin") or {}
        if (origin.get("kind"), origin.get("name")) == ("handler-need", "ask-router"):
            router(agent)
    write_private(path, json.dumps(agents, indent=2))


def bindings(folder: Path) -> bool:
    """The configurations of the addon, renamed; whether the one named miniapp was."""
    for path in folder.glob("*.toml"):
        text = path.read_text()
        new = re.sub(r'^(\s*addon\s*=\s*)"miniapp"', r'\1"app-builder"', text, flags=re.M)
        if new != text:
            path.write_text(new)
    old, new_path = folder / "miniapp.toml", folder / "app-builder.toml"
    if old.exists() and not new_path.exists():
        old.rename(new_path)
        return True
    return False


def router(agent: dict) -> None:
    interface = agent.get("interface") or {}
    fields, result = interface.get("fields") or {}, interface.get("result") or {}
    props = fields.get("properties") or {}
    if "asks" in props:
        props["actions"] = props.pop("asks")
        props["actions"]["description"] = (
            "Each app's actions: its name, the action's name, what it does, its form."
        )
        fields["required"] = ["actions" if r == "asks" else r for r in fields.get("required", [])]
    out = result.get("properties") or {}
    if "ask" in out:
        out["action"] = out.pop("ask") | {"title": "Action"}
    text = agent.get("instructions") or ""
    for a, b in ROUTER_WORDS:
        text = text.replace(a, b)
    agent["instructions"] = text or None
    agent["origin"]["version"] = 2
