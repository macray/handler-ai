"""Contract H — App (`handler.app/v1`), apps design.

An app's code is a folder written by an agent (with the `app-builder` addon's skill): a manifest
(`app.toml`), a Bun backend in its own directory, a built UI. handler runs it on demand in a
sandbox and serves it at its own origin. The manifest is hand-written TOML: unknown keys are errors.

It says what the app needs in its own words (`needs.files.<name>`): the person gives each need a
folder at install (a binding, H.2), never written in the app's folder, which holds nothing of
theirs. Its jobs (`jobs.<name>`, H.1) are the work of it that needs a model: their instructions
(`jobs/<name>.md`), form, result and what each reaches are the app's; who runs them (its Who
works, H.2) is the person's.
"""

import tomllib
from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from .automation import AutomationAgentInput, AutomationName, Schedule
from .common import (
    AppName,
    Document,
    Duration,
    EgressEntry,
    Resources,
    SchemaId,
    StrictDocument,
    duration_minutes,
)

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
# handler's side (H.9, H.11), with `needs.notify`, `jobs`, `nudges` or `schemas`
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
# H.12, H.17: on that call, when it answers a nudge, which one: `<id>` or `<id>; key=<key>`
NUDGE_HEADER = "X-HANDLER-Nudge"
# H.12: on that call, where it was asked: `ask` (Ask's pick, D.24), `nudge`, or `try` (its form
# filled by the person); the same as a job's `startedBy.via`
VIA_HEADER = "X-HANDLER-Via"
# H.17: a nudge's key (`POST /nudge`), carried as is in NUDGE_HEADER: what a header value holds
NudgeKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,100}$")]

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


class AppManifestNeeds(StrictDocument):
    """What the app may reach (H.2). Shown when it is deployed; more than before is flagged."""

    egress: list[EgressEntry] = []  # hosts the backend may reach, through the filtered network
    # env vars whose values the person enters in handler (never in the app's folder): API keys…
    secrets: list[SecretName] = []
    files: Annotated[dict[NeedName, AppManifestFileNeed], Field(max_length=10)] = {}
    notify: bool = False  # it may send notifications (desktop, phones): H.9


# H.12: the app's actions, what the person can ask it in a sentence (Ask's router reads them).
ActionRoute = Annotated[str, Field(pattern=r"^POST /api/[A-Za-z0-9/_.-]*$")]
ActionStatus = Literal["ok", "attention", "failed"]
ActionSentence = Annotated[str, Field(min_length=1, max_length=200)]


JobAccess = Literal["read", "write"]  # a job's files need: mounted read-only, or read-write
MAX_JOB_TIMEOUT_MINUTES = 24 * 60
JOB_INSTRUCTIONS_DIR = "jobs"  # in an app's folder: `<name>.md` for each of its jobs


class AppManifestJob(StrictDocument):
    """A job (H.1): work of the app's that needs a model, run by the Who works the person chose
    for the app. Its instructions are `jobs/<name>.md` of the app's folder; what it reaches (its
    folders and their access, its schemas, its hosts) is declared here, said before a deploy that
    adds to it."""

    description: ActionSentence  # "Writes a CV for a job ad"
    # files needs of the app's: read (a read-only mount) or write (the need given `rw`)
    files: Annotated[dict[NeedName, JobAccess], Field(max_length=10)] = {}
    works_in: list[NeedName] = []  # the folders it works in, among its `files`
    schemas: Annotated[list[SchemaId], Field(max_length=10)] = []  # among the app's `schemas`
    egress: list[EgressEntry] = []  # hosts it may reach, through the filtered network
    # its form: the JSON Schema of an object (D.18's `fields`); none: it takes nothing
    fields: dict[str, Any] | None = None
    # what its final message gives back (D.18's `result`), with a required `status` and `summary`
    result: dict[str, Any]
    timeout: Duration | None = None  # each turn, at most "1d"; none: D.18's default
    # a route of the app's, called once when one of its runs ends (as the owner, no start token)
    then: ActionRoute | None = None

    @property
    def timeout_sec(self) -> int | None:
        return None if self.timeout is None else duration_minutes(self.timeout) * 60

    @model_validator(mode="after")
    def _own(self) -> Self:
        if outside := [n for n in self.works_in if n not in self.files]:
            raise ValueError(f"worksIn: {outside[0]} is not one of its files")
        if len(set(self.works_in)) != len(self.works_in):
            raise ValueError("worksIn: a folder named twice")
        if len(set(self.schemas)) != len(self.schemas):
            raise ValueError("schemas: a schema named twice")
        if self.timeout is not None and duration_minutes(self.timeout) > MAX_JOB_TIMEOUT_MINUTES:
            raise ValueError("timeout: at most 1d")
        return self

    def reach(self) -> set[str]:
        """What it reaches, as `added_needs` says it: "file NEED (read)", "schema ID", "egress
        host:port"."""
        return {
            *(f"file {n} ({a})" for n, a in self.files.items()),
            *(f"schema {i}" for i in self.schemas),
            *(f"egress {e}" for e in self.egress),
        }


