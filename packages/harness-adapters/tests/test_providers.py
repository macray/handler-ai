"""An agent's provider written for each harness (handler_harness/providers.py), through `render`."""

import json
import tomllib
from typing import Any

import pytest

from handler_contracts import AgentSpec
from handler_harness import RenderError, catalog, render
from handler_harness.providers import reachable

SCOPE = "/home/you/code/project"
LLAMACPP: dict[str, Any] = {
    "apiVersion": "handler.provider/v1",
    "description": "llama.cpp on this machine",
    "endpoints": {
        "openai-chat": "http://127.0.0.1:3000/v1",
        "responses": "http://localhost:3000/v1",
    },
    "models": [
        {
            "id": "qwen",
            "name": "Qwen",
            "contextWindow": 200000,
            "maxOutput": 32768,
            "reasoning": True,
            "temperature": 0.2,
            "native": {"pi": {"compat": {"maxTokensField": "max_tokens"}}},
        },
        {"id": "small"},
    ],
}
ANTHROPIC: dict[str, Any] = {
    "apiVersion": "handler.provider/v1",
    "endpoints": {"anthropic": "https://api.anthropic.com"},
    "apiKey": {"env": "ANTHROPIC_API_KEY"},
    "models": [{"id": "claude-sonnet-5-5"}],
}


def agent(harness: str, provider: dict[str, Any], **overrides: Any) -> AgentSpec:
    """`files`: the provider's for this harness (its `[files.<harness>]`)."""
    data: dict[str, Any] = {
        "harness": harness,
        "provider": "the-provider",
        "providerSpec": provider,
    }
    return AgentSpec.model_validate(data | overrides)


def launch(harness: str, provider: dict[str, Any], key: str | None = None, **overrides: Any):
    p = agent(harness, provider, **overrides)
    files = {slot: "x" for slot in (p.files or {})}
    descriptor = catalog.get(harness).descriptor
    return render(descriptor, p, SCOPE, files, provider_key=key, permission_mode="bypass")


def files(result: Any) -> dict[str, str]:
    return {f.target: f.content for f in result.files}


def test_loopback_is_the_containers_host() -> None:
    assert reachable("http://127.0.0.1:3000/v1") == "http://host.containers.internal:3000/v1"
    assert reachable("http://localhost/v1") == "http://host.containers.internal/v1"
    assert reachable("http://192.168.1.20:3000/v1") == "http://192.168.1.20:3000/v1"
    assert reachable("https://api.example.com/v1") == "https://api.example.com/v1"


def test_codex_gets_a_config_and_a_model_catalog() -> None:
    result = launch("codex", LLAMACPP)
    written = files(result)
    config = tomllib.loads(written["/home/agent/.codex/config.toml"])
    assert config["model"] == "qwen" and config["model_provider"] == "handler"
    assert config["model_providers"]["handler"] == {
        "name": "handler provider",
        "base_url": "http://host.containers.internal:3000/v1",
        "wire_api": "responses",
    }
    assert config["model_reasoning_effort"] == "medium"
    assert "model_instructions_file" not in config
    catalog_json = json.loads(written["/home/agent/.codex/model-catalog.json"])
    [entry] = catalog_json["models"]
    assert (entry["slug"], entry["context_window"], entry["input_modalities"]) == (
        "qwen",
        200000,
        ["text"],
    )
    assert result.env["OPENAI_API_KEY"] == "none"  # a server that checks nothing
    assert result.egress == ["host.containers.internal:3000"]
    assert result.session_defaults is not None
    assert result.session_defaults.config_options is None  # in the config, not chosen over ACP


def test_codex_points_at_the_system_prompt_the_provider_gives() -> None:
    result = launch("codex", LLAMACPP, files={"instructions_md": {"content": "You are…"}})
    config = tomllib.loads(files(result)["/home/agent/.codex/config.toml"])
    assert config["model_instructions_file"] == "~/.codex/instructions.md"
    assert "/home/agent/.codex/instructions.md" in files(result)


def test_vibe_gets_a_provider_and_a_model() -> None:
    result = launch("vibe", LLAMACPP)
    config = tomllib.loads(files(result)["/home/agent/.vibe/config.toml"])
    assert config["active_model"] == "qwen"
    [provider] = config["providers"]
    assert (provider["api_base"], provider["api_key_env_var"]) == (
        "http://host.containers.internal:3000/v1",
        "",
    )
    [model] = config["models"]
    assert (model["name"], model["temperature"], model["thinking"]) == ("qwen", 0.2, "medium")
    assert model["display_name"] == "Qwen"
    # its only window setting: compacts with room left for a reply of maxOutput (B9)
    assert model["auto_compact_threshold"] == 200000 - 32768
    assert "MISTRAL_API_KEY" not in result.env


