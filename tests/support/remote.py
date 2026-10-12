"""Remote control for tests: a real gateway (subprocess) and a paired device speaking the envelope
protocol (docs/dev/design/remote.md §4) — what the phone's remote client does, in Python.

The gateway is an independent project (remote-gateway/): it is run from its sources, with the
test environment's Starlette and uvicorn, never imported.
"""

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from handler_control import remote_crypto as rc

REPO = Path(__file__).resolve().parents[2]
GATEWAY_SRC = REPO / "remote-gateway" / "src"

Frame = dict[str, Any]


@dataclass
class Gateway:
    url: str
    host_token: str
    process: subprocess.Popen[bytes]
    env: dict[str, str]

    def add_host(self, name: str) -> str:
        return gateway_cli(self.env, "add-host", name)


def gateway_cli(env: dict[str, str], *args: str) -> str:
    out = subprocess.run(
        [sys.executable, "-m", "handler_gateway", *args],
        env=env,
        capture_output=True,
        check=True,
        text=True,
    )
    return out.stdout.strip()


def start_gateway(client_dir: Path | None = None) -> Iterator[Gateway]:
    """`client_dir`: the built remote client, served at / (browser tests)."""
    tmp = Path(tempfile.mkdtemp(prefix="handler-gateway-"))
    env = os.environ | {
        "PYTHONPATH": str(GATEWAY_SRC),
        "HANDLER_GATEWAY_STATE": str(tmp / "state.json"),
    }
    host_token = gateway_cli(env, "add-host", "tests")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    log = open(tmp / "gateway.log", "wb")  # noqa: SIM115 — kept open for its lifetime
    proc = subprocess.Popen(
        [sys.executable, "-m", "handler_gateway", "serve", "--port", str(port)]
        + (["--client", str(client_dir)] if client_dir else []),
        env=env,
        stdout=log,
        stderr=log,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while True:
        try:
            if httpx.get(f"{url}/v1/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            if time.monotonic() > deadline:
                proc.kill()
                raise RuntimeError((tmp / "gateway.log").read_text()) from None
            time.sleep(0.1)
    try:
        yield Gateway(url, host_token, proc, env)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()


class Device:
    """A paired device: sends frames in sealed envelopes, polls and opens what the host sends."""

    def __init__(self, pairing_url: str) -> None:
        fragment = pairing_url.split("#", 1)[1]
        assert fragment.startswith("pair=")
        raw = fragment[len("pair=") :]
        pairing = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        self.gateway, self.host_id, self.id = pairing["g"], pairing["h"], pairing["d"]
        self.key = rc.unb64(pairing["k"])
        token = rc.gateway_token(self.key)
        self.http = httpx.Client(
            base_url=self.gateway,
            headers={"Authorization": f"Bearer {self.id}.{token}"},
            timeout=30,
        )
        self.cursor = ""
        self.frames: list[Frame] = []  # everything received, in order
        self.used: set[int] = set()  # indexes of frames a wait_* call returned
        self.acks: list[str] = []
        self.rejected: list[dict[str, Any]] = []
        self.fetched: list[str] = []
        self.envelopes: list[dict[str, Any]] = []  # raw up envelopes (for replay tests)
        self.ids = 0

    # ── sending ─────────────────────────────────────────────────────────

    def seal(self, frames: list[Frame], ts: int | None = None) -> dict[str, str]:
        plain = {"ts": ts if ts is not None else int(time.time() * 1000), "frames": frames}
        return rc.seal(self.key, self.host_id, self.id, "down", plain)

    def post(self, envelope: dict[str, Any]) -> httpx.Response:
        return self.http.post("/v1/device/down", json=envelope)

    def send(self, frames: list[Frame], ts: int | None = None) -> dict[str, str]:
        envelope = self.seal(frames, ts)
        r = self.post(envelope)
        assert r.status_code == 202, r.text
        return envelope

    def queue(self, frames: list[Frame], ts: int | None = None) -> dict[str, str]:
        """Leave frames at the gateway for when the host is back (A5)."""
        envelope = self.seal(frames, ts)
        r = self.http.post("/v1/device/queue", json=envelope)
        assert r.status_code == 202, r.text
        return envelope

    def notify(self, s: str | None, method: str, params: dict[str, Any] | None = None) -> None:
        self.send([{"s": s, "m": {"jsonrpc": "2.0", "method": method, "params": params or {}}}])

    def call(self, s: str | None, method: str, params: dict[str, Any] | None = None) -> int:
        self.ids += 1
        m = {"jsonrpc": "2.0", "id": self.ids, "method": method, "params": params or {}}
        self.send([{"s": s, "m": m}])
        return self.ids

    def request(
        self, s: str | None, method: str, params: dict[str, Any] | None = None, timeout: float = 30
    ) -> Any:
        rid = self.call(s, method, params)
        m = self.wait_frame(lambda f: f["s"] == s and f["m"].get("id") == rid, timeout)["m"]
        if "error" in m:
            raise DeviceError(m["error"])
        return m.get("result")

    def answer(self, s: str, request_id: Any, option_id: str) -> None:
        outcome = {"outcome": "selected", "optionId": option_id}
        m = {"jsonrpc": "2.0", "id": request_id, "result": {"outcome": outcome}}
        self.send([{"s": s, "m": m}])

    # ── receiving ───────────────────────────────────────────────────────

    def poll(self, wait: float = 1.0) -> int:
        r = self.http.get("/v1/device/poll", params={"after": self.cursor, "wait": wait})
        r.raise_for_status()
        data = r.json()
        self.cursor = data["cursor"]
        self.fetched += data["fetched"]
        for envelope in data["envelopes"]:
            self.envelopes.append(envelope)
            plain = rc.open_envelope(self.key, self.host_id, self.id, "up", envelope)
            self.frames += plain.get("frames", [])
            self.acks += plain.get("acks", [])
            self.rejected += plain.get("rejected", [])
        return len(data["envelopes"])

    def wait_frame(self, match: Callable[[Frame], bool], timeout: float = 30) -> Frame:
        deadline = time.monotonic() + timeout
        while True:
            for i, frame in enumerate(self.frames):
                if i not in self.used and match(frame):
                    self.used.add(i)
                    return frame
            if time.monotonic() > deadline:
                raise TimeoutError(f"no matching frame; received: {self.frames[-5:]}")
            self.poll()

    def wait_until(self, check: Callable[[], bool], timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while not check():
            if time.monotonic() > deadline:
                raise TimeoutError("condition not met")
            self.poll()

    def notifications(self, s: str | None, method: str) -> list[dict[str, Any]]:
        return [
            f["m"].get("params") or {}
            for f in self.frames
            if f["s"] == s and f["m"].get("method") == method and "id" not in f["m"]
        ]

    def text(self, s: str) -> str:
        return "".join(
            u["update"]["content"].get("text", "")
            for u in self.notifications(s, "session/update")
            if u["update"].get("sessionUpdate") == "agent_message_chunk"
        )


class DeviceError(RuntimeError):
    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(f"{error.get('code')}: {error.get('message')}")
        self.code = error.get("code")
