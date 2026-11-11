"""A device's push subscription keeps its keys (H.10): pushes are encrypted to them, as Firefox
for Android drops a push without a body. A subscription kept so far has no keys, so it is
dropped; the phone sends its subscription again, keys included, the next time it opens.

    <config>/remote-devices.json   each device's `pushEndpoint` becomes `push: null`
"""

import json

from ..files import write_private
from ..settings import Settings


def migrate(settings: Settings) -> None:
    path = settings.config_dir / "remote-devices.json"
    if not path.exists():
        return
    kept = json.loads(path.read_text())
    for device in kept.get("devices", []):
        device.pop("pushEndpoint", None)
        device["push"] = None
    write_private(path, json.dumps(kept, indent=2))
