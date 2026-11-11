"""The `llm/v1` service's connector, built into handlerd (I.5): model calls on a provider, with
its key from the secret store (it never enters a sandbox). Text in, text out: no tools are ever
offered to the model, and an answer asking for one is refused (D.18, I.5).

    complete    "provider/model" + LlmRequest → LlmResponse (a script's call): the provider's
                `openai-chat` endpoint (else its `anthropic` one); with a schema, the JSON taken
                from the answer and checked, and asked once more with the error when it does not
                match
    converse    a conversation → the model's next message (an agent on the model alone, D.18)
    check       a provider and model the model alone can run on (when an agent is saved)

Errors are those of `llm/v1` (services.ServiceError): `unavailable` when the provider fails or
cannot be reached, `refused` when its answer asks for a tool. The caller (the router, the model
agent) enforces the selection and the limits.
"""

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from handler_contracts import CONTAINER_HOST, LlmRequest, LlmResponse, LlmUsage, Provider

from . import interfaces, providers, secrets
from .services import ServiceError
from .settings import Settings

PROTOCOLS = ("openai-chat", "anthropic")  # in order of preference
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 8192  # an answer's, when the provider's model does not say (anthropic needs one)
FENCED = re.compile(r"```(?:json)?[ \t]*\n(.*?)\n```", re.S)
ERROR_CHARS = 300  # of a provider's error told
# an anthropic answer's blocks that are text; any other (a tool call) is refused
ANTHROPIC_TEXT_BLOCKS = ("text", "thinking", "redacted_thinking")
TOOL_REFUSED = "the model asked for a tool: it has none, text in and text out only"


@dataclass(frozen=True)
class Completion:
    response: LlmResponse
    repaired: bool  # the answer was asked for once more


@dataclass(frozen=True)
class Target:
    protocol: str
    url: str
    model: str
    key: str | None
    max_tokens: int


def target(settings: Settings, model: str) -> Target:
    """A script's "provider/model" (I.5), ready to call."""
    provider_name, _, model_id = model.partition("/")
    return target_of(settings, provider_name, model_id)


def target_of(settings: Settings, provider_name: str, model_id: str | None) -> Target:
    """A provider's model (None: its first), ready to call: its endpoint and its key."""
    provider = _provider(settings.providers_dir, provider_name)
    found = provider.endpoint_for(PROTOCOLS)
    chat = provider.chat_models
    described = provider.model_named(model_id) if model_id else (chat[0] if chat else None)
    if found is None or described is None:
        raise ServiceError("unavailable", f"{provider_name}/{model_id}: not a model it can call")
    store = secrets.SecretStore(settings.data_dir)
    try:
        key = secrets.resolve(provider.api_key, store) if provider.api_key else None
    except secrets.SecretError as e:
        raise ServiceError("unavailable", f"provider {provider_name}: {e}") from None
    protocol, endpoint = found
    max_tokens = described.max_output or MAX_TOKENS
    return Target(protocol, from_host(endpoint), described.id, key, max_tokens)


def check(providers_dir: Path, provider_name: str, model_id: str | None) -> None:
    """ValueError unless the model alone can run on that provider's model (D.18): the provider
    loads, speaks one of PROTOCOLS and serves the model."""
    try:
        provider = _provider(providers_dir, provider_name)
    except ServiceError as e:
        raise ValueError(e.message) from None
    if provider.endpoint_for(PROTOCOLS) is None:
        raise ValueError(
            f"provider '{provider_name}' speaks {', '.join(provider.endpoints)}: the model alone "
            f"needs {' or '.join(PROTOCOLS)}"
        )
    if model_id is not None and provider.model_named(model_id) is None:
        served = ", ".join(m.id for m in provider.chat_models)
        raise ValueError(
            f"provider '{provider_name}' has no model '{model_id}' (it serves: {served})"
        )


def secret_values(settings: Settings, provider_name: str) -> list[str]:
    """Invariant 4: the provider's key, to redact; [] when it cannot be read (no call can be
    made either)."""
    try:
        provider = _provider(settings.providers_dir, provider_name)
        store = secrets.SecretStore(settings.data_dir)
        return [secrets.resolve(provider.api_key, store)] if provider.api_key else []
    except (ServiceError, secrets.SecretError):
        return []


def _provider(providers_dir: Path, name: str) -> Provider:
    loaded = providers.get(providers_dir, name)
    if loaded.provider is None:
        raise ServiceError("unavailable", f"provider {name}: {loaded.error}")
    return loaded.provider


def from_host(endpoint: str) -> str:
    """handlerd runs on the host: a container's name for it is the loopback here."""
    parsed = urlparse(endpoint)
    if parsed.hostname != CONTAINER_HOST:
        return endpoint
    netloc = f"127.0.0.1:{parsed.port}" if parsed.port else "127.0.0.1"
    return parsed._replace(netloc=netloc).geturl()


def system_prompt(request: LlmRequest) -> str | None:
    parts = [request.system] if request.system else []
    if request.schema_ is not None:
        parts.append(
            "Answer with one JSON value only, valid against this JSON Schema, and nothing else:\n"
            + json.dumps(request.schema_)
        )
    return "\n\n".join(parts) or None


