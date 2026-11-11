"""Image rebuilds (D.4): what the check reports, the build log, restart recovery. No podman here;
the real build → check → switch flow is in tests/harness/test_rebuild.py."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from handler_contracts import (
    AddonManifest,
    Build,
    BuildState,
    HarnessDescriptor,
    NoNetwork,
    ToolboxRecord,
)
from handler_control import builds, compose
from handler_control.agents import AgentRegistry
from handler_control.builds import BuildStore, _Job
from handler_control.image_check import (
    DUMMY_SECRET,
    MCP_PROBE_ENV,
    ImageCheckError,
    check_agent,
    mcp_probe,
    mcp_problems,
    mismatches,
)
from handler_control.settings import Settings
from handler_harness import catalog, images
from handler_harness.addons import Addon

DESCRIPTOR = HarnessDescriptor.model_validate(
    {
        "apiVersion": "handler.harness/v1",
        "name": "agent",
        "product": "Agent",
        "image": "localhost/handler-ai-agent",
        "acpCommand": ["agent-acp"],
        "home": "/home/agent",
        "modelOption": "model",
        "permissions": {
            "ask": {"sessionMode": "default"},
            "accept-edits": {"sessionMode": "acceptEdits"},
            "bypass": {"sessionMode": "bypassPermissions"},
        },
    }
)


def session(modes: list[str], options: list[str]) -> dict[str, Any]:
    return {
        "modes": {"availableModes": [{"id": m} for m in modes]},
        "configOptions": [{"id": o} for o in options],
    }


@pytest.mark.rule("image.checked-against-its-descriptor")
def test_check_accepts_a_matching_session() -> None:
    modes = ["default", "acceptEdits", "bypassPermissions", "plan"]
    assert mismatches(DESCRIPTOR, session(modes, ["model"])) == []


@pytest.mark.rule("image.checked-against-its-descriptor")
def test_check_reports_a_renamed_mode_and_a_missing_model_option() -> None:
    problems = mismatches(DESCRIPTOR, session(["default", "acceptEdits", "yolo"], []))
    assert len(problems) == 2
    assert "'bypass'" in problems[0] and "'bypassPermissions'" in problems[0]
    assert "yolo" in problems[0]  # what the agent offers instead, to fix the descriptor
    assert "'model'" in problems[1]


def settings(tmp_path: Path) -> Settings:
    return Settings(
        port=0,
        config_dir=tmp_path,
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path,
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
    )


def build(state: BuildState = "running", build_id: str = "b1") -> Build:
    return Build(
        id=build_id,
        target="vibe",
        state=state,
        started_at=datetime.now(UTC),
    )


@pytest.mark.rule(
    "launch.stdio-mcp-servers-see-the-sandbox", "image.checked-against-its-descriptor"
)
def test_the_mcp_probe_must_start_with_the_sandbox_env_and_no_secret() -> None:
    """B6 in the rebuild's check: the stdio server a session gets, as an addon's would."""
    probe = mcp_probe("/scope/.handler-mcp-probe")
    assert (probe.command, probe.args[-1]) == (
        "sh",
        "env > /scope/.handler-mcp-probe; exec cat > /dev/null",
    )
    good = f"PATH=/usr/bin\n{MCP_PROBE_ENV}=m4rk\n"
    assert mcp_problems(good, "m4rk", "s3cr3t") == []
    assert "did not start" in mcp_problems(None, "m4rk", "s3cr3t")[0]
    [reduced] = mcp_problems("PATH=/usr/bin\n", "m4rk", "s3cr3t")  # vibe's own env, unwrapped
    assert "sandbox's environment" in reduced
    [leak] = mcp_problems(good + "TOKEN=s3cr3t\n", "m4rk", "s3cr3t")
    assert "secret" in leak


@pytest.mark.rule("image.checked-against-its-descriptor")
def test_the_check_gives_each_harness_a_credential_it_accepts() -> None:
    """A token login: a dummy token on an account; else a provider with a dummy key (codex-acp
    refuses session/new with neither), as the conformance suite does. No model is called."""
    claude, token, key = check_agent(catalog.get("claude-code").descriptor)
    assert (claude.account, token, key) == ("image-check", DUMMY_SECRET, None)
    codex, token, key = check_agent(catalog.get("codex").descriptor)
    assert codex.account is None and codex.provider_spec is not None
    assert (token, key) == (None, DUMMY_SECRET)
    assert set(codex.provider_spec.endpoints) == {"responses"}


def test_daemon_restart_fails_running_builds(tmp_path: Path) -> None:
    store = BuildStore(settings(tmp_path), AgentRegistry(tmp_path))
    store._save(build("running"))
    restarted = BuildStore(settings(tmp_path), AgentRegistry(tmp_path))
    found = restarted.get("b1")
    assert found is not None and found.state == "failed" and found.error == "daemon restarted"


def test_log_is_read_in_whole_lines_from_an_offset(tmp_path: Path) -> None:
    store = BuildStore(settings(tmp_path), AgentRegistry(tmp_path))
    (store.dir / "b1.log").write_text("STEP 1/2: FROM x\nSTEP 2/2: RUN é")
    first = store.read_log(build("running"), 0)
    assert first.text == "STEP 1/2: FROM x\n" and not first.complete  # the last line is unfinished
    rest = store.read_log(build("succeeded"), first.next_offset)
    assert rest.text == "STEP 2/2: RUN é" and rest.complete
    assert store.read_log(build("succeeded"), rest.next_offset).text == ""


def test_log_lines_lose_terminal_escapes(tmp_path: Path) -> None:
    store = BuildStore(settings(tmp_path), AgentRegistry(tmp_path))
    job = _Job(store, build())
    with (store.dir / "b1.log").open("a") as out:
        job.out = out
        job.line("\x1b[1;32mSTEP 1/3:\x1b[0m FROM toolbox\r\n")
    assert (store.dir / "b1.log").read_text() == "STEP 1/3: FROM toolbox\n"


@pytest.mark.rule("toolbox.each-system-package-is-checked")
def test_the_toolbox_check_runs_like_an_agent() -> None:
    s = compose.toolbox_check_spec(name="c", toolbox="t", scope="/s", argv=["bun", "--version"])
    assert (s.image, s.isolation, s.workdir) == ("t", "strict", "/s")
    assert isinstance(s.network, NoNetwork) and s.addons == []


@pytest.mark.rule("tool.built-once-it-can-be")
def test_an_addons_state_follows_its_builds(tmp_path: Path) -> None:
    """G.5: preparing while a build making it runs (its own, or the toolbox it waits for);
    failed when its last build failed; ready; else installed."""
    store = BuildStore(settings(tmp_path), AgentRegistry(tmp_path))
    assert store.addon_state("tool", ready=False) == ("installed", None)
    assert store.addon_state("tool", ready=True) == ("ready", None)
    failed = build("failed").model_copy(update={"target": "addon:tool", "addons": ["tool"]})
    store._save(failed.model_copy(update={"error": "check: tool --version failed"}))
    assert store.addon_state("tool", ready=False) == ("failed", "check: tool --version failed")
    assert store.addon_state("tool", ready=True) == ("ready", None)  # an older folder works
    store.running_addons = ["tool"]
    assert store.addon_state("tool", ready=True) == ("preparing", None)
    store.running_addons = []
    store.waiting.add("tool")
    store._save(build(build_id="b2").model_copy(update={"target": "toolbox"}))
    store.running = ("b2", cast(Any, None))
    assert store.addon_state("tool", ready=False) == ("preparing", None)
    store.running = None
    assert store.addon_state("tool", ready=False)[0] == "failed"  # no toolbox build: waits


class FakeImages:
    """The runtime's side of a toolbox build: every image built gets an id; what is tagged
    `:latest`, removed, and the toolbox record written are kept, in order."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        failing_check: str | None,
        built: list[str] | None = None,  # the harnesses already built; None: every one
    ) -> None:
        self.tagged: list[str] = []
        self.removed: list[str] = []
        self.records: list[ToolboxRecord] = []

        async def image_build(job: _Job, stage: str, recipe: Any) -> str:
            return f"id-of-{stage}"

        async def build_toolbox(job: _Job) -> str:  # as it ends: its image built and checked
            base = job.built[images.TOOLBOX] = "id-of-build toolbox"
            job.record = ToolboxRecord(
                image_id=base, built_at=datetime.now(UTC), distro="x", system_packages={},
                commands={},
            )  # fmt: skip
            return base

        async def check(*args: Any) -> None:
            return None

        async def check_addon(settings: Settings, addon: Any, *args: Any) -> str:
            if addon.name == failing_check:
                raise ImageCheckError(f"check: {addon.name} --version failed")
            return "1.0"

        tool = Addon(
            AddonManifest.model_validate(
                {
                    "apiVersion": "handler.tool/v1",
                    "name": "tool",
                    "image": TOOL_IMAGE,
                    "commands": ["tool"],
                }
            ),
            Path("/addons/tool"),
        )
        for target, name, value in [
            (_Job, "image_build", image_build),
            (_Job, "build_toolbox", build_toolbox),
            (builds, "built_addons", lambda settings: [tool]),
            (
                builds,
                "built_harnesses",
                lambda: [h for h in catalog.all_harnesses() if built is None or h.name in built],
            ),
            (builds.images, "recipe", lambda unit, base: None),
            (builds.runtime, "version", lambda image, file: None),
            (builds.runtime, "remove", self.removed.append),
            (builds.image_check, "check", check),
            (builds.image_check, "check_addon", check_addon),
            (builds.addon_folders, "extract", lambda settings, addon, image: Path("/f")),
            (builds.addon_folders, "release", lambda *args: None),
            (builds.addon_folders, "sweep", lambda *args: None),
            (builds.addon_folders, "switch", lambda *args: None),
            (builds, "switch", lambda repo, image, line: self.tagged.append(repo)),
            (builds.toolbox, "write_record", lambda settings, record: self.records.append(record)),
        ]:
            monkeypatch.setattr(target, name, value)