def test_vibe_reserves_a_default_reply_and_at_most_a_fifth_of_the_window() -> None:
    def threshold(model: dict[str, Any]) -> int:
        config = tomllib.loads(
            files(launch("vibe", LLAMACPP | {"models": [model]}))["/home/agent/.vibe/config.toml"]
        )
        return config["models"][0]["auto_compact_threshold"]

    assert threshold({"id": "m", "contextWindow": 100000}) == 100000 - 16384
    # a small window compacts at 80 %, not at half, whatever its maxOutput
    assert threshold({"id": "m", "contextWindow": 32000, "maxOutput": 32000}) == 25600
    assert threshold({"id": "m", "contextWindow": 65536, "maxOutput": 32768}) == 65536 - 13107


def test_vibe_key_goes_to_its_own_variable() -> None:
    result = launch("vibe", LLAMACPP | {"apiKey": {"env": "K"}}, key="sk-secret")
    config = tomllib.loads(files(result)["/home/agent/.vibe/config.toml"])
    assert config["providers"][0]["api_key_env_var"] == "MISTRAL_API_KEY"
    assert result.env["MISTRAL_API_KEY"] == "sk-secret"
    assert "sk-secret" not in "".join(files(result).values())  # never in a file (B3)


def test_pi_gets_models_and_settings_with_the_models_native_fields() -> None:
    result = launch("pi", LLAMACPP)
    written = files(result)
    models = json.loads(written["/home/agent/.pi/agent/models.json"])
    provider = models["providers"]["handler"]
    assert provider["baseUrl"] == "http://host.containers.internal:3000/v1"
    assert provider["apiKey"] == "none"
    [model, *_] = provider["models"]
    assert model["id"] == "qwen" and model["contextWindow"] == 200000
    assert (model["name"], model["maxTokens"]) == ("Qwen", 32768)
    assert model["compat"] == {"maxTokensField": "max_tokens"}  # `native.pi` merged in
    assert model["samplingParams"] == {"temperature": 0.2}
    settings = json.loads(written["/home/agent/.pi/agent/settings.json"])
    assert (settings["defaultProvider"], settings["defaultModel"]) == ("handler", "qwen")
    assert settings["compaction"] == {"reserveTokens": 32768}  # room for a reply (B9)


def test_pi_reserves_at_most_a_fifth_of_a_small_window() -> None:
    result = launch("pi", LLAMACPP | {"models": [{"id": "small", "contextWindow": 32000}]})
    settings = json.loads(files(result)["/home/agent/.pi/agent/settings.json"])
    assert settings["compaction"] == {"reserveTokens": 6400}  # not pi's own 16384: half of it


def test_pi_key_is_the_name_of_its_variable() -> None:
    result = launch("pi", LLAMACPP, key="sk-secret")
    models = json.loads(files(result)["/home/agent/.pi/agent/models.json"])
    assert models["providers"]["handler"]["apiKey"] == "OPENAI_API_KEY"
    assert result.env["OPENAI_API_KEY"] == "sk-secret"
    assert "sk-secret" not in "".join(files(result).values())


def test_claude_code_gets_its_endpoint_key_and_model_in_the_environment() -> None:
    result = launch("claude-code", ANTHROPIC, key="sk-ant")
    assert result.env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
    assert result.env["ANTHROPIC_API_KEY"] == "sk-ant"
    assert result.env["ANTHROPIC_MODEL"] == "claude-sonnet-5-5"
    assert result.egress == ["api.anthropic.com:443"]  # the provider's, not the harness's
    assert result.session_defaults is not None
    assert result.session_defaults.config_options is None  # the model is not chosen over ACP


def test_the_model_is_chosen_by_config_model() -> None:
    result = launch("vibe", LLAMACPP, config={"model": "small"})
    config = tomllib.loads(files(result)["/home/agent/.vibe/config.toml"])
    assert config["active_model"] == "small"
    with pytest.raises(RenderError, match="no model 'nope'"):
        launch("vibe", LLAMACPP, config={"model": "nope"})


def test_a_protocol_the_harness_does_not_speak_is_refused() -> None:
    with pytest.raises(RenderError, match="speaks openai-chat, the provider anthropic"):
        launch("vibe", ANTHROPIC)
    with pytest.raises(RenderError, match="speaks anthropic, the provider openai-chat"):
        launch("claude-code", LLAMACPP)


def test_a_file_the_provider_writes_cannot_also_be_one_of_its_files() -> None:
    with pytest.raises(RenderError, match="written from provider 'the-provider'"):
        launch("codex", LLAMACPP, files={"config_toml": {"content": "x = 1"}})
    with pytest.raises(RenderError, match="written from provider"):
        launch("pi", LLAMACPP, files={"settings_json": {"content": "{}"}})


def test_the_login_or_the_provider_hosts_are_the_only_egress() -> None:
    codex = catalog.get("codex").descriptor
    on_provider = render(codex, agent("codex", LLAMACPP), SCOPE, permission_mode="bypass")
    assert on_provider.egress == ["host.containers.internal:3000"]
    written = agent("codex", LLAMACPP).model_dump(by_alias=True, exclude_none=True)
    data = {k: v for k, v in written.items() if k not in ("provider", "providerSpec")}
    on_account = AgentSpec.model_validate(data | {"account": "chatgpt"})
    assert render(codex, on_account, SCOPE, permission_mode="bypass").egress == [
        "chatgpt.com:443",
        "auth.openai.com:443",
    ]
