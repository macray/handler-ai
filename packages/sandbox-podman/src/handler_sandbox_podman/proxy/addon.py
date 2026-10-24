"""handler's egress proxy (contract A.3, A.4): the addon mitmdump loads in a sandbox's proxy
container.

Self-contained (the image has mitmproxy, not handler). In /cfg:

- `egress.json` (`{"allow": [...], "enforcement": "enforce"|"log-only"|"open"}`): read again
  whenever it changes (`set-egress`, `set-allow`); `open` filters nothing and reports nothing
  (an open sandbox's proxy is there for its secrets only).
- `secrets.json` (`[{"name", "phantom", "value", "hosts"}]`, A.3 injections), read at start.
- `events.jsonl`: one event per decision, which handler-sandbox-podman reports on stderr:
  `{"decision": "allowed"|"denied"|"unlisted", "host": "host:port"}`, and for a secret
  `{"decision": "injected"|"leak", "host": "host:port", "secret": name}`.
- `started`: created once the proxy accepts connections, after `ca-bundle.pem` (the system's
  roots and this proxy's CA, for the agent to trust) when there are secrets.

What it decides on is the target a client asks for: `CONNECT host:port` for a tunnel, the URL of a
forwarded `http://` request. A tunnel is relayed undecrypted (mitmproxy's `ignore_hosts` or
`allow_hosts`, set by handler-sandbox-podman), whatever the protocol and whichever side speaks
first, except towards a host a secret is for: that one is decrypted, so the proxy can swap the
secret's phantom for its value. A phantom it sees going anywhere else is a leak: refused.
"""

import asyncio
import base64
import binascii
import json
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CFG = Path("/cfg")
SETTINGS = "egress.json"
SECRETS = "secrets.json"
EVENTS = "events.jsonl"
STARTED = "started"
CA_CERT = "ca/mitmproxy-ca-cert.pem"  # made by mitmproxy at start (confdir=/cfg/ca)
CA_BUNDLE = "ca-bundle.pem"
SYSTEM_ROOTS = Path("/etc/ssl/certs/ca-certificates.crt")


def entry_pattern(entry: str) -> re.Pattern[str]:
    """Allow-list entry 'host:port' (A.3) → the 'host:port' targets it allows. 'a.b.com' exact;
    '*.b.com' one or more subdomain labels. Entries are validated before they get here."""
    host, _, port = entry.rpartition(":")
    literal = re.escape(host.removeprefix("*."))
    host_re = rf"([a-z0-9-]+\.)+{literal}" if host.startswith("*.") else literal
    return re.compile(rf"{host_re}:{re.escape(port)}")


def listed(target: str, allow: list[str]) -> bool:
    """Whether an entry allows a target 'host:port'."""
    return any(entry_pattern(e).fullmatch(target.lower()) for e in allow)


def decide(target: str, allow: list[str], enforcement: str) -> str:
    """'allowed', 'denied', or 'unlisted' (log only: let through, but enforcing would deny it)."""
    if listed(target, allow):
        return "allowed"
    return "unlisted" if enforcement == "log-only" else "denied"


@dataclass(frozen=True)
class Injection:
    name: str
    phantom: str
    value: str
    hosts: list[str]


