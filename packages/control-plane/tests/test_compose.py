"""Unit tests: composition HarnessLaunch (B) + the agent's sandbox settings → SandboxSpec (A)."""

import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import (
    HARNESS_LAUNCH_API_VERSION,
    Addon,
    HarnessLaunch,
    HostFolder,
    Injection,
    SystemPackageDaemon,
)
from handler_control import compose


def launch() -> HarnessLaunch:
    return HarnessLaunch(
        api_version=HARNESS_LAUNCH_API_VERSION,
        image="localhost/handler-ai-claude-code:latest",
        argv=["claude-agent-acp"],
        home="/home/agent",
        env={"A": "1"},
        folders=[HostFolder(source="/s", target="/home/agent/.claude", writable=True)],
        skills=[
            HostFolder(
                source="/k/review", target="/home/agent/.claude/skills/review", writable=False
            )
        ],
        egress=["api.anthropic.com:443"],
    )


@pytest.mark.rule("folders.agents-work-only-inside-them")
def test_check_scope_inside_allowed_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    assert compose.check_scope([str(tmp_path)], str(project)) == str(project.resolve())


@pytest.mark.rule("folders.agents-work-only-inside-them")
def test_check_scope_rejects_outside_root(tmp_path: Path) -> None:
    root, other = tmp_path / "root", tmp_path / "other"
    root.mkdir()
    other.mkdir()
    with pytest.raises(compose.ScopeError, match="outside the work folders"):
        compose.check_scope([str(root)], str(other))


@pytest.mark.rule("folders.agents-work-only-inside-them")
def test_check_scope_rejects_symlink_escape(tmp_path: Path) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(compose.ScopeError):
        compose.check_scope([str(root)], str(root / "link"))


@pytest.mark.rule("folders.agents-work-only-inside-them")
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


@pytest.mark.rule("agent.it-reaches-only-the-hosts-of-what-it-uses")
def test_sandbox_spec(tmp_path: Path) -> None:
    s = spec(tmp_path)
    assert s.workdir == str(tmp_path)
    assert s.work_folder.path == str(tmp_path)
    assert [f.target for f in s.folders] == [
        "/home/agent/.claude",
        "/home/agent/.claude/skills/review",
    ]
    assert s.home == "/home/agent"
    assert s.network.mode == "filtered"
    assert s.network.allow == ["api.anthropic.com:443", "pypi.org:443"]  # required + its own
    assert s.network.enforcement == "enforce"
    assert s.resources is None
    assert s.isolation == "strict"


def test_the_agent_s_confinement(tmp_path: Path) -> None:
    assert spec(tmp_path, confinement="nested").isolation == "nested"


@pytest.mark.parametrize("mode", ["none", "open"])
def test_the_agent_s_network(tmp_path: Path, mode: Any) -> None:
    assert spec(tmp_path, network=mode).network.mode == mode


def test_log_only(tmp_path: Path) -> None:
    s = spec(tmp_path, enforcement="log-only")
    assert s.network.mode == "filtered" and s.network.enforcement == "log-only"


DOCKERD = SystemPackageDaemon(
    command="handler-dockerd",
    abilities=["nested", "privileged"],
    env={"DOCKER_HOST": "unix:///tmp/handler-docker/docker.sock"},
)


@pytest.mark.rule("toolbox.a-daemon-only-for-agents-given-its-ability")
def test_the_toolbox_s_daemons_start_before_the_program_where_their_abilities_are(
    tmp_path: Path,
) -> None:
    s = spec(tmp_path, confinement="nested", daemons=[DOCKERD])
    assert s.argv == [compose.DAEMONS_TOOL, "handler-dockerd", "--", "claude-agent-acp"]
    assert compose.DAEMONS_TOOL in [t.target for t in s.tools]
    assert s.env["DOCKER_HOST"] == "unix:///tmp/handler-docker/docker.sock"
    strict = spec(tmp_path, daemons=[DOCKERD])  # its abilities only
    assert strict.argv == ["claude-agent-acp"]
    assert "DOCKER_HOST" not in strict.env
    assert compose.DAEMONS_TOOL not in [t.target for t in strict.tools]


