"""A sandbox's mirror of container registries (Apple container): an engine's `images` cache
shared by its downloads, which are files named by their digest (contract A.9).

An engine inside a `nested` sandbox keeps its store on the sandbox's own disk (no lock crosses
Apple's VMs); what is shared is what it downloads. Its launcher serves, on a Unix socket the
sandbox's relay reaches, the read part of the OCI distribution API for a fixed list of public
registries (REGISTRIES; `registries.conf` names it as their mirror, `/v2/<registry>/<name>/…`):

- a blob, or a manifest by its digest: from the cache's folder (`blobs/sha256/<hex>`,
  `manifests/sha256/<hex>` and its media type beside it) when there; else fetched from the
  registry through the sandbox's own network (its filter's proxy when filtered: a registry the
  sandbox may not reach is not reached), checked against its digest, then added as every
  cache's file is: written under a temporary name, hard-linked to its name (never replaced, no
  lock), the temporary name removed;
- a manifest by its tag: always asked of the registry (a tag moves), kept by its digest only.

Credentials are never sent to a mirror: what needs them (a private image) gets 401 here, and
the engine pulls it from the registry itself, uncached. Anonymous tokens are asked for as the
registry says (`WWW-Authenticate`), kept for their lifetime.
"""

import contextlib
import hashlib
import json
import os
import re
import socket
import ssl
import sys
import tempfile
import threading
import time
import urllib.parse
from collections.abc import Iterator
from http import client, server
from pathlib import Path

# the registries mirrored (docs: Apple container's page), by the name an image says and the
# host its API is on
REGISTRIES = {
    "docker.io": "registry-1.docker.io",
    "ghcr.io": "ghcr.io",
    "quay.io": "quay.io",
    "registry.k8s.io": "registry.k8s.io",
    "gcr.io": "gcr.io",
    "public.ecr.aws": "public.ecr.aws",
    "mcr.microsoft.com": "mcr.microsoft.com",
}
DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
PATH = re.compile(r"^/v2/([^/]+)/(.+)/(manifests|blobs)/([^/]+)$")
MANIFEST_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])  # fmt: skip
TIMEOUT = 60  # one request to a registry, at most
REDIRECTS = 5
CHUNK = 1 << 20


