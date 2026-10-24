"""The `transcribe/v1` service's connector, built into handlerd (I.11): a recording written down by
a provider's speech model (`speech = true`) at its `transcriptions` endpoint, the OpenAI-style
`POST <endpoint>/audio/transcriptions` that vendors' APIs (Mistral, OpenAI, Groq) and servers on
this machine (vLLM, whisper.cpp's server, speaches) speak. Its key comes from the secret store; the
recording is sent and never kept.

    transcribe   TranscribeRequest → TranscribeResponse
    models       the speech models of every provider, for Settings → Voice (D.25)
    check        a "provider/model" that is a speech model

Errors are those of `transcribe/v1` (services.ServiceError): `unavailable` when the provider fails
or cannot be reached (or in time), `limit` past the recording's size.
"""

import base64
import binascii
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from handler_contracts import MAX_AUDIO, Provider, TranscribeRequest, TranscribeResponse

from . import llm, providers, secrets
from .services import ServiceError
from .settings import Settings

TIMEOUT = 60.0
MIME = {"webm": "audio/webm", "ogg": "audio/ogg", "mp4": "audio/mp4", "wav": "audio/wav"}
MIME |= {"mp3": "audio/mpeg"}
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "host.containers.internal")


@dataclass(frozen=True)
class SpeechModel:
    model: str  # "provider/model"
    name: str
    provider: str
    local: bool  # served on this machine: the recording does not leave it


def local(endpoint: str) -> bool:
    return urlparse(endpoint).hostname in LOCAL_HOSTS


def models(settings: Settings) -> list[SpeechModel]:
    found = []
    for loaded in providers.load_all(settings.providers_dir):
        p = loaded.provider
        if p is None or "transcriptions" not in p.endpoints:
            continue
        for m in p.models:
            if m.speech:
                at = p.endpoints["transcriptions"]
                found.append(
                    SpeechModel(f"{loaded.name}/{m.id}", m.name or m.id, loaded.name, local(at))
                )
    return found


def _speech(settings: Settings, model: str) -> tuple[Provider, str]:
    provider_name, _, model_id = model.partition("/")
    loaded = providers.get(settings.providers_dir, provider_name)
    if loaded.provider is None:
        raise ServiceError("unavailable", f"provider {provider_name}: {loaded.error}")
    if loaded.provider.speech_model(model_id) is None:
        raise ServiceError("refused", f"{model}: not a speech model")
    return loaded.provider, model_id


def check(settings: Settings, model: str) -> None:
    """ValueError unless `model` is a provider's speech model."""
    try:
        _speech(settings, model)
    except ServiceError as e:
        raise ValueError(e.message) from None


async def transcribe(settings: Settings, request: TranscribeRequest) -> TranscribeResponse:
    provider, model_id = _speech(settings, request.model)
    try:
        audio = base64.b64decode(request.audio, validate=True)
    except binascii.Error:
        raise ServiceError("refused", "audio: not base64") from None
    if len(audio) > MAX_AUDIO:
        raise ServiceError("limit", f"the recording is larger than {MAX_AUDIO // 1024} KiB")
    store = secrets.SecretStore(settings.data_dir)
    try:
        key = secrets.resolve(provider.api_key, store) if provider.api_key else None
    except secrets.SecretError as e:
        raise ServiceError("unavailable", f"{request.model}: {e}") from None
    url = llm.from_host(provider.endpoints["transcriptions"]).rstrip("/") + "/audio/transcriptions"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    data = {"model": model_id, "response_format": "json"}
    if request.language:
        data["language"] = request.language
    files = {"file": (f"speech.{request.format}", audio, MIME[request.format])}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(url, data=data, files=files, headers=headers)
    except httpx.TimeoutException:
        raise ServiceError("unavailable", "the provider did not answer in time") from None
    except httpx.HTTPError as e:
        raise ServiceError("unavailable", f"{urlparse(url).netloc}: {e}") from None
    if r.status_code >= 400:
        told = r.text[: llm.ERROR_CHARS]
        raise ServiceError("unavailable", f"the provider answered {r.status_code}: {told}")
    try:
        text = str(r.json()["text"])
    except (ValueError, KeyError, TypeError):
        raise ServiceError("unavailable", "the provider's answer has no text") from None
    return TranscribeResponse(text=text.strip(), ms=int((time.monotonic() - started) * 1000))