TOOL_IMAGE = "localhost/handler-ai-tool-tool"


def _toolbox_build(tmp_path: Path) -> _Job:
    store = BuildStore(settings(tmp_path), AgentRegistry(tmp_path))
    job = _Job(store, build().model_copy(update={"target": "toolbox"}))
    asyncio.run(job.run())
    return job


@pytest.mark.rule("toolbox.switches-with-all-its-images")
def test_a_toolbox_build_whose_addon_check_fails_switches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The toolbox and every harness image built and checked, then one addon's check fails:
    nothing is tagged `:latest`, every image it built is removed, the record is not written.

    If this fails: a harness runs on the new toolbox and an addon on the old one, and a command
    one needs is missing."""
    fake = FakeImages(monkeypatch, failing_check="tool")
    job = _toolbox_build(tmp_path)
    assert job.build.state == "failed" and "tool --version failed" in (job.build.error or "")
    assert fake.tagged == [] and fake.records == []
    harness_ids = [f"id-of-build {h.name}" for h in catalog.all_harnesses()]
    assert set(harness_ids) | {"id-of-build toolbox"} <= set(fake.removed)


@pytest.mark.rule("toolbox.switches-with-all-its-images")
def test_a_toolbox_build_whose_checks_pass_switches_every_image_then_the_toolbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If this fails: agents run on images built on two toolboxes, or the record says a toolbox
    nothing runs on."""
    fake = FakeImages(monkeypatch, failing_check=None)
    job = _toolbox_build(tmp_path)
    assert job.build.state == "succeeded", job.build.error
    harness_repos = [h.descriptor.image for h in catalog.all_harnesses()]
    assert sorted(fake.tagged[:-1]) == sorted(harness_repos)
    assert fake.tagged[-1] == images.TOOLBOX  # once nothing is built on the old one
    assert [r.image_id for r in fake.records] == ["id-of-build toolbox"]