class AppManifestSuggestedRun(StrictDocument):
    """What a suggested automation runs: one of the app's jobs (`job`, with its `input`), or one
    of its routes (`call`, as a person's automation calls it: `run = { app, call }`, I.3)."""

    job: NeedName | None = None  # one of its `jobs`
    input: AutomationAgentInput = AutomationAgentInput()
    call: ActionRoute | None = None  # "POST /api/archive": its code, no model

    @model_validator(mode="after")
    def _one(self) -> Self:
        if (self.job is None) == (self.call is None):
            raise ValueError(
                "a suggested automation runs one of its jobs (job) or calls a route (call): one"
            )
        if self.call is not None and "input" in self.model_fields_set:
            raise ValueError("input: a job's, not a call's")
        return self


class AppManifestSuggestedAutomation(StrictDocument):
    """An automation the app suggests (`[[automations]]`, I.1): installed with the app, made and
    turned on at Install unless the person switches it off there (`optional`: off unless they
    switch it on; the CLI asks for each); later made from the app's page, off; its results open
    the app."""

    description: Annotated[str, Field(min_length=1)]  # "What to do next, every 5 hours"
    when: Schedule
    run: AppManifestSuggestedRun
    optional: bool = False  # off at Install unless the person turns it on


class AppManifestAction(StrictDocument):
    """An action: something the person can ask the app in a sentence (H.12), what Ask's router
    reads, what the app's page lists (with Try). Done by its code (`route`: the backend answers an
    ActionResult at once) or by one of its jobs (`job`: a run of it, its form the job's)."""

    description: ActionSentence  # what it does, for the person and the router: "Add to my calendar"
    examples: Annotated[list[ActionSentence], Field(max_length=5)] = []  # what a person says
    route: ActionRoute | None = None
    job: NeedName | None = None
    # a route's form: the JSON Schema of an object (as a job's, D.18); a job's action takes the
    # job's `fields`
    fields: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _done_by(self) -> Self:
        if (self.route is None) == (self.job is None):
            raise ValueError("an action is done by its code (route) or a job (job): one")
        if self.job is not None and self.fields is not None:
            raise ValueError("fields: a job's action takes the form of its job")
        return self


def _own_path(p: str) -> str:
    if p.startswith("//"):
        raise ValueError("a path of the app's own (`//` would name another site)")
    return p


# a page of the app's own UI, opened by Handler: a nudge's (H.17), what an action did (H.12)
AppPage = Annotated[
    str,
    Field(pattern=r"^/[A-Za-z0-9/_.~%-]*(\?[A-Za-z0-9=&_.~%-]*)?$", max_length=200),
    AfterValidator(_own_path),
]


class ActionResult(StrictDocument):
    """What an action gives (H.12): how it went, one or two sentences readable aloud, and what else
    the app wants to show. A route answers it; a job's run gives it from its result (its
    `status` and `summary`, I.3's rule)."""

    status: ActionStatus
    summary: Annotated[str, Field(min_length=1, max_length=500)]
    data: Any = None
    open: AppPage | None = None  # "/?line=…": the page of its UI showing what it did


# H.17: the app's nudges, what it asks a person to do (an action's form, or a page of its UI).
MIN_REMIND_MINUTES = 30


class AppManifestNudgeRemind(StrictDocument):
    """How often an open nudge alerts again, by default (the person tones it per nudge, H.17):
    every `every`, `times` times after its first alert."""

    every: Duration  # "30m", "2h", "1d"
    times: Annotated[int, Field(ge=1, le=5)] = 1

    @property
    def every_minutes(self) -> int:
        return duration_minutes(self.every)

    @model_validator(mode="after")
    def _often(self) -> Self:
        if self.every_minutes < MIN_REMIND_MINUTES:
            raise ValueError(f"every: at least {MIN_REMIND_MINUTES}m")
        return self


