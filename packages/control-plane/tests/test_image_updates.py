"""Automatic image updates (D.4): when they are due, and what a run does."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from handler_contracts import ImageInfo, ProxyImage
from handler_control import __version__, image_updates
from handler_control.agents import AgentRecord, AgentRegistry, RunsAs
from handler_control.builds import BuildBusyError, BuildStore
from handler_control.image_updates import ImageUpdater
from handler_control.settings import Settings


def settings(tmp_path: Path) -> Settings:
    return Settings(
        port=0,
        config_dir=tmp_path,
        state_dir=tmp_path,
        bindings_dir=tmp_path,
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
    )


class FakeBuilds:
    """Builds that end at once: `fail` ones fail; the first start of `busy` finds another build."""

    def __init__(self, fail: frozenset[str] = frozenset(), busy: bool = False) -> None:
        self.fail, self.busy, self.started = fail, busy, []

    def start(self, target: str) -> Any:
        if self.busy:
            self.busy = False
            raise BuildBusyError("another build")
        self.started.append(target)
        return SimpleNamespace(id=target)

    async def wait(self, build_id: str) -> None:
        return None

    def get(self, build_id: str) -> Any:
        return SimpleNamespace(state="failed" if build_id in self.fail else "succeeded", error="x")


def make(tmp_path: Path, builds: "FakeBuilds") -> ImageUpdater:
    return ImageUpdater(settings(tmp_path), cast(BuildStore, builds), AgentRegistry(tmp_path))


def test_the_first_start_counts_from_now(tmp_path: Path) -> None:
    updater = make(tmp_path, FakeBuilds())
    view = updater.view()
    assert view.schedule == "weekly" and not view.running
    assert view.next_run is not None and view.last_run is not None
    assert view.next_run - view.last_run == timedelta(days=7)
    assert (
        json.loads((tmp_path / "image-updates.json").read_text())["handlerVersion"] == __version__
    )
    assert updater.set_schedule("off").next_run is None
    assert make(tmp_path, FakeBuilds()).schedule == "off"


def test_an_upgrade_makes_them_due_now(tmp_path: Path) -> None:
    an_hour_ago = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    state = {
        "schedule": "weekly",
        "lastRun": an_hour_ago,
        "handlerVersion": "0.0.1",
        "lastFailed": [],
    }
    (tmp_path / "image-updates.json").write_text(json.dumps(state))
    updater = make(tmp_path, FakeBuilds())
    due = updater.next_run()
    assert due is not None and due <= datetime.now(UTC)


def test_a_run_rebuilds_every_built_image_and_records_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image_updates, "targets", lambda: ["claude-code", "addon:shopify"])
    monkeypatch.setattr(image_updates, "BUSY_WAIT", 0.01)
    builds = FakeBuilds(fail=frozenset({"addon:shopify"}), busy=True)
    updater = make(tmp_path, builds)

    async def run() -> None:
        assert updater.run_now()
        assert not updater.run_now()  # one run at a time
        assert updater.view().running
        assert updater.run_task is not None
        await updater.run_task

    asyncio.run(run())
    assert builds.started == ["claude-code", "addon:shopify"]  # after the busy one ended
    view = updater.view()
    assert view.last_failed == ["addon:shopify"] and not view.running


def test_handlerd_builds_a_missing_network_filter_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing as handlerd starts: built, after the build running then; built by it: not again."""
    monkeypatch.setattr(image_updates, "BUSY_WAIT", 0.01)
    built: list[ImageInfo | None] = [None, None]
    monkeypatch.setattr(
        image_updates.runtime,
        "proxy",
        lambda: ProxyImage(
            ref="localhost/handler-ai-proxy:2", image=built.pop(0) if built else None
        ),
    )
    builds = FakeBuilds(busy=True)
    asyncio.run(make(tmp_path, builds)._build_missing_network_filter())
    assert builds.started == ["network-filter"]

    present = ImageInfo(id="0" * 64, created=datetime.now(UTC))
    built[:] = [None, present]  # the build running was this one (`handler setup`)
    builds = FakeBuilds(busy=True)
    asyncio.run(make(tmp_path, builds)._build_missing_network_filter())
    assert builds.started == []


def test_updates_start_with_the_network_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_updates.runtime, "exists", lambda ref: "claude" in ref)
    monkeypatch.setattr(image_updates, "built_addons", list)
    assert image_updates.targets() == ["network-filter", "claude-code"]


def test_an_addon_an_agent_uses_is_built_when_it_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As handlerd starts and when an agent starts using one; not without the toolbox."""
    built = {"localhost/handler-ai-toolbox:latest"}
    monkeypatch.setattr(image_updates.runtime, "exists", lambda ref: ref in built)
    addon = tmp_path / "addons" / "tool"
    addon.mkdir(parents=True)
    (addon / "addon.toml").write_text(
        'apiVersion = "handler.addon/v1"\nname = "tool"\n'
        'image = "localhost/handler-ai-addon-tool"\ncommands = ["tool"]\n'
    )
    (addon / "Containerfile").write_text("FROM scratch\n")
    monkeypatch.setenv("HANDLER_ADDONS_DIR", str(addon.parent))
    (tmp_path / "tools.toml").write_text('apiVersion = "handler.binding/v1"\naddon = "tool"\n')
    builds = FakeBuilds()
    updater = make(tmp_path, builds)
    on = RunsAs(harness="codex", provider="local")
    agent = updater.registry.add(AgentRecord(model=on, scope=str(tmp_path)))

    async def saved(bindings: list[str]) -> None:
        agent.bindings = bindings
        updater.registry.save()
        await asyncio.sleep(0)  # the registry's call, on the loop
        if updater.addons_task is not None:
            await updater.addons_task

    async def run() -> None:
        updater.start()  # no agent uses an addon yet
        await saved([])
        assert builds.started == []
        await saved(["tools"])
        assert builds.started == ["addon:tool"]
        await saved(["tools"])  # nothing new used
        assert builds.started == ["addon:tool"]
        await updater.close()

    asyncio.run(run())
    built.clear()  # no toolbox: `handler setup` first
    assert image_updates.missing_addons(updater.registry, tmp_path) == []
