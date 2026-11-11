"""Image rebuilds (contract D.4): build from the files on disk, check, switch. One at a time.

    harness   an untagged image FROM toolbox:latest, no cache (fetches the agent's latest release)
              → check (image_check) → tagged :latest
    addon:X   the same for an addon's image (G.4), extracted into its folder (addon_folders),
              checked there mounted into the toolbox as agents get it; the switch makes that
              folder current and removes the image (the folder is what agents mount)
    toolbox   the toolbox generated from its parts (B.7) into <state>/toolbox-build/, built
              untagged: applying a change with the build cache (only the layers from the first
              changed one run), or updating (pull + no cache: system updates) → its system
              packages' checks, the commands it gives, every need in use among them → every
              harness image and every addon already built, FROM it (a harness never built waits
              for its own first build: `handler setup` builds the one chosen, Prepare now the others) → check each → switch them
              all, or none; the toolbox's record (<state>/toolbox.json) moves with it
    network-filter  the egress proxy's image (A.3), the runtime's own: `image build-proxy` builds
              it (pull + no cache), checks it and switches to it (A.7)

The image `:latest` leaves is removed if nothing uses it (the runtime refuses while a container
runs from it or mounts it, A.7). There is no rollback: to go back, fix the files and rebuild.

A failed or cancelled build removes the images it built (and the folders it extracted); `:latest`
and an addon's current folder only ever move to what passed its check. Running agents keep the
image and the folders they started with.

An addon installed while the toolbox lacks what it needs waits for the toolbox (`waiting`): it is
built once a toolbox build gives its needs (image_updates, told by `listeners` when a build ends).
Its state (G.5, `addon_state`) follows its builds: preparing while one that makes it runs, failed
when its last one failed.

The client names a target, nothing else: no Containerfile, path, tag or build argument comes from
the API. Builds run through the sandbox's executable (`runtime`) as the daemon's user, with an
argument list (no shell).

Storage under <state>/builds/:
    <id>.json   the build (contract Build)
    <id>.log    the runtime's output and the check's lines, ANSI escapes removed, size-capped
    <id>.iid    the id of the image just built (`image build --id-file`), until it is read
"""

import asyncio
import contextlib
import logging
import os
import re
import signal
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import IO, Any

from handler_contracts import AddonState, Build, BuildLog, ToolboxRecord
from handler_harness import addons, catalog, images
from handler_harness import toolbox as toolbox_parts

from . import addon_folders, image_check, runtime, toolbox
from .agents import AgentRegistry
from .settings import Settings

log = logging.getLogger("handler.builds")

TOOLBOX_TARGET = "toolbox"
NETWORK_FILTER_TARGET = "network-filter"
ADDON_PREFIX = "addon:"
MAX_LOG_BYTES = 8 * 1024 * 1024
LOG_CHUNK_BYTES = 256 * 1024
KEEP_BUILDS = 20

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Z0-9]|\r")
_STEP = re.compile(r"^STEP (\d+)/(\d+):")


class BuildError(RuntimeError):
    """A build step failed (the reason is shown to the user)."""


class BuildBusyError(RuntimeError):
    pass


class NoImageError(LookupError):
    """The addon has no image: nothing to build."""


def addon_with_image(name: str) -> addons.Addon:
    """Raises UnknownAddonError, InvalidAddonError or NoImageError."""
    addon = addons.get(name)
    if addon.manifest.image is None:
        raise NoImageError(f"tool '{name}' has no image (nothing to build)")
    return addon


def built_addons(settings: Settings) -> list[addons.Addon]:
    """The valid addons with an image already built (their folder current): a toolbox rebuild
    rebuilds those (an addon in use is built first when it is not, image_updates); invalid ones
    are reported by GET /v1/addons."""
    found = []
    for name in addons.names():
        with contextlib.suppress(addons.InvalidAddonError):
            addon = addons.get(name)
            if addon.manifest.image is not None and addon_folders.built(settings, name):
                found.append(addon)
    return found


