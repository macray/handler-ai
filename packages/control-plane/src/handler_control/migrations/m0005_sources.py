"""What Handler shipped comes from its official source (D.26): an addon installed from the
catalog was installed from it, and so was one of Handler's apps.

    ~/.config/handler-ai/addons.lock.toml   `source = "catalog:<name>"` → "source:official/<name>"
    <state>/apps.json                       an app's `fromHandler: true` → `fromSource: "official"`
                                            (`fromHandler` goes)
"""

import json
import re

from handler_harness import addons

from ..files import write_private
from ..settings import Settings

CATALOG = re.compile(r'^(\s*source\s*=\s*)"catalog:([^"]*)"', re.M)


def migrate(settings: Settings) -> None:
    lock = addons.user_dir().parent / "addons.lock.toml"
    if lock.exists():
        text = lock.read_text()
        new = CATALOG.sub(r'\1"source:official/\2"', text)
        if new != text:
            lock.write_text(new)
    path = settings.state_dir / "apps.json"
    if not path.exists():
        return
    data = json.loads(path.read_text())
    for app in data.get("apps", {}).values():
        if app.pop("fromHandler", False):
            app["fromSource"] = "official"
    write_private(path, json.dumps(data, indent=2))