@pytest.mark.rule("toolbox.a-daemon-only-for-agents-given-its-ability")
def test_the_daemons_command_starts_each_then_runs_the_program(tmp_path: Path) -> None:
    script = tmp_path / "handler-daemons"
    script.write_text(compose.DAEMONS_SCRIPT)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "started"
    daemon = bin_dir / "fake-daemon"
    daemon.write_text(f"#!/bin/sh\necho running\ntouch {marker}\nsleep 30\n")
    daemon.chmod(0o755)
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    out = subprocess.run(
        ["sh", str(script), "fake-daemon", "--", "echo", "the program"],
        capture_output=True, text=True, env=env, check=True, timeout=10,
    )  # fmt: skip
    assert out.stdout == "the program\n"  # the daemon's output is not on the agent's stdio
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.1)
    assert marker.exists()
    subprocess.run(["pkill", "-f", str(daemon)], check=False)


@pytest.mark.rule("toolbox.a-daemon-only-for-agents-given-its-ability")
def test_a_daemon_s_env_set_by_the_harness_too_is_refused(tmp_path: Path) -> None:
    clashing = DOCKERD.model_copy(update={"env": {"A": "2"}})
    with pytest.raises(compose.DaemonConflictError, match="A"):
        spec(tmp_path, confinement="nested", daemons=[clashing])


@pytest.mark.rule("tool.checked-against-its-manifest")
def test_addon_check_runs_as_agents_get_the_addon() -> None:
    """G.4: the addon image mounted in the toolbox, confined like an agent, no network; on PATH
    only when asked (to see first what the toolbox alone provides)."""
    common: dict[str, Any] = {
        "name": "handler-check-1",
        "toolbox": "sha256:toolbox",
        "source": "/data/addons/shopify/abc",
        "target": "/opt/handler/addons/shopify",
        "scope": "/state/image-check/addon-x",
        "argv": ["sh", "-c", "exec 2>&1\nls"],
    }
    spec = compose.addon_check_spec(**common)
    assert (spec.image, spec.isolation, spec.network.mode) == ("sha256:toolbox", "strict", "none")
    assert [(a.source, a.target, a.path) for a in spec.addons] == [
        ("/data/addons/shopify/abc", "/opt/handler/addons/shopify", None)
    ]
    assert (spec.workdir, spec.work_folder.path) == (common["scope"],) * 2
    bin_dir = "/opt/handler/addons/shopify/bin"
    assert compose.addon_check_spec(**common, path=bin_dir).addons[0].path == bin_dir


@pytest.mark.rule("connection.its-check-runs-as-an-agent-would")
def test_a_connection_check_gets_what_an_agent_of_it_gets_no_more() -> None:
    """G.2: the tool's folder on PATH in the toolbox, the env given (its secrets' phantoms), the
    network filtered and enforced to the tool's egress alone with the injections swapping them
    back, an empty folder to work in, confined like an agent."""
    tool = Addon(
        source="/data/addons/shopify/abc",
        target="/opt/tools/shopify",
        path="/opt/tools/shopify/bin",
    )
    injection = Injection(
        name="connections/shop/theme_token",
        phantom="shptka_00000000000000000000000000",
        value="shptka_1234567890abcdef1234567890",
        hosts=["theme-kit-access.shopifyapps.com:443"],
    )
    spec = compose.connection_check_spec(
        name="handler-check-2",
        toolbox="localhost/handler-ai-toolbox:latest",
        scope="/state/image-check/connection-shop-x",
        argv=["shopify", "theme", "list"],
        tool=tool,
        env={"SHOPIFY_FLAG_STORE": "a.myshopify.com", "SHOPIFY_CLI_THEME_TOKEN": injection.phantom},
        egress=["theme-kit-access.shopifyapps.com:443", "*.myshopify.com:443"],
        injections=[injection],
    )
    assert (spec.image, spec.isolation) == ("localhost/handler-ai-toolbox:latest", "strict")
    assert spec.argv == ["shopify", "theme", "list"] and spec.addons == [tool]
    assert spec.env["SHOPIFY_CLI_THEME_TOKEN"] == injection.phantom  # never the value
    assert injection.value not in spec.env.values()
    network = spec.network
    assert network.mode == "filtered" and network.enforcement == "enforce"
    assert network.allow == ["*.myshopify.com:443", "theme-kit-access.shopifyapps.com:443"]
    assert network.injections == [injection]
    assert (spec.workdir, spec.work_folder.path) == ("/state/image-check/connection-shop-x",) * 2
    assert spec.folders == [] and spec.caches == []  # no project, no notes, nothing kept


