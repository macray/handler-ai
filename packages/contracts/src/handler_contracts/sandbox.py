"""Contract A — Sandbox (`handler.sandbox/v2`): what a sandbox needs, in Handler's words; each
runtime gives each need its own way."""

from datetime import datetime
from enum import IntEnum
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from .common import (
    AbsolutePath,
    Confinement,
    Document,
    EgressEntry,
    Enforcement,
    EnvMap,
    Resources,
    is_within,
)

SANDBOX_API_VERSION = "handler.sandbox/v2"

Ability = Literal["nested", "privileged", "display"]
"""What a sandbox may need that a runtime may lack, on a platform or a host (A.8): a runtime
declares those it gives in `check`, and a spec needing one it lacks is refused (A1). What every
runtime gives (the work folder, the network filter, a terminal…) is not an ability."""

# Each ability as the person reads it, e.g. after "not on this computer: ".
ABILITIES: dict[Ability, str] = {
    "nested": "sandboxes that run containers",
    "privileged": "privileged sandboxes",
    "display": "windows on your screen",
}

# B.6: what a sandbox with an ability runs from the toolbox, one of these commands: the engine
# inside `nested` and `privileged` sandboxes is the toolbox's (its system packages), not the
# runtime's.
ABILITY_NEEDS: dict[Ability, list[str]] = {
    "nested": ["podman", "docker"],
    "privileged": ["podman", "docker"],
    "display": ["wl-paste"],
}

# A.3: the name a sandbox reaches the machine running handlerd by, its loopback services included;
# every implementation provides it (in a filtered sandbox, its filter resolves it).
CONTAINER_HOST = "host.containers.internal"

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

# D.16: what the client pastes into the program (an image, Ctrl+V): it writes PASTE_IMAGE into
# the paste folder (replaced whole; removed when its clipboard holds no image); the sandbox reads
# it at PASTE_DIR, read-only, as the clipboard (`paste`: an `xclip` answering from it).
PASTE_DIR = "/run/handler/paste"
PASTE_IMAGE = "image.png"


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


class NoNetwork(Document):
    """No route at all, loopback only."""

    mode: Literal["none"]


class OpenNetwork(Document):
    """The runtime's network; its secrets (`injections`) given by Handler's filter (A.3)."""

    mode: Literal["open"]
    injections: list[Injection] = []


class FilteredNetwork(Document):
    """Only the allowed hosts, through Handler's filter, which fails closed (A.3); its allow-list,
    kept-blocked list and enforcement changed while it runs, in force when the verb returns
    (A.4)."""

    mode: Literal["filtered"]
    allow: list[EgressEntry]
    # the hosts the person kept blocked: refused as any unlisted one, the refusal saying it is
    # their choice (A.3)
    blocked: list[EgressEntry] = []
    enforcement: Enforcement  # log-only = all HTTP(S) allowed but logged; live-switchable (A.4)
    injections: list[Injection] = []


NetworkPolicy = Annotated[NoNetwork | OpenNetwork | FilteredNetwork, Field(discriminator="mode")]


class Addon(Document):
    """An addon's tools (G.2): a host folder (its image extracted, A.7 `image extract`),
    read-only at `target`; `path`, its folder of commands, on PATH after the image's and the
    caches'."""

    source: AbsolutePath
    target: AbsolutePath
    path: AbsolutePath | None = None

    @model_validator(mode="after")
    def _path_is_its_own(self) -> Self:
        if self.path is not None and not is_within(self.path, self.target):
            raise ValueError(f"tool at {self.target}: its commands' folder is in it")
        return self


class Paste(Document):
    """An image pasted in the terminal reaches the program's clipboard reader (D.16): `xclip -o`
    answers from this host folder, read-only at PASTE_DIR."""

    source: AbsolutePath


# A.1: Handler's own folders, which no image has: its tools are there, and the runtime's own
# files (the CA bundle, the display's socket). A tool in HANDLER_BIN is a command: on PATH, after
# the image's and the addons' folders.
HANDLER_FOLDERS = ("/run/handler", "/opt/handler")
HANDLER_BIN = "/run/handler/bin"


