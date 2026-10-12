"""Contract H — Mini app (`handler.miniapp/v1`), docs/dev/design/miniapps.md.

A mini app is a folder written by an agent (with the `miniapp` addon's skill): a manifest
(`app.toml`), a Deno backend in its own directory, a built UI. handler runs it on demand in a
sandbox and serves it at its own origin. The manifest is hand-written TOML: unknown keys are errors.
"""

import tomllib
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from .common import EgressEntry, HostPath, Resources, StrictDocument

MINIAPP_API_VERSION = "handler.miniapp/v1"
MANIFEST_FILE = "app.toml"

# The runtime every app runs on (H.3). Pinned: an app is tested against it when it is deployed.
# The `miniapp` addon ships the same Deno version to the agents that write apps.
RUNTIME_IMAGE = "docker.io/denoland/deno:distroless-2.9.7"

# H.3: where things are inside an app's sandbox.
APP_CODE_DIR = "/opt/app"
APP_RUN_DIR = "/run/handler-app"
APP_SOCKET = f"{APP_RUN_DIR}/app.sock"
APP_API_SOCKET = f"{APP_RUN_DIR}/handler.sock"  # handler's side (H.9), with `needs.notify`
APP_HOME = "/home/app"

# H.4: what every backend answers once ready (migrations applied), and the prefix of its routes.
API_PREFIX = "/api/"
HEALTH_PATH = "/api/health"
PERSON_HEADER = "X-HANDLER-Person"

# A DNS label (the app's origin is http://<name>.localhost:<port>), kept short for socket paths.
AppName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,29}$")]
AppVersion = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")]

# Env vars the platform sets (H.3): a secret may not take their names.
RESERVED_SECRET_PREFIXES = ("HANDLER_", "DENO_")
RESERVED_SECRETS = frozenset(
    {"PATH", "HOME", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "NO_COLOR", "TINI_SUBREAPER"}
)


def _secret_name(name: str) -> str:
    if name in RESERVED_SECRETS or name.startswith(RESERVED_SECRET_PREFIXES):
        raise ValueError(f"{name} is set by handler: pick another name")
    return name


SecretName = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$"), AfterValidator(_secret_name)]


def _relative_path(p: str) -> str:
    segments = p.split("/")
    if p.startswith("/") or any(s in ("", ".", "..") for s in segments):
        raise ValueError("must be a normalized relative path (no '/', '.' or '..' segments)")
    return p


RelativePath = Annotated[str, AfterValidator(_relative_path)]


class MiniAppServer(StrictDocument):
    # The backend: its directory (the entry's) is deployed whole, with its vendored dependencies.
    entry: RelativePath = "server/main.ts"

    @property
    def dir(self) -> str:
        return self.entry.rpartition("/")[0]


class MiniAppUi(StrictDocument):
    dir: RelativePath = "ui/dist"  # built static files, with an index.html


class MiniAppFile(StrictDocument):
    """A file or folder of the host the backend may read (or write): mounted at the same path."""

    path: HostPath  # "~/notes/agenda.md": the home of the person running handler
    mode: Literal["ro", "rw"] = "ro"


class MiniAppNeeds(StrictDocument):
    """What the app may reach (H.2). Shown when it is deployed; more than before is flagged."""

    egress: list[EgressEntry] = []  # hosts the backend may reach, through the filtered network
    # env vars whose values the person enters in handler (never in the app's folder): API keys…
    secrets: list[SecretName] = []
    files: Annotated[list[MiniAppFile], Field(max_length=10)] = []
    notify: bool = False  # it may send notifications (desktop, phones): H.9


# H.10: a route run later when the host is off (the phone queues it at the gateway).
RouteKey = Annotated[str, Field(pattern=r"^(POST|PUT|PATCH|DELETE) /api/[A-Za-z0-9/_.-]*$")]
RouteKind = Literal["sync", "queued"]


class MiniAppManifest(StrictDocument):
    api_version: Literal["handler.miniapp/v1"]
    name: AppName
    version: AppVersion
    description: str | None = None
    server: MiniAppServer = MiniAppServer()
    ui: MiniAppUi = MiniAppUi()
    needs: MiniAppNeeds = MiniAppNeeds()
    routes: dict[RouteKey, RouteKind] = {}
    resources: Resources | None = None  # default: 512 MiB

    @property
    def queued_routes(self) -> list[str]:
        return sorted(k for k, v in self.routes.items() if v == "queued")

    @model_validator(mode="after")
    def _layout(self) -> Self:
        if "/" not in self.server.entry:
            raise ValueError("server.entry must be inside a directory (e.g. server/main.ts)")
        server, ui = self.server.dir, self.ui.dir
        if ui == server or ui.startswith(f"{server}/") or server.startswith(f"{ui}/"):
            raise ValueError("server and ui directories must not overlap")
        return self

    @classmethod
    def from_toml(cls, text: str) -> "MiniAppManifest":
        return cls.model_validate(tomllib.loads(text))

    def added_needs(self, previous: MiniAppNeeds | None) -> list[str]:
        """What this version may reach that `previous` could not: "egress host:port",
        "secret NAME"."""
        previous = previous or MiniAppNeeds()
        files_before = {(f.path, f.mode) for f in previous.files}
        return [
            *(f"egress {e}" for e in sorted(set(self.needs.egress) - set(previous.egress))),
            *(f"secret {n}" for n in sorted(set(self.needs.secrets) - set(previous.secrets))),
            *(
                f"file {f.path} ({f.mode})"
                for f in self.needs.files
                if (f.path, f.mode) not in files_before
            ),
            *(["notifications"] if self.needs.notify and not previous.notify else []),
        ]