@pytest.mark.rule("terminal.only-what-you-paste")
def test_a_terminal_reads_what_is_pasted_as_its_clipboard(tmp_path: Path) -> None:
    """D.16: the paste need, its folder the client's; not without a paste folder."""
    pasted = spec(tmp_path, paste="/run/user/1000/handler-ai/terminals/handler-x")
    assert pasted.paste is not None
    assert pasted.paste.source == "/run/user/1000/handler-ai/terminals/handler-x"
    assert spec(tmp_path).paste is None


@pytest.mark.rule("files.access-lists-what-the-sandbox-sees")
def test_what_a_session_sees_is_each_by_what_it_is(tmp_path: Path) -> None:
    """F.8: its folder, the harness's state, skills, knowledge, a subject, an addon's tools."""
    known = [HostFolder(source="/n", target="/notes/n", writable=False)]
    subject = HostFolder(source="/sk/x", target="/subject/x", writable=False)
    addons = compose.AddonLaunch(images=[Addon(source="/data/addons/i/abc", target="/opt/tools/i")])
    seen = compose.seen(launch=launch(), scope=str(tmp_path), addons=addons, knowledge=known,
                        subject=subject)  # fmt: skip
    assert [(m.kind, m.target, m.read_only, m.browsable) for m in seen] == [
        ("scope", str(tmp_path), False, True),
        ("state", "/home/agent/.claude", False, False),
        ("config", "/home/agent/.claude/skills/review", True, True),
        ("knowledge", "/notes/n", True, True),
        ("subject", "/subject/x", True, True),
        ("tools", "/opt/tools/i", True, False),
    ]


@pytest.mark.rule("agent.its-env-reaches-each-start")
def test_the_agent_s_own_variables_reach_its_sandbox(tmp_path: Path) -> None:
    s = spec(tmp_path, agent_env={"ASTRO_TELEMETRY_DISABLED": "1"})
    assert s.env["ASTRO_TELEMETRY_DISABLED"] == "1" and s.env["A"] == "1"  # the harness's kept


@pytest.mark.rule("agent.its-env-never-sets-what-others-own")
def test_the_agent_s_own_variables_never_replace_another_s(tmp_path: Path) -> None:
    """Checked again at start: what the save could not see (a session on another model, a tool
    given by its project since, a toolbox daemon, a terminal)."""
    with pytest.raises(compose.AgentEnvConflictError, match="A"):
        spec(tmp_path, agent_env={"A": "2"})  # its harness's
    tools = compose.AddonLaunch(env={"SHOP": "x"})
    with pytest.raises(compose.AgentEnvConflictError, match="SHOP"):
        spec(tmp_path, addons=tools, agent_env={"SHOP": "y"})
    dockerd = {"daemons": [DOCKERD], "confinement": "nested"}
    with pytest.raises(compose.AgentEnvConflictError, match="DOCKER_HOST"):
        spec(tmp_path, **dockerd, agent_env={"DOCKER_HOST": "tcp://elsewhere"})


@pytest.mark.rule("knowledge.schemas-read-only")
def test_an_agent_s_schemas_are_read_only_files_its_command_finds(tmp_path: Path) -> None:
    """D.29: the files of its knowledge uses' schemas, read-only in its home, `SMD_SCHEMAS`
    their folder (no flag for the format's command); none: neither."""
    s = spec(tmp_path, schemas={"contacts@1.schema.json": "{}\n"})
    assert s.env["SMD_SCHEMAS"] == "/home/agent/.smd-schemas"
    [given] = [f for f in s.files if f.target.startswith("/home/agent/.smd-schemas/")]
    assert (given.target, given.content, given.mode, given.writable) == (
        "/home/agent/.smd-schemas/contacts@1.schema.json",
        "{}\n",
        "0444",
        False,
    )
    assert "SMD_SCHEMAS" not in spec(tmp_path).env
    with pytest.raises(compose.AgentEnvConflictError, match="SMD_SCHEMAS"):
        spec(tmp_path, schemas={"a@1.schema.json": "{}"}, agent_env={"SMD_SCHEMAS": "/tmp"})
