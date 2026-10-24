"""A model provider speaking `openai-chat` for the tests calling models (I.5, the model alone):
every request is answered with `answer` (a text, or a function of the request's body giving one),
and kept in `requests`. It also writes down speech (`transcriptions`, I.11): `heard`, whatever
was sent (its size kept in `requests`). Runs in the test process."""

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class StubLlm:
    def __init__(self, answer: str | Callable[[dict[str, Any]], str], heard: str = "") -> None:
        self.answer = answer
        self.heard = heard
        self.requests: list[dict[str, Any]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                sent = self.rfile.read(int(self.headers["Content-Length"]))
                seen = {"path": self.path, "headers": dict(self.headers)}
                if self.path.endswith("/audio/transcriptions"):
                    stub.requests.append(seen | {"bytes": len(sent)})
                    raw = json.dumps({"text": stub.heard}).encode()
                else:
                    body = json.loads(sent)
                    stub.requests.append(seen | body)
                    said = stub.answer(body) if callable(stub.answer) else stub.answer
                    raw = json.dumps(
                        {
                            "choices": [{"message": {"role": "assistant", "content": said}}],
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
        """A provider's TOML (contract E) for it: a model, `m`, a speech model, `ears`, and a
        key."""
        return (
            'apiVersion = "handler.provider/v1"\napiKey = { env = "HANDLER_TEST_STUB_KEY" }\n'
            f'[endpoints]\nopenai-chat = "http://127.0.0.1:{self.port}/v1"\n'
            f'transcriptions = "http://127.0.0.1:{self.port}/v1"\n'
            '[[models]]\nid = "m"\n[[models]]\nid = "ears"\nspeech = true\n'
        )

    def close(self) -> None:
        self.server.shutdown()
