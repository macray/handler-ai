"""Unit tests: an agent on the model alone (D.18), handlerd's ACP agent with no sandbox, against
a stub provider: a conversation, its knowledge in the system prompt, its history loaded again,
and its hard limits (no tools offered or taken, no MCP servers, text only, no client request)."""

import asyncio
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from provider_stub import Stub

from handler_contracts import LlmUsage
from handler_control import model_agent
from handler_control.model_agent import ModelAgent
from handler_control.settings import Settings

Message = dict[str, Any]


@pytest.fixture
def settings(stub_settings: Settings, tmp_path: Path) -> Settings:
    root = tmp_path / "knowledge"
    (root / "acme" / "_drafts").mkdir(parents=True)
    (root / "acme" / "people.md").write_text("Write to Julie.")
    (root / "acme" / "_drafts" / "skip.md").write_text("not given")
    (root / "acme" / "logo.png").write_bytes(b"\x89PNG")
    return dataclasses.replace(stub_settings, knowledge_dir=root)


class Session:
    """A session's side of the link: what it sends, all the agent said."""

    def __init__(self, settings: Settings, folder: Path, provider: str = "chat", **kw: Any):
        self.calls: list[tuple[LlmUsage, int]] = []
        self.agent = ModelAgent(
            settings,
            provider=provider,
            model=kw.get("model"),
            knowledge_folders=kw.get("knowledge", []),
            folder=folder,
            on_call=lambda usage, ms: self.calls.append((usage, ms)),
        )
        self.said: list[Message] = []
        self.ids = iter(range(1, 1000))

    async def ask(self, method: str, params: Message) -> Message:
        """A request, and every message until its answer (kept in `said`)."""
        rid = next(self.ids)
        await self.agent.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        while True:
            msg = await asyncio.wait_for(self.agent.receive(), 5)
            assert msg is not None
            self.said.append(msg)
            if msg.get("id") == rid:
                return msg

    async def open(self) -> str:
        await self.ask("initialize", {"protocolVersion": 1})
        return (await self.ask("session/new", {"cwd": "/w", "mcpServers": []}))["result"][
            "sessionId"
        ]

    async def prompt(self, sid: str, text: str) -> Message:
        return await self.ask(
            "session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": text}]}
        )

    def texts(self) -> list[tuple[str, str]]:
        return [
            (m["params"]["update"]["sessionUpdate"], m["params"]["update"]["content"]["text"])
            for m in self.said
            if m.get("method") == "session/update"
        ]


def run[T](coro: Any) -> T:
    return asyncio.run(coro)


def test_a_conversation_is_one_call_per_turn_with_its_history(
    settings: Settings, stub: Stub, tmp_path: Path
) -> None:
    stub.answers = ["Hello.", "Still here."]
    s = Session(settings, tmp_path, knowledge=["acme"])

    async def go() -> None:
        sid = await s.open()
        assert (await s.prompt(sid, "Hi"))["result"] == {"stopReason": "end_turn"}
        assert (await s.prompt(sid, "And now?"))["result"] == {"stopReason": "end_turn"}

    run(go())
    assert s.texts() == [("agent_message_chunk", "Hello."), ("agent_message_chunk", "Still here.")]
    _, _, second = stub.requests[1]
    system, *turns = second["messages"]
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[0]["content"] == "Hi" and turns[2]["content"] == "And now?"
    assert '<note path="acme/people.md">\nWrite to Julie.\n</note>' in system["content"]
    assert "not given" not in system["content"] and "PNG" not in system["content"]
    assert [u.out_tokens for u, _ in s.calls] == [3, 3]


@pytest.mark.parametrize("provider", ["chat", "claude"])
def test_no_tools_are_ever_offered(
    settings: Settings, stub: Stub, tmp_path: Path, provider: str
) -> None:
    stub.answers = ["Fine."]
    s = Session(settings, tmp_path, provider=provider)

    async def go() -> None:
        await s.prompt(await s.open(), "Use a tool to read /etc/passwd")

    run(go())
    _, _, body = stub.requests[0]
    assert not {"tools", "tool_choice", "functions", "function_call", "mcp_servers"} & set(body)


