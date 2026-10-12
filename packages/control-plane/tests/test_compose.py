"""Unit tests: composition HarnessLaunch (B) + the agent's sandbox settings → SandboxSpec (A)."""

from pathlib import Path
from typing import Any

import pytest

from handler_contracts import HARNESS_LAUNCH_API_VERSION, HarnessLaunch, Mount
from handler_control import compose


def launch() -> HarnessLaunch:
    return HarnessLaunch(
        api_version=HARNESS_LAUNCH_API_VERSION,
        image="localhost/handler-ai-claude-code:latest",
        argv=["claude-agent-acp"],
        home="/home/agent",
        env={"A": "1"},
        files=[],
        mounts=[Mount(source="/s", target="/home/agent/.claude", read_only=False, kind="state")],
        egress=["api.anthropic.com:443"],
    )


def test_check_scope_inside_allowed_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    assert compose.check_scope([str(tmp_path)], str(project)) == str(project.resolve())


def test_check_scope_rejects_outside_root(tmp_path: Path) -> None:
    root, other = tmp_path / "root", tmp_path / "other"
    root.mkdir()
    other.mkdir()
    with pytest.raises(compose.ScopeError, match="outside the work folders"):
        compose.check_scope([str(root)], str(other))


def test_check_scope_rejects_symlink_escape(tmp_path: Path) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(compose.ScopeError):
        compose.check_scope([str(root)], str(root / "link"))


def test_check_scope_rejects_prefix_sibling(tmp_path: Path) -> None:
    root, sibling = tmp_path / "code", tmp_path / "codex"
    root.mkdir()
    sibling.mkdir()
    with pytest.raises(compose.ScopeError):
        compose.check_scope([str(root)], str(sibling))


def spec(tmp_path: Path, **settings: Any) -> Any:
    agent: dict[str, Any] = {"network": "filtered", "enforcement": "enforce"}
    agent |= {"confinement": "strict", "allow": ["pypi.org:443"]}
    return compose.sandbox_spec(
        name="handler-x", launch=launch(), scope=str(tmp_path), **agent | settings
    )


def test_sandbox_spec(tmp_path: Path) -> None:
    s = spec(tmp_path)
    assert s.workdir == str(tmp_path)
    assert s.mounts[0] == Mount(
        source=str(tmp_path), target=str(tmp_path), read_only=False, kind="scope"
    )
    assert s.user.home == "/home/agent"
    assert s.network.mode == "filtered"
    assert s.network.allow == ["api.anthropic.com:443", "pypi.org:443"]  # required + its own
    assert s.network.enforcement == "enforce"
    assert s.resources is None
    assert s.confinement == "strict"


def test_the_agent_s_confinement(tmp_path: Path) -> None:
    assert spec(tmp_path, confinement="nested").confinement == "nested"


@pytest.mark.parametrize("mode", ["none", "open"])
def test_the_agent_s_network(tmp_path: Path, mode: Any) -> None:
    assert spec(tmp_path, network=mode).network.mode == mode


def test_log_only(tmp_path: Path) -> None:
    s = spec(tmp_path, enforcement="log-only")
    assert s.network.mode == "filtered" and s.network.enforcement == "log-only"


def test_addon_check_runs_as_agents_get_the_addon() -> None:
    """G.4: the addon image mounted in the toolbox, confined like an agent, no network; on PATH
    only when asked (to see first what the toolbox alone provides)."""
    common: dict[str, Any] = {
        "name": "handler-check-1",
        "toolbox": "sha256:toolbox",
        "image": "sha256:addon",
        "target": "/opt/handler/addons/shopify",
        "scope": "/state/image-check/addon-x",
        "argv": ["sh", "-c", "exec 2>&1\nls"],
    }
    spec = compose.addon_check_spec(**common)
    assert (spec.image, spec.confinement, spec.network.mode) == ("sha256:toolbox", "strict", "none")
    assert [(m.image, m.target) for m in spec.image_mounts] == [
        ("sha256:addon", "/opt/handler/addons/shopify")
    ]
    assert (spec.workdir, spec.user.mode, spec.path_append) == (common["scope"], "host-user", [])
    bin_dir = "/opt/handler/addons/shopify/bin"
    assert compose.addon_check_spec(**common, path_append=[bin_dir]).path_append == [bin_dir]
