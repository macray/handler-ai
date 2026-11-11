"""An agent keeps a list of the hosts the person keeps blocked, beside its allowed ones (A.3,
D.2): refused as any unlisted one, the agent told not to ask for them.

    <state>/agents.json        each agent gets `blocked: []` (nobody has kept a host blocked yet)
"""

import json

from ..files import write_private
from ..settings import Settings


def migrate(settings: Settings) -> None:
    path = settings.state_dir / "agents.json"
    if not path.exists():
        return
    agents = json.loads(path.read_text())
    for agent in agents:
        agent.setdefault("blocked", [])
    write_private(path, json.dumps(agents, indent=2))
