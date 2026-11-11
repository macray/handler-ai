"""Testing a provider — contract D.12: ask its server for the models it serves (`GET
<endpoint>/models`; an Anthropic endpoint's `/v1/models`) from where a sandbox would. A server on
this computer is asked at the address sandboxes reach it by, this computer's address on its
network, never its loopback: a server listening on 127.0.0.1 only answers handlerd but no sandbox.
The answer gives the model ids, and the context when the server reports it (vLLM's
`max_model_len`, OpenRouter's `context_length`, llama-server's `/props`).

The last answer for each set of endpoints is kept while handlerd runs (`Reaches`): a provider's
`reached` (D.12), so one saved after a test in its form shows that test.
"""

import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from handler_contracts import CONTAINER_HOST, Protocol, ProviderModel, ProviderReach
from handler_harness.providers import reachable

from .llm import ANTHROPIC_VERSION

TIMEOUT = 5.0  # seconds: a server on this computer answers its model list at once
ERROR_CHARS = 200
HINT = (
    "A model server on this computer must listen where sandboxes reach it, not only on "
    "127.0.0.1: start llama-server with --host 0.0.0.0 --jinja, Ollama with OLLAMA_HOST=0.0.0.0."
)
CONTEXT_FIELDS = ("max_model_len", "context_length", "context_window")


class NoAddressError(Exception):
    """This computer has no address on a network: nothing in a sandbox reaches its servers."""


def models_url(protocol: Protocol, endpoint: str) -> str:
    """Where the endpoint lists its models, as agents reach it."""
    base = reachable(endpoint).rstrip("/")
    return f"{base}/v1/models" if protocol == "anthropic" else f"{base}/models"


def urls(endpoints: Mapping[Protocol, str]) -> list[str]:
    """The model lists to ask, each once (llama.cpp's two protocols are one server)."""
    return list(dict.fromkeys(models_url(p, e) for p, e in endpoints.items()))


def local(endpoints: Mapping[Protocol, str]) -> bool:
    """Whether its server is on this computer (D.12: shown ready only once it answered)."""
    return any(urlparse(reachable(e)).hostname == CONTAINER_HOST for e in endpoints.values())


def host_address() -> str:
    """This computer's address on its network: where podman's `host.containers.internal` and
    Docker's `host-gateway` lead, not its loopback. The interface of its default route (a UDP
    socket sends nothing when connected), else what its name resolves to."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1: never reached
            return probe.getsockname()[0]
        except OSError:
            pass
    try:
        named = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        named = []
    found = next((a for a in named if not a.startswith("127.")), None)
    if found is None:
        raise NoAddressError("this computer has no network address a sandbox reaches it by")
    return found


def asked_at(url: str) -> tuple[str, bool]:
    """The URL handlerd asks for `url` as agents reach it, and whether it is on this computer."""
    parsed = urlparse(url)
    if parsed.hostname != CONTAINER_HOST:
        return url, False
    address = host_address()
    netloc = f"{address}:{parsed.port}" if parsed.port else address
    return parsed._replace(netloc=netloc).geturl(), True


async def test(endpoints: Mapping[Protocol, str], key: str | None) -> ProviderReach:
    """Ask each endpoint for its models: `ok` once every one gave a list."""
    asked = urls(endpoints)
    headers: dict[str, dict[str, str]] = {}
    for protocol, endpoint in endpoints.items():
        sent = {"Authorization": f"Bearer {key}"} if key else {}
        if protocol == "anthropic":
            sent = {"anthropic-version": ANTHROPIC_VERSION} | ({"x-api-key": key} if key else {})
        headers.setdefault(models_url(protocol, endpoint), sent)
    served: dict[str, ProviderModel] = {}
    for url in asked:
        failed = await _ask(url, headers[url], served)
        if failed is not None:
            error, hint = failed
            return ProviderReach(ok=False, at=_now(), urls=asked, error=error, hint=hint)
    return ProviderReach(ok=True, at=_now(), urls=asked, models=list(served.values()))


async def _ask(
    url: str, headers: dict[str, str], served: dict[str, ProviderModel]
) -> tuple[str, str | None] | None:
    """Add what `url` serves to `served`; or (the error, the hint) when it does not answer."""
    where = urlparse(url).netloc
    try:
        target, local = asked_at(url)
    except NoAddressError as e:
        return str(e), HINT
    # a sandbox reaches this computer directly, never through a proxy handlerd may be given
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=not local) as client:
        try:
            r = await client.get(target, headers=headers)
        except httpx.TimeoutException:
            return f"{where} did not answer in {TIMEOUT:g} s", HINT if local else None
        except httpx.HTTPError as e:
            return f"nothing answered at {where} ({e})", HINT if local else None
        if r.status_code >= 400:
            return f"{where} answered {r.status_code}: {r.text[:ERROR_CHARS]}", None
        try:
            entries = [e for e in r.json()["data"] if isinstance(e, dict) and e.get("id")]
        except (ValueError, KeyError, TypeError):
            return f"{where} answered, but not with a list of models", None
        found = [_model(e) for e in entries]
        if local and len(found) == 1 and found[0].context_window is None:
            found = [found[0].model_copy(update={"context_window": await _props(client, target)})]
    for m in found:
        served.setdefault(m.id, m)
    return None


def _model(entry: dict[str, Any]) -> ProviderModel:
    meta = entry.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    sizes = [entry.get(f) for f in CONTEXT_FIELDS] + [meta.get("n_ctx")]
    context = next((s for s in sizes if isinstance(s, int) and s > 0), None)
    return ProviderModel(id=str(entry["id"]), context_window=context)


async def _props(client: httpx.AsyncClient, models: str) -> int | None:
    """llama-server's context, as it was started (`-c`): its `/props`, beside `/v1`."""
    root = models.removesuffix("/models").removesuffix("/v1")
    try:
        props = (await client.get(f"{root}/props")).json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(props, dict):
        return None
    settings = props.get("default_generation_settings")
    size = settings.get("n_ctx") if isinstance(settings, dict) else None
    return size if isinstance(size, int) and size > 0 else None


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Reaches:
    """The last answer for each set of endpoints, while handlerd runs."""

    last: dict[tuple[str, ...], ProviderReach] = field(default_factory=dict)

    def keep(self, reach: ProviderReach) -> None:
        self.last[tuple(reach.urls)] = reach

    def of(self, endpoints: Mapping[Protocol, str]) -> ProviderReach | None:
        return self.last.get(tuple(urls(endpoints)))
