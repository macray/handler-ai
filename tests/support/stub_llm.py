"""A model provider speaking `openai-chat` for the automations' tests (I.5): every request is
answered with `answer` (a JSON text), and kept in `requests`. Runs in the test process."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class StubLlm:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests: list[dict[str, Any]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append({"path": self.path, "headers": dict(self.headers)} | body)
                raw = json.dumps(
                    {
                        "choices": [{"message": {"role": "assistant", "content": stub.answer}}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                    }
                ).encode()
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

    def provider(self) -> str:
        """A provider's TOML (contract E) for it: one model, `m`, and a key."""
        return (
            'apiVersion = "handler.provider/v1"\napiKey = { env = "HANDLER_TEST_STUB_KEY" }\n'
            f'[endpoints]\nopenai-chat = "http://127.0.0.1:{self.port}/v1"\n'
            '[[models]]\nid = "m"\n'
        )

    def close(self) -> None:
        self.server.shutdown()
