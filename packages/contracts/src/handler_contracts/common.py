"""Building blocks shared by several contracts (docs/dev/contracts.md)."""

import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field
from pydantic.alias_generators import to_camel


def _absolute_path(p: str) -> str:
    if not p.startswith("/"):
        raise ValueError("must be an absolute path")
    if p != "/" and any(seg in ("", ".", "..") for seg in p[1:].split("/")):
        raise ValueError("must be normalized (no empty, '.' or '..' segments, no trailing slash)")
    return p


def _expand_home(p: object) -> object:
    """'~' and '~/rel' → the home of the user reading the document (the daemon's user)."""
    if isinstance(p, str) and (p == "~" or p.startswith("~/")):
        return str(Path.home()) + p[1:]
    return p


def _home_path(p: str) -> str:
    if not (p == "~" or p.startswith("~/") or p.startswith("/")):
        raise ValueError("must be absolute or start with '~/'")
    if any(seg in (".", "..") for seg in p.split("/")[1:]):
        raise ValueError("must not contain '.' or '..' segments")
    return p


_EGRESS_HOST_RE = re.compile(r"^(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_OCTET = r"(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4_RE = re.compile(rf"^({_OCTET}\.){{3}}{_OCTET}$")
_PORT_RE = re.compile(r"^([1-9]\d{0,3}|[1-5]\d{4}|6[0-4]\d{3}|65[0-4]\d\d|655[0-2]\d|6553[0-5])$")


def _egress_entry(e: str) -> str:
    host, sep, port = e.rpartition(":")
    if not (sep and _PORT_RE.match(port) and (_EGRESS_HOST_RE.match(host) or _IPV4_RE.match(host))):
        raise ValueError(
            "must be HOST:PORT, HOST a lowercase hostname (optionally prefixed with '*.') or an "
            "IPv4 address, and an explicit port (443 for https, 80 for http)"
        )
    return e


def egress_target(url: str) -> str:
    """The allow-list entry a URL needs: its lowercased host and port, the scheme's default port
    (https 443, http 80) when the URL has none."""
    parsed = urlparse(url)
    port = parsed.port or {"https": 443, "http": 80}[parsed.scheme]
    return f"{(parsed.hostname or '').lower()}:{port}"


AbsolutePath = Annotated[str, AfterValidator(_absolute_path)]
"""Absolute, normalized path: starts with '/', no '.', '..' or empty segments."""

HostPath = Annotated[str, BeforeValidator(_expand_home), AfterValidator(_absolute_path)]
"""Host path in a hand-written document (providers, bindings, mini app manifests): an
AbsolutePath, or '~' / '~/rel' for the host user's home, expanded when the document is read."""

HomePath = Annotated[str, AfterValidator(_home_path)]
"""Sandbox path that may be relative to the harness home: '/abs', '~' or '~/rel'."""

EgressEntry = Annotated[str, AfterValidator(_egress_entry)]
"""Allow-list entry (A.3), always with its port: 'example.com:443' exact host, '*.example.com:443'
subdomains only, '192.168.1.20:11434' an IPv4 address (e.g. a model server on the LAN). No default
port: https is 443, http 80, and any other port is written out."""

EnvName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
EnvMap = dict[EnvName, str]

PermissionMode = Literal["ask", "accept-edits", "bypass"]
PERMISSION_MODES: tuple[PermissionMode, ...] = ("ask", "accept-edits", "bypass")
NetworkMode = Literal["none", "filtered", "open"]
# D.8: a project's agents use the global caches (with other projects), their own, or none
CacheSharing = Literal["global", "project", "off"]
Enforcement = Literal["enforce", "log-only"]
Confinement = Literal["strict", "nested", "privileged"]
"""How locked down a container is (A.5): "strict" = the A3 hardening; "nested" = what running
containers inside it needs (podman-in-podman); "privileged" = no confinement beyond the user
namespace, about as safe as no sandbox."""


class Document(BaseModel):
    """Exchanged document: camelCase on the wire, unknown fields ignored (contracts §0)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        frozen=True,
    )


ResourceName = Annotated[str, Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
"""The name of an account, a provider or a binding: its file's stem."""

ANY_CONTEXT = "any"
"""In an account's or a provider's contexts: usable in every project (a local model)."""


def _not_any(name: str) -> str:
    if name.lower() == ANY_CONTEXT:
        raise ValueError(f"'{ANY_CONTEXT}' is not a context's name: it means every context")
    return name


_CONTEXT = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]([A-Za-z0-9 _-]*[A-Za-z0-9])?$")
ContextName = Annotated[str, _CONTEXT, AfterValidator(_not_any)]
"""A project context (D.19): "Work", "Personal", a client's name."""
AccessContext = Annotated[str, _CONTEXT]
"""Where an account or a provider may be used (D.19): a context's name, or `any`."""
ContextColor = Literal["blue", "violet", "cyan", "pink", "slate"]
"""A context's colour (D.19): never the accent's nor a status's (orange, green, amber, red)."""


class StrictDocument(Document):
    """Hand-written document (accounts, providers, bindings, mini app manifests): unknown keys
    are errors (typo protection)."""

    model_config = ConfigDict(extra="forbid")


class EnvSecret(StrictDocument):
    env: EnvName


class FileSecret(StrictDocument):
    file: HostPath


class CommandSecret(StrictDocument):
    command: Annotated[list[Annotated[str, Field(min_length=1)]], Field(min_length=1)]


# A value in handler's secret store (D.14), named after what owns it: `providers/openrouter/apiKey`,
# `apps/notes/TOKEN`. Segments never start with a dot.
SecretPath = Annotated[
    str,
    Field(
        max_length=256,
        pattern=r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*(/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*$",
    ),
]


class StoreSecret(StrictDocument):
    secret: SecretPath


SecretRef = EnvSecret | FileSecret | CommandSecret | StoreSecret
"""Reference to a secret, never the value itself (E2)."""


class FileContent(StrictDocument):
    content: str


FileSource = FileSecret | EnvSecret | FileContent
"""Where a config file's content comes from: a host file (`file`), an environment variable of
the daemon (`env`), or inline in the provider (`content`)."""


# app: H.3; subject: the handler object a run works on (D.18), read-only
MountKind = Literal["scope", "state", "cache", "config", "knowledge", "app", "subject"]


class Mount(Document):
    """Filesystem mount as seen by the sandbox (A.1). Targets are absolute."""

    source: AbsolutePath
    target: AbsolutePath
    read_only: bool
    kind: MountKind


class GeneratedFile(Document):
    """File generated by the platform: mounted read-only into the sandbox, or — with `seed` —
    copied into a writable path before the process starts, so the harness may rewrite it
    (changes are discarded with the sandbox). A seeded file must lie under a writable path."""

    target: AbsolutePath
    content: str
    mode: Annotated[str, Field(pattern=r"^0?[0-7]{3}$")] | None = None
    seed: bool = False


class NameValue(StrictDocument):
    name: str
    value: str


class StdioMcpServer(StrictDocument):
    name: Annotated[str, Field(min_length=1)]
    command: Annotated[str, Field(min_length=1)]
    args: list[str] = []
    env: list[NameValue] = []


class HttpMcpServer(StrictDocument):
    type: Literal["http", "sse"]
    name: Annotated[str, Field(min_length=1)]
    url: Annotated[str, Field(pattern=r"^https?://")]
    headers: list[NameValue] = []


McpServer = StdioMcpServer | HttpMcpServer
"""MCP server, same shape as ACP `session/new` `mcpServers` entries."""

McpTransport = Literal["stdio", "http", "sse"]


def mcp_transport(server: McpServer) -> McpTransport:
    return "stdio" if isinstance(server, StdioMcpServer) else server.type


class Resources(StrictDocument):
    memory: Annotated[str, Field(pattern=r"^\d+[kmgKMG]?$")] | None = None
    cpus: Annotated[str, Field(pattern=r"^\d+(\.\d+)?$")] | None = None


def is_within(path: str, root: str) -> bool:
    """True when `path` equals `root` or is below it (both already normalized)."""
    return path == root or path.startswith("/" if root == "/" else f"{root}/")
