"""An agent uses addons, not bindings (G.3): a binding only fills an addon's slots, and an addon
without slots is used by its name alone (G.2).

    <state>/agents.json        an agent's `bindings: [name]` → `addons: [{addon, binding}]`, the
                               addon read from the binding; `{addon}` alone when that addon has
                               no slots. A binding that cannot be read is dropped (the agent could
                               not start with it either), and logged
    <config>/bindings/*.toml   a binding of an addon without slots (`addon = "app-builder"`) is
                               removed: nothing fills it any more
"""

import json
import logging
import os
import tomllib
from pathlib import Path

from handler_harness import addons

from ..files import write_private
from ..settings import Settings

log = logging.getLogger("handler.migrations")


def has_slots(addon: str, settings: Settings) -> bool:
    """Whether the addon declares settings or secrets; an addon that is gone or unreadable is
    taken as having some (its binding is kept, the agent's checks say what is wrong). The user's
    addons in the folder of this migration's time (`addons/<name>/addon.toml`), else built in."""
    own = Path(os.environ.get("HANDLER_ADDONS_DIR", settings.config_dir / "addons")) / addon
    for manifest in (own / "addon.toml", addons.BUILTIN_DIR / addon / addons.MANIFEST):
        if manifest.is_file():
            try:
                found = tomllib.loads(manifest.read_text())
            except (OSError, tomllib.TOMLDecodeError):
                return True
            return bool(found.get("settings") or found.get("secretSlots"))
    return True


def binding_addon(path: Path) -> str | None:
    try:
        addon = tomllib.loads(path.read_text()).get("addon")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return addon if isinstance(addon, str) else None


def migrate(settings: Settings) -> None:
    folder = settings.bindings_dir
    path = settings.state_dir / "agents.json"
    if path.exists():
        agents = json.loads(path.read_text())
        for agent in agents:
            uses: dict[str, dict[str, str]] = {}
            for name in agent.pop("bindings", []):
                addon = binding_addon(folder / f"{name}.toml")
                if addon is None:
                    log.warning("agent %s: binding %s unreadable, dropped", agent.get("id"), name)
                elif has_slots(addon, settings):
                    uses[addon] = {"addon": addon, "binding": name}
                else:
                    uses[addon] = {"addon": addon}
            agent["addons"] = [uses[a] for a in sorted(uses)]
        write_private(path, json.dumps(agents, indent=2))
    for binding in list(folder.glob("*.toml")):
        if (addon := binding_addon(binding)) is not None and not has_slots(addon, settings):
            binding.unlink()
