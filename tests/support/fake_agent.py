#!/usr/bin/env python3
"""A fake ACP agent on stdio, for testing the platform (not a harness).

It records what it receives, and the last line of the last block of `session/prompt` selects
a behaviour (the texts of every block are kept in the report's "prompt", an image as
"(image <mimeType>)"; it takes images):
    report   reply with a JSON report: initialize capabilities, methods received, mode, options,
             names of the MCP servers of the last session/new or session/load, its WAYLAND_DISPLAY,
             whether the prompt named its own session ("own") or another ("other")
    fs       ask the client to read /etc/passwd (fs/read_text_file) and report the answer
    big      send one ~1 MB agent_message_chunk
    exit     exit immediately with status 3
    sleep    wait for session/cancel, then end the turn with stopReason "cancelled"
    permission  ask session/request_permission, report the chosen outcome
    leak     print the FAKE_TOKEN environment variable (secret redaction tests)
    xss      reply with hostile markup (web UI sanitization tests)
    write    write notes.md in its folder and report it as a completed tool call (files pane)
Anything else: reply "ok".
A run of an agent with an interface (D.18: its request has an "## Input" JSON block) is answered
by the input's `fake`: "valid" gives `answer` back as its `handler-result` block, "repair" only
after the daemon asks again, one of exit, sleep, permission, leak behaves as above; anything else:
"ok". The report also gives its cwd and the files there.
Its session id is "s<pid>" (a new one per process), or the one `session/load` names: that
replays one agent message, "resumed <sessionId>", then answers like session/new.
"""

import json
import os
import re
import sys

state: dict[str, object] = {
    "capabilities": None,
    "methods": [],
    "mode": "ask",
    "options": {},
    "mcpServers": [],
    "display": os.environ.get("WAYLAND_DISPLAY"),
    "prompt": [],
    "session": f"s{os.getpid()}",  # a new one per process, the loaded one after session/load
}
methods: list[str] = state["methods"]


XSS = (
    'hello <img src=x onerror="window.__pwned=1"> <script>window.__pwned=2</script> '
    '[click](javascript:window.__pwned=3) <iframe src="javascript:parent.__pwned=4"></iframe>'
)


def send(msg: dict[str, object]) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", **msg}) + "\n")
    sys.stdout.flush()


def sid() -> str:
    return str(state["session"])


def say(session: str, text: str) -> None:
    update = {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}
    send({"method": "session/update", "params": {"sessionId": session, "update": update}})


INPUT = re.compile(r"## Input\n\n```json\n(.*?)\n```", re.S)
BEHAVIOURS = {"exit", "sleep", "permission", "leak"}  # a run may ask for these too
run: dict[str, object] = {}  # the input of a run (D.18), once its request came


def run_reply(text: str) -> str | None:
    """A run's answer (D.18) or one of BEHAVIOURS, or None when this is not a run."""
    if (found := INPUT.search(text)) is not None:
        run.clear()
        run.update(json.loads(found.group(1)))
    elif not text.startswith("Your result could not be used") or not run:
        return None
    if run.get("fake") in BEHAVIOURS:
        return str(run["fake"])
    if run.get("fake") == "valid" or (run.get("fake") == "repair" and "## Input" not in text):
        return "Here it is.\n\n```json handler-result\n" + json.dumps(run.get("answer")) + "\n```"
    return "ok"


def read() -> dict[str, object] | None:
    line = sys.stdin.readline()
    return json.loads(line) if line else None


def main() -> None:  # noqa: PLR0912, PLR0915 — one branch per ACP method
    while (msg := read()) is not None:
        method, mid = msg.get("method"), msg.get("id")
        params: dict[str, object] = msg.get("params") or {}  # ty: ignore[invalid-assignment]
        if isinstance(method, str):
            methods.append(method)
        if method == "initialize":
            state["capabilities"] = params.get("clientCapabilities")
            capabilities = {"loadSession": True, "promptCapabilities": {"image": True}}
            init = {"protocolVersion": 1, "agentCapabilities": capabilities}
            send({"id": mid, "result": init | {"authMethods": []}})
        elif method in ("session/new", "session/load"):
            servers = params.get("mcpServers") or []
            state["mcpServers"] = [s.get("name") for s in servers]  # ty: ignore[not-iterable]
            if method == "session/load":
                state["session"] = str(params.get("sessionId"))
                say(sid(), f"resumed {sid()}")
            modes = [{"id": m, "name": m} for m in ("ask", "edits", "yolo")]
            options = [{"id": "model", "type": "select", "currentValue": "small", "options": []}]
            result: dict[str, object] = {"modes": {"currentModeId": "ask", "availableModes": modes}}
            if method == "session/new":
                result["sessionId"] = sid()
            send({"id": mid, "result": result | {"configOptions": options}})
        elif method == "session/set_mode":
            state["mode"] = params.get("modeId")
            send({"id": mid, "result": {}})
        elif method == "session/set_config_option":
            state["options"][str(params.get("configId"))] = params.get("value")  # ty: ignore[invalid-assignment]
            send({"id": mid, "result": {}})
        elif method == "session/prompt":
            blocks: list[dict[str, str]] = params["prompt"]  # ty: ignore[invalid-assignment]
            prompt = [b.get("text", f"(image {b.get('mimeType')})") for b in blocks]
            state["prompt"] = prompt
            state["promptSession"] = "own" if params.get("sessionId") == sid() else "other"
            last = prompt[-1]
            text = (last.splitlines() or [""])[-1]
            if (reply := run_reply(last)) in BEHAVIOURS:
                text = str(reply)
            elif reply is not None:
                say(sid(), reply)
                send({"id": mid, "result": {"stopReason": "end_turn"}})
                continue
            if text == "exit":
                sys.exit(3)
            if text == "report":
                here = {"cwd": os.getcwd(), "files": sorted(os.listdir())}
                say(sid(), json.dumps(state | here))
            elif text == "fs":
                send(
                    {
                        "id": "fs-1",
                        "method": "fs/read_text_file",
                        "params": {"sessionId": sid(), "path": "/etc/passwd"},
                    }
                )
                say(sid(), json.dumps(read()))
            elif text == "big":
                say(sid(), "x" * 1_000_000)
            elif text == "sleep":
                while (m := read()) is not None and m.get("method") != "session/cancel":
                    pass
                send({"id": mid, "result": {"stopReason": "cancelled"}})
                continue
            elif text == "permission":
                options = [
                    {"optionId": "yes", "name": "Allow", "kind": "allow_once"},
                    {"optionId": "no", "name": "Reject", "kind": "reject_once"},
                ]
                tool = {"toolCallId": "t1", "title": "rm -rf /"}
                params = {"sessionId": sid(), "toolCall": tool, "options": options}
                send({"id": "perm-1", "method": "session/request_permission", "params": params})
                say(sid(), json.dumps(read()))
            elif text == "write":
                with open("notes.md", "w") as f:
                    f.write("# plan\n")
                tool = {"toolCallId": "w1", "title": "Write notes.md", "kind": "edit"}
                done = {"sessionUpdate": "tool_call", **tool, "status": "completed"}
                send({"method": "session/update", "params": {"sessionId": sid(), "update": done}})
                say(sid(), "written")
            elif text == "xss":
                say(sid(), XSS)
            elif text == "leak":
                say(sid(), f"the token is {os.environ.get('FAKE_TOKEN')}")
            else:
                say(sid(), "ok")
            send({"id": mid, "result": {"stopReason": "end_turn"}})
        elif mid is not None and method is not None:
            send({"id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}})


if __name__ == "__main__":
    main()