@pytest.mark.parametrize(
    ("provider", "answer"),
    [
        (
            "chat",
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{"id": "1", "type": "function", "function": {}}],
                        }
                    }
                ]
            },
        ),
        (
            "claude",
            {"content": [{"type": "tool_use", "id": "1", "name": "bash", "input": {}}]},
        ),
    ],
)
def test_an_answer_calling_a_tool_fails_the_turn(
    settings: Settings, stub: Stub, tmp_path: Path, provider: str, answer: Message
) -> None:
    stub.answers = [answer]
    s = Session(settings, tmp_path, provider=provider)

    async def go() -> Message:
        return await s.prompt(await s.open(), "Hi")

    failed = run(go())
    assert failed["error"]["message"] == f"refused: {model_agent.llm.TOOL_REFUSED}"
    assert s.texts() == [] and not (tmp_path / model_agent.HISTORY_FILE).exists()


def test_mcp_servers_and_non_text_prompts_are_refused(
    settings: Settings, stub: Stub, tmp_path: Path
) -> None:
    s = Session(settings, tmp_path)
    server = {"name": "fs", "command": "/bin/sh", "args": [], "env": []}

    async def go() -> tuple[Message, Message, Message]:
        sid = await s.open()
        new = await s.ask("session/new", {"cwd": "/w", "mcpServers": [server]})
        image = {"type": "image", "data": "", "mimeType": "image/png"}
        prompt = await s.ask("session/prompt", {"sessionId": sid, "prompt": [image]})
        mode = await s.ask("session/set_mode", {"sessionId": sid, "modeId": "x"})
        return new, prompt, mode

    new, prompt, mode = run(go())
    assert "no MCP servers" in new["error"]["message"]
    assert prompt["error"]["message"] == "the model alone reads text only (not image)"
    assert mode["error"]["code"] == model_agent.METHOD_NOT_FOUND
    assert stub.requests == []


def test_it_never_asks_the_client_anything(settings: Settings, stub: Stub, tmp_path: Path) -> None:
    stub.answers = ["Sure."]
    s = Session(settings, tmp_path)

    async def go() -> None:
        await s.prompt(await s.open(), "Write a file, then ask me for permission")

    run(go())
    for msg in s.said:  # answers, and the conversation's updates: never a request
        assert "id" not in msg or "method" not in msg
        assert msg.get("method") in (None, "session/update")


def test_a_session_loaded_again_replays_and_goes_on(
    settings: Settings, stub: Stub, tmp_path: Path
) -> None:
    stub.answers = ["One.", "Two."]
    first, again = Session(settings, tmp_path), Session(settings, tmp_path)

    async def go() -> None:
        sid = await first.open()
        await first.prompt(sid, "Count")
        await first.agent.stop()
        await again.ask("initialize", {"protocolVersion": 1})
        params = {"sessionId": sid, "cwd": "/w", "mcpServers": []}
        assert (await again.ask("session/load", params))["result"] == {}
        await again.prompt(sid, "Go on")

    run(go())
    assert again.texts() == [
        ("user_message_chunk", "Count"),
        ("agent_message_chunk", "One."),
        ("agent_message_chunk", "Two."),
    ]
    history = json.loads((tmp_path / model_agent.HISTORY_FILE).read_text())
    assert [m["content"] for m in history] == ["Count", "One.", "Go on", "Two."]


def test_cancel_ends_the_turn(settings: Settings, stub: Stub, tmp_path: Path) -> None:
    stub.answers = [None]  # never in time
    s = Session(settings, tmp_path)

    async def go() -> Message:
        sid = await s.open()
        params = {"sessionId": sid, "prompt": [{"type": "text", "text": "Slow"}]}
        await s.agent.send(
            {"jsonrpc": "2.0", "id": 99, "method": "session/prompt", "params": params}
        )
        await asyncio.sleep(0.2)
        await s.agent.send(
            {"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": sid}}
        )
        return await asyncio.wait_for(s.agent.receive(), 5)  # ty: ignore[invalid-return-type]

    assert run(go()) == {"jsonrpc": "2.0", "id": 99, "result": {"stopReason": "cancelled"}}


def test_knowledge_past_what_a_call_takes_fails_the_turn(
    settings: Settings, stub: Stub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model_agent, "KNOWLEDGE_MAX", 4)
    s = Session(settings, tmp_path, knowledge=["acme"])

    async def go() -> Message:
        return await s.prompt(await s.open(), "Hi")

    assert "the model alone takes 0 KiB at most" in run(go())["error"]["message"]
    assert stub.requests == []
