"""Caches (D.8): the toolchains' state kept between sessions. A cache is its target, a home path,
whoever declares it (B.6): Handler's base, a system package on, an addon (G.1), the user (their
own, in the toolbox's toolbox.toml, B.7, edited from Settings → Caches); its host folder is named
from it (`cache_name`: `~/.cargo` → cargo). An agent gets those of the toolbox and those of the
addons it uses (its own and its project's). Each project chooses for its agents:

    project   the project's own (the default): <data>/caches/<project id>/<name>
    global    one folder per cache for every project choosing it and agents outside projects:
              <cache dir>/<name> (~/.cache/handler-ai/cargo)
    off       none

A global cache is a write channel between projects: what one project's agent leaves in it (a
crate, a build script's output) another project's agent runs.

Their files may be of the sandbox's inner ids (inner podman's image store): sizes and emptying go
through the sandbox's executable (runtime, A.9).
"""

import contextlib
import logging
import shutil
from collections.abc import Collection, Iterable
from pathlib import Path
from typing import Any

from handler_contracts import (
    CacheDeclaration,
    CacheInfo,
    CacheSharing,
    CachesInfo,
    GlobalCachesInfo,
    ProjectCachesInfo,
    cache_name,
)
from handler_harness import addons, catalog
from handler_harness import toolbox as toolbox_parts

from . import runtime
from .projects import ProjectRecord
from .settings import Settings

log = logging.getLogger("handler.caches")


def project_dir(settings: Settings, project_id: str) -> Path:
    return settings.data_dir / "caches" / project_id


class CacheError(ValueError):
    """The user's caches cannot be saved like this (the message says why)."""


def addon_caches() -> list[tuple[CacheDeclaration, str]]:
    """The caches of every addon (G.1) with who declares them ("addon:<name>"); an invalid addon
    declares none (GET /v1/addons says why)."""
    found = []
    for name in addons.names():
        with contextlib.suppress(addons.UnknownAddonError, addons.InvalidAddonError):
            found += [(c, f"addon:{name}") for c in addons.get(name).manifest.caches]
    return found


def declared() -> dict[str, CacheInfo]:
    """Every cache by its folder's name, in the order of their declarers (base, system packages,
    addons, the user's); one declared by several says what the first one says it holds, and puts
    the first commands' folder one gives on PATH."""
    toolbox = toolbox_parts.caches(catalog.toolbox())
    ordered = [d for d in toolbox if d[1] != "user"] + addon_caches()
    found: dict[str, CacheInfo] = {}
    for cache, by in ordered + [d for d in toolbox if d[1] == "user"]:
        name = cache_name(cache.target)
        if (seen := found.get(name)) is not None and seen.target != cache.target:
            continue  # refused where it is used (addons.check), or saved (save)
        if seen is not None:
            found[name] = seen.model_copy(
                update={"declared_by": [*seen.declared_by, by], "bin": seen.bin or cache.bin}
            )
        else:
            found[name] = CacheInfo(
                name=name,
                target=cache.target,
                about=cache.about,
                general=cache.general,
                bin=cache.bin,
                declared_by=[by],
            )
    return found


def for_agent(info: CacheInfo, uses: Collection[str]) -> bool:
    """An agent gets a cache of the toolbox, and one of an addon it uses."""
    return any(
        not by.startswith("addon:") or by[len("addon:") :] in uses for by in info.declared_by
    )


def mounts(
    settings: Settings, sharing: CacheSharing, project_id: str | None, uses: Collection[str]
) -> list[tuple[CacheDeclaration, str]]:
    """Each cache of an agent using the addons `uses`, with its host folder, as render takes them
    (B.3). Ad-hoc agents (outside projects) use the global ones."""
    if sharing == "off":
        return []
    if sharing == "project" and project_id is not None:
        root = project_dir(settings, project_id)
    else:
        root = settings.cache_dir
    return [
        (
            CacheDeclaration(target=c.target, about=c.about, general=c.general, bin=c.bin),
            str(root / n),
        )
        for n, c in declared().items()
        if for_agent(c, uses)
    ]


def left(root: Path, caches: Collection[str]) -> list[str]:
    """The folders in `root` (the global one, a project's) of caches no longer declared."""
    found = sorted(d.name for d in root.iterdir() if d.is_dir()) if root.is_dir() else []
    return [name for name in found if name not in caches]


def info(settings: Settings, projects: Iterable[ProjectRecord]) -> CachesInfo:
    """The toolbox's caches, the global folders and each project's own, and who uses what. A
    project that chose otherwise since keeps its own folder, listed, until emptied."""
    projects = sorted(projects, key=lambda p: p.name.lower())
    caches = declared()

    def folders(root: Path) -> dict[str, Any]:
        return {
            "folder": str(root),
            "caches": {name: str(root / name) for name in caches},
            "removed": {name: str(root / name) for name in left(root, caches)},
        }

    def own(p: ProjectRecord) -> bool:
        folder = project_dir(settings, p.id)
        return p.caches == "project" or (folder.is_dir() and any(folder.iterdir()))

    return CachesInfo(
        caches=list(caches.values()),
        global_=GlobalCachesInfo(
            **folders(settings.cache_dir),
            projects=[p.name for p in projects if p.caches == "global"],
        ),
        own=[
            ProjectCachesInfo(project_id=p.id, name=p.name, **folders(project_dir(settings, p.id)))
            for p in projects
            if own(p)
        ],
        off=[p.name for p in projects if p.caches == "off"],
    )


def save(caches: list[CacheDeclaration]) -> None:
    """The user's own caches (applies to new sessions). One at a place another declarer's cache
    is shares it; one whose folder would be another place's is refused."""
    others = {i.name: i.target for i in declared().values() if i.declared_by != ["user"]}
    for cache in caches:
        if others.get(name := cache_name(cache.target), cache.target) != cache.target:
            raise CacheError(f"{cache.target} would share the folder of {others[name]}")
    catalog.save_toolbox(catalog.toolbox().model_copy(update={"caches": caches}))


def remove_project(settings: Settings, project_id: str) -> None:
    """A deleted project's own caches (its sandboxes are stopped first). Best effort: what a
    sandbox still mounting them keeps is left, and logged."""
    folder = project_dir(settings, project_id)
    if not folder.exists():
        return
    if reason := runtime.clear_cache(folder):
        log.warning("caches of deleted project %s not removed: %s", project_id, reason)
        return
    shutil.rmtree(folder, ignore_errors=True)
