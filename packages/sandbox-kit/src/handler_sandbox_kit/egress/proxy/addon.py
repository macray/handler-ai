"""handler's egress proxy (contract A.3, A.4): the addon mitmdump loads in a sandbox's proxy
container.

Self-contained (the image has mitmproxy, not handler). In /cfg:

- `egress.json` (`{"allow": [...], "blocked": [...], "enforcement": "enforce"|"log-only"|"open",
  "watched": "<turn>"|null, "version": n}`): read again whenever it changes (`set-egress`,
  `set-allow`, `set-blocked`, `set-watched`), looked at every SETTINGS_POLL; `blocked`, the hosts
  the user kept blocked, only changes what a refusal says; `watched`, the turn someone watches
  the session in (null: nobody does): then the first request to a host neither allowed nor kept
  blocked is held up to HOLD seconds for the person's answer, once per host and turn (`held`
  event), and goes through only if the host becomes allowed meanwhile;
  `open` filters nothing and reports nothing (an open sandbox's proxy is there for its secrets
  only). While it cannot be read (a runtime's shared folder may lose it a moment as it is
  replaced: Apple container's), the settings read last stay in force: never none.
- `applied`: the version of the settings in force, for `set-egress` to wait for.
- `secrets.json` (`[{"name", "phantom", "value", "hosts"}]`, A.3 injections), read at start.
- `events.jsonl`: one event per decision, which the runtime reports on stderr:
  `{"decision": "allowed"|"denied"|"unlisted", "host": "host:port"}`, `{"decision": "held",
  "host": "host:port", "wait": HOLD}` when a request starts waiting (its decision follows), and
  for a secret
  `{"decision": "injected"|"leak", "host": "host:port", "secret": name}`. Then how its
  connection to the host went, once per connection (requests may share one): `{"decision":
  "reached", "host": "host:port"}`, or `{"decision": "unreached", "host": "host:port", "error":
  "connection refused"}` (`connect_error`); none when chained to a development proxy (every
  connection goes to it, `chained`).
- `started`: created once the proxy accepts connections, after `ca-bundle.pem` (the system's
  roots and this proxy's CA, for the agent to trust) when there are secrets.

What it decides on is the target a client asks for: `CONNECT host:port` for a tunnel, the URL of a
forwarded `http://` request. A tunnel is relayed undecrypted (mitmproxy's `ignore_hosts` or
`allow_hosts`, set by the runtime), whatever the protocol and whichever side speaks
first, except towards a host a secret is for: that one is decrypted, so the proxy can swap the
secret's phantom for its value. A phantom it sees going anywhere else is a leak: refused.
"""

import asyncio
import base64
import binascii
import json
import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CFG = Path("/cfg")
# the name a sandbox reaches the host by (contract A.3, handler_contracts.CONTAINER_HOST); where a
# runtime's network does not resolve it (Apple container), the runtime gives the filter the host's
# address in HOST_ADDRESS_ENV, and connections to that name go there (decided on the name)
HOST_ALIAS = "host.containers.internal"
HOST_ADDRESS_ENV = "HANDLER_HOST_ADDRESS"
SETTINGS = "egress.json"
APPLIED = "applied"
SETTINGS_POLL = 0.05  # seconds
# seconds a request to an undecided host waits for the person's answer while they watch: below
# what common clients wait for a proxy's answer (measured 2026-11-01 on a proxy that never
# answers CONNECT: uv 10 s, pip 15 s, curl and npm minutes)
HOLD = 8
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
class Refusal:
    """What a refused request is answered with: a 403 whose reason phrase says it (most clients
    print only the status line of a refused tunnel), and a body saying it longer."""

    reason: str
    body: str


def refusal(target: str) -> Refusal:
    """The answer to a request for a host the allow list does not hold, the user's answer
    unknown."""
    return Refusal(
        reason=f"Blocked by Handler's network filter: ask the user to allow {target}",
        body=(
            f"Blocked by Handler's network filter: {target} is not in this agent's allow list.\n"
            "This is the network filter, not an outage nor a proxy problem: only allowed hosts "
            "answer.\n"
            f"If your task cannot be done well without {target}, ask the user to allow it "
            "(name the host and port) and end your turn. If you can do the task well without it, "
            "go on, and say at the end that it was refused and what you did instead.\n"
            "Never try to get around the filter (other proxies, mirrors of the same service, "
            "other ports).\n"
        ),
    )


