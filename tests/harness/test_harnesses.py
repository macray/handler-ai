"""Contract B conformance for every harness in harnesses/ (contract B)."""

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import McpServer, Provider, StdioMcpServer
from handler_control.settings import TEMPLATES
from handler_harness import catalog, images

from ..support import dev_env
from ..support.acp_client import AcpClient
from ..support.dev_env import sandbox_uid
from .conftest import image_present, make_agent, start_agent

REPO = Path(__file__).resolve().parents[2]

HARNESSES = [h.name for h in catalog.all_harnesses()]
pytestmark = pytest.mark.timeout(dev_env.IMAGE_TIMEOUT)


def _require_image(name: str) -> None:
    image = images.ref(catalog.get(name).descriptor.image, images.LATEST)
    if not image_present(image):
        pytest.skip(f"{image} not built (run: handler image rebuild toolbox)")


@pytest.mark.parametrize("name", HARNESSES)
@pytest.mark.rule("image.checked-against-its-descriptor")
def test_image_answers_initialize(name: str, scope: Path) -> None:
    _require_image(name)
    client, _ = start_agent(make_agent(name, scope), scope)
    try:
        result = client.initialize()
        assert result["protocolVersion"] >= 1
    finally:
        client.close()


# A provider written into each harness's own configuration (handler_harness/providers.py). No model
# is called, so no server is needed: a dummy key is enough for session/new (pi-acp refuses it
# without a provider, codex-acp logs in with the key, DEFAULT_AUTH_REQUEST, without checking it).
PROVIDER = {
    "apiVersion": "handler.provider/v1",
    "endpoints": {
        "openai-chat": "http://127.0.0.1:3000/v1",
        "responses": "http://127.0.0.1:3000/v1",
        "anthropic": "http://127.0.0.1:3000",
    },
    "models": [{"id": "handler-probe-model", "contextWindow": 32000, "reasoning": True}],
}


def session_agent(
    name: str,
    scope: Path,
    key: str,
    mcp_servers: list[McpServer] | None = None,
    **network: Any,
) -> tuple[AcpClient, Any]:
    """An agent that can start a session with no real credential: on a provider, whose key is
    checked at the first prompt. (Claude Code on an account would wait ~20 s at session/new
    first: it retries fetching its remote settings from api.anthropic.com, unreachable here.)"""
    on_provider = {"account": None, "provider": "probe", "providerSpec": PROVIDER}
    agent = make_agent(name, scope, **on_provider)
    return start_agent(agent, scope, provider_key=key, mcp_servers=mcp_servers, **network)


@pytest.mark.parametrize("name", HARNESSES)
@pytest.mark.rule("image.checked-against-its-descriptor")
def test_descriptor_matches_real_session(name: str, scope: Path) -> None:
    """Every mapped ACP mode and the model option must exist in the harness's real session."""
    _require_image(name)
    descriptor = catalog.get(name).descriptor
    client, _ = session_agent(name, scope, "dummy-key-for-session-new")
    try:
        client.initialize()
        session = client.new_session(str(scope))
    finally:
        client.close()
    modes = {m["id"] for m in session["modes"]["availableModes"]}
    for neutral, mapping in descriptor.permissions.items():
        if mapping.session_mode:
            assert mapping.session_mode in modes, (
                f"{neutral} → {mapping.session_mode} not in {modes}"
            )
    if descriptor.model_option:
        options = {o["id"] for o in session.get("configOptions") or []}
        assert descriptor.model_option in options


@pytest.mark.parametrize(
    "name", [h.name for h in catalog.all_harnesses() if "stdio" in h.descriptor.mcp_transports]
)
@pytest.mark.rule("launch.stdio-mcp-servers-see-the-sandbox")
def test_stdio_mcp_server_gets_the_sandbox_env(name: str, scope: Path) -> None:
    """B.1 mcpTransports / mcpEnv: the harness starts the stdio MCP servers of session/new, and
    they see the sandbox's environment (here the proxy of a filtered network), whatever the
    harness passes them, but not the harness's own secrets. No prompt, no credentials needed."""
    _require_image(name)
    dump = scope / "mcp-env"
    server = StdioMcpServer(
        name="probe", command="sh", args=["-c", f"env > {dump}; exec cat > /dev/null"]
    )
    client, launch = session_agent(
        name,
        scope,
        "mcp-probe-s3cr3t",
        mcp_servers=[server],
        network="filtered",
        allow=["example.org:443"],
    )
    try:
        client.initialize()
        assert launch.session_defaults is not None
        servers = [
            s.model_dump(mode="json", by_alias=True)
            for s in launch.session_defaults.mcp_servers or []
        ]
        client.request("session/new", {"cwd": str(scope), "mcpServers": servers})  # as P8 does
        deadline = time.monotonic() + 30
        while not dump.exists() and time.monotonic() < deadline:
            time.sleep(0.5)
        time.sleep(0.5)
        env = dict(line.split("=", 1) for line in dump.read_text().splitlines() if "=" in line)
    finally:
        client.close()
    assert env.get("HTTPS_PROXY", "").startswith("http://"), sorted(env)
    assert "mcp-probe-s3cr3t" not in dump.read_text()


