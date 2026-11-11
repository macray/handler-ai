"""Unit tests: the hosts a filtered agent requires, as clients are shown them, are the ones its
sandboxes are given (A.3, D.2)."""

from pathlib import Path

import pytest

from handler_contracts import AddonUse, FilteredNetwork
from handler_control import launcher
from handler_control.agents import AgentRecord, RunsAs
from handler_control.settings import Settings


@pytest.fixture(autouse=True)
def tool_addon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An addon with a tool image (app-builder has none), without settings."""
    folder = tmp_path / "addons" / "tool"
    folder.mkdir(parents=True)
    (folder / "tool.toml").write_text(
        'apiVersion = "handler.tool/v1"\nname = "tool"\n'
        'image = "localhost/handler-ai-tool-tool"\ncommands = ["tool"]\n'
    )
    (folder / "Containerfile").write_text("FROM scratch\n")
    monkeypatch.setenv("HANDLER_TOOLS_DIR", str(folder.parent))


def settings(tmp_path: Path) -> Settings:
    """A provider for Codex, work folders under code/."""
    s = Settings(
        port=0,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path / "bindings",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        accounts_dir=tmp_path / "accounts",
        providers_dir=tmp_path / "providers",
        skills_dir=tmp_path / "skills",
        knowledge_dir=tmp_path / "knowledge",
    )
    for folder in (s.config_dir, s.bindings_dir, s.providers_dir, tmp_path / "code" / "shop"):
        folder.mkdir(parents=True)
    (s.config_dir / "folders.toml").write_text(f'roots = ["{tmp_path / "code"}"]\n')
    for name, host in (("local", "llm.test:8080"), ("other", "other.test:8080")):
        (s.providers_dir / f"{name}.toml").write_text(
            'apiVersion = "handler.provider/v1"\n'
            f'endpoints = {{ responses = "http://{host}/v1" }}\n'
            'models = [{ id = "m" }]\n'
        )
    return s


@pytest.mark.rule("agent.it-reaches-only-the-hosts-of-what-it-uses")
def test_shown_hosts_are_the_sandbox_allow_list(tmp_path: Path) -> None:
    s = settings(tmp_path)
    local = RunsAs(harness="codex", provider="local")
    agent = AgentRecord(
        id="a1",
        model=local,
        scope=str(tmp_path / "code" / "shop"),
        addons=[AddonUse(addon="app-builder")],
        allow=["own.test:443"],
    )
    spec, _, base, _ = launcher.prepare(s, agent, local, "c1")
    shown = launcher.required_hosts(s, launcher.agent_spec(s, local), agent)
    assert base is not None and sorted(h.host for h in shown) == base
    assert isinstance(spec.network, FilteredNetwork)
    assert spec.network.allow == sorted({*base, "own.test:443"})
    assert {(h.host, h.by) for h in shown} == {
        ("llm.test:8080", "provider local"),
        ("registry.npmjs.org:443", "the app-builder tool"),
    }


@pytest.mark.rule("agent.it-reaches-only-the-hosts-of-what-it-uses")
def test_a_session_reaches_only_its_models_hosts(tmp_path: Path) -> None:
    s = settings(tmp_path)
    local, other = (RunsAs(harness="codex", provider=p) for p in ("local", "other"))
    agent = AgentRecord(id="a1", model=local, scope=str(tmp_path / "code" / "shop"))
    _, _, on_local, _ = launcher.prepare(s, agent, local, "c1")
    _, _, on_other, _ = launcher.prepare(s, agent, other, "c2")
    assert on_local == ["llm.test:8080"]
    assert on_other == ["other.test:8080"]


def test_a_sandbox_needing_an_image_not_built_is_not_launched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A.7: a launch never builds an image; the error names the build that makes it (D.4)."""
    s = settings(tmp_path)
    local = RunsAs(harness="codex", provider="local")
    agent = AgentRecord(id="a1", model=local, scope=str(tmp_path / "code" / "shop"))
    spec, _, _, _ = launcher.prepare(
        s, agent.model_copy(update={"addons": [AddonUse(addon="tool")]}), local, "c1"
    )
    built = {spec.image}
    monkeypatch.setattr(launcher.runtime, "not_ready", lambda: None)
    monkeypatch.setattr(launcher.runtime, "missing_proxy", lambda _: False)
    monkeypatch.setattr(launcher.runtime, "exists", lambda ref: ref in built)
    with pytest.raises(launcher.ImageMissingError) as refused:
        launcher._require_images(spec, "codex")
    assert refused.value.target == "addon:tool"
    assert "`handler image rebuild tool:tool`" in str(refused.value)

    built.clear()  # its harness's first
    with pytest.raises(launcher.ImageMissingError) as refused:
        launcher._require_images(spec, "codex")
    assert refused.value.target == "codex"

    monkeypatch.setattr(launcher.runtime, "missing_proxy", lambda _: True)
    with pytest.raises(launcher.ImageMissingError) as refused:
        launcher._require_images(spec, "codex")
    assert str(refused.value) == launcher.NETWORK_FILTER_MISSING


def test_an_engine_that_cannot_run_is_said_not_an_image_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stopped engine (Apple's service, Docker Desktop) knows of no image: its host check's
    reason is said, not a build to make (which would fail too)."""
    why = "Apple container 1.7.1: container service: not running: `container system start`"
    monkeypatch.setattr(launcher.runtime, "not_ready", lambda: why)
    refused = launcher.missing(launcher.NETWORK_FILTER)
    assert not isinstance(refused, launcher.ImageMissingError)
    assert str(refused) == f"sandboxes cannot start now: {why}"
