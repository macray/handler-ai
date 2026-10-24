"""An agent's home is stored (D.1, H.14): its project, its app (one of an app's parts, or Chat's:
`app` "chat"), or none. Until now an app's part was told by its origin ("app:<app>/<need>") and
someone in Chat by what it lacked (no project, no app, no folder, no form, given for no role and
set up from none of Handler's roles' blueprints). Its origin, what it was set up from, is no
longer a string but a record.

    <state>/agents.json   each agent: + "app"; "origin" from a string to a record:
                          "app:<app>/<need>"             → {kind: app, name, agent}
                          "blueprint:<name>@<v>/<agent>" → {kind: blueprint, name, version, agent}
"""

import json
import re

from ..files import write_private
from ..settings import Settings

# Handler's roles when this migration was written (data/roles.toml): their blueprints' names
ROLES = {"skill-review", "skill-creator", "prompt-writer", "app-creator", "ask-router"}
APP = re.compile(r"^app:([a-z0-9-]+)/([a-z0-9-]+)$")
BLUEPRINT = re.compile(r"^blueprint:([a-z0-9-]+)@([0-9]+)/([a-z0-9-]+)$")


def migrate(settings: Settings) -> None:
    path = settings.state_dir / "agents.json"
    if not path.exists():
        return
    agents = json.loads(path.read_text())
    try:
        given = set(json.loads((settings.state_dir / "roles.json").read_text()).values())
    except FileNotFoundError:
        given = set()
    for agent in agents:
        origin = agent.get("origin")
        app = blueprint = None
        if origin and (m := APP.fullmatch(origin)):
            app = m[1]
            agent["origin"] = {"kind": "app", "name": m[1], "agent": m[2]}
        elif origin and (m := BLUEPRINT.fullmatch(origin)):
            blueprint = m[1]
            agent["origin"] = {
                "kind": "blueprint",
                "name": m[1],
                "version": int(m[2]),
                "agent": m[3],
            }
        elif origin:
            raise ValueError(f"agent {agent.get('id')}: an origin of no known form: {origin}")
        chat = (
            agent.get("projectId") is None
            and app is None
            and agent.get("scope") is None
            and agent.get("interface") is None
            and agent.get("id") not in given
            and blueprint not in ROLES
        )
        agent["app"] = app or ("chat" if chat else None)
    write_private(path, json.dumps(agents, indent=2))
