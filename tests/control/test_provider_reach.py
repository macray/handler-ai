"""A provider's test through a real handlerd (D.12): its server asked for its models from where a
sandbox would, against a fake OpenAI-compatible server."""

from collections.abc import Iterator

import pytest

from ..support.daemon import Daemon, start_daemon
from ..support.models_server import ModelsServer

AGENTS_HOST = "host.containers.internal"  # where agents reach this computer (A.3)
KEY = "sk-local-not-a-real-key"


@pytest.fixture(scope="module")
def daemon() -> Iterator[Daemon]:
    yield from start_daemon()


@pytest.fixture
def server() -> Iterator[ModelsServer]:
    s = ModelsServer(
        [{"id": "qwen-coder", "object": "model", "meta": {"n_ctx_train": 262144}}],
        props={"default_generation_settings": {"n_ctx": 32768}},
    )
    yield s
    s.close()


@pytest.mark.rule("provider.a-test-asks-from-where-a-sandbox-is")
def test_a_server_that_answers_fills_the_models(daemon: Daemon, server: ModelsServer) -> None:
    """llama-server's two protocols are one server, asked once at this computer's network address
    (never its loopback); its model and the context it was started with (`/props`, not the
    trained one); the provider saved with those endpoints is then ready."""
    endpoint = server.endpoint()
    endpoints = {"openai-chat": endpoint, "responses": endpoint}
    with daemon.http() as c:
        r = c.post("/v1/providers/test", json={"endpoints": endpoints})
        assert r.status_code == 200, r.text
        reach = r.json()
        assert reach["ok"] and "error" not in reach
        assert reach["urls"] == [f"http://{AGENTS_HOST}:{server.port}/v1/models"]
        [model] = reach["models"]
        assert (model["id"], model["contextWindow"]) == ("qwen-coder", 32768)
        asked = [q for q in server.requests if q["path"] == "/v1/models"]
        assert len(asked) == 1 and not asked[0]["from"].startswith("127.")
        assert "authorization" not in {h.lower() for h in asked[0]["headers"]}

        body = {"name": "llama", "endpoints": endpoints, "models": reach["models"]}
        made = c.post("/v1/providers", json=body).json()
        assert made["local"] and made["reached"]["ok"]
        c.delete("/v1/providers/llama")


@pytest.mark.rule("provider.a-test-asks-from-where-a-sandbox-is")
def test_a_server_on_the_loopback_only_is_not_reached(daemon: Daemon) -> None:
    """llama-server as started by default answers handlerd on 127.0.0.1, but no sandbox: not
    reached, with the error and what to start it with."""
    loopback = ModelsServer([{"id": "m"}], listen="127.0.0.1")
    try:
        with daemon.http() as c:
            reach = c.post(
                "/v1/providers/test", json={"endpoints": {"openai-chat": loopback.endpoint()}}
            ).json()
    finally:
        loopback.close()
    assert not reach["ok"] and reach["models"] == []
    assert reach["error"].startswith(f"nothing answered at {AGENTS_HOST}:{loopback.port}")
    assert "--host 0.0.0.0 --jinja" in reach["hint"] and "OLLAMA_HOST=0.0.0.0" in reach["hint"]
    assert loopback.requests == []


@pytest.mark.rule("provider.a-test-asks-from-where-a-sandbox-is")
def test_a_saved_provider_is_tested_with_its_key(daemon: Daemon, server: ModelsServer) -> None:
    """Its key goes to its own endpoints' hosts only; an answer that is not a model list is not
    ready; the list shows the last test."""
    endpoint = server.endpoint()
    with daemon.http() as c:
        body = {"name": "keyed", "endpoints": {"openai-chat": endpoint}, "models": [{"id": "m"}]}
        made = c.post("/v1/providers", json=body | {"key": KEY}).json()
        assert made["local"] and made.get("reached") is None  # never tested: not shown ready

        reach = c.post("/v1/providers/test", json={"provider": "keyed"}).json()
        assert reach["ok"] and KEY not in str(reach)
        asked = [q for q in server.requests if q["path"] == "/v1/models"]
        assert asked[-1]["headers"]["Authorization"] == f"Bearer {KEY}"
        listed = next(p for p in c.get("/v1/providers").json() if p["name"] == "keyed")
        assert listed["reached"]["ok"] and listed["reached"]["models"][0]["id"] == "qwen-coder"

        # another host typed in the form: the saved key is not sent there
        elsewhere = {"openai-chat": f"http://localhost:{server.port}/v1"}
        c.post("/v1/providers/test", json={"provider": "keyed", "endpoints": elsewhere})
        asked = [q for q in server.requests if q["path"] == "/v1/models"]
        assert len(asked) == 2 and "Authorization" not in asked[-1]["headers"]

        assert c.post("/v1/providers/test", json={"provider": "nope"}).status_code == 404
        assert c.post("/v1/providers/test", json={}).status_code == 422
        c.delete("/v1/providers/keyed")

    refusing = ModelsServer([], status=401)
    try:
        with daemon.http() as c:
            reach = c.post(
                "/v1/providers/test", json={"endpoints": {"openai-chat": refusing.endpoint()}}
            ).json()
    finally:
        refusing.close()
    assert not reach["ok"] and f":{refusing.port} answered 401" in reach["error"]
    assert reach.get("hint") is None  # it answered: where it listens is right


def test_local_templates_are_neutral(daemon: Daemon) -> None:
    """A server on this computer's template: its own port, no model (picked from what it serves),
    so no context nor reply typed for it."""
    with daemon.http() as c:
        templates = {t["name"]: t for t in c.get("/v1/provider-templates").json()}
    llamacpp, ollama = templates["llamacpp"], templates["ollama"]
    assert llamacpp["endpoints"]["openai-chat"] == f"http://{AGENTS_HOST}:8080/v1"
    assert llamacpp["models"] == [] and ollama["models"] == []
    assert ollama["endpoints"]["openai-chat"].endswith(":11434/v1")
