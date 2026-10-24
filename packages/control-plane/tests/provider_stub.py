"""A model provider for the unit tests calling models (llm.py, model_agent.py, transcribe.py): it
speaks `openai-chat`, `anthropic` and `transcriptions` on the loopback, in the test process."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class Stub:
    """A provider: answers each request with the next of `answers` (text, or an int: that HTTP
    status, or None: never in time, or a dict: that body as it is), in the protocol it was asked
    in."""

    def __init__(self) -> None:
        self.answers: list[Any] = []
        self.requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                sent = self.rfile.read(int(self.headers["Content-Length"]))
                heard = self.path.endswith("/audio/transcriptions")  # multipart: kept as text
                body = {"multipart": sent.decode("latin-1")} if heard else json.loads(sent)
                stub.requests.append((self.path, dict(self.headers), body))
                answer = stub.answers.pop(0)
                if answer is None:
                    time.sleep(1.5)
                    return
                if isinstance(answer, int):
                    self.send_response(answer)
                    self.end_headers()
                    self.wfile.write(b'{"error": "overloaded"}')
                    return
                if isinstance(answer, dict):
                    data = answer
                elif heard:
                    data = {"text": answer}
                elif self.path.endswith("/chat/completions"):
                    data = {
                        "choices": [{"message": {"role": "assistant", "content": answer}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                    }
                else:
                    data = {
                        "content": [{"type": "text", "text": answer}],
                        "usage": {"input_tokens": 7, "output_tokens": 2},
                    }
                raw = json.dumps(data).encode()
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