def _handler_path(p: str) -> str:
    if not any(is_within(p, f) and p != f for f in HANDLER_FOLDERS):
        raise ValueError(f"must be in one of Handler's folders ({', '.join(HANDLER_FOLDERS)})")
    return p


HandlerPath = Annotated[AbsolutePath, AfterValidator(_handler_path)]
FileMode = Annotated[str, Field(pattern=r"^0?[0-7]{3}$")]


# The files group (A.1): where the sandbox works and what it keeps. Every target is absolute.


class WorkFolder(Document):
    """The scope: read-write, at the same absolute path (A2); what is written there is the host
    user's."""

    path: AbsolutePath


class HostFolder(Document):
    """A host folder at `target`; what the sandbox writes there (`writable`) is on the host."""

    source: AbsolutePath
    target: AbsolutePath
    writable: bool


SocketName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")]


class SocketFolder(Document):
    """Where the sandbox and the host meet through Unix sockets (A.10): `source` on the host,
    `target` in the sandbox, each socket in it named with its direction. `serves`: the sandbox
    listens at `target/<name>`, the host connects at `source/<name>` (an app's backend). `reaches`:
    the host listens at `source/<name>`, the sandbox connects at `target/<name>`. Nothing else in
    it is shared: what the sandbox writes there may stay in the sandbox (Apple: in its VM)."""

    source: AbsolutePath
    target: AbsolutePath
    serves: list[SocketName] = []
    reaches: list[SocketName] = []

    @model_validator(mode="after")
    def _names(self) -> Self:
        names = [*self.serves, *self.reaches]
        if not names:
            raise ValueError(f"{self.target}: a socket folder names at least one socket")
        if len(set(names)) != len(names):
            raise ValueError(f"{self.target}: each socket is named once")
        return self


class CacheFolder(Document):
    """A host folder kept between sandboxes, read-write, created if missing; its size and its
    clearing through the `cache` verbs (A.9). `path`, its folder of commands, on PATH after the
    image's (B.6: `~/.cargo/bin`)."""

    source: AbsolutePath
    target: AbsolutePath
    path: AbsolutePath | None = None

    @model_validator(mode="after")
    def _path_is_its_own(self) -> Self:
        if self.path is not None and not is_within(self.path, self.target):
            raise ValueError(f"cache {self.target}: its commands' folder is in it")
        return self


class KeptFile(Document):
    """A host file, read-write, alone in its folder (a runtime may mount that folder): what the
    sandbox writes in place is on the host after. In the home."""

    source: AbsolutePath
    target: AbsolutePath


class File(Document):
    """A file Handler gives, its content here, in the home: read-only, or `writable` (the program
    rewrites it); either way discarded with the sandbox, nothing goes back."""

    target: AbsolutePath
    content: str
    mode: FileMode  # e.g. "0444", "0600"
    writable: bool = False


class HandlerTool(Document):
    """An executable Handler gives, in one of Handler's folders (e.g. `handler-sandbox-env`); in
    HANDLER_BIN, a command (`handler-llm`)."""

    target: HandlerPath
    content: str


