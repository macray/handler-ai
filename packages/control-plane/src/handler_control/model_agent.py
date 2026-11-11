"""An agent on the model alone (D.18): no program, no sandbox. Its sessions talk ACP to it as to
an agent program in its sandbox, so a session, a run and its result work the same; one turn is
one model call (llm.py) with the conversation so far, the agent's knowledge notes put into the
system prompt.

Text in, text out, whatever it is told (D.18, hard limits):

- no tools: llm.py offers none to the model and refuses an answer calling one (the turn fails);
- no client requests: it never sends `fs/*`, `terminal/*` or `session/request_permission`, and
  has no code that could; MCP servers given to `session/new` or `session/load` are refused;
- it reads its knowledge notes and its conversation (`messages.json` in the session's agent
  folder), nothing else; its only network is the provider's endpoint, called by llm.py.

    ModelAgent(...)   one session's agent; `send` takes the session's messages, `receive` gives
                      its own, `wait` and `stop` as for a sandbox's process
"""

import asyncio
import contextlib
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from handler_contracts import LlmUsage

from . import knowledge, llm
from .services import ServiceError
from .settings import Settings

Message = dict[str, Any]

PROTOCOL_VERSION = 1
CALL_TIMEOUT = 120.0  # seconds, a model call's (as a script's, I.5)
KNOWLEDGE_MAX = 192 * 1024  # bytes of notes put into a call (llm/v1 takes 256 KiB in all)
HISTORY_FILE = "messages.json"
INVALID_PARAMS, METHOD_NOT_FOUND, INTERNAL_ERROR = -32602, -32601, -32603
NO_TOOLS = (
    "You have no tools and no files: answer with text only, from this conversation and the "
    "notes below."
)


class KnowledgeTooLargeError(ValueError):
    """An agent's notes are more than a call takes."""


def knowledge_prompt(notes: list[knowledge.Note]) -> str:
    """The system prompt: the notes it is given, each under its path; KnowledgeTooLargeError
    past KNOWLEDGE_MAX."""
    size = sum(len(n.text.encode()) for n in notes)
    if size > KNOWLEDGE_MAX:
        raise KnowledgeTooLargeError(
            f"its notes are {size // 1024} KiB: the model alone takes {KNOWLEDGE_MAX // 1024} "
            "KiB at most in a call"
        )
    given = "".join(f'\n\n<note path="{n.path}">\n{n.text}\n</note>' for n in notes)
    return NO_TOOLS + (given or "\n\n(No notes.)")


def prompt_text(blocks: list[Any]) -> str:
    """A prompt's text: its text blocks and embedded text resources; ValueError for anything
    else (an image, a link to a file it cannot read)."""
    parts = []
    for block in blocks:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind == "text":
            parts.append(block["text"])
        elif kind == "resource" and "text" in (block.get("resource") or {}):
            resource = block["resource"]
            parts.append(f'<file uri="{resource.get("uri", "")}">\n{resource["text"]}\n</file>')
        else:
            raise ValueError(f"the model alone reads text only (not {kind})")
    return "\n\n".join(parts)