class Upstream:
    """HTTPS to a registry through the sandbox's own network: its filter's proxy (a Unix socket
    of the host speaking HTTP CONNECT) when filtered, else directly; the roots the filter's
    proxy signs with trusted too (secrets given)."""

    def __init__(self, proxy: Path | None, extra_roots: Path | None, offline: bool) -> None:
        self.proxy = proxy
        self.offline = offline  # the sandbox has no network: only what the cache has
        self.context = ssl.create_default_context()
        if extra_roots is not None:
            self.context.load_verify_locations(cafile=str(extra_roots))
        self.tokens: dict[tuple[str, str], tuple[str, float]] = {}
        self.lock = threading.Lock()

    def connect(self, host: str) -> client.HTTPSConnection:
        if self.offline:
            raise PermissionError("the sandbox has no network: the network filter refused it")
        conn = client.HTTPSConnection(host, timeout=TIMEOUT, context=self.context)
        if self.proxy is None:
            return conn
        raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        raw.settimeout(TIMEOUT)
        raw.connect(str(self.proxy))
        raw.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode())
        answer = b""
        while b"\r\n\r\n" not in answer:
            if not (data := raw.recv(4096)):
                break
            answer += data
        status = answer.split(b"\r\n", 1)[0].split()
        if len(status) < 2 or status[1] != b"200":
            raw.close()
            raise PermissionError(f"the network filter refused {host}")
        conn.sock = self.context.wrap_socket(raw, server_hostname=host)
        return conn

    def get(
        self, url: str, headers: dict[str, str]
    ) -> tuple[client.HTTPResponse, client.HTTPSConnection]:
        """The registry's answer to `url`, redirects followed (to a CDN: no authorization)."""
        for _ in range(REDIRECTS):
            parts = urllib.parse.urlsplit(url)
            conn = self.connect(parts.hostname or "")
            path = parts.path + (f"?{parts.query}" if parts.query else "")
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308) and resp.getheader("location"):
                resp.read()
                conn.close()
                url = urllib.parse.urljoin(url, resp.getheader("location", ""))
                headers = {k: v for k, v in headers.items() if k != "Authorization"}
                continue
            return resp, conn
        raise ConnectionError(f"too many redirects: {url}")

    def token(self, challenge: str, scope_default: str) -> str | None:
        """An anonymous token as `challenge` (a Bearer WWW-Authenticate) says, kept."""
        params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        realm = params.get("realm")
        if not realm or not challenge.lower().startswith("bearer"):
            return None
        scope = params.get("scope", scope_default)
        key = (realm, scope)
        with self.lock:
            found = self.tokens.get(key)
            if found and found[1] > time.monotonic():
                return found[0]
        query = urllib.parse.urlencode({"service": params.get("service", ""), "scope": scope})
        resp, conn = self.get(f"{realm}?{query}", {})
        try:
            if resp.status != 200:
                return None
            doc = json.loads(resp.read())
        finally:
            conn.close()
        value = doc.get("token") or doc.get("access_token")
        if not isinstance(value, str):
            return None
        life = int(doc.get("expires_in") or 60)
        with self.lock:
            self.tokens[key] = (value, time.monotonic() + max(life - 10, 10))
        return value

    def fetch(
        self, registry: str, name: str, kind: str, ref: str, accept: str
    ) -> tuple[client.HTTPResponse, client.HTTPSConnection]:
        url = f"https://{REGISTRIES[registry]}/v2/{name}/{kind}/{ref}"
        headers = {"Accept": accept} if accept else {}
        resp, conn = self.get(url, headers)
        if resp.status == 401:
            challenge = resp.getheader("www-authenticate", "")
            resp.read()
            conn.close()
            token = self.token(challenge, f"repository:{name}:pull")
            if token is None:
                raise PermissionError("the registry asks for credentials")
            resp, conn = self.get(url, {**headers, "Authorization": f"Bearer {token}"})
        return resp, conn


def add(folder: Path, name: str, write: "Iterator[bytes]") -> Path:
    """Write what `write` gives as `name` in `folder`, never replacing it (a cache's file)."""
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / name
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".handler-mirror-")
    try:
        with os.fdopen(fd, "wb") as out:
            for chunk in write:
                out.write(chunk)
        with contextlib.suppress(FileExistsError):  # added meanwhile, the same bytes
            os.link(tmp, final)
    finally:
        os.unlink(tmp)
    return final


class Mirror:
    """The mirror of one sandbox: its cache's folder, its upstream, its sockets."""

    def __init__(self, folder: Path, upstream: Upstream, only: str = "") -> None:
        self.folder = folder
        self.upstream = upstream
        self.only = only  # Docker's mirror is Docker Hub's alone: its paths say no registry

    def serve(self, path: Path) -> "Served":
        path.unlink(missing_ok=True)
        httpd = _Server(str(path), _Handler)  # ty: ignore[invalid-argument-type] — a Unix path (AF_UNIX)
        httpd.mirror = self
        thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="handler-mirror")
        thread.start()
        return Served(httpd, path)

    def blob_path(self, hex_: str) -> Path:
        return self.folder / "blobs" / "sha256" / hex_

    def manifest_path(self, hex_: str) -> Path:
        return self.folder / "manifests" / "sha256" / hex_


class Served:
    def __init__(self, httpd: "_Server", path: Path) -> None:
        self.httpd, self.path = httpd, path

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.path.unlink(missing_ok=True)


class _Server(server.ThreadingHTTPServer):
    address_family = socket.AF_UNIX
    daemon_threads = True
    mirror: Mirror

    def server_bind(self) -> None:
        self.socket.bind(self.server_address)

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        conn, _ = self.socket.accept()
        return conn, ("sandbox", 0)  # a Unix socket has no address: logs say whose


