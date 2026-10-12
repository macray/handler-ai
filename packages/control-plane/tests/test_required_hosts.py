"""Unit tests: the hosts a filtered agent requires, as clients are shown them, are the ones its
sandboxes are given (A.3, D.2)."""

from pathlib import Path

from handler_contracts import FilteredNetwork
from handler_control import launcher
from handler_control.agents import AgentRecord, RunsAs
from handler_control.settings import Settings


def settings(tmp_path: Path) -> Settings:
    """A provider for Codex, the miniapp addon bound as "apps", work folders under code/."""
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
    (s.bindings_dir / "apps.toml").write_text(
        'apiVersion = "handler.binding/v1"\naddon = "miniapp"\n'
    )
    return s


def test_shown_hosts_are_the_sandbox_allow_list(tmp_path: Path) -> None:
    s = settings(tmp_path)
    local, other = (RunsAs(harness="codex", provider=p) for p in ("local", "other"))
    agent = AgentRecord(
        id="a1",
        models=[local, other],
        scope=str(tmp_path / "code" / "shop"),
        bindings=["apps"],
        allow=["own.test:443"],
    )
    spec, _, base = launcher.prepare(s, agent, local, "c1")
    shown = launcher.required_hosts(s, launcher.agent_spec(s, local), agent)
    assert base is not None and sorted(h.host for h in shown) == base
    assert isinstance(spec.network, FilteredNetwork)
    assert spec.network.allow == sorted({*base, "own.test:443"})
    assert {(h.host, h.by) for h in shown} == {
        ("llm.test:8080", "provider local"),
        ("registry.npmjs.org:443", "addon miniapp: apps"),
        ("jsr.io:443", "addon miniapp: apps"),
    }


def test_a_session_reaches_only_its_own_models_hosts(tmp_path: Path) -> None:
    s = settings(tmp_path)
    local, other = (RunsAs(harness="codex", provider=p) for p in ("local", "other"))
    agent = AgentRecord(id="a1", models=[local, other], scope=str(tmp_path / "code" / "shop"))
    _, _, on_local = launcher.prepare(s, agent, local, "c1")
    _, _, on_other = launcher.prepare(s, agent, other, "c2")
    assert on_local == ["llm.test:8080"]
    assert on_other == ["other.test:8080"]