class ModelAgent:
    def __init__(
        self,
        settings: Settings,
        *,
        provider: str,
        model: str | None,
        knowledge_folders: list[str],
        folder: Path,
        on_call: Callable[[LlmUsage, int], None],
    ) -> None:
        self.settings, self.provider, self.model = settings, provider, model
        self.knowledge_folders = knowledge_folders
        self.history_file = folder / HISTORY_FILE
        self.on_call = on_call  # each model call's usage and time (ms), for the session's log
        self.messages: list[dict[str, str]] = []
        self.session_id: str | None = None
        self.outbox: asyncio.Queue[Message | None] = asyncio.Queue()
        self.turn: asyncio.Task[None] | None = None
        self.stopped = asyncio.Event()

    # ── the link a session talks through (sessions.AgentLink) ──────────

    async def send(self, msg: Message) -> None:
        """A message from the session: a request, a notification, or an answer (it asks none:
        dropped)."""
        method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if method is None:
            return
        if method == "session/cancel":
            if self.turn is not None:
                self.turn.cancel()
            return
        if rid is None:
            return  # another notification: nothing to do
        try:
            if method == "initialize":
                self.answer(rid, self.initialized())
            elif method in ("session/new", "session/load"):
                if params.get("mcpServers"):
                    raise ValueError("the model alone takes no MCP servers: it has no tools")
                self.answer(rid, self.opened(method, params))
            elif method == "session/prompt":
                if self.turn is not None:
                    raise ValueError("a turn is in progress")
                text = prompt_text(params.get("prompt") or [])
                self.turn = asyncio.create_task(self.take_turn(rid, text))
            else:
                self.fail(rid, METHOD_NOT_FOUND, f"{method}: not offered by the model alone")
        except ValueError as e:
            self.fail(rid, INVALID_PARAMS, str(e))

    async def receive(self) -> Message | None:
        """Its next message to the session; None once stopped."""
        return await self.outbox.get()

    async def wait(self) -> int:
        await self.stopped.wait()
        return 0

    async def stop(self) -> None:
        if self.turn is not None:
            self.turn.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.turn
        self.outbox.put_nowait(None)
        self.stopped.set()

    # ── ACP ─────────────────────────────────────────────────────────────

    def initialized(self) -> Message:
        prompts = {"image": False, "audio": False, "embeddedContext": True}
        capabilities = {"loadSession": True, "promptCapabilities": prompts}
        return {"protocolVersion": PROTOCOL_VERSION, "agentCapabilities": capabilities}

    def opened(self, method: str, params: Message) -> Message:
        if method == "session/new":
            self.session_id, self.messages = uuid.uuid4().hex, []
            return {"sessionId": self.session_id}
        self.session_id = params.get("sessionId")
        self.messages = (
            json.loads(self.history_file.read_text()) if self.history_file.exists() else []
        )
        for m in self.messages:
            kind = "user_message_chunk" if m["role"] == "user" else "agent_message_chunk"
            self.update(kind, m["content"])
        return {}

    async def take_turn(self, rid: Any, text: str) -> None:
        asked = [*self.messages, {"role": "user", "content": text}]
        try:
            root, _ = knowledge.root(self.settings)
            system = knowledge_prompt(knowledge.notes(root, self.knowledge_folders))
            reply = await llm.converse(
                self.settings, self.provider, self.model, system, asked, timeout=CALL_TIMEOUT
            )
        except asyncio.CancelledError:
            self.answer(rid, {"stopReason": "cancelled"})
            return
        except ServiceError as e:
            self.fail(rid, INTERNAL_ERROR, e.message)  # the person's words, not the code
            return
        except (knowledge.KnowledgeError, KnowledgeTooLargeError) as e:
            self.fail(rid, INTERNAL_ERROR, str(e))
            return
        finally:
            self.turn = None
        self.on_call(reply.usage, reply.ms)
        self.messages = [*asked, {"role": "assistant", "content": reply.text}]
        self.history_file.write_text(json.dumps(self.messages))
        self.update("agent_message_chunk", reply.text)
        self.answer(rid, {"stopReason": "end_turn"})

    def update(self, kind: str, text: str) -> None:
        content = {"type": "text", "text": text}
        update = {"sessionUpdate": kind, "content": content}
        params = {"sessionId": self.session_id, "update": update}
        self.outbox.put_nowait({"jsonrpc": "2.0", "method": "session/update", "params": params})

    def answer(self, rid: Any, result: Message) -> None:
        self.outbox.put_nowait({"jsonrpc": "2.0", "id": rid, "result": result})

    def fail(self, rid: Any, code: int, message: str) -> None:
        error = {"code": code, "message": message}
        self.outbox.put_nowait({"jsonrpc": "2.0", "id": rid, "error": error})
