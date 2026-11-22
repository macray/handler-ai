"""The tests' local destination (runtimes.local_server), on port 8000, run by `python3 -c` in an
image every machine running the suite has (the filter's: Python, no packages). Two of httpbin's
answers and a slow one, so that no test depends on a service on the internet:

    /basic-auth/USER/PASSWORD   200 when the request's `Basic` credentials are those, else 401
    /drip/N                     200, N lines, one every half second
    PUT, any path               200, `<bytes> <seconds>`: the body's length, and how long it took
                                to arrive after the request's head (a held body: none)
    anything else               200, the request as JSON (indented: one line per field): its
                                query's arguments, its headers, its URL
"""

import base64
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit


class Echo(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # kept alive, as most servers: every answer has its length

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        parts = url.path.split("/")
        if parts[1:2] == ["basic-auth"] and len(parts) == 4:
            expected = base64.b64encode(f"{parts[2]}:{parts[3]}".encode()).decode()
            given = self.headers.get("Authorization")
            self.answer(200 if given == f"Basic {expected}" else 401, {})
            return
        if parts[1:2] == ["drip"] and len(parts) == 3:
            self.drip(int(parts[2]))
            return
        args = dict(parse_qsl(url.query))
        self.answer(200, {"args": args, "headers": dict(self.headers), "url": self.path})

    def do_PUT(self) -> None:
        start, size = time.monotonic(), 0
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            while length := int(self.rfile.readline().split(b";")[0], 16):
                size += len(self.rfile.read(length))
                self.rfile.readline()
            while self.rfile.readline() not in (b"\r\n", b"\n", b""):  # trailers
                pass
        else:
            size = len(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        data = f"{size} {time.monotonic() - start:.2f}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def drip(self, lines: int) -> None:
        self.send_response(200)
        self.send_header("Content-Length", str(5 * lines))
        self.end_headers()
        for _ in range(lines):
            self.wfile.write(b"drip\n")
            self.wfile.flush()
            time.sleep(0.5)

    def answer(self, status: int, body: dict) -> None:
        data = json.dumps(body, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


ThreadingHTTPServer(("", 8000), Echo).serve_forever()