class SandboxSpec(Document):
    api_version: Literal["handler.sandbox/v2"]
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,62}$")]
    image: str
    argv: Annotated[list[Annotated[str, Field(min_length=1)]], Field(min_length=1)]
    env: EnvMap  # not PATH: the runtime's (the image's, the addons' folders, HANDLER_BIN)
    workdir: AbsolutePath  # in the work folder or a folder
    # writable, empty at the start (over the image's), discarded; the process runs as the host
    # user (A3) with this HOME. The folders in it holding what is mounted stay writable.
    home: AbsolutePath
    isolation: Confinement = "strict"  # A.5
    resources: Resources | None = None
    work_folder: WorkFolder
    folders: list[HostFolder] = []
    socket_folders: list[SocketFolder] = []
    caches: list[CacheFolder] = []
    kept_files: list[KeptFile] = []
    files: list[File] = []
    tools: list[HandlerTool] = []
    addons: list[Addon] = []
    network: NetworkPolicy
    tty: bool = False  # the process on a terminal (D.16), reached with `attach`, not on stdio
    display: bool = False  # its windows on the person's screen (A.6): the runtime finds it
    paste: Paste | None = None
    labels: dict[str, str] | None = None

    def abilities(self) -> frozenset[Ability]:
        """What this sandbox needs that a runtime may lack (A1: refused when it does)."""
        needed: set[Ability] = set()
        if self.isolation != "strict":
            needed.add(self.isolation)
        if self.display:
            needed.add("display")
        return frozenset(needed)

    @property
    def injections(self) -> list[Injection]:
        """The secrets its filter gives (A.3), in an open or a filtered network."""
        return [] if isinstance(self.network, NoNetwork) else self.network.injections

    def targets(self) -> list[str]:
        """Where each need of the files group, each addon and the paste folder are."""
        found = [self.work_folder.path]
        for group in (self.folders, self.socket_folders, self.caches, self.kept_files,
                      self.files, self.tools, self.addons):  # fmt: skip
            found += [n.target for n in group]
        return found + ([PASTE_DIR] if self.paste else [])

    @model_validator(mode="after")
    def _injections(self) -> Self:
        if not self.injections:
            return self
        if clash := sorted(CA_ENV & self.env.keys()):
            raise ValueError(f"injections: the implementation sets {clash}, env must not")
        phantoms = [i.phantom for i in self.injections]
        if len(set(phantoms)) != len(phantoms):
            raise ValueError("injections: each phantom must be unique")
        return self

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        if not self.image:
            raise ValueError("image is required")
        roots = [self.work_folder.path, *(f.target for f in self.folders)]
        if not any(is_within(self.workdir, r) for r in roots):
            raise ValueError("workdir must be in the work folder or a folder")
        for f in [*self.kept_files, *self.files]:
            if not (is_within(f.target, self.home) and f.target != self.home):
                raise ValueError(f"{f.target}: a file is in the home ({self.home})")
        if self.display and (clash := sorted(DISPLAY_ENV & self.env.keys())):
            raise ValueError(f"display is set by the implementation: env must not set {clash}")
        if "PATH" in self.env:
            raise ValueError("PATH is the runtime's: the image's, the tools', Handler's commands")
        seen: set[str] = set()
        for t in self.targets():
            if t in seen:
                raise ValueError(f"duplicate target {t}")
            seen.add(t)
        return self


class SandboxExit(IntEnum):
    """Exit codes of `handler-sandbox-<impl>` of its own: before the sandboxed process starts
    (64-66), or the sandbox ended by its launcher while it ran (67)."""

    UNENFORCEABLE = 64  # A1: spec cannot be fully enforced by this implementation
    INVALID_SPEC = 65
    SETUP_FAILED = 66
    FILTER_STOPPED = 67  # its network filter stopped: the sandbox, left with no network, ended


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


class RuntimeSupports(Document):
    """What a runtime gives on this host (A.8): a spec needing an ability it lacks is refused
    (A1), and an agent needing one is refused when it is saved (D.2)."""

    isolation: str  # what keeps a sandbox from the computer, in the person's words
    abilities: list[Ability]  # those it gives here
    # a spec's memory and CPU limits (`resources`) are applied here; False: the host does not let
    # them be (e.g. cgroups v1 with a rootless runtime), the sandbox runs without them, said
    limits: bool


class RuntimeCheck(Document):
    """What `handler-sandbox-<impl> check` prints (A.8): can this host run sandboxes."""

    runtime: str  # the engine and its version, e.g. "podman 5.4.1"
    ok: bool  # every required item is ok
    items: list[RuntimeCheckItem]
    supports: RuntimeSupports | None = None  # None: it cannot run sandboxes here at all
