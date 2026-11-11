"""A fake OpenAI-compatible model server for the provider tests (D.12): `GET /v1/models` answers
`models` (OpenAI's `{"data": [...]}`), `GET /props` llama-server's `props` when given; `status`
another answer instead. It keeps each request's path, headers and the address it came from.
Listening on every address (as `llama-server --host 0.0.0.0`) or on the loopback only (as
llama-server by default). Runs in the test process."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class ModelsServer:
    def __init__(
        self,
        models: list[dict[str, Any]],
        *,
        props: dict[str, Any] | None = None,
        listen: str = "0.0.0.0",
        status: int = 200,
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                server.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "from": self.client_address[0],
                    }
                )
                if status != 200:
                    answer, code = {"error": "no key"}, status
                elif self.path == "/v1/models":
                    answer, code = {"object": "list", "data": models}, 200
                elif self.path == "/props" and props is not None:
                    answer, code = props, 200
                else:
                    answer, code = {"error": "not found"}, 404
                raw = json.dumps(answer).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer((listen, 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def endpoint(self) -> str:
        """Its endpoint as a person types it: on this computer."""
        return f"http://127.0.0.1:{self.port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
