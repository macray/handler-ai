"""A session's event log (F.5), or a slice of it, as markdown for reading (I.4): what an
automation's script, and the model it calls, read of a conversation.

    read      the events of a log from one `seq` to another
    render    those events as a transcript: a header, then each event in order with its `seq`

Pure: no redaction here. The log is already redacted with the session's own secrets (F.5); the
caller redacts the result again with every value of the secret store before it leaves.
"""

import contextlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

HEAD = 2000  # characters kept at the start of a tool call's input or output
TAIL = 1000  # and at its end
CHUNKS = {
    "user_message_chunk": "Person",
    "agent_message_chunk": "Agent",
    "agent_thought_chunk": "Agent's thought",
}
TOOL_CALLS = ("tool_call", "tool_call_update")

Event = dict[str, Any]


def read(log: Path, seq_from: int, seq_to: int) -> list[Event]:
    """The events of `log` with `seq_from <= seq <= seq_to`, in order (unreadable lines skipped)."""
    events = []
    with contextlib.suppress(FileNotFoundError):
        for line in log.read_text().splitlines():
            with contextlib.suppress(ValueError, KeyError, TypeError):
                event = json.loads(line)
                if seq_from <= event["seq"] <= seq_to:
                    events.append(event)
    return events


def cut(text: str) -> str:
    """The first HEAD and last TAIL characters, saying how many were left out between them."""
    if len(text) <= HEAD + TAIL:
        return text
    left = len(text) - HEAD - TAIL
    return f"{text[:HEAD]}\n… ({left} characters left out) …\n{text[-TAIL:]}"


def fenced(text: str) -> str:
    """A code block that the text cannot close (its fence is longer than any run of backticks)."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def block_text(block: Any) -> str:
    """One ACP content block, as text."""
    if not isinstance(block, dict):
        return ""
    kind = block.get("type")
    if kind == "text":
        return str(block.get("text", ""))
    if kind == "resource_link":
        return f"[link: {block.get('uri', '')}]"
    if kind == "resource":
        resource = block.get("resource") or {}
        return str(resource.get("text") or f"[resource: {resource.get('uri', '')}]")
    return f"[{kind}]"


def tool_output(call: Event) -> str:
    """A tool call's output: its raw output, else its content (text, diffs)."""
    if call.get("rawOutput") is not None:
        raw = call["rawOutput"]
        return raw if isinstance(raw, str) else json.dumps(raw, indent=2)
    parts = []
    for item in call.get("content") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "content":
            parts.append(block_text(item.get("content")))
        elif item.get("type") == "diff":
            parts.append(f"diff of {item.get('path', '')}:\n{item.get('newText', '')}")
    return "\n".join(p for p in parts if p)


def tool_call(seq: int, call: Event) -> str:
    kind, status = call.get("kind"), call.get("status")
    about = ", ".join(str(x) for x in (kind, status) if x)
    lines = [f"### [{seq}] Tool call: {call.get('title') or call.get('toolCallId', '')}"]
    if about:
        lines[0] += f" ({about})"
    if call.get("rawInput") is not None:
        raw = call["rawInput"]
        text = raw if isinstance(raw, str) else json.dumps(raw, indent=2)
        lines.append("Input:\n" + fenced(cut(text)))
    if output := tool_output(call):
        lines.append("Output:\n" + fenced(cut(output)))
    return "\n\n".join(lines)


def merged_calls(events: Sequence[Event]) -> dict[str, Event]:
    """toolCallId → the call as it ended: its `tool_call` with its updates merged into it."""
    calls: dict[str, Event] = {}
    for event in events:
        update = event.get("update") or {}
        if event.get("kind") == "update" and update.get("sessionUpdate") in TOOL_CALLS:
            call_id = str(update.get("toolCallId", ""))
            merged = calls.get(call_id, {})
            calls[call_id] = merged | {k: v for k, v in update.items() if v is not None}
    return calls


def line(event: Event) -> str | None:
    """An event that is neither a message chunk nor a tool call, or None when not shown."""
    seq, kind, update = event.get("seq", 0), event.get("kind"), event.get("update") or {}
    if kind == "update" and update.get("sessionUpdate") == "plan":
        entries = update.get("entries") or []
        items = "\n".join(f"- [{e.get('status', '')}] {e.get('content', '')}" for e in entries)
        return f"[{seq}] Plan:\n{items}"
    if kind == "turn" and event.get("phase") == "end":
        return f"[{seq}] Turn ended ({event.get('stopReason', '')})"
    if kind != "lifecycle":
        return None
    detail = event.get("detail", "")
    how = f" ({event['how']})" if event.get("how") else ""
    shown = {
        "started": "Agent started",
        "stopped": f"Session stopped{how}: {detail}",
        "permission answered": f"Permission answered: {detail}",
        "told agent": f"Handler told the agent: {event.get('text', '')}",
        "model unreached": f"Handler: {model_unreached(event)}",
    }.get(event.get("event", ""))
    return f"[{seq}] {shown}" if shown else None


def model_unreached(event: Event) -> str:
    """What Handler said of the model's host not answering (F.9), as the session showed it."""
    local = " Is the server listening on 0.0.0.0?" if event.get("local") else ""
    return f"The model at {event.get('host')} does not answer ({event.get('error')}).{local}"


def render(events: Sequence[Event], header: Sequence[tuple[str, str]]) -> str:
    """The transcript: `header` (label, value) as a list, then the events. Message chunks of one
    kind that follow each other are joined; a tool call is shown where it started, as it ended."""
    calls = merged_calls(events)
    parts = ["# Session transcript", "\n".join(f"- {label}: {value}" for label, value in header)]
    chunk_kind: str | None = None
    chunk_seq = 0
    chunk: list[str] = []
    shown: set[str] = set()

    def flush() -> None:
        nonlocal chunk_kind
        if chunk_kind is not None and (text := "".join(chunk).strip()):
            parts.append(f"## [{chunk_seq}] {CHUNKS[chunk_kind]}\n\n{text}")
        chunk_kind = None
        chunk.clear()

    for event in events:
        update = event.get("update") or {}
        what = update.get("sessionUpdate") if event.get("kind") == "update" else None
        if what in CHUNKS:
            if what != chunk_kind:
                flush()
                chunk_kind, chunk_seq = what, event.get("seq", 0)
            chunk.append(block_text(update.get("content")))
            continue
        shown_as = None
        if what in TOOL_CALLS:
            call_id = str(update.get("toolCallId", ""))
            if call_id not in shown:
                shown.add(call_id)
                shown_as = tool_call(event.get("seq", 0), calls[call_id])
        else:
            shown_as = line(event)
        if shown_as is not None:
            flush()
            parts.append(shown_as)
    flush()
    return "\n\n".join(parts) + "\n"