@pytest.mark.rule("toolbox.switches-with-all-its-images")
def test_a_toolbox_build_rebuilds_only_the_harnesses_already_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only codex built: the toolbox build rebuilds codex and says so (`harnesses`); the other
    agent programs wait for their own first build.

    If this fails: a first setup builds every agent program (gigabytes) when one was chosen, or
    the web UI follows a toolbox build for a program it does not make."""
    fake = FakeImages(monkeypatch, failing_check=None, built=["codex"])
    job = _toolbox_build(tmp_path)
    assert job.build.state == "succeeded", job.build.error
    assert job.build.harnesses == ["codex"]
    codex = catalog.get("codex").descriptor.image
    assert fake.tagged == [codex, images.TOOLBOX]  # the addon's folder switches, not an image


@pytest.mark.rule("toolbox.each-system-package-is-checked")
def test_a_check_whose_sandbox_did_not_start_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    """A check's sandbox that never started (its launcher's 64, 65 or 66) is not the checked
    package's failure: the build says the sandbox did not start, with the launcher's reason.
    If this fails: a missing relay reads "system package podman: its check exited with 66"."""
    from handler_control import image_check, sandbox_process  # noqa: PLC0415

    reason = "setup failed: …/relay/handler-relay is missing"
    script = f"echo '{sandbox_process.launcher_prefix()}{reason}' >&2; exit 66"

    async def start_async(spec: Any, **_: Any) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            "sh", "-c", script,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip

    monkeypatch.setattr(image_check.sandbox_process, "start_async", start_async)
    logged: list[str] = []
    spec = cast(Any, None)
    with pytest.raises(image_check.ImageCheckError, match=f"its sandbox did not start: {reason}"):
        asyncio.run(image_check._run_check(spec, logged.append))
    assert any(reason in line for line in logged)  # in the build's log too