# ── real prompt turns (opt-in: need credentials) ───────────────────────


def _bypass_turn(
    name: str, scope: Path, overrides: dict[str, object], provider_key: str | None = None
) -> None:
    agent = make_agent(name, scope, **overrides)
    client, launch = start_agent(agent, scope, provider_key=provider_key, network="open")
    try:
        client.initialize()
        session = client.new_session(str(scope))
        assert launch.session_defaults is not None and launch.session_defaults.mode_id
        client.request(
            "session/set_mode",
            {"sessionId": session["sessionId"], "modeId": launch.session_defaults.mode_id},
        )  # P7, done here by the test (the control plane does it from M3)
        result = client.prompt(
            session["sessionId"],
            "Using your shell tool, run exactly: echo handler-ok > handler-ok.txt . "
            "Then reply 'done'.",
        )
    finally:
        client.close()
    assert result["stopReason"] == "end_turn"
    assert client.permission_requests == [], "bypass mode must not ask for permission"
    assert client.other_agent_requests == [], "no fs/terminal delegation to the client"
    written = scope / "handler-ok.txt"
    assert written.read_text().strip() == "handler-ok"
    assert written.stat().st_uid == sandbox_uid()


@pytest.mark.skipif(
    not os.environ.get("HANDLER_TEST_CLAUDE_CONFIG_DIR"),
    reason="HANDLER_TEST_CLAUDE_CONFIG_DIR not set",
)
def test_claude_bypass_turn(scope: Path) -> None:
    _require_image("claude-code")
    state = {"config_dir": os.environ["HANDLER_TEST_CLAUDE_CONFIG_DIR"]}
    if json_file := os.environ.get("HANDLER_TEST_CLAUDE_CONFIG_JSON"):
        state["config_json"] = json_file
    _bypass_turn("claude-code", scope, {"state": state})


@pytest.mark.skipif(
    not os.environ.get("HANDLER_TEST_MISTRAL_API_KEY"),
    reason="HANDLER_TEST_MISTRAL_API_KEY not set",
)
def test_vibe_bypass_turn(scope: Path, tmp_path: Path) -> None:
    """On an account: the dotenv file Vibe's sign-in leaves, holding the key."""
    _require_image("vibe")
    login = tmp_path / "credential"
    login.write_text(f"MISTRAL_API_KEY={os.environ['HANDLER_TEST_MISTRAL_API_KEY']}\n")
    _bypass_turn("vibe", scope, {"accountLogin": str(login)})


@pytest.mark.skipif(
    not os.environ.get("HANDLER_TEST_OPENAI_API_KEY"), reason="HANDLER_TEST_OPENAI_API_KEY not set"
)
def test_codex_bypass_turn(scope: Path) -> None:
    """On the OpenAI API: the provider of templates/providers/openai-api.toml."""
    _require_image("codex")
    template = TEMPLATES / "providers" / "openai-api.toml"
    spec = Provider.from_toml(template.read_text()).model_dump(by_alias=True, exclude_none=True)
    on_provider = {"account": None, "provider": "openai-api", "providerSpec": spec}
    _bypass_turn("codex", scope, on_provider, os.environ["HANDLER_TEST_OPENAI_API_KEY"])


LOCAL_MODEL_CONFIG = """
active_model = "local-coder"

[[providers]]
name = "local"
api_base = "http://host.containers.internal:11434/v1"
api_key_env_var = ""

[[models]]
name = "qwen2.5-coder:7b"
provider = "local"
alias = "local-coder"
"""


def test_vibe_custom_config_toml(scope: Path) -> None:
    """A provider's config.toml for Vibe reaches it (local model), and Vibe can still rewrite it."""
    _require_image("vibe")
    files = {"config_toml": {"content": LOCAL_MODEL_CONFIG}}
    client, _ = start_agent(
        make_agent("vibe", scope, files=files), scope, {"config_toml": LOCAL_MODEL_CONFIG}
    )
    try:
        client.initialize()
        session = client.new_session(str(scope))
        model = next(o for o in session["configOptions"] if o["id"] == "model")
        assert model["currentValue"] == "local-coder"
        params = {
            "sessionId": session["sessionId"],
            "configId": "model",
            "value": "mistral-medium-3.5",
        }
        client.request("session/set_config_option", params)  # Vibe persists this into config.toml
    finally:
        client.close()


@pytest.mark.parametrize("name", HARNESSES)
@pytest.mark.rule("provider.every-field-reaches-the-harness")
def test_provider_config_is_accepted_by_the_harness(name: str, scope: Path) -> None:
    """The real harness accepts the provider as written: the session starts, and it offers the
    provider's model."""
    _require_image(name)
    agent = make_agent(name, scope, account=None, provider="probe", providerSpec=PROVIDER)
    client, launch = start_agent(agent, scope)
    try:
        client.initialize()
        session = client.new_session(str(scope))
    finally:
        client.close()
    assert launch.egress == ["host.containers.internal:3000"] or name == "claude-code"
    options = {o["id"]: o for o in session.get("configOptions") or []}
    if name != "claude-code":  # its model comes from the environment, not from the ACP options
        assert "handler-probe-model" in json.dumps(options["model"]), options["model"]
