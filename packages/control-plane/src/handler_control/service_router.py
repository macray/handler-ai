"""The service router (services design §5, I.5): handlerd's side of a services socket
mounted in a sandbox. It speaks MCP (JSON-RPC 2.0, one message per line) and serves the tools of the
interfaces its caller was granted, as the interface states them (S1); it validates each call's
input and output against the tool's schemas (S2), enforces the caller's selection and limits,
logs each call (never its payload), and dispatches to the built-in connector.

Only `llm/v1` exists: its connector is `llm.complete`, its selection the models a caller may
call. Its callers are automation runs; agents and apps reach the same router later.

    Grant    what one caller may use (models, limits) and what it used (calls, tokens)
    serve    a unix socket for one caller
"""

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from handler_contracts import MAX_LLM_INPUT, MAX_LLM_SCHEMA, LlmRequest

from . import __version__, llm, services
from .services import ServiceError
from .settings import Settings

LLM = "llm/v1"
PROTOCOL_VERSION = "2025-06-18"  # MCP's, answered when the client names none
MAX_MESSAGE = 2 * 1024 * 1024  # one line: the input and the schema, JSON-escaped
INVALID_PARAMS, METHOD_NOT_FOUND, PARSE_ERROR = -32602, -32601, -32700

Message = dict[str, Any]


@dataclass
class Grant:
    """One caller's: the models it may call and its limits (I.5), what it used so far."""

    llm: frozenset[str]
    log: Path  # services.ndjson: one line per call
    # llm/v1's [limits]: a call's time, the calls of a run
    timeout: float = field(default_factory=lambda: services.load(LLM).limits["timeoutSeconds"])
    max_calls: int = field(default_factory=lambda: services.load(LLM).limits["callsPerRun"])
    calls: int = 0
    in_tokens: int = 0
    out_tokens: int = 0
    busy: bool = False  # one call at a time


def tool_result(value: Message, error: bool = False) -> Message:
    result: Message = {"content": [{"type": "text", "text": json.dumps(value)}], "isError": error}
    return result if error else result | {"structuredContent": value}


class InvalidCallError(ValueError):
    """The call is not one the tool accepts (JSON-RPC invalid params)."""


async def call_llm(settings: Settings, grant: Grant, arguments: Any) -> Message:
    interface = services.load(LLM)
    tool = interface.tools["llm_complete"]
    if found := sorted(tool.input.iter_errors(arguments), key=lambda e: list(e.path)):
        raise InvalidCallError("; ".join(e.message for e in found[:3]))
    request = LlmRequest.model_validate(arguments)
    size = sum(len((t or "").encode()) for t in (request.system, request.prompt, request.input))
    if size > MAX_LLM_INPUT:
        raise InvalidCallError(f"system, prompt and input: more than {MAX_LLM_INPUT // 1024} KiB")
    if request.schema_ is not None and len(json.dumps(request.schema_)) > MAX_LLM_SCHEMA:
        raise InvalidCallError(f"schema: more than {MAX_LLM_SCHEMA // 1024} KiB")
    entry: Message = {"interface": LLM, "model": request.model}
    try:
        if request.model not in grant.llm:
            raise ServiceError("refused", f"{request.model} is not one of {sorted(grant.llm)}")
        if grant.busy:
            raise ServiceError("limit", "one call at a time")
        if grant.calls >= grant.max_calls:
            raise ServiceError("limit", f"{grant.max_calls} calls per run")
        grant.calls += 1
        grant.busy = True
        try:
            done = await asyncio.wait_for(
                llm.complete(settings, request, grant.timeout), grant.timeout
            )
        except TimeoutError:
            raise ServiceError("limit", f"no answer in {grant.timeout:.0f} s") from None
        except ValueError as e:  # the schema given is not a JSON Schema
            raise InvalidCallError(str(e)) from None
        finally:
            grant.busy = False
        usage = done.response.usage
        grant.in_tokens += usage.in_tokens
        grant.out_tokens += usage.out_tokens
        entry |= {"inTokens": usage.in_tokens, "outTokens": usage.out_tokens}
        entry |= {"ms": done.response.ms, "valid": done.response.valid, "repaired": done.repaired}
        output = done.response.model_dump(mode="json", by_alias=True, exclude_none=True)
        if list(tool.output.iter_errors(output)):  # S2: never what the tool does not state
            raise ServiceError("unavailable", "the connector's answer does not match llm/v1")
        return tool_result(output)
    except ServiceError as e:
        entry["error"] = e.code
        return tool_result({"error": e.code, "message": e.message}, error=True)
    finally:
        append_log(grant.log, entry)


def append_log(path: Path, entry: Message) -> None:
    line = json.dumps({"t": datetime.now(UTC).isoformat()} | entry)
    with contextlib.suppress(OSError), path.open("a") as f:
        f.write(line + "\n")


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


async def result_of(settings: Settings, grant: Grant, method: Any, params: Message) -> Message:
    if method == "initialize":
        version = params.get("protocolVersion") or PROTOCOL_VERSION
        info = {"name": "handlerd", "version": __version__}
        return {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": info}
    if method == "ping":
        return {}
    tools = services.load(LLM).tools if grant.llm else {}
    if method == "tools/list":
        return {"tools": [t.definition for t in tools.values()]}
    if method != "tools/call":
        raise RpcError(METHOD_NOT_FOUND, f"unknown method {method}")
    if params.get("name") not in tools:
        raise RpcError(INVALID_PARAMS, f"unknown tool {params.get('name')}")
    try:
        return await call_llm(settings, grant, params.get("arguments") or {})
    except (InvalidCallError, ValidationError) as e:
        raise RpcError(INVALID_PARAMS, str(e)) from None


async def answer(settings: Settings, grant: Grant, msg: Message) -> Message | None:
    """A request's response (None for a notification)."""
    if "id" not in msg:
        return None
    reply: Message = {"jsonrpc": "2.0", "id": msg["id"]}
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    try:
        result = await result_of(settings, grant, msg.get("method"), params or {})
    except RpcError as e:
        return reply | {"error": {"code": e.code, "message": e.message}}
    return reply | {"result": result}


async def serve(settings: Settings, path: Path, grant: Grant) -> asyncio.Server:
    """The socket at `path` (replaced if it exists), serving `grant`'s caller until closed."""

    async def connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while line := await reader.readline():
                try:
                    msg = json.loads(line)
                    if not isinstance(msg, dict):
                        raise ValueError("not an object")
                except ValueError:
                    reply: Message | None = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": PARSE_ERROR, "message": "not a JSON-RPC message"},
                    }
                else:
                    reply = await answer(settings, grant, msg)
                if reply is not None:
                    writer.write(json.dumps(reply).encode() + b"\n")
                    await writer.drain()
        except (ValueError, ConnectionError):  # a line past MAX_MESSAGE, the caller gone
            pass
        finally:
            writer.close()

    path.unlink(missing_ok=True)
    return await asyncio.start_unix_server(connection, path=str(path), limit=MAX_MESSAGE)
