"""Contract H — App (`handler.app/v1`), apps design.

An app's code is a folder written by an agent (with the `app-builder` addon's skill): a manifest
(`app.toml`), a Bun backend in its own directory, a built UI. handler runs it on demand in a
sandbox and serves it at its own origin. The manifest is hand-written TOML: unknown keys are errors.

It says what the app needs in its own words (`needs.files.<name>`, `needs.agents.<name>`): the
person gives each need a folder, an agent, at install (a binding, H.2), never written in the app's
folder, which holds nothing of theirs.
"""

import tomllib
from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from .automation import AutomationAgentInput, Schedule
from .common import AppName, Document, EgressEntry, Resources, StrictDocument

APP_API_VERSION = "handler.app/v1"
MANIFEST_FILE = "app.toml"

# The runtime every app runs on (H.3). Pinned: an app is tested against it when it is deployed.
# The app-builder addon installs the same Bun version for the agents that write apps.
RUNTIME_VERSION = "1.4.2"
RUNTIME_IMAGE = f"docker.io/oven/bun:{RUNTIME_VERSION}-distroless"

# H.3: where things are inside an app's sandbox.
APP_CODE_DIR = "/opt/app"
APP_RUN_DIR = "/run/handler-app"
APP_SOCKET = f"{APP_RUN_DIR}/app.sock"
# handler's side (H.9, H.11), with `needs.notify` or `needs.agents`
APP_API_SOCKET = f"{APP_RUN_DIR}/handler.sock"
APP_HOME = "/home/app"

# H.4: what every backend answers once ready (migrations applied), and the prefix of its routes.
API_PREFIX = "/api/"
HEALTH_PATH = "/api/health"
PERSON_HEADER = "X-HANDLER-Person"
# H.11: on a request of the owner's, what lets the backend start a run while it answers it
START_HEADER = "X-HANDLER-Start"
# H.12: on a call of an action done by its code, which action
ACTION_HEADER = "X-HANDLER-Action"

AppVersion = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")]

# Env vars the platform sets (H.3): a secret may not take their names.
RESERVED_SECRET_PREFIXES = ("HANDLER_", "BUN_")
RESERVED_SECRETS = frozenset({"PATH", "HOME", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "NO_COLOR"})


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


class AppManifestServer(StrictDocument):
    # The backend: its directory (the entry's) is deployed whole, with its vendored dependencies.
    entry: RelativePath = "server/main.ts"

    @property
    def dir(self) -> str:
        return self.entry.rpartition("/")[0]


class AppManifestUi(StrictDocument):
    dir: RelativePath = "ui/dist"  # built static files, with an index.html


# The app's own word for one of its needs (what its code uses): `needs.files.tasks`.
NeedName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,29}$")]


class AppManifestFileNeed(StrictDocument):
    """A folder (or a file) of the person's the backend reads (or writes), H.9: which one is the
    person's choice at install, mounted at the same path."""

    description: str | None = None  # for the person: "where your tasks are kept"
    mode: Literal["ro", "rw"] = "ro"
    # files of the app's folder copied into the folder given, when it has none of that name
    init: Annotated[list[RelativePath], Field(max_length=10)] = []


class AppManifestAgentNeed(StrictDocument):
    """A job the app starts runs of (H.11): which agent is the person's choice at install, one of
    theirs that fits or one set up from the definition the app ships."""

    description: str | None = None  # for the person: "tells you what to do next"
    # its definition: a folder of the app's, in the built-in agents' format (D.18): agent.toml,
    # instructions.md, interface.json (a job's: with a result), skills/
    from_: Annotated[RelativePath, Field(alias="from")]
    works_in: NeedName | None = None  # a `files` need: the agent works in the folder given for it


class AppManifestNeeds(StrictDocument):
    """What the app may reach (H.2). Shown when it is deployed; more than before is flagged."""

    egress: list[EgressEntry] = []  # hosts the backend may reach, through the filtered network
    # env vars whose values the person enters in handler (never in the app's folder): API keys…
    secrets: list[SecretName] = []
    files: Annotated[dict[NeedName, AppManifestFileNeed], Field(max_length=10)] = {}
    notify: bool = False  # it may send notifications (desktop, phones): H.9
    agents: Annotated[dict[NeedName, AppManifestAgentNeed], Field(max_length=10)] = {}  # H.11

    @property
    def handler_api(self) -> bool:
        """It talks to handler on APP_API_SOCKET (H.9, H.11)."""
        return self.notify or bool(self.agents)

    @model_validator(mode="after")
    def _names(self) -> Self:
        if both := sorted(set(self.files) & set(self.agents)):
            raise ValueError(f"a need's name names one need: {', '.join(both)}")
        for name, agent in self.agents.items():
            if agent.works_in is not None and agent.works_in not in self.files:
                raise ValueError(f"agents.{name}.worksIn: no files need {agent.works_in}")
        return self


class AppManifestSuggestedRun(StrictDocument):
    """What a suggested automation runs: the agent given for one of the app's needs."""

    agent: NeedName  # a `needs.agents` need
    input: AutomationAgentInput = AutomationAgentInput()


