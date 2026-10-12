"""Contract E — Provider (`handler.provider/v1`): where a harness sends its model calls: an endpoint
for each protocol it speaks, an optional key, and the models it serves (a local llama.cpp,
OpenRouter, a Claude API key). Hand-written TOML, one file per provider in
`~/.config/handler-ai/providers/<name>.toml`. A provider knows nothing of harnesses: each harness
says which protocols it accepts, and how to express a provider in its own configuration
(handler_harness/providers.py)."""

import tomllib
from collections.abc import Sequence
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlparse

from pydantic import AfterValidator, Field, model_validator

from .common import AccessContext, FileSource, SecretRef, StrictDocument

PROVIDER_API_VERSION = "handler.provider/v1"

Protocol = Literal["anthropic", "openai-chat", "responses"]
PROTOCOLS: tuple[Protocol, ...] = ("anthropic", "openai-chat", "responses")


def _endpoint(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("must be an http:// or https:// URL")
    if parsed.username or parsed.password:
        raise ValueError("must not carry credentials (the key goes in apiKey)")
    try:
        parsed.port  # noqa: B018 — raises ValueError for a port out of range
    except ValueError:
        raise ValueError("has an invalid port") from None
    return url


Endpoint = Annotated[str, AfterValidator(_endpoint)]


class ProviderModel(StrictDocument):
    id: Annotated[str, Field(min_length=1)]
    name: str | None = None  # for showing it; the id otherwise
    context_window: Annotated[int, Field(gt=0)] | None = None
    max_output: Annotated[int, Field(gt=0)] | None = None
    reasoning: bool = False
    images: bool = False
    temperature: Annotated[float, Field(ge=0, le=2)] | None = None
    # what only one harness knows about this model, merged into the entry written for it:
    # `[models.native.pi]`, `[models.native.codex]`… (a chat template, a compat flag)
    native: dict[str, dict[str, Any]] | None = None


class Provider(StrictDocument):
    api_version: Literal["handler.provider/v1"]
    description: str | None = None
    # the URL to give a harness for each protocol the server speaks: the same server may speak
    # several (llama.cpp: openai-chat and responses), often at different paths
    endpoints: Annotated[dict[Protocol, Endpoint], Field(min_length=1)]
    api_key: SecretRef | None = None  # none for a local server
    models: Annotated[list[ProviderModel], Field(min_length=1)]
    # how one harness talks to this model: content for its config file slots (B.1 configFiles),
    # `[files.codex] instructions_md = { file = "…" }`
    files: dict[str, dict[str, FileSource]] | None = None
    # the project contexts it may be used in (D.19), as an account's
    contexts: list[AccessContext] = []

    @model_validator(mode="after")
    def _unique_models(self) -> Self:
        ids = [m.id for m in self.models]
        if duplicates := sorted({i for i in ids if ids.count(i) > 1}):
            raise ValueError(f"two models have the id {', '.join(duplicates)}")
        return self

    def endpoint_for(self, accepted: Sequence[Protocol]) -> tuple[Protocol, str] | None:
        """The first of the protocols `accepted` (in order of preference) it has an endpoint for."""
        return next(((p, self.endpoints[p]) for p in accepted if p in self.endpoints), None)

    def model_named(self, model_id: str) -> ProviderModel | None:
        return next((m for m in self.models if m.id == model_id), None)

    @classmethod
    def from_toml(cls, text: str) -> Self:
        return cls.model_validate(tomllib.loads(text))