class AppManifestNudge(StrictDocument):
    """A nudge (H.17): something the app asks a person to do, under a name that stays the same
    from one to the next (`daily-log`). A click opens one of its actions' form (`action`) or a
    page of its UI (`open`): the manifest's, never the call's."""

    description: ActionSentence  # for the person: "Add what you did today"
    action: NeedName | None = None  # one of its `actions`
    open: AppPage | None = None  # "/log": a page of its UI
    remind: AppManifestNudgeRemind | None = None  # none: alerted once
    if_ignored: ActionSentence | None = None  # what happens when it expires unanswered
    # when handlerd sends it (the app's proposal; the person's own replaces it); none: its code
    # sends it (`POST /nudge` on handler.sock)
    when: Schedule | None = None
    # with `when`: called at each slot as the owner, with no start token; answers PreparedNudge,
    # a list of them, or 204 (none this time). None: sent with `description` as its title
    prepare: ActionRoute | None = None
    # with `when`: "next", its open ones expire when its next slot comes (a skipped week's does
    # not stay beside the next week's); none: open until done, dismissed or its call's `until`
    until: Literal["next"] | None = None

    @model_validator(mode="after")
    def _target(self) -> Self:
        if (self.action is None) == (self.open is None):
            raise ValueError("a nudge opens an action's form (action) or a page (open): one")
        if self.prepare is not None and self.when is None:
            raise ValueError("prepare: called at the nudge's `when`, which it lacks")
        if self.until is not None and self.when is None:
            raise ValueError("until: its next slot, of a `when` it lacks")
        return self


class PreparedNudge(StrictDocument):
    """What a nudge's `prepare` route answers at one of its slots (H.17): the nudge to send, its
    key the slot's (`2026-W47`, `2026-11-16`) unless it gives one. A list of them: several of its
    name, each with its own key."""

    title: Annotated[str, Field(min_length=1, max_length=120)]
    body: Annotated[str, Field(max_length=1000)] | None = None
    fields: dict[str, Any] | None = None  # its action's form, filled in
    key: NudgeKey | None = None


# H.10: a route run later when the host is off (the phone queues it at the gateway).
RouteKey = Annotated[str, Field(pattern=r"^(POST|PUT|PATCH|DELETE) /api/[A-Za-z0-9/_.-]*$")]
RouteKind = Literal["sync", "queued"]


class AppManifest(StrictDocument):
    api_version: Literal["handler.app/v1"]
    name: AppName
    # what the person sees it called ("Planner"); none: its name. Its name stays its id (its
    # address, its folder in Handler)
    title: Annotated[str, Field(min_length=1, max_length=60)] | None = None
    version: AppVersion
    description: str | None = None
    # what this version changes, for whoever updates to it ("Import a LinkedIn profile from its
    # link; CVs in two columns"): its page says it before Update (H.6)
    changes: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    server: AppManifestServer = AppManifestServer()
    ui: AppManifestUi = AppManifestUi()
    needs: AppManifestNeeds = AppManifestNeeds()
    routes: dict[RouteKey, RouteKind] = {}
    automations: Annotated[list[AppManifestSuggestedAutomation], Field(max_length=5)] = []
    actions: Annotated[dict[NeedName, AppManifestAction], Field(max_length=10)] = {}  # H.12
    jobs: Annotated[dict[NeedName, AppManifestJob], Field(max_length=10)] = {}  # H.1
    nudges: Annotated[dict[NeedName, AppManifestNudge], Field(max_length=10)] = {}  # H.17
    resources: Resources | None = None  # default: 512 MiB
    # the formats it reads and writes (structured markdown, D.29), each `$id` the file
    # `schemas/<$id>.schema.json` of its folder: into the Library at deploy; its code reads and
    # writes their documents in the folders given to it through handler.sock (H.9)
    schemas: Annotated[list[SchemaId], Field(max_length=10)] = []

    @property
    def handler_api(self) -> bool:
        """It talks to handler on APP_API_SOCKET (H.9, H.11, H.17); a read-write files need: its
        history (H.9)."""
        written = any(f.mode == "rw" for f in self.needs.files.values())
        return (
            self.needs.notify
            or bool(self.jobs)
            or bool(self.nudges)
            or bool(self.schemas)
            or written
        )

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
        for name, nudge in self.nudges.items():
            if nudge.action is not None and nudge.action not in self.actions:
                raise ValueError(f"nudges.{name}.action: no action {nudge.action}")
        if len(set(self.schemas)) != len(self.schemas):
            raise ValueError("schemas: a schema named twice")
        return self

    @model_validator(mode="after")
    def _jobs(self) -> Self:
        """Its jobs reach only its own: files needs it declares (written only when given `rw`),
        schemas it ships; its actions and suggested automations name jobs it has."""
        for name, job in self.jobs.items():
            for need, access in job.files.items():
                wanted = self.needs.files.get(need)
                if wanted is None:
                    raise ValueError(f"jobs.{name}.files: no files need {need}")
                if access == "write" and wanted.mode != "rw":
                    raise ValueError(f"jobs.{name}.files.{need}: write, but the need is ro")
            if unknown := [i for i in job.schemas if i not in self.schemas]:
                raise ValueError(f"jobs.{name}.schemas: {unknown[0]} is not in the app's schemas")
        for name, action in self.actions.items():
            if action.job is not None and action.job not in self.jobs:
                raise ValueError(f"actions.{name}.job: no job {action.job}")
        for i, suggested in enumerate(self.automations):
            if suggested.run.job is not None and suggested.run.job not in self.jobs:
                raise ValueError(f"automations[{i}].run.job: no job {suggested.run.job}")
        return self

    @classmethod
    def from_toml(cls, text: str) -> "AppManifest":
        return cls.model_validate(tomllib.loads(text))

    def added_needs(self, installed: "AppManifest | None") -> list[str]:
        """What this version may reach that the `installed` one could not: "egress host:port",
        "secret NAME", "file NAME (MODE)", "notifications", "job NAME", and what a
        job reaches: "job NAME: file NEED (read|write)", "job NAME: schema ID", "job NAME: egress
        host:port"."""
        previous = installed.needs if installed else AppManifestNeeds()
        jobs_before = installed.jobs if installed else {}
        files_before = {(n, f.mode) for n, f in previous.files.items()}
        added = [
            *(f"egress {e}" for e in sorted(set(self.needs.egress) - set(previous.egress))),
            *(f"secret {n}" for n in sorted(set(self.needs.secrets) - set(previous.secrets))),
            *(
                f"file {n} ({f.mode})"
                for n, f in sorted(self.needs.files.items())
                if (n, f.mode) not in files_before
            ),
            *(["notifications"] if self.needs.notify and not previous.notify else []),
        ]
        for name, job in sorted(self.jobs.items()):
            before = jobs_before.get(name)
            if before is None:
                added.append(f"job {name}")
            reach = job.reach() - (before.reach() if before else set())
            added += [f"job {name}: {r}" for r in sorted(reach)]
        return added


