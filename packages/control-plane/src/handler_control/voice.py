"""Voice (D.25): speaking to Ask. What writes down what you say, one of the providers' speech
models (the `transcribe/v1` service, transcribe.py), and when answers are read aloud (by the
device itself: nothing is sent for that). Off until a model is chosen.

    <state>/voice.json   VoiceSettings

A recording is written down and forgotten: never stored, never logged.
"""

import json
from pathlib import Path

from pydantic import ValidationError

from handler_contracts import (
    SpeechModelInfo,
    SpeechRequest,
    TranscribeRequest,
    Transcription,
    Voice,
    VoiceSettings,
)

from . import transcribe
from .files import write_private
from .settings import Settings

FILE = "voice.json"


class VoiceOffError(Exception):
    """No speech model is chosen: nothing writes down what is said."""


class VoiceStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def file(self) -> Path:
        return self.settings.state_dir / FILE

    def get(self) -> VoiceSettings:
        try:
            return VoiceSettings.model_validate_json(self.file.read_text())
        except (OSError, ValidationError):  # none yet, or unreadable: off, as before any choice
            return VoiceSettings()

    def view(self) -> Voice:
        chosen = self.get()
        problem = None
        if chosen.model is not None:
            try:
                transcribe.check(self.settings, chosen.model)
            except ValueError as e:
                problem = str(e)
        models = [
            SpeechModelInfo(model=m.model, name=m.name, provider=m.provider, local=m.local)
            for m in transcribe.models(self.settings)
        ]
        return Voice(**chosen.model_dump(), models=models, problem=problem)

    def put(self, chosen: VoiceSettings) -> Voice:
        """ValueError when the model is not a provider's speech model."""
        if chosen.model is not None:
            transcribe.check(self.settings, chosen.model)
        write_private(self.file, json.dumps(chosen.model_dump(by_alias=True), indent=2))
        return self.view()

    def listens(self) -> bool:
        chosen = self.view()
        return chosen.model is not None and chosen.problem is None

    async def hear(self, speech: SpeechRequest) -> Transcription:
        """VoiceOffError when no model is chosen; services.ServiceError when the call fails."""
        model = self.get().model
        if model is None:
            raise VoiceOffError("no speech model is chosen (Settings → Voice)")
        request = TranscribeRequest(
            model=model, audio=speech.audio, format=speech.format, language=speech.language
        )
        heard = await transcribe.transcribe(self.settings, request)
        return Transcription(text=heard.text)
