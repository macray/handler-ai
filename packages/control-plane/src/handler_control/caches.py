"""Caches (D.8): the toolchains' state kept between sessions. Declared once by the toolbox
(its toolbox.toml: a home path per name, what it holds, B.6, edited from Settings → Caches); each
project chooses for its agents:

    project   the project's own (the default): <data>/caches/<project id>/<name>
    global    one folder per cache for every project choosing it and agents outside projects:
              <cache dir>/<name> (~/.cache/handler-ai/cargo)
    off       none

A global cache is a write channel between projects: what one project's agent leaves in it (a
crate, a build script's output) another project's agent runs.

Their files may be of the sandbox's inner ids (inner podman's image store): sizes and emptying go
through the sandbox's executable (runtime, A.9).
"""

import logging
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from handler_contracts import (
    CacheDeclaration,
    CacheInfo,
    CacheSharing,
    CachesInfo,
    GlobalCachesInfo,
    ProjectCachesInfo,
    ToolboxManifest,
)
from handler_harness import catalog

from . import runtime
from .projects import ProjectRecord
from .settings import Settings

log = logging.getLogger("handler.caches")


class CacheError(Exception):
    """A cache list that cannot be saved; the message says why."""


def project_dir(settings: Settings, project_id: str) -> Path:
    return settings.data_dir / "caches" / project_id


def mounts(settings: Settings, sharing: CacheSharing, project_id: str | None) -> dict[str, str]:
    """Home path → host folder of each cache, as render takes them (B.3). Ad-hoc agents (outside
    projects) use the global ones."""
    if sharing == "off":
        return {}
    if sharing == "project" and project_id is not None:
        root = project_dir(settings, project_id)
    else:
        root = settings.cache_dir
    return {c.target: str(root / name) for name, c in catalog.toolbox().caches.items()}


def info(settings: Settings, projects: Iterable[ProjectRecord]) -> CachesInfo:
    """The toolbox's caches, the global folders and each project's own, and who uses what."""
    projects = sorted(projects, key=lambda p: p.name.lower())
    declared = catalog.toolbox().caches

    def folders(root: Path) -> dict[str, Any]:
        found = sorted(d.name for d in root.iterdir() if d.is_dir()) if root.is_dir() else []
        return {
            "folder": str(root),
            "caches": {name: str(root / name) for name in declared},
            "removed": {name: str(root / name) for name in found if name not in declared},
        }

    return CachesInfo(
        caches=[
            CacheInfo(name=n, target=c.target, about=c.about, general=c.general)
            for n, c in declared.items()
        ],
        global_=GlobalCachesInfo(
            **folders(settings.cache_dir),
            projects=[p.name for p in projects if p.caches == "global"],
        ),
        own=[
            ProjectCachesInfo(project_id=p.id, name=p.name, **folders(project_dir(settings, p.id)))
            for p in projects
            if p.caches == "project"
        ],
        off=[p.name for p in projects if p.caches == "off"],
    )


def save(caches: dict[str, CacheDeclaration]) -> None:
    """The toolbox's new cache list (applies to new sessions). A cache over the whole home or
    the root would hide what the harness keeps there; two at one place cannot both be mounted."""
    targets = [c.target for c in caches.values()]
    for target in targets:
        if target in ("~", "/"):
            raise CacheError(f"a cache cannot be the whole {'home' if target == '~' else 'disk'}")
    if len(set(targets)) < len(targets):
        raise CacheError("two caches at the same place")
    catalog.save_toolbox(ToolboxManifest(caches=caches))


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
