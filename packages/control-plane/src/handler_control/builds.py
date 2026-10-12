"""Image rebuilds (contract D.4): build from the files on disk, check, switch. One at a time.

    harness   an untagged image FROM toolbox:latest, no cache (fetches the agent's latest release)
              → check (image_check) → tagged :latest
    addon:X   the same for an addon's image (G.4), checked by mounting it into the toolbox
    toolbox   an untagged toolbox (pull + no cache: system updates) → every harness image and
              every addon image already built, FROM it → check each → tag them all, or none
    network-filter  the egress proxy's image (A.3), the runtime's own: `image build-proxy` builds
              it (pull + no cache), checks it and switches to it (A.7)

The image `:latest` leaves is removed if nothing uses it (the runtime refuses while a container
runs from it or mounts it, A.7). There is no rollback: to go back, fix the files and rebuild.

A failed or cancelled build removes the images it built; `:latest` only ever moves to an image
that passed its check. Running agents keep the image they started with.

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
from datetime import UTC, datetime
from typing import IO, Any

from handler_contracts import Build, BuildLog
from handler_harness import addons, catalog, images

from . import image_check, runtime
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
        raise NoImageError(f"addon '{name}' has no image (nothing to build)")
    return addon


def repository(target: str) -> str:
    """The image repository a harness or `addon:<name>` target builds."""
    if target.startswith(ADDON_PREFIX):
        image = addon_with_image(target.removeprefix(ADDON_PREFIX)).manifest.image
        assert image is not None
        return image
    return catalog.get(target).descriptor.image


def built_addons() -> list[addons.Addon]:
    """The valid addons whose image is already built: a toolbox rebuild rebuilds those. An addon
    never built is not in use, so it is not built behind the user's back; invalid ones are
    reported by GET /v1/addons."""
    found = []
    for name in addons.names():
        with contextlib.suppress(addons.InvalidAddonError):
            image = (addon := addons.get(name)).manifest.image
            if image is not None and runtime.exists(images.ref(image, images.LATEST)):
                found.append(addon)
    return found


class BuildStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dir = settings.state_dir / "builds"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.running: tuple[str, asyncio.Task[None]] | None = None
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

    def start(self, target: str) -> Build:
        """`target`: "toolbox", "network-filter", a harness name (unknown →
        catalog.UnknownHarnessError) or "addon:<name>" (→ addons.UnknownAddonError,
        InvalidAddonError, NoImageError)."""
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
        self._save(build)
        job = asyncio.create_task(_Job(self, build).run())
        self.running = (build.id, job)
        job.add_done_callback(lambda _: setattr(self, "running", None))
        return build

    @staticmethod
    def check_target(target: str) -> None:
        """Raises if `target` cannot be built (see `start`)."""
        if target not in (TOOLBOX_TARGET, NETWORK_FILTER_TARGET):
            repository(target)

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

    def __init__(self, store: BuildStore, build: Build) -> None:
        self.store = store
        self.build = build
        self.log_size = 0
        self.out: IO[str] | None = None
        self.built: dict[str, str] = {}  # repository → id of its new image, until tagged

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
                (self.store.dir / f"{self.build.id}.iid").unlink(missing_ok=True)
                self.update(ended_at=datetime.now(UTC))
                self.out = None

    async def steps(self) -> None:
        target = self.build.target
        if target == NETWORK_FILTER_TARGET:
            await self.run_logged("build network filter", runtime.build_proxy_argv())
            return
        if target == TOOLBOX_TARGET:
            recipe = images.toolbox_recipe()
            base = self.built[images.TOOLBOX] = await self.image_build("build toolbox", recipe)
            harnesses = catalog.all_harnesses()
            addon_list = await asyncio.to_thread(built_addons)
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
            image = self.built[h.descriptor.image]
            self.update(stage=f"check {h.name}", step=None, steps=None)
            version = await asyncio.to_thread(runtime.version, image, images.version_file(h))
            self.line(f"{h.name}: {version or 'no version recorded'}")
            if version:
                self.update(versions=self.build.versions | {h.name: version})
            await image_check.check(self.store.settings, h, image, self.line)
        for a in addon_list:
            image = self.built[_repo(a)]
            self.update(stage=f"check {_label(a)}", step=None, steps=None)
            version = await image_check.check_addon(self.store.settings, a, image, base, self.line)
            self.update(versions=self.build.versions | {_label(a): version})
        self.update(stage="switch")
        # harnesses before the toolbox: an old toolbox can only go once nothing is built on it
        for repo in sorted(self.built, key=lambda r: r == images.TOOLBOX):
            await asyncio.to_thread(switch, repo, self.built[repo], self.line)
        self.built = {}

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
    """Tag `image_id` `:latest`; the image it replaces is removed unless something still uses it
    (a container runs from it or mounts it, an image is built on it)."""
    latest = images.ref(repo, images.LATEST)
    old = runtime.inspect(latest)
    runtime.tag(image_id, latest)
    if old and old.id != image_id and (why := runtime.remove(old.id)):
        line(f"{old.id[:12]} kept: {why}")
    line(f"{latest} switched to {image_id[:12]}")
