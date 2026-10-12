"""Unit tests: the `llm/v1` service (I.5): its interface data, the connector (`llm.complete`)
against a stub provider speaking `openai-chat` and `anthropic`, and the router on a socket."""

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import LlmRequest, LlmResponse
from handler_control import llm, service_router, services
from handler_control.secrets import SecretStore
from handler_control.services import ServiceError
from handler_control.settings import Settings

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings"],
    "properties": {"findings": {"type": "array", "items": {"type": "string"}}},
}


class Stub:
    """A provider: answers each request with the next of `answers` (text, or an int: that HTTP
    status, or None: never in time), in the protocol it was asked in."""

    def __init__(self) -> None:
        self.answers: list[Any] = []
        self.requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append((self.path, dict(self.headers), body))
                answer = stub.answers.pop(0)
                if answer is None:
                    time.sleep(1.5)
                    return
                if isinstance(answer, int):
                    self.send_response(answer)
                    self.end_headers()
                    self.wfile.write(b'{"error": "overloaded"}')
                    return
                if self.path.endswith("/chat/completions"):
                    data = {
                        "choices": [{"message": {"role": "assistant", "content": answer}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                    }
                else:
                    data = {
                        "content": [{"type": "text", "text": answer}],
                        "usage": {"input_tokens": 7, "output_tokens": 2},
                    }
                raw = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def stub() -> Iterator[Stub]:
    s = Stub()
    yield s
    s.server.shutdown()


@pytest.fixture
def settings(tmp_path: Path, stub: Stub) -> Settings:
    providers = tmp_path / "providers"
    providers.mkdir()
    base = f"http://host.containers.internal:{stub.port}"  # as a container sees the host
    for name, endpoint in (
        ("chat", f'openai-chat = "{base}/v1"'),
        ("claude", f'anthropic = "{base}"'),
    ):
        (providers / f"{name}.toml").write_text(
            'apiVersion = "handler.provider/v1"\n'
            f'apiKey = {{ secret = "providers/{name}/apiKey" }}\n'
            f'[endpoints]\n{endpoint}\n[[models]]\nid = "m"\n'
        )  # fmt: skip
    store = SecretStore(tmp_path / "data")
    store.put("providers/chat/apiKey", "sk-chat-secret")
    store.put("providers/claude/apiKey", "sk-claude-secret")
    return Settings(
        port=0,
        config_dir=tmp_path,
        state_dir=tmp_path,
        bindings_dir=tmp_path,
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
        data_dir=tmp_path / "data",
        providers_dir=providers,
    )


def complete(settings: Settings, timeout: float = 5, **request: Any) -> llm.Completion:
    return asyncio.run(llm.complete(settings, LlmRequest.model_validate(request), timeout))


def test_the_interface_states_the_contract_models() -> None:
    interface = services.load("llm/v1")
    assert set(interface.errors) == {"refused", "limit", "unavailable"}
    tool = interface.tools["llm_complete"].definition
    assert tool["inputSchema"] == LlmRequest.model_json_schema(by_alias=True)
    assert tool["outputSchema"] == LlmResponse.model_json_schema(
        by_alias=True, mode="serialization"
    )


def test_open_objects_are_found() -> None:
    assert services.open_objects({"properties": {"a": {}}}) == ["/"]
    nested = {
        "properties": {"a": {"type": "object", "properties": {}}},
        "additionalProperties": False,
    }
    assert services.open_objects(nested) == ["/properties/a"]
    assert services.open_objects({"type": "object", "additionalProperties": True}) == []


def test_openai_chat_text(settings: Settings, stub: Stub) -> None:
    stub.answers = ["Hello."]
    done = complete(settings, model="chat/m", system="Be brief.", prompt="Hi", input="data")
    assert done.response.valid and done.response.text == "Hello." and not done.repaired
    assert done.response.usage.in_tokens == 10 and done.response.usage.out_tokens == 3
    path, headers, body = stub.requests[0]
    assert path == "/v1/chat/completions" and headers["Authorization"] == "Bearer sk-chat-secret"
    assert body["model"] == "m" and body["messages"][0] == {
        "role": "system",
        "content": "Be brief.",
    }
    assert body["messages"][1]["content"] == "Hi\n\n<input>\ndata\n</input>"


def test_anthropic_schema_repaired_once(settings: Settings, stub: Stub) -> None:
    stub.answers = ['Sure: {"findings": [1]}', 'Here:\n```json\n{"findings": ["npm"]}\n```']
    done = complete(settings, model="claude/m", prompt="List", schema=SCHEMA)
    assert done.response.valid and done.response.value == {"findings": ["npm"]} and done.repaired
    assert done.response.text is None
    assert done.response.usage.in_tokens == 14 and done.response.usage.out_tokens == 4  # both
    path, headers, body = stub.requests[0]
    assert path == "/v1/messages" and headers["x-api-key"] == "sk-claude-secret"
    assert "JSON Schema" in body["system"] and body["max_tokens"] == llm.MAX_TOKENS
    repair = stub.requests[1][2]["messages"]
    assert repair[1]["role"] == "assistant" and "could not be used" in repair[2]["content"]


def test_still_invalid_after_the_repair(settings: Settings, stub: Stub) -> None:
    stub.answers = ["no json here", '{"other": 1}']
    done = complete(settings, model="chat/m", prompt="List", schema=SCHEMA)
    assert not done.response.valid and done.response.value == {"other": 1}
    assert done.response.error and "findings" in done.response.error
    assert done.response.text == '{"other": 1}'


def test_provider_errors(settings: Settings, stub: Stub) -> None:
    stub.answers = [503]
    with pytest.raises(ServiceError) as failed:
        complete(settings, model="chat/m", prompt="x")
    assert failed.value.code == "unavailable" and "503" in failed.value.message
    stub.answers = [None]
    with pytest.raises(ServiceError) as slow:
        complete(settings, timeout=0.5, model="chat/m", prompt="x")
    assert slow.value.code == "limit"
    with pytest.raises(ServiceError, match="no provider"):
        complete(settings, model="nope/m", prompt="x")
    with pytest.raises(ValueError, match="not a JSON Schema"):
        complete(settings, model="chat/m", prompt="x", schema={"type": 3})


@pytest.mark.parametrize(
    ("answer", "value"),
    [
        ('{"a": 1}', {"a": 1}),
        ("Text then [1, 2] and more", [1, 2]),
        ('```json\n{"a": [1]}\n```\nbye', {"a": [1]}),
        ('broken { then\n```\n{"b": 2}\n```', {"b": 2}),
    ],
)
def test_json_in(answer: str, value: Any) -> None:
    assert llm.json_in(answer) == value


def test_from_host() -> None:
    assert llm.from_host("http://host.containers.internal:3000/v1") == "http://127.0.0.1:3000/v1"
    assert llm.from_host("https://api.mistral.ai/v1") == "https://api.mistral.ai/v1"


# ── the router (MCP over the socket) ────────────────────────────────────


async def session(
    settings: Settings, grant: service_router.Grant, messages: list[Any]
) -> list[Any]:
    path = Path(settings.state_dir) / "s.sock"
    server = await service_router.serve(settings, path, grant)
    try:
        reader, writer = await asyncio.open_unix_connection(str(path))
        replies = []
        for msg in messages:
            writer.write((msg if isinstance(msg, str) else json.dumps(msg)).encode() + b"\n")
            await writer.drain()
            if isinstance(msg, dict) and "id" not in msg:
                continue
            replies.append(json.loads(await reader.readline()))
        writer.close()
        return replies
    finally:
        server.close()


def call(rid: int, **arguments: Any) -> dict[str, Any]:
    params = {"name": "llm_complete", "arguments": arguments}
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": params}


def test_router_serves_llm_complete(settings: Settings, stub: Stub, tmp_path: Path) -> None:
    stub.answers = ['{"findings": []}', "x"]
    grant = service_router.Grant(
        llm=frozenset({"chat/m"}), log=tmp_path / "services.ndjson", max_calls=2
    )
    replies = asyncio.run(
        session(
            settings,
            grant,
            [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                call(3, model="chat/m", prompt="List", schema=SCHEMA),
                call(4, model="claude/m", prompt="x"),  # not granted
                call(5, model="chat/m"),  # no prompt
                call(6, model="chat/m", prompt="x", extra=1),
                call(7, model="chat/m", prompt="x"),
                call(8, model="chat/m", prompt="x"),  # past max_calls
                "not json",
                {"jsonrpc": "2.0", "id": 9, "method": "resources/list"},
            ],
        )
    )  # fmt: skip
    assert replies[0]["result"]["capabilities"] == {"tools": {}}
    assert [t["name"] for t in replies[1]["result"]["tools"]] == ["llm_complete"]
    ok = replies[2]["result"]
    assert ok["isError"] is False and ok["structuredContent"]["value"] == {"findings": []}
    assert json.loads(ok["content"][0]["text"]) == ok["structuredContent"]
    refused = json.loads(replies[3]["result"]["content"][0]["text"])
    assert replies[3]["result"]["isError"] and refused["error"] == "refused"
    assert replies[4]["error"]["code"] == -32602 and replies[5]["error"]["code"] == -32602
    assert replies[6]["result"]["structuredContent"]["text"] == "x"
    assert json.loads(replies[7]["result"]["content"][0]["text"])["error"] == "limit"
    assert replies[8]["error"]["code"] == -32700 and replies[9]["error"]["code"] == -32601
    assert (grant.calls, grant.in_tokens, grant.out_tokens) == (2, 20, 6)
    logged = [json.loads(line) for line in grant.log.read_text().splitlines()]
    assert [e.get("error") for e in logged] == [None, "refused", None, "limit"]
    assert logged[0]["interface"] == "llm/v1" and logged[0]["valid"] is True
    assert logged[0]["repaired"] is False and logged[0]["inTokens"] == 10
    assert "List" not in grant.log.read_text()  # never the payload


def test_router_without_models_lists_no_tools(settings: Settings, tmp_path: Path) -> None:
    grant = service_router.Grant(llm=frozenset(), log=tmp_path / "services.ndjson")
    listed, called = asyncio.run(
        session(settings, grant, [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, call(2)])
    )
    assert listed["result"]["tools"] == [] and called["error"]["code"] == -32602
