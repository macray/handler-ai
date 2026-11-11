"""Contract B conformance: the full pipeline for a harness, black box.

    agent ──render (B)──► HarnessLaunch ──compose──► SandboxSpec ──handler-sandbox-<runtime> (A)──► ACP

On the default runtime (runtimes.default_runtime: Podman; Apple container on a Mac), its images
looked up through its own `image inspect` (A.7).

Credentials for real prompt turns are opt-in (tests are skipped without them):
    HANDLER_TEST_CLAUDE_CONFIG_DIR / HANDLER_TEST_CLAUDE_CONFIG_JSON
                                    a Claude login (e.g. ~/.claude-perso)
    HANDLER_TEST_MISTRAL_API_KEY    a Mistral API key
"""

import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import AgentSpec, McpServer, NetworkMode
from handler_control import compose
from handler_harness import catalog, render

from ..sandbox.conftest import popen
from ..support import dev_env
from ..support.acp_client import AcpClient
from ..support.runtimes import default_runtime


def image_present(image: str) -> bool:
    runtime = default_runtime()
    if runtime is None:
        return False
    found = [runtime.binary, "image", "inspect", image]
    return subprocess.run(found, capture_output=True, check=False).returncode == 0


@pytest.fixture
def scope() -> Iterator[Path]:
    path = dev_env.make_scope()
    yield path
    dev_env.remove_scope(path)


def make_agent(harness: str, scope: Path, **overrides: Any) -> AgentSpec:
    """The harness on an account built here (no account file), unless `overrides` say."""
    data: dict[str, Any] = {"harness": harness, "account": "conformance"}
    return AgentSpec.model_validate(data | overrides)


def start_agent(
    agent: AgentSpec,
    scope: Path,
    files: dict[str, str] | None = None,
    *,
    account_token: str | None = None,
    provider_key: str | None = None,
    mcp_servers: list[McpServer] | None = None,
    network: NetworkMode = "none",
    allow: list[str] | None = None,
) -> tuple[AcpClient, Any]:
    """Run the real pipeline and return an ACP client connected to the agent + the launch
    (`mcp_servers`: as an addon gives them), in bypass mode, with this network."""
    harness = catalog.get(agent.harness)
    checked = compose.check_scope([str(scope.parent)], str(scope))
    launch = render(
        harness.descriptor,
        agent,
        files or {},
        account_token=account_token,
        provider_key=provider_key,
        mcp_servers=mcp_servers,
        permission_mode="bypass",
    )
    spec = compose.sandbox_spec(
        name=f"handler-test-{uuid.uuid4().hex[:10]}",
        launch=launch,
        scope=checked,
        network=network,
        enforcement="enforce",
        confinement="strict",
        allow=allow,
    )
    runtime = default_runtime()
    assert runtime is not None  # image_present said so
    if network != "none":
        dev_env.ensure_network_filter(runtime.binary)
    doc = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    proc = popen(
        runtime.binary, doc, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )  # fmt: skip
    return AcpClient.over_process(proc, on_permission="deny"), launch
