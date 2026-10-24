"""How a provider (contract E, `handler.provider/v1`) is written in a harness's own configuration.

A provider says where model calls go: an endpoint, its protocol, a key, the models. Each harness
that can use one (`providerProtocols` in its descriptor) has a function here turning it into what
that harness reads: environment variables, and the content of its config file slots. Pure, like
`render` (B1): the key arrives resolved, files are returned as text.

Every field of a provider's model reaches the harness where it has a setting for it (B9): the
context window is what it measures the conversation against, and it compacts early enough to leave
room for a reply of `max_output` tokens (`reserve`), at most a fifth of the window.

The `native` table of a model (`[models.native.<harness>]`) is merged into the entry written for
that harness, for what only it knows (a chat template, a compat flag).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from handler_contracts import HarnessDescriptor, Provider, ProviderModel, egress_target

CONTAINER_HOST = "host.containers.internal"  # a container's name for the machine it runs on
_LOOPBACK = ("localhost", "127.0.0.1", "::1")
NO_KEY = "none"  # what a server that checks nothing is given as a key
REPLY_RESERVE = 16384  # room left for a reply when the model gives no max_output (pi's default)
RESERVE_SHARE = 0.2  # the most of a window kept free: a small window still compacts at 80 %


class ProviderError(ValueError):
    """The provider cannot be expressed for this harness (E1, B5)."""


@dataclass(frozen=True)
class Expressed:
    env: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)  # config file slot → content
    secret_env: list[str] = field(default_factory=list)  # the variables of `env` holding the key


@dataclass(frozen=True)
class Call:
    """Everything an adapter needs, resolved."""

    descriptor: HarnessDescriptor
    provider: Provider
    model: ProviderModel
    endpoint: str  # the one for the harness's protocol, as the agent reaches it (`reachable`)
    key: str | None
    has_instructions: bool  # the provider's files give the harness a system prompt file


def reachable(endpoint: str) -> str:
    """The endpoint as the agent reaches it: in a container, the machine's loopback is not the
    host's, so `http://127.0.0.1:3000` is written with the container host's name."""
    parsed = urlparse(endpoint)
    if parsed.hostname not in _LOOPBACK:
        return endpoint
    netloc = f"{CONTAINER_HOST}:{parsed.port}" if parsed.port else CONTAINER_HOST
    return parsed._replace(netloc=netloc).geturl()


def choose_endpoint(descriptor: HarnessDescriptor, provider: Provider) -> str:
    """The provider's endpoint for a protocol the harness speaks (its first choice first)."""
    if not descriptor.provider_protocols or descriptor.name not in ADAPTERS:
        raise ProviderError(f"harness '{descriptor.name}' cannot use a provider")
    found = provider.endpoint_for(descriptor.provider_protocols)
    if found is None:
        accepted = ", ".join(descriptor.provider_protocols)
        speaks = ", ".join(provider.endpoints)
        raise ProviderError(f"harness '{descriptor.name}' speaks {accepted}, the provider {speaks}")
    return found[1]


def egress(descriptor: HarnessDescriptor, provider: Provider) -> str:
    """The allow-list entry the provider needs (A.3): its endpoint's host and port."""
    return egress_target(reachable(choose_endpoint(descriptor, provider)))


def choose_model(provider: Provider, wanted: str | None, harness: str) -> ProviderModel:
    if wanted is None:
        if not provider.chat_models:
            raise ProviderError("provider serves speech models only")
        return provider.chat_models[0]
    if (model := provider.model_named(wanted)) is None:
        known = ", ".join(m.id for m in provider.chat_models)
        raise ProviderError(f"provider has no model '{wanted}' (it serves: {known})")
    return model


def express(
    descriptor: HarnessDescriptor,
    provider: Provider,
    wanted_model: str | None,
    key: str | None,
    *,
    has_instructions: bool = False,
) -> Expressed:
    """`provider` written for `descriptor`'s harness. ProviderError if it cannot be."""
    endpoint = choose_endpoint(descriptor, provider)  # ProviderError for a harness without
    call = Call(
        descriptor=descriptor,
        provider=provider,
        model=choose_model(provider, wanted_model, descriptor.name),
        endpoint=reachable(endpoint),
        key=key,
        has_instructions=has_instructions,
    )
    return ADAPTERS[descriptor.name](call)


def reserve(model: ProviderModel, context: int) -> int:
    """The tokens a harness keeps free in a `context` window for the reply (B9): the model's
    `max_output`, at most a fifth of the window (a `max_output` as large as the window would
    otherwise compact a small one at half)."""
    return min(model.max_output or REPLY_RESERVE, int(context * RESERVE_SHARE))


def _merged(call: Call, entry: dict[str, Any]) -> dict[str, Any]:
    return entry | ((call.model.native or {}).get(call.descriptor.name) or {})


# ── one function per harness ────────────────────────────────────────────


def claude_code(call: Call) -> Expressed:
    """Claude Code reads the endpoint, the key and the model from its environment."""
    env = {"ANTHROPIC_BASE_URL": call.endpoint, "ANTHROPIC_MODEL": call.model.id}
    key = {"ANTHROPIC_API_KEY": call.key or NO_KEY}
    return Expressed(env=env | key, secret_env=list(key))


