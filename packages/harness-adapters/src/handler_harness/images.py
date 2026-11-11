"""Harness and addon images: their names, how each is built, where it records its version.

Image layering (code map):
    toolbox (generated, toolbox.py) → localhost/handler-ai-toolbox:<tag>  (the system)
    harnesses/<name>/Containerfile  → <descriptor.image>:<tag>  (the agent, FROM the toolbox)
    addons/<name>/Containerfile     → <manifest.image>:<tag>    (a tool, built in the toolbox,
                                                                 shipped FROM scratch, G.1)

Tags (contract B.6): agents launch `:latest`, the only tag. A rebuild (handlerd, D.4) builds an
untagged image from the files on disk, checks it, then tags it `:latest`. Harness recipes
are not version-pinned: a rebuild installs the latest release and the image records what it got
in IMAGE_VERSION_FILE.

Only data: the runtime builds and queries images (sandbox's `image` verbs, A.7, run by handlerd).
"""

from dataclasses import dataclass
from pathlib import Path

from handler_contracts import ADDON_VERSION_FILE, IMAGE_VERSION_FILE

from .addons import Addon
from .catalog import Harness

TOOLBOX = "localhost/handler-ai-toolbox"
LATEST = "latest"


def ref(image: str, tag: str) -> str:
    return f"{image}:{tag}"


@dataclass(frozen=True)
class Recipe:
    """What a rebuild builds (D.4, G.4), for the runtime's `image build`."""

    context: Path  # holds the Containerfile
    build_args: dict[str, str]
    pull: bool  # pull the base image again: system updates
    no_cache: bool  # every step runs again: the agent's or tool's latest release
    no_intermediate: bool  # keep only the final image (an addon's build stage would stay behind)


def toolbox_recipe(context: Path, update: bool) -> Recipe:
    """The toolbox from its generated build context (toolbox.write_context): a change applied
    with the build cache, or `update`d (pull + no cache: system updates)."""
    return Recipe(context, {}, pull=update, no_cache=update, no_intermediate=False)


def recipe(unit: Harness | Addon, toolbox: str) -> Recipe:
    """A harness or an addon image, FROM the toolbox (a reference or an image id)."""
    return Recipe(
        unit.directory,
        {"TOOLBOX_IMAGE": toolbox},
        pull=False,
        no_cache=True,
        no_intermediate=isinstance(unit, Addon),
    )


def version_file(unit: Harness | Addon) -> str:
    """Where the image records what it installed: B.6 for a harness; an addon's `version` (G.1) is
    at the root of its image, which is mounted at its mount path."""
    return f"/{ADDON_VERSION_FILE}" if isinstance(unit, Addon) else IMAGE_VERSION_FILE
