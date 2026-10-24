"""D.25 conformance, Voice: a speech model of a provider (a stub writing down anything as one
sentence) chosen in the settings; a recording written down over HTTP and from the owner's phone
(D.7), never from a family member's; off, nothing listens."""

import base64
from collections.abc import Iterator

import pytest

from ..support.daemon import Daemon, start_daemon
from ..support.remote import Device, DeviceError, Gateway, start_gateway
from ..support.stub_llm import StubLlm
from .test_remote import pair, wait_light

SAID = "Tomorrow I call the bank at ten"
RECORDING = {"audio": base64.b64encode(b"OggS opus").decode(), "format": "webm"}


@pytest.fixture(scope="module")
def stub() -> Iterator[StubLlm]:
    s = StubLlm("Hello.", heard=SAID)
    yield s
    s.close()


@pytest.fixture(scope="module")
def gateway() -> Iterator[Gateway]:
    yield from start_gateway()


@pytest.fixture(scope="module")
def daemon(stub: StubLlm, gateway: Gateway) -> Iterator[Daemon]:
    env = {"HANDLER_TEST_STUB_KEY": "sk-stub"}
    for d in start_daemon(extra_env=env, extra_providers={"stub": stub.provider()}):
        with d.http() as c:
            body = {"gatewayUrl": gateway.url, "hostToken": gateway.host_token}
            assert c.put("/v1/remote/gateway", json=body).status_code == 200
        yield d


def test_voice_is_off_until_a_speech_model_is_chosen(daemon: Daemon, stub: StubLlm) -> None:
    with daemon.http() as c:
        voice = c.get("/v1/voice").json()
        assert "model" not in voice and voice["readAloudSpoken"] and not voice["readAloudTyped"]
        assert [m["model"] for m in voice["models"]] == ["stub/ears"]  # not its chat model
        assert voice["models"][0]["local"]
        assert c.post("/v1/voice/transcribe", json=RECORDING).status_code == 409
        assert c.put("/v1/voice", json={"model": "stub/m"}).status_code == 400  # a chat model
        chosen = c.put("/v1/voice", json={"model": "stub/ears", "readAloudTyped": True}).json()
        assert chosen["model"] == "stub/ears" and chosen["readAloudTyped"]
        r = c.post("/v1/voice/transcribe", json=RECORDING)
        assert r.status_code == 200, r.text
        assert r.json() == {"text": SAID}
        assert stub.requests[-1]["path"] == "/v1/audio/transcriptions"
        assert stub.requests[-1]["headers"]["Authorization"] == "Bearer sk-stub"
        assert (
            c.post("/v1/voice/transcribe", json={"audio": "", "format": "webm"}).status_code == 422
        )


def test_the_owner_s_phone_speaks(daemon: Daemon) -> None:
    with daemon.http() as c:
        assert c.put("/v1/voice", json={"model": "stub/ears"}).is_success
        made = c.post(
            "/v1/agents", json={"model": {"account": "fake"}, "name": "Claude", "chat": True}
        )
        assert made.status_code == 201, made.text  # someone to talk to: the host polls
    wait_light(daemon, "ok")
    owner = pair(daemon, "phone")
    options = owner.request(None, "_handler/remote/ask_options")
    assert options["listens"] and options["readAloudSpoken"] and not options["readAloudTyped"]
    assert owner.request(None, "_handler/remote/transcribe", RECORDING) == {"text": SAID}
    with daemon.http() as c:
        r = c.post("/v1/remote/devices", json={"name": "kid", "person": "kid", "scope": "apps"})
    kid = Device(r.json()["pairingUrl"])
    with pytest.raises(DeviceError):
        kid.request(None, "_handler/remote/transcribe", RECORDING)