def built_harnesses() -> list[catalog.Harness]:
    """The harnesses whose image is built (`:latest`): a toolbox build rebuilds those."""
    return [
        h
        for h in catalog.all_harnesses()
        if runtime.exists(images.ref(h.descriptor.image, images.LATEST))
    ]


class BuildStore:
    def __init__(self, settings: Settings, registry: AgentRegistry) -> None:
        self.settings = settings
        self.registry = registry  # its agents' abilities are needs in use (toolbox.py)
        self.dir = settings.state_dir / "builds"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.running: tuple[str, asyncio.Task[None]] | None = None
        self.running_addons: list[str] = []  # those the running build builds
        self.waiting: set[str] = set()  # addons installed, waiting for the toolbox (in memory)
        self.listeners: list[Callable[[Build], None]] = []  # told when a build ends
        self.queued: dict[asyncio.Task[None], str] = {}  # `start_soon`'s → their targets
        self._load()

    # ── persistence ─────────────────────────────────────────────────────

    def _load(self) -> None:
        builds = self.list()
        for build in builds:  # interrupted by a daemon stop
            if build.state == "running":
                self._save(
                    build.model_copy(
                        update={
                            "state": "failed",
                            "error": "daemon restarted",
                            "ended_at": datetime.now(UTC),
                        }
                    )
                )
        for old in builds[KEEP_BUILDS:]:
            (self.dir / f"{old.id}.json").unlink(missing_ok=True)
            (self.dir / f"{old.id}.log").unlink(missing_ok=True)

    def _save(self, build: Build) -> None:
        path = self.dir / f"{build.id}.json"
        path.with_suffix(".tmp").write_text(build.model_dump_json(by_alias=True, exclude_none=True))
        path.with_suffix(".tmp").replace(path)

    def list(self) -> list[Build]:
        found = [Build.model_validate_json(p.read_text()) for p in self.dir.glob("*.json")]
        return sorted(found, key=lambda b: b.started_at, reverse=True)

    def get(self, build_id: str) -> Build | None:
        path = self.dir / f"{build_id}.json"
        return Build.model_validate_json(path.read_text()) if path.exists() else None

    def read_log(self, build: Build, offset: int) -> BuildLog:
        """The log from byte `offset`, cut at a line end so no character is split."""
        path = self.dir / f"{build.id}.log"
        with contextlib.suppress(FileNotFoundError), path.open("rb") as f:
            f.seek(max(offset, 0))
            chunk = f.read(LOG_CHUNK_BYTES)
            if b"\n" in chunk:
                chunk = chunk[: chunk.rindex(b"\n") + 1]
            elif build.state == "running":
                chunk = b""  # wait for the line to finish
            end = max(offset, 0) + len(chunk)
            done = build.state != "running" and end >= path.stat().st_size
            return BuildLog(text=chunk.decode(errors="replace"), next_offset=end, complete=done)
        return BuildLog(text="", next_offset=0, complete=build.state != "running")

    # ── lifecycle ───────────────────────────────────────────────────────

    def start(self, target: str, update: bool = False) -> Build:
        """`target`: "toolbox", "network-filter", a harness name (unknown →
        catalog.UnknownHarnessError) or "addon:<name>" (→ addons.UnknownAddonError,
        InvalidAddonError, NoImageError). `update`: the toolbox's, pulled and built without
        cache (system updates); else a change applied."""
        self.check_target(target)
        if self.running:
            raise BuildBusyError(f"build {self.running[0]} is still running")
        build_id = uuid.uuid4().hex[:12]
        build = Build(
            id=build_id,
            target=target,
            state="running",
            started_at=datetime.now(UTC),
        )
        harnesses: list[str] = []  # a toolbox build's: found as it starts (`_Job.steps`)
        if target == TOOLBOX_TARGET:
            names = [a.name for a in built_addons(self.settings)]
        elif target.startswith(ADDON_PREFIX):
            names = [target.removeprefix(ADDON_PREFIX)]
        else:
            names = []
            if target != NETWORK_FILTER_TARGET:
                harnesses = [target]
        build = build.model_copy(update={"addons": names, "harnesses": harnesses})
        self.waiting -= set(names)
        self._save(build)
        job = asyncio.create_task(_Job(self, build, update).run())
        self.running = (build.id, job)
        self.running_addons = names
        job.add_done_callback(lambda _: self._ended(build.id))
        return build

    def _ended(self, build_id: str) -> None:
        self.running, self.running_addons = None, []
        if (build := self.get(build_id)) is not None:
            for listener in self.listeners:
                listener(build)

    def start_soon(self, target: str) -> Build | None:
        """`start` now, or once the build running ends (None: queued)."""
        try:
            return self.start(target)
        except BuildBusyError:
            task = asyncio.create_task(self._start_after(target))
            self.queued[task] = target
            task.add_done_callback(lambda t: self.queued.pop(t, None))
            return None

    async def _start_after(self, target: str) -> None:
        while True:
            if self.running:
                await self.wait(self.running[0])
            with contextlib.suppress(BuildBusyError):
                self.start(target)
                return
            await asyncio.sleep(0)  # another started first: wait for it too

    def toolbox_pending(self) -> bool:
        """A toolbox build runs or is queued."""
        running = self.running is not None and self.get(self.running[0])
        if running and running.target == TOOLBOX_TARGET:
            return True
        return TOOLBOX_TARGET in self.queued.values()

    def addon_state(self, name: str, ready: bool) -> tuple[AddonState, str | None]:
        """An addon's state (G.5) from its builds; `ready`: its folder built (when it has an
        image) and its needs in the toolbox."""
        if name in self.running_addons or (name in self.waiting and self.toolbox_pending()):
            return "preparing", None
        if ready:
            return "ready", None
        last = next((b for b in self.list() if name in b.addons and b.state != "running"), None)
        if last is not None and last.state == "failed":
            return "failed", last.error
        return "installed", None

    @staticmethod
    def check_target(target: str) -> None:
        """Raises if `target` cannot be built (see `start`)."""
        if target.startswith(ADDON_PREFIX):
            addon_with_image(target.removeprefix(ADDON_PREFIX))
        elif target not in (TOOLBOX_TARGET, NETWORK_FILTER_TARGET):
            catalog.get(target)

    def cancel(self, build_id: str) -> bool:
        if self.running and self.running[0] == build_id:
            self.running[1].cancel()
            return True
        return False

    async def wait(self, build_id: str) -> None:
        if self.running and self.running[0] == build_id:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(self.running[1])