class AppManifestSuggestedAutomation(StrictDocument):
    """An automation the app suggests (`[[automations]]`, I.1): made by the person from the app's
    page, off until they turn it on; its results open the app."""

    description: Annotated[str, Field(min_length=1)]  # "What to do next, every 5 hours"
    when: Schedule
    run: AppManifestSuggestedRun


# H.12: the app's actions, what the person can ask it in a sentence (Ask's router reads them).
ActionRoute = Annotated[str, Field(pattern=r"^POST /api/[A-Za-z0-9/_.-]*$")]
ActionStatus = Literal["ok", "attention", "failed"]
ActionSentence = Annotated[str, Field(min_length=1, max_length=200)]


class AppManifestAction(StrictDocument):
    """An action: something the person can ask the app in a sentence (H.12), what Ask's router
    reads, what the app's page lists (with Try). Done by its code (`route`: the backend answers an
    ActionResult at once) or by one of its agents (`agent`: a run of the agent given for that need,
    its form filled with the action's fields)."""

    description: ActionSentence  # what it does, for the person and the router: "Add to my calendar"
    examples: Annotated[list[ActionSentence], Field(max_length=5)] = []  # what a person says
    route: ActionRoute | None = None
    agent: NeedName | None = None
    # a route's form: the JSON Schema of an object (as a job's, D.18); an agent's action takes the
    # form of the agent's definition
    fields: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _done_by(self) -> Self:
        if (self.route is None) == (self.agent is None):
            raise ValueError("an action is done by its code (route) or by an agent (agent): one")
        if self.agent is not None and self.fields is not None:
            raise ValueError("fields: an agent's action takes the form of its agent")
        return self


class ActionResult(StrictDocument):
    """What an action gives (H.12): how it went, one or two sentences readable aloud, and what else
    the app wants to show. A route answers it; an agent's run gives it from its result (its
    `status` and `summary`, I.3's rule)."""

    status: ActionStatus
    summary: Annotated[str, Field(min_length=1, max_length=500)]
    data: Any = None


# H.10: a route run later when the host is off (the phone queues it at the gateway).
RouteKey = Annotated[str, Field(pattern=r"^(POST|PUT|PATCH|DELETE) /api/[A-Za-z0-9/_.-]*$")]
RouteKind = Literal["sync", "queued"]


class AppManifest(StrictDocument):
    api_version: Literal["handler.app/v1"]
    name: AppName
    version: AppVersion
    description: str | None = None
    server: AppManifestServer = AppManifestServer()
    ui: AppManifestUi = AppManifestUi()
    needs: AppManifestNeeds = AppManifestNeeds()
    routes: dict[RouteKey, RouteKind] = {}
    automations: Annotated[list[AppManifestSuggestedAutomation], Field(max_length=5)] = []
    actions: Annotated[dict[NeedName, AppManifestAction], Field(max_length=10)] = {}  # H.12
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
        for i, suggested in enumerate(self.automations):
            if suggested.run.agent not in self.needs.agents:
                raise ValueError(
                    f"automations[{i}].run.agent: no agents need {suggested.run.agent}"
                )
        for name, action in self.actions.items():
            if action.agent is not None and action.agent not in self.needs.agents:
                raise ValueError(f"actions.{name}.agent: no agents need {action.agent}")
        return self

    @classmethod
    def from_toml(cls, text: str) -> "AppManifest":
        return cls.model_validate(tomllib.loads(text))

    def added_needs(self, previous: AppManifestNeeds | None) -> list[str]:
        """What this version may reach that `previous` could not: "egress host:port",
        "secret NAME", "file NAME (MODE)", "notifications", "agent NAME"."""
        previous = previous or AppManifestNeeds()
        files_before = {(n, f.mode) for n, f in previous.files.items()}
        return [
            *(f"egress {e}" for e in sorted(set(self.needs.egress) - set(previous.egress))),
            *(f"secret {n}" for n in sorted(set(self.needs.secrets) - set(previous.secrets))),
            *(
                f"file {n} ({f.mode})"
                for n, f in sorted(self.needs.files.items())
                if (n, f.mode) not in files_before
            ),
            *(["notifications"] if self.needs.notify and not previous.notify else []),
            *(f"agent {n}" for n in sorted(set(self.needs.agents) - set(previous.agents))),
        ]


# ── H.11: runs of agents, asked on handler.sock ─────────────────────────────

AppRunState = Literal["waiting", "running", "succeeded", "failed", "cancelled"]


class AppRunRequest(StrictDocument):
    """`POST /runs`: start a run of one of the app's jobs, while answering an owner's request."""

    agent: NeedName  # the need (`needs.agents.<name>`): the agent given for it runs
    fields: dict[str, Any] = {}  # its form (D.18 `SessionInput.fields`)
    start: Annotated[str, Field(min_length=1)]  # the request's START_HEADER


class AppRun(Document):
    """A run the app started (`POST /runs`, `GET /runs/{id}`)."""

    id: str  # "r_" + 16 hex
    agent: str  # the need it was started for
    session_id: str  # its session (F, D.18)
    state: AppRunState
    at: AwareDatetime  # when it was started
    result: Any = None  # succeeded: the job's whole result (D.18)
    error: str | None = None  # failed: why