class _Handler(server.BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        """Quiet: the launcher's stderr is handlerd's log."""

    def do_HEAD(self) -> None:
        self._answer(head=True)

    def do_GET(self) -> None:
        self._answer(head=False)

    def _say(self, status: int, body: bytes = b"", content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _answer(self, head: bool) -> None:
        mirror = self.server.mirror
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/v2/", "/v2"):
            self._say(200, b"{}", "application/json")
            return
        if mirror.only:  # Docker's: /v2/<name>/…, the registry its own
            path = f"/v2/{mirror.only}/" + path.removeprefix("/v2/")
        found = PATH.match(path)
        if not found or found.group(1) not in REGISTRIES:
            self._say(404, b"not mirrored")
            return
        registry, name, kind, ref = found.groups()
        if self.headers.get("Authorization"):  # a private image: the engine asks the registry
            self._say(401, b"credentials are not for a mirror")
            return
        try:
            if kind == "blobs":
                self._blob(registry, name, ref, head)
            else:
                self._manifest(registry, name, ref, head)
        except PermissionError as e:  # the filter or the registry said no: the engine asks it
            self._say(403 if "filter" in str(e) else 401, str(e).encode())
        except (OSError, client.HTTPException, ValueError) as e:
            print(f"handler-sandbox-apple: mirror: {registry}/{name}: {e}", file=sys.stderr)
            self._say(502, b"the registry did not answer")

    def _send_file(self, file: Path, content_type: str, digest: str, head: bool) -> None:
        size = file.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Docker-Content-Digest", digest)
        self.end_headers()
        if head:
            return
        with file.open("rb") as f:
            while chunk := f.read(CHUNK):
                self.wfile.write(chunk)

    def _blob(self, registry: str, name: str, ref: str, head: bool) -> None:
        mirror = self.server.mirror
        found = DIGEST.match(ref)
        if not found:
            self._say(404, b"a blob is named by its digest")
            return
        file = mirror.blob_path(found.group(1))
        if not file.exists():
            resp, conn = mirror.upstream.fetch(registry, name, "blobs", ref, "")
            try:
                if resp.status != 200:
                    self._say(resp.status if resp.status in (401, 403, 404) else 502)
                    return
                checked = _checked(resp, found.group(1))
                add(file.parent, file.name, checked)
            finally:
                conn.close()
        self._send_file(file, "application/octet-stream", ref, head)

    def _manifest(self, registry: str, name: str, ref: str, head: bool) -> None:
        mirror = self.server.mirror
        found = DIGEST.match(ref)
        if found and (file := mirror.manifest_path(found.group(1))).exists():
            kind = (file.parent / f"{file.name}.type").read_text().strip()
            self._send_file(file, kind, ref, head)
            return
        accept = self.headers.get("Accept") or MANIFEST_TYPES
        resp, conn = mirror.upstream.fetch(registry, name, "manifests", ref, accept)
        try:
            if resp.status != 200:
                self._say(resp.status if resp.status in (401, 403, 404) else 502)
                return
            body = resp.read()
            content_type = resp.getheader("content-type", "application/json")
        finally:
            conn.close()
        hex_ = hashlib.sha256(body).hexdigest()
        if found and hex_ != found.group(1):
            raise ValueError(f"manifest {ref} does not match its digest")
        file = mirror.manifest_path(hex_)
        add(file.parent, f"{hex_}.type", iter([content_type.encode()]))
        add(file.parent, hex_, iter([body]))
        self._send_file(file, content_type, f"sha256:{hex_}", head)


def _checked(resp: client.HTTPResponse, hex_: str) -> Iterator[bytes]:
    """The body, its digest checked at its end (a mismatch raises: nothing is kept)."""
    digest = hashlib.sha256()
    while chunk := resp.read(CHUNK):
        digest.update(chunk)
        yield chunk
    if digest.hexdigest() != hex_:
        raise ValueError(f"blob sha256:{hex_} does not match its digest")
