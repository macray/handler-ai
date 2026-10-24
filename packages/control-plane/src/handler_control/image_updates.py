"""Automatic image updates (contract D.4): the network filter (the egress proxy's image: base
pulled again, for its security updates), then every harness and addon image already built, are
rebuilt (the latest release), checked and switched only if it passes, one after the other through
the build store, as a user's rebuild would be. A failed check keeps the image agents have.

The network filter is part of handler and most agents need it: when it is missing (a first start, an
handler upgrade naming a new image), handlerd builds it as it starts, whatever the schedule.

An addon is in use when a saved agent has one of its bindings (G.3): its image, when it has one, is
built if it is not (a first build), as handlerd starts and when an agent starts using it (its
set-up, its editor). A launch never builds one (A.7): until it is built, the agent's sessions do
not start (`missingImage`, F.1).

When: on a schedule (weekly by default, daily or off), and once after a handler upgrade (handlerd's
version differs from the one that last ran them: a release may change the recipes). Not the
toolbox: it is the user's, and its rebuild is a system update (Rebuild all, by the user).

Storage: <state>/image-updates.json. On the first start the period counts from then: the images
`handler setup` just built are new.
"""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from handler_contracts import ImageUpdates
from handler_contracts.control import UpdateSchedule
from handler_harness import catalog, images

from . import __version__, bindings, runtime
from .agents import AgentRegistry
from .builds import ADDON_PREFIX, NETWORK_FILTER_TARGET, BuildBusyError, BuildStore, built_addons
from .files import write_private
from .settings import Settings

log = logging.getLogger("handler.image_updates")

PERIODS = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}
TICK = 3600.0  # seconds between two looks at whether a run is due
BUSY_WAIT = 5.0  # seconds between two looks at whether another build ended


def targets() -> list[str]:
    """The images to update: the network filter, the harnesses and addons whose image is built."""
    harnesses = [
        h.name
        for h in catalog.all_harnesses()
        if runtime.exists(images.ref(h.descriptor.image, images.LATEST))
    ]
    return [NETWORK_FILTER_TARGET, *harnesses] + [f"{ADDON_PREFIX}{a.name}" for a in built_addons()]


def missing_addons(registry: AgentRegistry, bindings_dir: Path) -> list[str]:
    """The addons in use (a saved agent has one of their bindings) whose image is not built, as
    build targets. Not with the toolbox missing: they are built on it (`handler setup` first)."""
    if not runtime.exists(images.ref(images.TOOLBOX, images.LATEST)):
        return []
    used = {name for agent in list(registry.agents.values()) for name in agent.bindings}
    found: dict[str, str] = {}  # its addon's name → its image
    for name in sorted(used):
        loaded = bindings.get(bindings_dir, name)  # an invalid one: the agent's checks say so
        if loaded.addon is not None and loaded.addon.manifest.image is not None:
            found[loaded.addon.name] = loaded.addon.manifest.image
    return [
        f"{ADDON_PREFIX}{addon}"
        for addon, image in sorted(found.items())
        if not runtime.exists(images.ref(image, images.LATEST))
    ]