def swap_basic(header: str, phantom: str, value: str) -> str:
    """An `Authorization: Basic` value with the phantom swapped inside its base64 credentials;
    the header as it is when it holds none."""
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() != "basic":
        return header
    try:
        decoded = base64.b64decode(credentials.strip(), validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return header
    if phantom not in decoded:
        return header
    return f"{scheme} {base64.b64encode(decoded.replace(phantom, value).encode()).decode()}"


class Masker:
    """A streamed response body with secret values replaced by their phantoms (a server echoing
    a credential back). Holds back only what could be the start of a value until the next chunk
    (b"": the end), so streaming (server-sent events) is not delayed."""

    def __init__(self, pairs: list[tuple[bytes, bytes]]) -> None:
        self.pairs = pairs  # value → phantom
        self.tail = b""

    def __call__(self, chunk: bytes) -> bytes:
        data = self.tail + chunk
        for value, phantom in self.pairs:
            data = data.replace(value, phantom)
        keep = 0 if not chunk else self._partial(data)
        self.tail = data[len(data) - keep :]
        return data[: len(data) - keep]

    def _partial(self, data: bytes) -> int:
        """The length of the longest end of `data` that begins a value."""
        longest = 0
        for value, _ in self.pairs:
            for n in range(min(len(value) - 1, len(data)), longest, -1):
                if data.endswith(value[:n]):
                    longest = n
                    break
        return longest


class Egress:
    def __init__(self, cfg: Path = CFG) -> None:
        self.cfg = cfg
        self._stamp: tuple[int, int] | None = None
        self._allow: list[str] = []
        self._enforcement = "enforce"
        self.injections: list[Injection] = []

    def settings(self) -> tuple[list[str], str]:
        """The current settings, read again when the file changed: its writer replaces it with a
        new file, so a new inode, even within the clock's resolution."""
        st = (self.cfg / SETTINGS).stat()
        stamp = (st.st_ino, st.st_mtime_ns)
        if stamp != self._stamp:
            data = json.loads((self.cfg / SETTINGS).read_text())
            self._allow, self._enforcement, self._stamp = data["allow"], data["enforcement"], stamp
        return self._allow, self._enforcement

    def load_secrets(self) -> None:
        path = self.cfg / SECRETS
        if path.exists():
            self.injections = [Injection(**i) for i in json.loads(path.read_text())]

    def event(self, **event: str) -> None:
        with (self.cfg / EVENTS).open("a") as f:
            f.write(json.dumps(event) + "\n")

    def judge(self, target: str) -> bool:
        """Decide for a target, record the event; whether it may go through."""
        allow, enforcement = self.settings()
        if enforcement == "open":
            return True
        decision = decide(target, allow, enforcement)
        self.event(decision=decision, host=target)
        return decision != "denied"

    def secret_host(self, target: str) -> bool:
        return any(listed(target, i.hosts) for i in self.injections)

    def write_bundle(self) -> None:
        """The roots the agent trusts while its secret hosts are decrypted: the system's and this
        proxy's CA (made per sandbox, its key never leaves this container)."""
        bundle = SYSTEM_ROOTS.read_text().rstrip("\n") + "\n" + (self.cfg / CA_CERT).read_text()
        (self.cfg / CA_BUNDLE).write_text(bundle)

    # ── mitmproxy hooks ─────────────────────────────────────────────────

    def load(self, loader: Any) -> None:
        self.load_secrets()

    async def running(self) -> None:
        # mitmproxy is only in the proxy image: handler's tests import the rest of this file
        from mitmproxy import ctx  # noqa: PLC0415  # ty: ignore[unresolved-import]

        if self.injections:
            self.write_bundle()
        host, port = ctx.options.listen_host or "127.0.0.1", ctx.options.listen_port
        while True:
            try:
                socket.create_connection((host, port), timeout=1).close()
                break
            except OSError:
                await asyncio.sleep(0.02)
        (self.cfg / STARTED).touch()

    def http_connect(self, flow: Any) -> None:
        if not self.judge(_target(flow)):
            _refuse(flow, f"handler: {_target(flow)} is not allowed\n")

    def requestheaders(self, flow: Any) -> None:
        """A plain http:// request is judged here: its target is its host and port (mitmproxy has
        already made its first line relative in regular mode). One inside a TLS tunnel was judged
        with the tunnel (`http_connect`)."""
        target = _target(flow)
        if not flow.client_conn.tls and not self.judge(target):
            _refuse(flow, f"handler: {target} is not allowed\n")
        elif self.secret_host(target):
            flow.request.headers.pop("accept-encoding", None)  # bodies the masker can read

    def request(self, flow: Any) -> None:
        """Swap the phantoms the request holds (headers, `Basic` credentials, URL, body) for
        their values when it goes to their hosts; refuse it when one goes anywhere else."""
        if flow.response is not None or flow.request.method == "CONNECT":
            return
        req, target = flow.request, _target(flow)
        found = [i for i in self.injections if _holds(req, i.phantom)]
        if leaked := [i for i in found if not listed(target, i.hosts)]:
            for i in leaked:
                self.event(decision="leak", host=target, secret=i.name)
            _refuse(flow, f"handler: a secret is not for {target}\n")
            return
        for i in found:
            phantom, value = i.phantom.encode(), i.value.encode()
            req.headers.fields = tuple(
                (k, v.replace(phantom, value)) for k, v in req.headers.fields
            )
            if "authorization" in req.headers:
                req.headers["authorization"] = swap_basic(
                    req.headers["authorization"], i.phantom, i.value
                )
            req.url = req.url.replace(i.phantom, i.value)
            body = req.get_content(strict=False)
            if body and phantom in body:
                req.set_content(body.replace(phantom, value))
            self.event(decision="injected", host=target, secret=i.name)

    def responseheaders(self, flow: Any) -> None:
        if not self.injections or not self.secret_host(_target(flow)):
            return
        pairs = [(i.value.encode(), i.phantom.encode()) for i in self.injections]
        flow.response.headers.fields = tuple(
            (k, _replace_all(v, pairs)) for k, v in flow.response.headers.fields
        )
        flow.response.stream = Masker(pairs)


def _target(flow: Any) -> str:
    return f"{flow.request.host.lower()}:{flow.request.port}"


def _holds(req: Any, phantom: str) -> bool:
    raw = phantom.encode()
    if any(raw in v for _, v in req.headers.fields) or phantom in req.url:
        return True
    auth = req.headers.get("authorization", "")
    if swap_basic(auth, phantom, "") != auth:
        return True
    body = req.get_content(strict=False)
    return bool(body) and raw in body


def _replace_all(data: bytes, pairs: list[tuple[bytes, bytes]]) -> bytes:
    for old, new in pairs:
        data = data.replace(old, new)
    return data


def _refuse(flow: Any, text: str) -> None:
    from mitmproxy import http  # noqa: PLC0415  # ty: ignore[unresolved-import]

    flow.response = http.Response.make(403, text, {"Content-Type": "text/plain"})


addons = [Egress()]