# ── H.11: runs of its jobs, asked on handler.sock ───────────────────────────

AppRunState = Literal["waiting", "running", "succeeded", "failed", "cancelled"]


class AppRunRequest(StrictDocument):
    """`POST /runs`: start a run of one of the app's jobs (H.1), while answering an owner's
    request."""

    job: NeedName  # one of its jobs: run by its Who works (H.2)
    fields: dict[str, Any] = {}  # its form (D.18 `SessionInput.fields`)
    start: Annotated[str, Field(min_length=1)]  # the request's START_HEADER


class StartedByCode(Document):
    """A run the app's code started (`POST /runs`, while answering the owner)."""

    by: Literal["code"] = "code"


class StartedByAction(Document):
    """A run one of the app's actions started (H.12), and how the person asked it: Ask's pick
    (D.24), its form filled on the app's page or on a phone ("try"), or a nudge (H.17)."""

    by: Literal["action"] = "action"
    action: NeedName
    via: Literal["ask", "try", "nudge"]


class StartedByAutomation(Document):
    """A run an automation started (I.3): one the app suggested, or one of yours."""

    by: Literal["automation"] = "automation"
    automation: AutomationName


AppRunStartedBy = Annotated[
    StartedByCode | StartedByAction | StartedByAutomation, Field(discriminator="by")
]


class AppRun(Document):
    """A run of one of the app's jobs (`POST /runs`, `GET /runs`, `GET /runs/{id}`)."""

    id: str  # "r_" + 16 hex
    job: NeedName  # the job it runs
    started_by: AppRunStartedBy  # what started it
    # what it was asked: the fields its run was given (its code's `POST /runs`, an action's
    # form, an automation's input)
    fields: dict[str, Any]
    session_id: str  # its session (F, D.18)
    state: AppRunState
    at: AwareDatetime  # when it was started
    ended_at: AwareDatetime | None = None  # once it ended: when (its session's last activity)
    result: Any = None  # succeeded: the job's whole result (D.18)
    error: str | None = None  # failed: why
    # its job's `then` route, called once when it ended (H.11), failed: why (no answer, an
    # error, not called because handlerd stopped meanwhile); never retried
    then_error: str | None = None