class ImageUpdater:
    def __init__(self, settings: Settings, builds: BuildStore, registry: AgentRegistry) -> None:
        self.path = settings.state_dir / "image-updates.json"
        self.bindings_dir = settings.bindings_dir
        self.builds = builds
        self.registry = registry
        self.run_task: asyncio.Task[None] | None = None
        self.loop_task: asyncio.Task[None] | None = None
        self.addons_task: asyncio.Task[None] | None = None  # building the missing addon images
        self.addons_again = False  # agents changed meanwhile: look again once it ends
        self.used: set[str] = set()  # the bindings the saved agents have, as last seen
        self.loop: asyncio.AbstractEventLoop | None = None
        state = self._load()
        self.schedule: UpdateSchedule = state.get("schedule", "weekly")
        self.last_run = _time(state.get("lastRun")) or datetime.now(UTC)
        self.handler_version: str = state.get("handlerVersion", __version__)
        self.last_failed: list[str] = state.get("lastFailed", [])
        if not self.path.exists():
            self._save()

    # ── state ───────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        state = {
            "schedule": self.schedule,
            "lastRun": self.last_run.isoformat(),
            "handlerVersion": self.handler_version,
            "lastFailed": self.last_failed,
        }
        write_private(self.path, json.dumps(state, indent=2))

    def next_run(self) -> datetime | None:
        if self.schedule == "off":
            return None
        if self.handler_version != __version__:
            return datetime.now(UTC)  # upgraded: now
        return self.last_run + PERIODS[self.schedule]

    def view(self) -> ImageUpdates:
        return ImageUpdates(
            schedule=self.schedule,
            running=self.run_task is not None,
            last_run=self.last_run,
            next_run=self.next_run(),
            last_failed=self.last_failed,
        )

    def set_schedule(self, schedule: UpdateSchedule) -> ImageUpdates:
        self.schedule = schedule
        self._save()
        return self.view()

    # ── runs ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """The loop that starts a run when one is due (handlerd's lifespan), and the first build of
        the addon images in use, now and when an agent starts using one."""
        self.loop = asyncio.get_running_loop()
        self.loop_task = asyncio.create_task(self._loop())
        self.registry.listeners.append(self.agents_saved)
        self.agents_saved()

    def agents_saved(self) -> None:
        """Told by the registry (from any thread): when the agents have a binding they had not,
        the missing addon images are looked for."""
        used = {name for agent in list(self.registry.agents.values()) for name in agent.bindings}
        new, self.used = used - self.used, used
        if new and self.loop is not None:
            self.loop.call_soon_threadsafe(self._build_missing_addons)

    def _build_missing_addons(self) -> None:
        if self.addons_task is not None:
            self.addons_again = True
            return
        self.addons_task = asyncio.create_task(self._missing_addons())
        self.addons_task.add_done_callback(lambda _: setattr(self, "addons_task", None))

    async def _missing_addons(self) -> None:
        self.addons_again = True
        while self.addons_again:
            self.addons_again = False
            try:
                missing = await asyncio.to_thread(missing_addons, self.registry, self.bindings_dir)
            except (OSError, ValueError) as e:  # no runtime: the host check (A.8) says so
                log.warning("cannot tell which addon images are built: %s", e)
                return
            for target in missing:
                log.info("%s is used by an agent and not built: building it", target)
                build = await self._start(target)
                await self.builds.wait(build)

    async def close(self) -> None:
        for task in (self.loop_task, self.run_task, self.addons_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    def run_now(self) -> bool:
        """Start a run; False when one is running."""
        if self.run_task is not None:
            return False
        self.run_task = asyncio.create_task(self._run())
        self.run_task.add_done_callback(lambda _: setattr(self, "run_task", None))
        return True

    async def _loop(self) -> None:
        due = self.next_run()
        if not (due is not None and datetime.now(UTC) >= due):  # else the run builds it first
            await self._build_missing_network_filter()
        while True:
            due = self.next_run()
            if due is not None and datetime.now(UTC) >= due:
                self.run_now()
            await asyncio.sleep(TICK)

    async def _run(self) -> None:
        failed = []
        for target in await asyncio.to_thread(targets):
            build = await self._start(target)
            await self.builds.wait(build)
            ended = self.builds.get(build)
            if ended is None or ended.state != "succeeded":
                failed.append(target)
                log.warning("update of %s: %s", target, ended.error if ended else "lost")
        self.last_run = datetime.now(UTC)
        self.handler_version = __version__
        self.last_failed = failed
        self._save()
        log.info("image updates done, %d failed", len(failed))

    async def _build_missing_network_filter(self) -> None:
        """Asked again after any build running now: it may be this one (`handler setup`)."""
        while True:
            try:
                if (await asyncio.to_thread(runtime.proxy)).image is not None:
                    return
            except (OSError, ValueError) as e:  # no runtime: the host check (A.8) says so
                log.warning("cannot tell whether the network filter is built: %s", e)
                return
            try:
                self.builds.start(NETWORK_FILTER_TARGET)
                log.info("the network filter is not built: building it")
                return
            except BuildBusyError:
                await asyncio.sleep(BUSY_WAIT)

    async def _start(self, target: str) -> str:
        """Start `target`'s rebuild, after any build running now (one at a time, D.4)."""
        while True:
            try:
                return self.builds.start(target).id
            except BuildBusyError:
                await asyncio.sleep(BUSY_WAIT)


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
