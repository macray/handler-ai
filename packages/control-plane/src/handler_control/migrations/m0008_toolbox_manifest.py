"""The toolbox is built from its parts (B.7): `toolbox.toml` says the distro, the system packages
on and the user's own caches, a list where a cache is its target (D.8).

    <config>/toolbox/toolbox.toml   `[caches.<name>]` tables → `distro = "fedora"`, podman and
                                    wl-clipboard on (what the toolbox had), the user's caches as
                                    `[[caches]]`; those Handler's default declared are dropped
                                    (the base, system packages and addons declare them now), one
                                    without `about` says its target

The toolbox's Containerfile is left: the user's own lines are now `custom.containerfile`.
"""

import json
import tomllib

from handler_harness import catalog

from ..settings import Settings

# the caches of the default toolbox.toml before the toolbox was built from its parts
DEFAULT_TARGETS = {
    "~/.cargo",
    "~/.rustup",
    "~/.bun",
    "~/.m2",
    "~/.npm",
    "~/.cache",
    "~/.local",
    "~/.local/share/containers/storage",
}


def migrate(settings: Settings) -> None:
    path = catalog.toolbox_dir() / "toolbox.toml"
    if not path.exists():
        return
    old = tomllib.loads(path.read_text())
    if "distro" in old:
        return
    text = catalog.TOOLBOX_TOML_HEADER + '\ndistro = "fedora"\n'
    text += "\n[systemPackages.podman]\n\n[systemPackages.wl-clipboard]\n"
    for cache in old.get("caches", {}).values():
        if cache["target"] in DEFAULT_TARGETS:
            continue
        text += f"\n[[caches]]\ntarget = {json.dumps(cache['target'])}\n"
        about = cache.get("about") or cache["target"]
        text += f"about = {json.dumps(about, ensure_ascii=False)}\n"
        if cache.get("general"):
            text += "general = true\n"
    path.write_text(text)