class _Job:
    """One build, from start to its final state."""

    def __init__(self, store: BuildStore, build: Build, update: bool = False) -> None:
        self.store = store
        self.build = build
        self.update_toolbox = update
        self.record: ToolboxRecord | None = None  # a new toolbox's, written when it switches
        self.log_size = 0
        self.out: IO[str] | None = None
        self.built: dict[str, str] = {}  # repository → id of its new image, until tagged
        self.extracted: dict[str, str] = {}  # addon → id of its image, extracted and checked

    def update(self, **fields: Any) -> None:
        self.build = self.build.model_copy(update=fields)
        self.store._save(self.build)

    def line(self, text: str) -> None:
        if self.out is None:
            return
        text = _ANSI.sub("", text).rstrip() + "\n"
        size = len(text.encode())
        if self.log_size + size > MAX_LOG_BYTES:
            if self.log_size <= MAX_LOG_BYTES:
                self.out.write("[log truncated]\n")
                self.log_size = MAX_LOG_BYTES + 1
            return
        self.log_size += size
        self.out.write(text)
        self.out.flush()

    async def run(self) -> None:
        with (self.store.dir / f"{self.build.id}.log").open("a") as out:
            self.out = out
            try:
                await self.steps()
                self.update(state="succeeded", stage=None, step=None, steps=None)
            except asyncio.CancelledError:
                self.line("cancelled")
                self.update(state="cancelled")
            except (BuildError, image_check.ImageCheckError, OSError) as e:
                self.line(f"failed: {e}")
                self.update(state="failed", error=str(e))
            except Exception as e:  # never leave a build "running"
                log.exception("build %s crashed", self.build.id)
                self.update(state="failed", error=f"internal error: {e}")
            finally:
                for image_id in reversed(self.built.values()):  # images before their base
                    await asyncio.to_thread(runtime.remove, image_id)
                if self.extracted:  # a failed build's folders, those it replaced
                    for name, image in self.extracted.items():
                        addon_folders.release(self.store.settings, name, image)
                    await asyncio.to_thread(addon_folders.sweep, self.store.settings)
                (self.store.dir / f"{self.build.id}.iid").unlink(missing_ok=True)
                self.update(ended_at=datetime.now(UTC))
                self.out = None

    async def steps(self) -> None:
        target = self.build.target
        if target == NETWORK_FILTER_TARGET:
            await self.run_logged("build network filter", runtime.build_proxy_argv())
            return
        if target == TOOLBOX_TARGET:
            harnesses = await asyncio.to_thread(built_harnesses)
            self.update(harnesses=[h.name for h in harnesses])
            base = await self.build_toolbox()
            addon_list = await asyncio.to_thread(built_addons, self.store.settings)
        else:
            base = images.ref(images.TOOLBOX, images.LATEST)
            if not await asyncio.to_thread(runtime.exists, base):
                raise BuildError(f"{base} is missing: rebuild the toolbox first")
            if target.startswith(ADDON_PREFIX):
                harnesses, addon_list = [], [addon_with_image(target.removeprefix(ADDON_PREFIX))]
            else:
                harnesses, addon_list = [catalog.get(target)], []
        units: list[catalog.Harness | addons.Addon] = [*harnesses, *addon_list]
        for unit in units:
            recipe = images.recipe(unit, base)
            self.built[_repo(unit)] = await self.image_build(f"build {_label(unit)}", recipe)
        for h in harnesses:
            await self.check_harness(h)
        for a in addon_list:
            await self.check_addon(a, base)
        self.update(stage="switch")
        # harnesses before the toolbox: an engine may keep an old toolbox while one is built on it
        for repo in sorted(self.built, key=lambda r: r == images.TOOLBOX):
            await asyncio.to_thread(switch, repo, self.built[repo], self.line)
        self.built = {}
        for name, image in self.extracted.items():
            await asyncio.to_thread(addon_folders.switch, self.store.settings, name, image)
            self.line(f"{ADDON_PREFIX}{name} switched to {image[:12]}")
        if self.record is not None:
            toolbox.write_record(self.store.settings, self.record)

    async def check_harness(self, harness: catalog.Harness) -> None:
        image = self.built[harness.descriptor.image]
        self.update(stage=f"check {harness.name}", step=None, steps=None)
        version = await asyncio.to_thread(runtime.version, image, images.version_file(harness))
        self.line(f"{harness.name}: {version or 'no version recorded'}")
        if version:
            self.update(versions=self.build.versions | {harness.name: version})
        await image_check.check(self.store.settings, harness, image, self.line)

    async def check_addon(self, addon: addons.Addon, base: str) -> None:
        """Its new image extracted into a folder of its own, then removed (the folder is what
        runs), the folder checked in the toolbox `base` (G.4)."""
        settings = self.store.settings
        image = self.built.pop(_repo(addon))
        self.update(stage=f"check {_label(addon)}", step=None, steps=None)
        try:
            folder = await asyncio.to_thread(addon_folders.extract, settings, addon, image)
        except addon_folders.ExtractError as e:
            raise BuildError(str(e)) from None
        finally:
            await asyncio.to_thread(runtime.remove, image)
        self.extracted[addon.name] = image
        version = await image_check.check_addon(settings, addon, str(folder), base, self.line)
        self.update(versions=self.build.versions | {_label(addon): version})

    async def build_toolbox(self) -> str:
        """The toolbox from its parts, checked; returns its image id (B.7)."""
        settings = self.store.settings
        try:
            manifest = catalog.toolbox()
            packages = toolbox_parts.ordered(manifest)
            context = settings.state_dir / toolbox.CONTEXT_DIR
            await asyncio.to_thread(
                toolbox_parts.write_context, context, manifest, toolbox_parts.lines()
            )
        except (OSError, ValueError) as e:  # toolbox.toml, a system package: ToolboxError
            raise BuildError(f"the toolbox cannot be generated: {e}") from None
        self.line(
            f"toolbox: {manifest.distro}, system packages: "
            f"{', '.join(p.name for p in packages) or 'none'}"
        )
        recipe = images.toolbox_recipe(context, update=self.update_toolbox)
        stage = "update toolbox" if self.update_toolbox else "build toolbox"
        base = self.built[images.TOOLBOX] = await self.image_build(stage, recipe)
        self.update(stage="check toolbox", step=None, steps=None)
        await image_check.check_system_packages(settings, base, packages, self.line)
        commands = await image_check.toolbox_commands(
            settings, base, toolbox.known_commands(manifest), self.line
        )
        if lacking := toolbox.missing(toolbox.needs_in_use(self.store.registry), commands):
            raise BuildError(f"the new toolbox lacks {'; '.join(lacking)}")
        self.record = ToolboxRecord(
            image_id=base,
            built_at=datetime.now(UTC),
            distro=manifest.distro,
            system_packages={p.name: p.manifest.version for p in packages},
            commands=commands,
        )
        return base

    async def image_build(self, stage: str, recipe: images.Recipe) -> str:
        """Run a build; returns the id of the image it built."""
        iidfile = self.store.dir / f"{self.build.id}.iid"
        await self.run_logged(stage, runtime.build_argv(recipe, str(iidfile)))
        image_id = iidfile.read_text().strip()
        iidfile.unlink()
        return image_id

    async def run_logged(self, stage: str, argv: list[str]) -> None:
        """Run the runtime's `argv`, its output to the log and its STEP lines to the build."""
        self.update(stage=stage, step=None, steps=None)
        self.line(f"$ {' '.join(argv)}")
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,  # its own process group: cancel stops the runtime's children
            limit=MAX_LOG_BYTES,
        )
        assert proc.stdout is not None
        try:
            async for raw in proc.stdout:
                text = raw.decode(errors="replace")
                self.line(text)
                if m := _STEP.match(_ANSI.sub("", text)):
                    self.update(step=int(m[1]), steps=int(m[2]))
            code = await proc.wait()
        except asyncio.CancelledError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(proc.wait(), 30)
            raise
        if code != 0:
            raise BuildError(f"{stage} failed (exit code {code}); see the log")


def _repo(unit: catalog.Harness | addons.Addon) -> str:
    if isinstance(unit, addons.Addon):
        assert unit.manifest.image is not None  # buildable addons only
        return unit.manifest.image
    return unit.descriptor.image


def _label(unit: catalog.Harness | addons.Addon) -> str:
    return f"{ADDON_PREFIX}{unit.name}" if isinstance(unit, addons.Addon) else unit.name


def switch(repo: str, image_id: str, line: image_check.Log) -> None:
    """Tag `image_id` `:latest`; the image it replaces is removed unless a container runs from it
    or mounts it (an engine may also keep it while an image is built on it)."""
    latest = images.ref(repo, images.LATEST)
    old = runtime.inspect(latest)
    runtime.tag(image_id, latest)
    if old and old.id != image_id and (why := runtime.remove(old.id)):
        line(f"{old.id[:12]} kept: {why}")
    line(f"{latest} switched to {image_id[:12]}")
