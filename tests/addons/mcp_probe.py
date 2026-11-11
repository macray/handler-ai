"""A minimal MCP client over stdio, run inside a sandbox the way a harness would run an addon's MCP
server: `python3 mcp_probe.py URL [URL …] -- COMMAND [ARG …]`.

Serves a page on 127.0.0.1:9292 first (a local preview, like `shopify theme dev`), then navigates
to each URL and prints one JSON object: per URL, whether the navigation failed and the start of
the tool's text; the browser processes' command lines (headless or not).
"""

import itertools
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

split = sys.argv.index("--")
urls, command = sys.argv[1:split], sys.argv[split + 1 :]

page = Path("/tmp/preview")
page.mkdir()
(page / "index.html").write_text("<title>handler preview</title><h1>local preview</h1>")
subprocess.Popen(
    ["python3", "-m", "http.server", "9292", "--bind", "127.0.0.1", "--directory", str(page)],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
time.sleep(1)

server = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
ids = itertools.count(1)
signal.signal(signal.SIGALRM, lambda *_: sys.exit("timeout waiting for the MCP server"))


def call(method: str, params: dict) -> dict:
    next_id = next(ids)
    assert server.stdin and server.stdout
    server.stdin.write(
        json.dumps({"jsonrpc": "2.0", "id": next_id, "method": method, "params": params}) + "\n"
    )
    server.stdin.flush()
    signal.alarm(90)
    while line := server.stdout.readline():
        message = json.loads(line)
        if message.get("id") == next_id:
            signal.alarm(0)
            if "error" in message:
                sys.exit(f"{method}: {message['error']}")
            return message["result"]
    sys.exit(f"MCP server exited ({server.poll()})")


call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "handler-probe", "version": "0"}})  # fmt: skip
assert server.stdin
server.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
server.stdin.flush()
report: dict = {"navigations": {}}
for url in urls:
    result = call("tools/call", {"name": "browser_navigate", "arguments": {"url": url}})
    text = " ".join(c.get("text", "") for c in result.get("content", []))
    report["navigations"][url] = {"error": bool(result.get("isError")), "text": text[:3000]}
ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, check=False).stdout
# by its program's name, whatever the distribution's path (Fedora's launcher execs the browser
# under the name it was started as: /usr/bin/chromium)
report["browsers"] = [
    line for line in ps.splitlines() if line and Path(line.split()[0]).name.startswith("chrom")
]
print(json.dumps(report))
server.stdin.close()
server.terminate()