def user_prompt(request: LlmRequest) -> str:
    if request.input is None:
        return request.prompt
    return f"{request.prompt}\n\n<input>\n{request.input}\n</input>"


def json_in(answer: str) -> Any:
    """The JSON value of an answer: a fenced block's, else from the first `{` or `[` to its
    end. ValueError when there is none."""
    candidates = [m.group(1) for m in FENCED.finditer(answer)]
    starts = [i for i in (answer.find("{"), answer.find("[")) if i >= 0]
    if starts:
        candidates.append(answer[min(starts) :])
    for candidate in candidates:
        try:
            return json.JSONDecoder().raw_decode(candidate.strip())[0]
        except ValueError:
            continue
    raise ValueError("no JSON value in the answer")


async def chat(
    client: httpx.AsyncClient, t: Target, system: str | None, messages: list[dict[str, str]]
) -> tuple[str, int, int]:
    """One request: (the answer's text, input tokens, output tokens). Its body offers no tools;
    an answer calling one anyway is `refused`."""
    if t.protocol == "openai-chat":
        headers = {"Authorization": f"Bearer {t.key}"} if t.key else {}
        sent = ([{"role": "system", "content": system}] if system else []) + messages
        body: dict[str, Any] = {"model": t.model, "messages": sent, "max_tokens": t.max_tokens}
        url = t.url.rstrip("/") + "/chat/completions"
    else:
        headers = {"anthropic-version": ANTHROPIC_VERSION}
        if t.key:
            headers["x-api-key"] = t.key
        body = {"model": t.model, "max_tokens": t.max_tokens, "messages": messages}
        if system:
            body["system"] = system
        url = t.url.rstrip("/") + "/v1/messages"
    try:
        r = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        raise ServiceError("limit", "the provider did not answer in time") from None
    except httpx.HTTPError as e:
        raise ServiceError("unavailable", f"{urlparse(url).netloc}: {e}") from None
    if r.status_code >= 400:
        told = r.text[:ERROR_CHARS]
        raise ServiceError("unavailable", f"the provider answered {r.status_code}: {told}")
    try:
        data = r.json()
        if t.protocol == "openai-chat":
            message = data["choices"][0]["message"]
            if message.get("tool_calls") or message.get("function_call"):
                raise ServiceError("refused", TOOL_REFUSED)
            usage = data.get("usage") or {}
            text = message["content"] or ""
            return text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        if any(b.get("type") not in ANTHROPIC_TEXT_BLOCKS for b in data["content"]):
            raise ServiceError("refused", TOOL_REFUSED)
        text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        usage = data.get("usage") or {}
        return text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ServiceError("unavailable", "the provider's answer could not be read") from None


def checked(answer: str, schema: dict[str, Any]) -> tuple[Any, str | None]:
    """(the answer's JSON value, why it does not match `schema` or None)."""
    try:
        value = json_in(answer)
    except ValueError as e:
        return None, str(e)
    return value, "; ".join(interfaces.errors(schema, value)) or None


async def complete(settings: Settings, request: LlmRequest, timeout: float) -> Completion:
    """ValueError when the request's schema is not a JSON Schema."""
    started = time.monotonic()
    schema = request.schema_
    if schema is not None:
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as e:
            raise ValueError(f"schema: not a JSON Schema: {e.message}") from None
    t = target(settings, request.model)
    system = system_prompt(request)
    messages = [{"role": "user", "content": user_prompt(request)}]
    value, error, repaired = None, None, False
    async with httpx.AsyncClient(timeout=timeout) as client:
        text, tokens_in, tokens_out = await chat(client, t, system, messages)
        if schema is not None:
            value, error = checked(text, schema)
            if error is not None:
                repaired = True
                again = f"Your answer could not be used: {error}. Answer again with one JSON value"
                messages += [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": again + " only, valid against the schema."},
                ]
                text, more_in, more_out = await chat(client, t, system, messages)
                tokens_in, tokens_out = tokens_in + more_in, tokens_out + more_out
                value, error = checked(text, schema)
    response = LlmResponse(
        valid=error is None,
        value=value,
        text=text if schema is None or error is not None else None,
        error=error,
        usage=LlmUsage(in_tokens=tokens_in, out_tokens=tokens_out),
        ms=int((time.monotonic() - started) * 1000),
    )
    return Completion(response, repaired)


@dataclass(frozen=True)
class Reply:
    text: str
    usage: LlmUsage
    ms: int


async def converse(
    settings: Settings,
    provider: str,
    model: str | None,
    system: str | None,
    messages: list[dict[str, str]],
    *,
    timeout: float,
) -> Reply:
    """The model's next message in a conversation (`messages`: user and assistant turns, the
    last the user's), for an agent on the model alone (D.18)."""
    started = time.monotonic()
    t = target_of(settings, provider, model)
    async with httpx.AsyncClient(timeout=timeout) as client:
        text, tokens_in, tokens_out = await chat(client, t, system, messages)
    usage = LlmUsage(in_tokens=tokens_in, out_tokens=tokens_out)
    return Reply(text, usage, int((time.monotonic() - started) * 1000))