def kept_blocked(target: str) -> Refusal:
    """The answer to a request for a host the user said stays blocked: not to be asked again."""
    return Refusal(
        reason=(
            f"Blocked by Handler's network filter on the user's choice: do not ask for {target}, "
            "go on without it."
        ),
        body=(
            f"Blocked by Handler's network filter on the user's choice: the user keeps {target} "
            "blocked for this agent.\n"
            f"Do not ask for {target}: go on without it, and say at the end that it was refused "
            "and what you did instead.\n"
            "Never try to get around the filter (other proxies, mirrors of the same service, "
            "other ports).\n"
        ),
    )


# what a failed connection says (an OSError's text, the errno first), in the person's words
CONNECT_ERRORS = (
    (("Errno 111]", "Connection refused"), "connection refused"),
    (("Errno 110]", "timed out"), "no answer: timed out"),
    (("Errno -2]", "Errno -3]", "Errno -5]", "not known"), "host not found"),
    (("Errno 113]", "Errno 101]", "unreachable"), "no route to the host"),
)
ERROR_CHARS = 200


def connect_error(text: str) -> str:
    """Why a connection to a host failed: `connection refused`, `host not found`…, else the
    error's own text, cut short."""
    for marks, said in CONNECT_ERRORS:
        if any(m in text for m in marks):
            return said
    return text[:ERROR_CHARS] or "connection failed"


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
        self._blocked: list[str] = []
        self._enforcement = "enforce"
        self._watched: str | None = None
        self._held: set[str] = set()  # the hosts already held in the turn `_held_in`
        self._held_in: str | None = None
        self._holds: dict[str, asyncio.Task[None]] = {}  # a host being held → its wait
        self._connecting: dict[str, str] = {}  # a server connection's id → its target
        self.chained = False  # every connection goes to a development proxy (`running`)
        self.injections: list[Injection] = []

    def settings(self) -> tuple[list[str], str]:
        """The current settings, read again when the file changed: its writer replaces it with a
        new file, so a new inode, even within the clock's resolution. Unreadable, those read
        last (at first: enforce, nothing allowed), so a request is never judged on none."""
        try:
            st = (self.cfg / SETTINGS).stat()
            stamp = (st.st_ino, st.st_mtime_ns)
            if stamp != self._stamp:
                data = json.loads((self.cfg / SETTINGS).read_text())
                allow, blocked, watched = data["allow"], data["blocked"], data["watched"]
                enforcement, version = data["enforcement"], data["version"]
                self._allow, self._blocked, self._enforcement = allow, blocked, enforcement
                self._watched = watched
                self._stamp = stamp
                tmp = self.cfg / f"{APPLIED}.tmp"
                tmp.write_text(str(version))
                tmp.replace(self.cfg / APPLIED)
        except (OSError, ValueError, KeyError):
            pass
        return self._allow, self._enforcement

    def load_secrets(self) -> None:
        path = self.cfg / SECRETS
        if path.exists():
            self.injections = [Injection(**i) for i in json.loads(path.read_text())]

    def event(self, **event: str | int) -> None:
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

    async def admit(self, target: str) -> bool:
        """Whether a request for `target` may go through: judged, or first held while someone
        watches (`hold`). Fails closed: an error on the way refuses it."""
        try:
            allow, enforcement = self.settings()
            if enforcement == "enforce" and not listed(target, allow) and self.holds(target):
                await self.hold(target)
            return self.judge(target)
        except Exception:  # whatever went wrong, nothing goes through
            return False

    def holds(self, target: str) -> bool:
        """Whether a refused `target` is held first: someone watches, the user did not keep it
        blocked, and it was not held already in this turn (a request for it while it is held
        waits with it)."""
        if self._watched is None or listed(target, self._blocked):
            return False
        if self._watched != self._held_in:
            self._held, self._held_in = set(), self._watched
        return target in self._holds or target not in self._held

    async def hold(self, target: str) -> None:
        """Until `target` is allowed, kept blocked, nobody watches any more, or HOLD seconds
        passed; then `judge` decides (rule network.a-watched-request-waits-for-the-answer)."""
        if target not in self._holds:
            self._held.add(target)
            self.event(decision="held", host=target, wait=HOLD)
            self._holds[target] = asyncio.ensure_future(self._wait(target))
        await asyncio.shield(self._holds[target])

    async def _wait(self, target: str) -> None:
        deadline = asyncio.get_running_loop().time() + HOLD
        try:
            while asyncio.get_running_loop().time() < deadline:
                allow, enforcement = self.settings()
                answered = listed(target, allow) or listed(target, self._blocked)
                if answered or enforcement != "enforce" or self._watched is None:
                    return
                await asyncio.sleep(SETTINGS_POLL)
        finally:
            del self._holds[target]

    def refusal(self, target: str) -> Refusal:
        """What a refused target is answered with: whether the user kept it blocked (the
        settings `judge` read)."""
        return kept_blocked(target) if listed(target, self._blocked) else refusal(target)

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

        self.chained = any(m.startswith("upstream") for m in ctx.options.mode)
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
        while True:  # a change applied (and said so) without waiting for a request
            self.settings()
            await asyncio.sleep(SETTINGS_POLL)

    async def http_connect(self, flow: Any) -> None:
        if not await self.admit(_target(flow)):
            _refuse(flow, self.refusal(_target(flow)))

    async def requestheaders(self, flow: Any) -> None:
        """A plain http:// request is judged here: its target is its host and port (mitmproxy has
        already made its first line relative in regular mode). One inside a TLS tunnel was judged
        with the tunnel (`http_connect`)."""
        target = _target(flow)
        if not flow.client_conn.tls and not await self.admit(target):
            _refuse(flow, self.refusal(target))
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
            _refuse(flow, Refusal("Forbidden", f"handler: a secret is not for {target}\n"))
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

    def server_connect(self, data: Any) -> None:
        """A connection to the host's name goes to its address, when the runtime gave one."""
        self._connecting[data.server.id] = "{}:{}".format(*data.server.address).lower()
        data.server.address = host_address(data.server.address, os.environ.get(HOST_ADDRESS_ENV))

    def server_connected(self, data: Any) -> None:
        self.outcome(data.server.id, None)

    def server_connect_error(self, data: Any) -> None:
        self.outcome(data.server.id, data.server.error or "")

    def outcome(self, connection: str, error: str | None) -> None:
        """How a connection to an admitted target went, `reached` or `unreached` with why (rule
        network.an-outcome-is-seen): an allowed host that does not answer is not shown as
        reached. Not reported chained (the connection is the development proxy's), nor open."""
        target = self._connecting.pop(connection, None)
        if target is None or self.chained or self.settings()[1] == "open":
            return
        if error is None:
            self.event(decision="reached", host=target)
        else:
            self.event(decision="unreached", host=target, error=connect_error(error))

    def responseheaders(self, flow: Any) -> None:
        """A response body is passed on as it comes, never held whole: a large download would
        take the filter's memory (an Apple container VM has 1 GiB). The secrets' hosts' through
        the masker."""
        if not self.injections or not self.secret_host(_target(flow)):
            flow.response.stream = True
            return
        pairs = [(i.value.encode(), i.phantom.encode()) for i in self.injections]
        flow.response.headers.fields = tuple(
            (k, _replace_all(v, pairs)) for k, v in flow.response.headers.fields
        )
        flow.response.stream = Masker(pairs)


def host_address(address: tuple[str, int], host: str | None) -> tuple[str, int]:
    """`address`, or the host's when it names the host and the runtime said where that is."""
    name, port = address
    return (host, port) if host and name.lower() == HOST_ALIAS else address


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


def _refuse(flow: Any, refused: Refusal) -> None:
    from mitmproxy import http  # noqa: PLC0415  # ty: ignore[unresolved-import]

    flow.response = http.Response.make(403, refused.body, {"Content-Type": "text/plain"})
    flow.response.reason = refused.reason


addons = [Egress()]
