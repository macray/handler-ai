"""Voice (D.25): what writes down what you say to Ask, and a recording written down."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import SpeechRequest, VoiceSettings

from ..services import ServiceError
from ..voice import VoiceOffError
from .common import Context, ProblemError, dump, parse_body


def add_voice_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/voice", dependencies=authed)
    def get_voice() -> Response:
        return dump(ctx.voice.view())

    @app.put("/v1/voice", dependencies=authed)
    async def put_voice(request: Request) -> Response:
        body = parse_body(VoiceSettings, await request.body())
        try:
            return dump(ctx.voice.put(body))
        except ValueError as e:
            raise ProblemError(400, "not a speech model", str(e)) from None

    @app.post("/v1/voice/transcribe", dependencies=authed)
    async def transcribe(request: Request) -> Response:
        body = parse_body(SpeechRequest, await request.body())
        try:
            return dump(await ctx.voice.hear(body))
        except VoiceOffError as e:
            raise ProblemError(409, "voice is off", str(e)) from None
        except ServiceError as e:  # the recording too large, the provider failing or too slow
            status = 413 if e.code == "limit" else 502
            raise ProblemError(status, "nothing was written down", e.message) from None