def codex(call: Call) -> Expressed:
    """Codex: a model provider in config.toml, and a model catalog for a model it does not know."""
    m = call.model
    lines = [
        f"model = {_toml(m.id)}",
        'model_provider = "handler"',
        'model_catalog_json = "~/.codex/model-catalog.json"',
        'web_search = "disabled"',
    ]
    if m.reasoning:
        lines.insert(2, 'model_reasoning_effort = "medium"')
    if call.has_instructions:
        lines.append('model_instructions_file = "~/.codex/instructions.md"')
    lines += [
        "",
        "[features]",
        "plugins = false",
        "goals = false",
        "multi_agent = false",
        "view_image = false",
        "",
        "[tools.update_plan]",
        "enabled = true",
        "",
        "[model_providers.handler]",
        'name = "handler provider"',
        f"base_url = {_toml(call.endpoint)}",
        'wire_api = "responses"',
    ]
    context = m.context_window or 128000
    entry = {
        "slug": m.id,
        "display_name": m.name or m.id,
        "description": call.provider.description or "Model of a handler provider",
        "default_reasoning_level": "medium",
        "supported_reasoning_levels": [
            {"effort": "low", "description": "Fast responses with lighter reasoning"},
            {"effort": "medium", "description": "Balances speed and reasoning depth"},
            {"effort": "high", "description": "Greater reasoning depth for complex problems"},
        ],
        "shell_type": "shell_command",
        "visibility": "list",
        "supported_in_api": True,
        "priority": 1,
        "availability_nux": None,
        "upgrade": None,
        "support_verbosity": False,
        "default_verbosity": None,
        "apply_patch_tool_type": None,
        "truncation_policy": {"mode": "bytes", "limit": 20000},
        "context_window": context,
        "max_context_window": context,
        "experimental_supported_tools": [],
        "input_modalities": ["text", "image"] if m.images else ["text"],
        "supports_search_tool": False,
        "include_skills_usage_instructions": True,
        "include_plugin_usage_instructions": False,
        "include_apps_usage_instructions": False,
        "model_messages": {
            "instructions_template": "Placeholder: the system prompt comes from instructions_md."
        },
    }
    catalog = {"models": [_merged(call, entry)]}
    return Expressed(
        env={"OPENAI_API_KEY": call.key or NO_KEY},
        secret_env=["OPENAI_API_KEY"],
        files={
            "config_toml": "\n".join(lines) + "\n",
            "model_catalog_json": json.dumps(catalog, indent=2) + "\n",
        },
    )


def vibe(call: Call) -> Expressed:
    """Vibe: a provider and a model in config.toml. Vibe has no context window setting: its
    `auto_compact_threshold` is both where it compacts and the window it reports over ACP; no
    setting takes the maximum output either."""
    m = call.model
    key_env = "MISTRAL_API_KEY" if call.key else ""
    provider = [
        "[[providers]]",
        'name = "handler"',
        f"api_base = {_toml(call.endpoint)}",
        f"api_key_env_var = {_toml(key_env)}",
        'api_style = "openai"',
        'backend = "generic"',
        'reasoning_field_name = "reasoning_content"',
        'project_id = ""',
        'region = ""',
    ]
    model = {
        "name": m.id,
        "provider": "handler",
        "alias": m.id,
        "display_name": m.name or m.id,
        "temperature": 0.2 if m.temperature is None else m.temperature,
        "input_price": 0.0,
        "output_price": 0.0,
        "supports_images": m.images,
    }
    if m.reasoning:
        model["thinking"] = "medium"
    if m.context_window:
        model["auto_compact_threshold"] = m.context_window - reserve(m, m.context_window)
    model = _merged(call, model)
    lines = [f"active_model = {_toml(m.id)}", "", *provider, "", "[[models]]"]
    lines += [f"{key} = {_toml(value)}" for key, value in model.items()]
    env = {key_env: call.key} if call.key else {}
    return Expressed(env=env, files={"config_toml": "\n".join(lines) + "\n"}, secret_env=list(env))


def pi(call: Call) -> Expressed:
    """pi: a provider in models.json, chosen in settings.json, which also says how much of the
    window compaction keeps free (`reserveTokens`)."""
    m = call.model
    entry: dict[str, Any] = {
        "id": m.id,
        "name": m.name or m.id,
        "reasoning": m.reasoning,
        "input": ["text", "image"] if m.images else ["text"],
    }
    if m.context_window:
        entry["contextWindow"] = m.context_window
    if m.max_output:
        entry["maxTokens"] = m.max_output
    if m.temperature is not None:
        entry["samplingParams"] = {"temperature": m.temperature}
    key_env = "OPENAI_API_KEY"
    models = {
        "providers": {
            "handler": {
                "baseUrl": call.endpoint,
                "api": "openai-completions",
                "apiKey": key_env if call.key else NO_KEY,  # the variable's name, or a literal
                "models": [_merged(call, entry)],
            }
        }
    }
    settings: dict[str, Any] = {
        "defaultProvider": "handler",
        "defaultModel": m.id,
        "defaultThinkingLevel": "medium" if m.reasoning else "off",
        "quietStartup": True,
    }
    window = m.context_window or 128000  # pi's own without one
    settings["compaction"] = {"reserveTokens": reserve(m, window)}
    return Expressed(
        env={key_env: call.key} if call.key else {},
        secret_env=[key_env] if call.key else [],
        files={
            "models_json": json.dumps(models, indent=2) + "\n",
            "settings_json": json.dumps(settings, indent=2) + "\n",
        },
    )


def _toml(value: object) -> str:
    """A TOML value for a string, number or boolean (a JSON string is a valid TOML basic string)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value)


ADAPTERS: dict[str, Callable[[Call], Expressed]] = {
    "claude-code": claude_code,
    "codex": codex,
    "vibe": vibe,
    "pi": pi,
}
