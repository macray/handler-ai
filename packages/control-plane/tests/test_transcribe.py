"""The `transcribe/v1` connector (transcribe.py, I.11): a provider's speech model writes down a
recording at its `transcriptions` endpoint."""

import asyncio
import base64
from pathlib import Path

import pytest
from provider_stub import Stub

from handler_contracts import (
    MAX_AUDIO,
    SpeechRequest,
    TranscribeRequest,
    TranscribeResponse,
    VoiceSettings,
)
from handler_control import llm, services, transcribe
from handler_control.secrets import SecretStore
from handler_control.services import ServiceError
from handler_control.settings import Settings
from handler_control.voice import VoiceOffError, VoiceStore

AUDIO = base64.b64encode(b"OggS fake opus").decode()


@pytest.fixture
def settings(stub_settings: Settings, stub: Stub) -> Settings:
    """Besides the stub's chat providers, `ears`: a server on this machine (no key) with a chat
    model and a speech one, and `cloud`: a speech model behind a key."""
    base = f"http://host.containers.internal:{stub.port}/v1"
    (stub_settings.providers_dir / "ears.toml").write_text(
        'apiVersion = "handler.provider/v1"\n'
        f'[endpoints]\nopenai-chat = "{base}"\ntranscriptions = "{base}"\n'
        '[[models]]\nid = "chat"\n[[models]]\nid = "whisper"\nname = "Whisper"\nspeech = true\n'
    )  # fmt: skip
    (stub_settings.providers_dir / "cloud.toml").write_text(
        'apiVersion = "handler.provider/v1"\napiKey = { secret = "providers/cloud/apiKey" }\n'
        '[endpoints]\ntranscriptions = "https://api.example.com/v1"\n'
        '[[models]]\nid = "voxtral"\nspeech = true\n'
    )  # fmt: skip
    SecretStore(stub_settings.data_dir).put("providers/cloud/apiKey", "sk-cloud")
    return stub_settings


def heard(settings: Settings, model: str, audio: str = AUDIO) -> TranscribeResponse:
    request = TranscribeRequest(model=model, audio=audio, format="ogg", language="fr")
    return asyncio.run(transcribe.transcribe(settings, request))


def test_the_interface_states_the_contract_models() -> None:
    interface = services.load("transcribe/v1")
    assert set(interface.errors) == {"refused", "limit", "unavailable"}
    tool = interface.tools["transcribe_audio"].definition
    assert tool["inputSchema"] == TranscribeRequest.model_json_schema(by_alias=True)
    assert tool["outputSchema"] == TranscribeResponse.model_json_schema(
        by_alias=True, mode="serialization"
    )


def test_speech_models_are_listed_with_where_they_run(settings: Settings) -> None:
    found = {m.model: m for m in transcribe.models(settings)}
    assert set(found) == {"ears/whisper", "cloud/voxtral"}
    assert found["ears/whisper"].local and found["ears/whisper"].name == "Whisper"
    assert not found["cloud/voxtral"].local


def test_a_recording_is_written_down_at_the_transcriptions_endpoint(
    settings: Settings, stub: Stub
) -> None:
    stub.answers = ["  Tomorrow I call the bank at ten "]
    assert heard(settings, "ears/whisper").text == "Tomorrow I call the bank at ten"
    path, headers, body = stub.requests[-1]
    assert path == "/v1/audio/transcriptions" and "authorization" not in {
        k.lower() for k in headers
    }
    sent = body["multipart"]
    assert 'name="model"' in sent and "whisper" in sent and "OggS fake opus" in sent
    assert 'name="language"' in sent and 'filename="speech.ogg"' in sent


def test_only_a_speech_model_writes_down(settings: Settings) -> None:
    with pytest.raises(ServiceError) as refused:
        heard(settings, "ears/chat")
    assert refused.value.code == "refused"
    with pytest.raises(ValueError):
        transcribe.check(settings, "chat/m")


def test_a_failing_provider_and_a_large_recording(settings: Settings, stub: Stub) -> None:
    stub.answers = [503]
    with pytest.raises(ServiceError) as failed:
        heard(settings, "ears/whisper")
    assert failed.value.code == "unavailable"
    large = base64.b64encode(b"x" * (MAX_AUDIO + 1)).decode()
    with pytest.raises(ServiceError) as limit:
        heard(settings, "ears/whisper", large)
    assert limit.value.code == "limit"


def test_a_speech_model_is_never_a_chat_model(settings: Settings) -> None:
    with pytest.raises(ValueError):
        llm.check(settings.providers_dir, "cloud", None)  # no chat endpoint
    with pytest.raises(ValueError):
        llm.check(settings.providers_dir, "ears", "whisper")
    assert llm.target_of(settings, "ears", None).model == "chat"


def test_voice_is_off_until_a_speech_model_is_chosen(settings: Settings, stub: Stub) -> None:
    store = VoiceStore(settings)
    assert store.view().model is None and not store.listens()
    with pytest.raises(VoiceOffError):
        asyncio.run(store.hear(SpeechRequest(audio=AUDIO, format="webm")))
    with pytest.raises(ValueError):
        store.put(VoiceSettings(model="chat/m"))
    chosen = store.put(VoiceSettings(model="ears/whisper", read_aloud_typed=True))
    assert chosen.model == "ears/whisper" and chosen.read_aloud_spoken and store.listens()
    stub.answers = ["hello"]
    assert asyncio.run(store.hear(SpeechRequest(audio=AUDIO, format="webm"))).text == "hello"
    (settings.providers_dir / "ears.toml").unlink()
    assert VoiceStore(settings).view().problem and not store.listens()
    assert Path(settings.state_dir / "voice.json").is_file()
