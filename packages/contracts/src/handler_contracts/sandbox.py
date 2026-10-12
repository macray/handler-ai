"""Contract A — Sandbox (`handler.sandbox/v1`)."""

from datetime import datetime
from enum import IntEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .common import (
    AbsolutePath,
    Confinement,
    Document,
    EgressEntry,
    Enforcement,
    EnvMap,
    GeneratedFile,
    Mount,
    Resources,
    is_within,
)

SANDBOX_API_VERSION = "handler.sandbox/v1"


class NoNetwork(Document):
    mode: Literal["none"]


class OpenNetwork(Document):
    mode: Literal["open"]


class FilteredNetwork(Document):
    mode: Literal["filtered"]
    allow: list[EgressEntry]
    enforcement: Enforcement  # log-only = all HTTP(S) allowed but logged; live-switchable (A.4)


NetworkPolicy = Annotated[NoNetwork | OpenNetwork | FilteredNetwork, Field(discriminator="mode")]


class ImageMount(Document):
    """An image's filesystem, mounted read-only (A.1), e.g. an addon (docs/dev/design/addons.md)."""

    image: Annotated[str, Field(min_length=1)]  # a reference; pinned to an id at creation (A6)
    target: AbsolutePath


class WaylandDisplay(Document):
    """A display the sandboxed process may draw on (A.6): only this Wayland socket."""

    mode: Literal["wayland"]
    socket: AbsolutePath  # on the host, e.g. /run/user/1000/wayland-0


# A.6: set by the implementation when a display is given; the spec's env must not set them.
DISPLAY_ENV = frozenset({"WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DISPLAY"})

# A.3: with injections, the implementation gives the process the roots it trusts (the system's
# and the sandbox's proxy's CA) in this file, named by these variables (the runtimes' own: Node
# and Bun add to their roots, the others replace them).
CA_BUNDLE = "/run/handler/ca-bundle.pem"
CA_ENV = frozenset(
    {
        "SSL_CERT_FILE",  # OpenSSL, Python's ssl and httpx, Go, Rust (native roots)
        "NODE_EXTRA_CA_CERTS",  # Node, Bun
        "REQUESTS_CA_BUNDLE",  # Python requests
        "CURL_CA_BUNDLE",  # curl
        "GIT_SSL_CAINFO",  # git over https
        "DENO_CERT",  # Deno
    }
)


class Injection(Document):
    """A secret the sandbox's proxy gives, not the sandbox (A.3): the process holds the
    `phantom`; the proxy puts `value` in its place in requests to `hosts`, and refuses a request
    holding it anywhere else. Both have the same length: swapping them (the value in a response
    becomes the phantom again) keeps every message's length."""

    name: Annotated[str, Field(min_length=1)]  # what egress events call it, e.g. a secret path
    phantom: Annotated[str, Field(min_length=8, pattern=r"^[!-~]+$")]  # printable, no space
    value: Annotated[str, Field(pattern=r"^[ -~]+$")]  # printable ASCII: one byte a character
    hosts: Annotated[list[EgressEntry], Field(min_length=1)]

    @model_validator(mode="after")
    def _same_length(self) -> Self:
        if len(self.value) != len(self.phantom):
            raise ValueError(f"injection {self.name}: its phantom must be as long as its value")
        return self


class SandboxUser(Document):
    mode: Literal["host-user"]  # v1: only the host user's uid/gid (A3)
    home: AbsolutePath


class SandboxSpec(Document):
    api_version: Literal["handler.sandbox/v1"]
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,62}$")]
    confinement: Confinement = "strict"  # A.5
    image: str
    argv: Annotated[list[Annotated[str, Field(min_length=1)]], Field(min_length=1)]
    env: EnvMap
    workdir: AbsolutePath
    user: SandboxUser
    mounts: list[Mount]
    image_mounts: list[ImageMount] = []
    path_append: list[AbsolutePath] = []  # appended to the image's PATH
    files: list[GeneratedFile]
    writable_paths: list[AbsolutePath]
    network: NetworkPolicy
    resources: Resources | None = None
    display: WaylandDisplay | None = None
    labels: dict[str, str] | None = None
    tty: bool = False  # the process on a terminal (D.16), reached with `attach`, not on stdio
    injections: list[Injection] = []  # A.3: secrets given by the proxy

    @model_validator(mode="after")
    def _injections(self) -> Self:
        if not self.injections:
            return self
        if isinstance(self.network, NoNetwork):
            raise ValueError("injections need a network: their proxy gives them (A.3)")
        if clash := sorted(CA_ENV & self.env.keys()):
            raise ValueError(f"injections: the implementation sets {clash}, env must not")
        phantoms = [i.phantom for i in self.injections]
        if len(set(phantoms)) != len(phantoms):
            raise ValueError("injections: each phantom must be unique")
        return self

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        scopes = [m for m in self.mounts if m.kind == "scope"]
        for m in scopes:
            if m.target != m.source:
                raise ValueError(f"scope mount {m.source} must use target = source (A2)")
        if not any(is_within(self.workdir, m.source) for m in scopes):
            raise ValueError("workdir must be inside a scope mount")
        if not self.image:
            raise ValueError("image is required")
        writable = [self.user.home, *self.writable_paths]
        for f in self.files:
            if f.seed and not any(is_within(f.target, w) and f.target != w for w in writable):
                raise ValueError(
                    f"seeded file {f.target} must be under the home or a writable path"
                )
        if self.display and (clash := sorted(DISPLAY_ENV & self.env.keys())):
            raise ValueError(f"display is set by the implementation: env must not set {clash}")
        if "PATH" in self.env and self.path_append:
            raise ValueError("pathAppend extends the image's PATH: env must not set PATH too")
        seen: set[str] = set()
        targets = [m.target for m in self.mounts] + [m.target for m in self.image_mounts]
        for t in targets + [f.target for f in self.files]:
            if t in seen:
                raise ValueError(f"duplicate target {t}")
            seen.add(t)
        return self


class SandboxExit(IntEnum):
    """Exit codes of `handler-sandbox-<impl>` before the sandboxed process starts."""

    UNENFORCEABLE = 64  # A1: spec cannot be fully enforced by this implementation
    INVALID_SPEC = 65
    SETUP_FAILED = 66


class ImageInfo(Document):
    """What `handler-sandbox-<impl> image inspect REF` prints (A.7): the image's id and build
    time."""

    id: str  # hex, without an algorithm prefix
    created: datetime


class ProxyImage(Document):
    """What `handler-sandbox-<impl> image proxy` prints (A.7): the egress proxy's image (A.3), whose
    recipe and name are the runtime's; `image` when it is built."""

    ref: str
    image: ImageInfo | None = None


class RuntimeCheckItem(Document):
    """One thing the runtime needs from the host (A.8), and what was found."""

    name: str
    ok: bool
    required: bool  # False: only some sandboxes need it (e.g. `nested`)
    detail: str


class RuntimeCheck(Document):
    """What `handler-sandbox-<impl> check` prints (A.8): can this host run sandboxes."""

    runtime: str  # the engine and its version, e.g. "podman 5.4.1"
    ok: bool  # every required item is ok
    items: list[RuntimeCheckItem]
