"""Chat is no app, and blueprints are gone (D.1, D.18, D.23): an agent of Chat has its own home,
`chat`, no longer `app` "chat"; what was set up from one of Handler's blueprints was set up for
one of Handler's needs, and from any other blueprint, from an agents file.

    <state>/agents.json          each agent: `app` "chat" → `app` null, `chat` true; `origin`
                                 {kind: blueprint, name, version, agent} →
                                 {kind: handler-need, name, version} (Handler's names), else
                                 {kind: agents-file, name, version, agent}
    <state>/roles.json           → <state>/handler-needs.json (the same content)
    <state>/agent-imports/<name>/blueprint.toml → agents.toml (files read, not set up yet)
"""

import json

from ..files import write_private
from ..settings import Settings

# Handler's blueprints when this migration was written: one per need, its only agent
NEEDS = {"skill-review", "skill-creator", "prompt-writer", "app-creator", "ask-router"}


def migrate(settings: Settings) -> None:
    state = settings.state_dir
    path = state / "agents.json"
    if path.exists():
        agents = json.loads(path.read_text())
        for agent in agents:
            if agent.get("app") == "chat":
                agent["app"], agent["chat"] = None, True
            origin = agent.get("origin")
            if origin and origin.get("kind") == "blueprint":
                if origin["name"] in NEEDS:
                    agent["origin"] = {
                        "kind": "handler-need",
                        "name": origin["name"],
                        "version": origin["version"],
                    }
                else:
                    origin["kind"] = "agents-file"
        write_private(path, json.dumps(agents, indent=2))
    roles = state / "roles.json"
    if roles.exists():
        write_private(state / "handler-needs.json", roles.read_text())
        roles.unlink()
    imports = state / "agent-imports"
    if imports.is_dir():
        for meta in imports.glob("*/blueprint.toml"):
            meta.rename(meta.with_name("agents.toml"))
