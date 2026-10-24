"""Contract D — Control API (`handler.control/v1`)."""

from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .addon import AddonName, BindingName, SlotName
from .agent_spec import HarnessName
from .app import (
    ActionResult,
    AppManifest,
    AppManifestNeeds,
    AppManifestSuggestedAutomation,
    AppName,
    NeedName,
)
from .automation import AudioFormat, LlmModel
from .common import (
    AbsolutePath,
    AccessArea,
    AreaColor,
    AreaName,
    CacheSharing,
    CommandSecret,
    Confinement,
    Document,
    EgressEntry,
    Enforcement,
    EnvSecret,
    FileSecret,
    FileSource,
    HostPath,
    MountKind,
    NetworkMode,
    PermissionMode,
    ResourceName,
    SecretPath,
    StrictDocument,
)
from .harness import CacheDeclaration, CacheName, LoginRecipe
from .provider import Endpoint, Protocol, ProviderModel

CONTROL_API_VERSION = "handler.control/v1"
CONTROL_BASE_PATH = "/v1"

# Discovery convention shared by the daemon and its clients:
# the daemon listens on 127.0.0.1:$HANDLER_PORT and its token is in $HANDLER_CONFIG_DIR/token
# (default ~/.config/handler-ai/token, mode 0600).
DEFAULT_PORT = 7430
TOKEN_FILE_NAME = "token"

Timestamp = AwareDatetime
SecretValue = Annotated[str, Field(min_length=1, max_length=16384, pattern=r"^[^\n\r]*$")]
# where a secret comes from: handler's secret store, or a reference the person wrote (E2)
SecretKind = Literal["secret", "env", "file", "command"]
NonEmpty = Annotated[str, Field(min_length=1)]
# a folder of the knowledge root (HANDLER_KNOWLEDGE_DIR), as a path relative to it; "." is the root
KnowledgeFolder = Annotated[str, Field(min_length=1, max_length=1024, pattern=r"^[^/\x00]")]


class HarnessInfo(Document):
    name: str
    product: str  # its product name ("Claude Code"): what the UI shows (B.1)
    image: str  # the repository; agents launch its ':latest'
    image_present: bool
    version: str | None = None  # what the image installed (B.6), e.g. "Claude Code 2.1.280 (…)"
    built_at: Timestamp | None = None
    provider_protocols: list[Protocol] = []  # the providers it can use; empty: accounts only
    login: LoginRecipe | None = None  # how an account of it is made; none: providers only
    login_file: str | None = None  # a file login's: the file name it leaves in `{dir}`
    permissions: list[PermissionMode] = []  # the permission modes it offers
    # the ACP session mode each permission mode is, when it is one: how a session's mode
    # selector names the harness's modes as handler does
    session_modes: dict[PermissionMode, str] = {}
    account_connectors: bool = False  # its accounts may use their own connectors (B.1)


class ToolboxInfo(Document):
    image: str
    image_present: bool
    built_at: Timestamp | None = None
    directory: str  # the user's toolbox folder: Containerfile, toolbox.toml (B.6)


class NetworkFilterInfo(Document):
    """The network filter (D.4): the egress proxy's image (A.3, A.7), part of handler. Agents and
    apps with a network allow-list or a secret need it; handlerd builds it when it is missing."""

    image: str  # its reference, e.g. "localhost/handler-ai-proxy:2"
    image_present: bool
    built_at: Timestamp | None = None


UpdateSchedule = Literal["off", "daily", "weekly"]


class ImageUpdates(Document):
    """Automatic image updates (D.4): the network filter and every built harness and addon image
    rebuilt, checked and switched only if it passes, on a schedule and after a handler upgrade. Not
    the toolbox."""

    schedule: UpdateSchedule
    running: bool = False
    last_run: Timestamp | None = None
    next_run: Timestamp | None = None  # None: off, or now (after an upgrade)
    last_failed: list[str] = []  # the targets whose rebuild failed in the last run


class ImageUpdatesRequest(Document):
    schedule: UpdateSchedule


MAX_CONTAINERFILE_BYTES = 256 * 1024


class ToolboxContainerfile(Document):
    """The user's toolbox Containerfile (B.6, D.4), and the default it was copied from."""

    content: str
    default_content: str


class ToolboxContainerfileUpdate(Document):
    """A new toolbox Containerfile; used by the next toolbox rebuild."""

    content: Annotated[str, Field(min_length=1, max_length=MAX_CONTAINERFILE_BYTES)]


class CacheInfo(Document):
    """A cache the toolbox declares (B.6), as Settings → Caches shows it (D.8)."""

    name: str
    target: str  # where agents find it: a home path ("~/.cargo")
    about: str = ""  # what it holds
    general: bool = False  # a folder any tool writes to (~/.cache), not one tool's


class CacheFolders(Document):
    """Where the caches are kept (D.8): a folder holding one folder per cache."""

    folder: str
    caches: dict[str, str]  # cache name → its folder, in the toolbox's order
    removed: dict[str, str] = {}  # what caches no longer declared left there: name → folder


class GlobalCachesInfo(CacheFolders):
    """The global caches: the projects that chose them and agents outside projects use them."""

    projects: list[str] = []  # the names of the projects using them


class ProjectCachesInfo(CacheFolders):
    """A project's own caches, removed with it."""

    project_id: str
    name: str


class CachesInfo(Document):
    """GET and PUT /v1/caches (D.8): what is kept, the toolbox's caches in its order; and where:
    the global folders, each project's own, and the projects without caches (`off`)."""

    caches: list[CacheInfo]
    global_: GlobalCachesInfo = Field(alias="global")
    own: list[ProjectCachesInfo] = []
    off: list[str] = []


class CachesRequest(Document):
    """PUT /v1/caches: the toolbox's caches by name, written to its toolbox.toml (B.6). Applies
    to new sessions."""

    caches: dict[CacheName, CacheDeclaration]


class CacheSizes(Document):
    """GET /v1/caches/sizes: bytes on disk of each folder of CachesInfo (0: not made yet)."""

    sizes: dict[str, int]


class AddonSlotInfo(Document):
    """A setting or secret slot of an addon (G.1), for the binding form."""

    name: str
    required: bool = False
    description: str | None = None


class AddonInfo(Document):
    """An addon (G.1) and, when it has a tool, its image (G.4)."""

    name: str
    description: str | None = None
    image: str | None = None  # the repository; agents mount its ':latest'. None: no tool
    image_present: bool = False
    version: str | None = None  # what the image installed (G.4)
    built_at: Timestamp | None = None
    commands: list[str] = []
    skills: list[str] = []
    settings: list[AddonSlotInfo] = []  # setting slots a binding may fill
    secret_slots: list[AddonSlotInfo] = []
    egress: list[str] = []  # what its bindings' agents reach (its secrets' hosts)
    error: str | None = None  # present when the addon's files are invalid
    directory: str  # where it is loaded from (G.1)
    builtin: bool = False  # shipped with handler; else the user's
    overrides_builtin: bool = False  # the user's, named as a built-in addon it replaces
    # installed from (G.5): "source:<source>/<name>" (D.26), a folder, an archive URL
    source: str | None = None
    update_available: bool = False  # installed from a source, which now holds other content


AddonSource = Annotated[str, Field(min_length=1, max_length=2048)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AddonPreview(Document):
    """What installing from `source` would add (G.5), shown before the user decides; `digest`
    names exactly this content: an install of other content is refused."""

    source: str
    digest: Digest
    name: str
    description: str | None = None
    image: str | None = None  # its Containerfile runs code when the image is built
    commands: list[str] = []
    env: list[str] = []  # the variables it sets in agents' sandboxes
    settings: list[AddonSlotInfo] = []
    secret_slots: list[AddonSlotInfo] = []
    egress: list[str] = []  # hosts its agents may reach
    mcp: list[str] | None = None  # the MCP server it gives every session (P8)
    skills: list[str] = []
    replaces: Literal["builtin", "installed", "own"] | None = None  # what has that name now


class AddonPreviewRequest(Document):
    """A source to look at (G.5): "source:<source>/<name>" (an addon of a source, D.26), an
    absolute folder path, an https:// URL of a .tar.gz archive."""

    source: AddonSource


class AddonInstallRequest(Document):
    source: AddonSource
    digest: Digest  # from the preview


class BindingInfo(Document):
    """A binding (G.2): never its secret references' targets, only the slot names."""

    name: str
    addon: str | None = None
    description: str | None = None
    settings: dict[str, str] = {}
    secrets: list[str] = []  # bound secret slots
    # the bound secret slots whose reference is hand-written (env, file, command): kept by the API
    hand_written: list[str] = []
    error: str | None = None  # present when the binding is invalid (it cannot be selected)
    used_by: list[str] = []  # "agents/<project>/<agent>", "ad-hoc/<agent id>"


class BindingRequest(Document):
    """Create a binding, or replace one (and rename it). Secret values go to the secret store
    (`bindings/<name>/<slot>`); a slot left out of `secrets` keeps what it has, unless it is in
    `removeSecrets`."""

    name: BindingName
    addon: AddonName
    description: str | None = None
    settings: dict[SlotName, Annotated[str, Field(min_length=1)]] = {}
    secrets: dict[SlotName, SecretValue] = {}
    remove_secrets: list[SlotName] = []


# a skill's name (agentskills.io): its folder's name and its SKILL.md's `name`
SkillName = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
MAX_SKILL_BYTES = 256 * 1024
MAX_SKILL_FILE_BYTES = 5 * 1024 * 1024  # one file of a skill
MAX_SKILL_ARCHIVE_BYTES = 20 * 1024 * 1024  # an imported archive, and what it unpacks to


class SkillFile(Document):
    """A file of a skill (D.17), relative to its folder. `text` when one file is read and it is
    UTF-8 text; absent: binary (or a listing)."""

    path: str
    size: int
    executable: bool = False
    text: str | None = None


class SkillFileRequest(Document):
    """Write a file of a skill: `text`, or `base64` for any content (an upload)."""

    text: Annotated[str, Field(max_length=MAX_SKILL_FILE_BYTES)] | None = None
    base64: Annotated[str, Field(max_length=MAX_SKILL_FILE_BYTES * 4 // 3 + 4)] | None = None
    executable: bool = False  # a script the agent runs

    @model_validator(mode="after")
    def _one_content(self) -> Self:
        if (self.text is None) == (self.base64 is None):
            raise ValueError("a file is either text or base64")
        return self


class ScanHit(Document):
    """Something the scan found at a line of a skill's file (D.17)."""

    path: str  # relative to the skill's folder
    line: int
    text: str  # what: a host, the line with its hidden characters shown, the start of a blob


class SkillScan(Document):
    """What handlerd finds in a skill's files, no model involved (D.17)."""

    executables: list[str] = []  # paths
    binaries: list[str] = []  # files that are not UTF-8 text
    hosts: list[ScanHit] = []  # URLs in its text, by host
    hidden_text: list[ScanHit] = []  # invisible or bidirectional Unicode
    blobs: list[ScanHit] = []  # long base64 or hex runs


class SkillInfo(Document):
    """A skill of the library (D.17): a folder with a SKILL.md and any other files, offered to
    every agent. Projects may give it to all their agents; other agents pick it. `content` (its
    SKILL.md), `digest` and `scan` only when one skill is read."""

    name: str
    description: str | None = None
    projects: list[str] = []  # the projects that give it to all their agents (ids)
    files: list[SkillFile] = []  # the folder's other files (without their text)
    error: str | None = None  # present when the skill is invalid (no agent can use it)
    used_by: list[str] = []  # "agents/<project>/<agent>", "ad-hoc/<agent>"
    content: str | None = None
    digest: str | None = None  # "sha256:…" of its files: what a review saw (D.18)
    scan: SkillScan | None = None


class SkillRequest(Document):
    """Create a skill, or replace its SKILL.md (its other files stay). The name is the SKILL.md's
    `name`: a different one renames the skill, and its agents follow. The projects that give it
    to all their agents are listed in full: their agents that picked it get it from them."""

    content: Annotated[str, Field(min_length=1, max_length=MAX_SKILL_BYTES)]
    projects: list[str] = []  # the projects (ids) that give it to all their agents


class CreateSkillRequest(SkillRequest):
    """A new skill; `copy_of`: another skill whose other files it starts with (its own SKILL.md
    is `content`), to change a skill for some agents and not for the others."""

    copy_of: SkillName | None = None


class SkillUrlRequest(Document):
    """Import a skill from a URL (D.17): a folder of a GitHub repository
    (`https://github.com/<owner>/<repo>/tree/<ref>/<folder>`, a `…/blob/<ref>/<folder>/SKILL.md`,
    or the repository itself), or an https:// zip archive of one skill (a `.skill`, a `.zip`)."""

    url: Annotated[str, Field(min_length=1, max_length=2048, pattern=r"^https://")]


# a harness, "toolbox", "network-filter", or "addon:<name>"
BuildTarget = Annotated[str, Field(pattern=r"^(addon:)?[a-z0-9][a-z0-9-]*$")]
BuildState = Literal["running", "succeeded", "failed", "cancelled"]


class Build(Document):
    """An image rebuild (D.4): build from the files on disk, check it, tag it ':latest'."""

    id: str
    target: BuildTarget
    state: BuildState
    stage: str | None = None  # what is happening now, e.g. "build claude-code"
    step: int | None = None  # podman's "STEP n/m" of the current image build
    steps: int | None = None
    versions: dict[str, str] = {}  # harness → version it installed (B.6), once known
    warnings: list[str] = []  # what works but should be fixed: a toolbox without what Handler needs
    error: str | None = None
    started_at: Timestamp
    ended_at: Timestamp | None = None


class AddonInstalled(Document):
    addon: AddonInfo
    build: Build | None = None  # its image's first build (G.4), when it has one


class BuildLog(Document):
    """A slice of a build's log, from byte `offset`; ask again from `next_offset` for more."""

    text: str
    next_offset: int
    complete: bool  # the build has ended and nothing more will be written


AccountStatus = Literal["ready", "incomplete", "invalid"]


class AccountInfo(Document):
    """An account (E, D.9): a subscription one harness logs in with."""

    name: str
    harness: str | None = None  # None when the file is invalid
    description: str | None = None
    plan: str | None = None  # its subscription's plan, as the account file says (not checked)
    login: Literal["token", "file"] | None = None  # its harness's kind of login
    # a token login: where its token comes from (handler's secret store, or a reference: never
    # shown)
    token: SecretKind | None = None
    # when handler was given its login (a token in its store, or the file a file login left); None
    # for a token by reference (handler does not know when it was made)
    logged_in_at: Timestamp | None = None
    # a token in handler's store: when it stops working (`loggedInAt` + its harness's
    # `tokenLifetimeDays`), if its harness says
    expires_at: Timestamp | None = None
    hosts: list[str] = []  # what its agents' sessions reach for it (the harness's login hosts)
    # ready: logged in; incomplete: `problems` says what is missing (not logged in yet, a token
    # past `expiresAt`); invalid: `error`
    status: AccountStatus
    problems: list[str] = []
    error: str | None = None
    connectors: bool = False  # its harness may use the account's own connectors (E)
    areas: list[str] = []  # the areas it may be used in, or `any` (D.19)
    agents: list[str] = []  # the agents that use it: "<project> · <agent>", or an ad-hoc one's name
    sessions: int = 0  # sessions on it (as kept by the daemon)
    last_used_at: Timestamp | None = None  # the last activity of one of those sessions


class AccountRequest(Document):
    """Create an account, or rename it and change its description, plan and connectors (not its
    harness)."""

    name: ResourceName
    harness: Annotated[str, Field(min_length=1)]
    description: str | None = None
    plan: Annotated[str, Field(min_length=1)] | None = None  # one of its harness's login plans
    connectors: bool = False  # its harness may use the account's connectors (B.1 accountConnectors)
    areas: list[AccessArea] = []  # the areas it may be used in, or `any` (D.19)


class LoginWindow(Document):
    """The terminal window handlerd opened for a file login (D.9): its harness's login runs in
    it."""

    terminal: str  # its name, e.g. "kgx"
    command: str  # what runs in it: `handler account login <name> --keep-open`


class AccountLoginRequest(Document):
    """An account's login (D.9). A token login: the token the person's own sign-in printed
    (`token`, kept in handler's secret store), or where they keep it (`tokenRef`: an env var, a
    file, a command). A file login: the content of the credential file its login left (`file`)."""

    token: SecretValue | None = None
    token_ref: EnvSecret | FileSecret | CommandSecret | None = None
    file: Annotated[str, Field(min_length=1, max_length=65536)] | None = None

    @model_validator(mode="after")
    def _one(self) -> Self:
        if sum(x is not None for x in (self.token, self.token_ref, self.file)) != 1:
            raise ValueError("give exactly one of 'token', 'tokenRef' and 'file'")
        return self


class WorkFolders(Document):
    """The folders agents may work in (D.13): a project's folder or an ad-hoc session's must be
    inside one. Absolute paths, or `~/…`, as written; handler's own folders are always refused."""

    roots: Annotated[list[NonEmpty], Field(min_length=1)]


class WorkFolderInfo(Document):
    """A work folder (D.13) as Settings shows it: as written, where that is, whether it exists,
    and the projects whose folder is inside it."""

    root: str  # as written (absolute, or `~/…`)
    path: str  # `~` expanded, links resolved
    exists: bool
    projects: list[str] = []  # their names


class WorkFoldersInfo(Document):
    """GET and PUT /v1/folders (D.13): the work folders, in their order."""

    folders: list[WorkFolderInfo]


class ProviderInfo(Document):
    """A provider (E, D.12): where model calls go."""

    name: str
    description: str | None = None
    endpoints: dict[Protocol, str] = {}  # the URL for each protocol it speaks
    models: list[ProviderModel] = []
    # where its key comes from: handler's secret store, or a hand-written reference (never shown)
    key: SecretKind | None = None
    # ready: its key, if it has one, is set; incomplete: `problems` says what is missing;
    # invalid: `error`
    status: AccountStatus
    problems: list[str] = []
    error: str | None = None
    agents: list[str] = []  # the agents that use it, as AccountInfo's
    harnesses: list[str] = []  # the harnesses that accept its protocol
    model_alone: bool = (
        False  # it speaks a protocol handlerd calls: the model alone runs on it (D.18)
    )
    files: list[str] = []  # the harnesses it has config files for (hand-written, E)
    areas: list[str] = []  # the areas it may be used in, or `any` (D.19)


class ProviderTemplate(Document):
    """A starting point for a provider (templates/providers/, D.12)."""

    name: str
    description: str | None = None
    endpoints: dict[Protocol, str]
    models: list[ProviderModel]
    needs_key: bool = False  # a hosted API: ask for its key
    files: dict[str, dict[str, FileSource]] | None = None  # E: how one harness talks to it


class ProviderRequest(Document):
    """Create a provider, or replace one (and rename it). Its key goes to the secret store
    (`providers/<name>/apiKey`); without `key`, the one it has is kept. Without `files`, the
    harnesses' config files it has are kept (a template's are given when it is created)."""

    name: ResourceName
    description: str | None = None
    endpoints: Annotated[dict[Protocol, Endpoint], Field(min_length=1)]
    models: Annotated[list[ProviderModel], Field(min_length=1)]
    key: SecretValue | None = None
    remove_key: bool = False
    files: dict[str, dict[str, FileSource]] | None = None  # E: per harness, config file slots
    areas: list[AccessArea] = []  # the areas it may be used in, or `any` (D.19)


class ModelAccess(Document):
    """What an agent runs as (E): a harness and the account or the provider its model calls use
    (exactly one), and the model. An agent has one (D.1); a session runs with it or another picked
    for that session (D.19). An agent on the model alone (D.18) has no harness: a provider only
    (AgentSettings checks it)."""

    harness: HarnessName | None = None  # an account's by default; required with a provider
    account: ResourceName | None = None
    provider: ResourceName | None = None
    model: Annotated[str, Field(min_length=1)] | None = None  # default: the harness's or provider's

    @model_validator(mode="after")
    def _account_or_provider(self) -> Self:
        if (self.account is None) == (self.provider is None):
            raise ValueError("name exactly one of 'account' and 'provider'")
        return self


# a JSON Schema (draft 2020-12), checked by handlerd; at most this many bytes as JSON
JsonSchema = dict[str, Any]
MAX_SCHEMA_BYTES = 64 * 1024
SUBJECT_ROOT = "/subject"  # where a run's subject is mounted, read-only: /subject/<name>
SKILL_FIELD = "skill"  # "x-handler" of the form's field naming a skill to work on (D.18)
RUN_TIMEOUT_SEC = 1800  # a job's turn when its interface says none (D.18)


class AgentInterface(Document):
    """How a session of an agent starts and ends (D.18): a form (one of its fields may name a
    skill of the library to work on, its subject), and maybe the result its final message holds.
    With a result, a job: each run is unattended, so in permission mode `bypass` (no one is there
    to answer its requests). Without, a brief: the form starts a session you then work in."""

    # an object schema: the form filled to start a session; a string property marked
    # "x-handler": "skill" (one at most) names a skill, mounted read-only at /subject/<name>
    fields: JsonSchema | None = None
    result: JsonSchema | None = None  # a job's: what its final message gives back
    # a job's: each turn (none: RUN_TIMEOUT_SEC); a brief has none
    timeout_sec: Annotated[int, Field(gt=0, le=86_400)] | None = None


class AgentDefinition(Document):
    """What an agent set up from it starts with (D.18): everything but what it runs as and where
    it works, its defaults; `skills` come with it, installed in the library when it is set up.
    An agents file's agents are definitions (D.23), and so are an app's (H.2, `needs.agents`)
    and those Handler ships for its needs (D.18)."""

    agent_name: str
    agent_description: str | None = None
    instructions: str | None = None
    network: NetworkMode = "filtered"
    egress: Enforcement = "enforce"
    allow: list[EgressEntry] = []
    confinement: Confinement = "strict"
    permissions: PermissionMode = "bypass"
    skills: list[SkillName] = []
    interface: AgentInterface | None = None
    # addons its agent needs a configuration of (G.2): the set-up page selects one of each
    addons: list[AddonName] = []
    # knowledge folders it reads (D.5), by their names: the set-up page selects one for each
    knowledge: list[KnowledgeFolder] = []
    display: bool = False  # its sandboxes get the host's Wayland display (A.6)
    model_alone: bool = False  # its agent has no program (D.18): it is set up on a provider


class HandlerNeed(Document):
    """One of Handler's own features that needs an agent (D.18: the skill review needs a
    reviewer), given one by the person as an app's need is (H.2). Handler ships the definition
    an agent is set up from for it (`data/handler-needs/<name>/`). The UI calls the agent given a
    helper."""

    name: SkillName  # "skill-review"
    description: str  # what the agent does for Handler
    version: Annotated[int, Field(ge=1)]  # one more on each change of its definition
    definition: AgentDefinition  # what an agent set up for it starts with
    agent_id: str | None = None  # the agent given: Handler's feature uses it
    # the person's agents that may be given: a job's whose form and result fit (as H.2), a chat's
    # set up for this need (nothing else says what it does)
    fits: list[str] = []


class SetHandlerNeedAgentRequest(Document):
    """The agent given for one of Handler's needs (D.18): one that fits."""

    agent_id: Annotated[str, Field(min_length=1)]


# what only an agent program's sandbox has: an agent on the model alone keeps their defaults
# (D.18)
SANDBOX_SETTINGS = (
    *("network", "egress", "allow", "confinement", "permissions"),
    *("bindings", "display"),
)


class AgentSettings(Document):
    """How an agent is set up, but where it works: what it runs as (its model), its sandbox,
    its permission mode, its tools, knowledge and display. Shared by the requests that create or
    change an agent and by the agent itself. The defaults are the preset of new agents (Guarded):
    filtered network, enforced (D.2, D.8)."""

    # what it runs as; a session may run with another, for that session only (D.1, D.19)
    model: ModelAccess
    network: NetworkMode = "filtered"  # A.4
    egress: Enforcement = "enforce"  # filtered: enforce, or only log to learn its hosts (A.4)
    allow: list[EgressEntry] = []  # filtered: its own hosts, besides the required ones (A.3)
    confinement: Confinement = "strict"  # nested: podman inside; privileged: last resort (A.5)
    permissions: PermissionMode = "bypass"  # its starting mode (one its harness offers)
    bindings: list[BindingName] = []  # its addons (G.3)
    knowledge: list[KnowledgeFolder] = []  # mounted read-only at /knowledge/<name> (D.5)
    display: bool = False  # its sandboxes get the host's Wayland display (A.6)
    interface: AgentInterface | None = None  # a form: a job (a result) or a brief (D.18)
    # no program: each session is a conversation with the model, on a provider; no sandbox, so
    # none of its settings (they keep their defaults), no tools of any kind (D.18)
    model_alone: bool = False

    @field_validator("allow", "bindings", "knowledge")
    @classmethod
    def _as_set(cls, values: list[str]) -> list[str]:
        return sorted(set(values))

    @model_validator(mode="after")
    def _who_works(self) -> Self:
        if not self.model_alone:
            if self.model.provider is not None and self.model.harness is None:
                raise ValueError("a provider needs the harness that talks to it")
            return self
        if self.model.provider is None or self.model.harness is not None:
            raise ValueError("the model alone runs on a provider, with no harness")
        defaults = AgentSettings.model_fields
        sandboxed = [k for k in SANDBOX_SETTINGS if getattr(self, k) != defaults[k].default]
        if sandboxed:
            raise ValueError(f"the model alone has no sandbox: {', '.join(sandboxed)} not allowed")
        return self


MAX_INSTRUCTIONS = 20_000


class AgentOrigin(Document):
    """What an agent was set up from, kept for good: the definition of an app's need (H.2), an
    agents file's agent (D.23), or the definition of one of Handler's needs (D.18). Only what it
    came from: where the agent lives is its home (`projectId`, `app`, `chat`)."""

    kind: Literal["app", "agents-file", "handler-need"]
    name: SkillName  # the app's, the agents file's, Handler's need's
    agent: SkillName | None = None  # the app's need, the file's agent (its part); a need's: none
    version: Annotated[int, Field(ge=1)] | None = None  # the file's, the need's (not an app's)

    @model_validator(mode="after")
    def _parts(self) -> Self:
        if (self.kind == "app") == (self.version is not None):
            raise ValueError("a version for an agents file's agent or a need's, and only then")
        if (self.kind == "handler-need") == (self.agent is not None):
            raise ValueError("an agent for an app's need or an agents file's, and only then")
        return self


class AgentRequest(AgentSettings):
    """An agent: the body of create (POST) and of a full update (PUT). Its home is one of: a
    project (`projectId`: it works in the project's folder), an app (`app`: one of its parts,
    H.14), Chat (`chat`: someone you talk to, with no folder), or none (outside projects, in its
    own folder or a folder per session). The home is given at creation and never changes."""

    project_id: str | None = None
    app: AppName | None = None
    chat: bool = False
    scope: AbsolutePath | None = None  # of no project: its folder (None: one per session)
    # its goal ("Dev", "Review"), required in a project and unique there (case-insensitive);
    # of no project, a label shown instead of its folder
    name: str | None = None
    description: str | None = None  # what it is for
    instructions: Annotated[str, Field(max_length=MAX_INSTRUCTIONS)] | None = None
    skills: list[SkillName] = []  # skills it picks; its project's come on top (D.17)
    origin: AgentOrigin | None = None  # what it is set up from (D.23, H.2), kept for good
    default: bool = False  # a project's: becomes its default agent
    remote_start: bool = False  # a project's: your paired devices may start sessions with it
    confirm_risks: bool = False  # save although it widens what the agent may do (D.8)

    @model_validator(mode="after")
    def _one_home(self) -> Self:
        if sum((self.project_id is not None, self.app is not None, self.chat)) > 1:
            raise ValueError("one home: a project, an app or Chat")
        if self.project_id is not None and self.scope is not None:
            raise ValueError("an agent of a project works in its folder: no scope")
        return self


class PatchAgentRequest(Document):
    egress: Enforcement  # filtered agents: enforce, or only log to learn its hosts (A.4)


class Connection(Document):
    """One of an agent's running sandboxes: a plain connection (C), a session's (F) or a
    terminal's (D.16)."""

    id: str
    sandbox: str
    since: Timestamp
    terminal: ModelAccess | None = None  # a terminal's (D.16): the model it runs with


class RequiredHost(Document):
    """A host a filtered agent reaches whatever its own list says, and why (D.2)."""

    host: str
    by: str  # what requires it: "account claude-pro", "provider llamacpp", "MCP server docs",
    # "tool browser"


class AgentModel(ModelAccess):
    """An agent's model (D.1): its harness resolved, and what it needs now."""

    harness: HarnessName | None  # resolved: an account's harness when none was named; None:
    # the model alone (D.18)
    problem: str | None = None  # why a session cannot start with it now (E1)
    # filtered agents: what its account or provider, MCP servers and the agent's addons require
    # in a session running with it (E4), exactly the required part of that sandbox's allow-list
    required_hosts: list[RequiredHost] = []


class Agent(AgentSettings):
    """What sessions are opened on: a harness on an account or a provider (what, its model)
    working in a folder (where), with its settings. Its home: a project (`projectId`: its
    settings all its own; its folder, caches and skills its project's), an app (`app`: one of its
    parts), Chat (`chat`: someone you talk to), or none (outside projects: made on the Other
    folders page, or by `handler run`, `handler acp` and `handler terminal`)."""

    model: AgentModel
    scope: AbsolutePath | None = None  # None: folderless, a folder per session (D.18)
    network: NetworkMode  # always sent (the defaults are for requests)
    egress: Enforcement | None = None  # filtered only
    confinement: Confinement
    permissions: PermissionMode
    id: str
    name: str | None = None  # its name; None: its folder (ad-hoc agents only)
    project_id: str | None = None  # the project it is an agent of
    description: str | None = None  # an agent's: what it is for
    instructions: str | None = None  # an agent's: sent before the request that starts a session
    app: str | None = None  # its home besides a project: the app it is one of the parts of (H.14)
    chat: bool = False  # its home: Chat, someone you talk to (D.1)
    origin: AgentOrigin | None = None  # what it was set up from (D.18, D.23, H.2)
    remote_start: bool = False  # an agent's: paired devices (owner's) may start sessions with it
    skills: list[str] = []  # the skills it picked (D.17), names
    project_skills: list[str] = []  # given by its project to all its agents (D.17)
    area: str | None = None  # its project's area (D.19): the models its sessions may use
    acp_url: str
    connections: list[Connection]
    created_at: Timestamp
    last_used_at: Timestamp | None = None  # last session, connection or run


class ProjectSettingsRequest(Document):
    """A project's own settings: the body of a full update (PUT). Nothing in it is an agent's."""

    name: str | None = None  # default: the folder's name
    description: str | None = None  # what the project is
    folder: AbsolutePath  # its code folder, mounted read-write at the same path in its agents
    default_agent: str | None = None  # the agent a request goes to unless another is chosen
    # the toolbox's caches (B.6) for its agents: its own, the global ones (with other projects),
    # or none
    caches: CacheSharing = "project"
    # its area (D.19): only the accounts and providers made for it run its agents; none: any
    area: AreaName | None = None
    # the library's skills it gives to all its agents (D.17); an agent that picked one itself
    # drops it, its project giving it
    skills: list[SkillName] = []


class SetProjectPinnedRequest(Document):
    """Pin a project to the web UI's menu, or take it off (D.8)."""

    pinned: bool


class CreateProjectRequest(ProjectSettingsRequest):
    """A new project and its first agents (at least one)."""

    agents: Annotated[list[AgentRequest], Field(min_length=1)]


class Project(Document):
    """What you work on: a code folder, its caches and skills, and its agents."""

    id: str
    name: str
    description: str | None = None
    folder: AbsolutePath
    default_agent: str | None = None
    caches: CacheSharing = "project"  # the toolbox's caches for its agents (B.6)
    area: str | None = None  # its area (D.19)
    skills: list[SkillName] = []  # the skills it gives to all its agents (D.17)
    apps: list[str] = []  # the apps given its folder, or one inside it (H.14), by name
    pinned: bool  # listed in the web UI's menu (new projects are)
    agents: list[Agent]  # default agent first, then by name
    created_at: Timestamp
    last_used_at: Timestamp | None = None  # its agents' last use


class AreaInfo(Document):
    """An area (D.19): Work, Personal, a client. A project has at most one; accounts and
    providers say which they may be used in."""

    name: str
    color: AreaColor
    projects: list[str] = []  # the projects in it, by name
    accounts: list[str] = []  # the accounts made for it (not those for `any`)
    providers: list[str] = []  # the providers made for it (not those for `any`)


class AreaRequest(Document):
    """Create an area, or change its colour (PUT: the name is the path's)."""

    name: AreaName
    color: AreaColor


class EgressEvent(Document):
    """A network decision reported by an agent's sandbox (A.3), exposed for the UI."""

    t: Timestamp
    connection: str
    # unlisted: log only let it through, but no entry allows it (enforcing would deny it);
    # injected: a secret given by the proxy to a request to `host`; leak: a secret's phantom seen
    # going to `host`, which it is not for (refused)
    decision: Literal["allowed", "denied", "unlisted", "injected", "leak"]
    host: str
    secret: str | None = None  # injected, leak: its name (D.14 path)


class DirectoryEntry(Document):
    name: str
    path: AbsolutePath


class DirectoryListing(Document):
    """Folder picker (UI): sub-directories of a path inside the work folders (D.13)."""

    path: AbsolutePath | None  # None: the listing of the work folders themselves
    parent: AbsolutePath | None = None  # None when at a work folder
    entries: list[DirectoryEntry]


class KnowledgeListing(Document):
    """The knowledge root and its folders that can be selected (D.5)."""

    root: AbsolutePath
    # where the root comes from: HANDLER_KNOWLEDGE_DIR (not changeable through the API), the root
    # set through the API, or the default (~/knowledge)
    source: Literal["env", "config", "default"]
    exists: bool  # False: the root folder does not exist (yet), `folders` is empty
    folders: list[str]  # relative to the root, parents before children


class SetKnowledgeRootRequest(Document):
    """Set the knowledge root (D.5); `root: null` goes back to the default."""

    root: NonEmpty | None  # absolute, "~" allowed
    create: bool = False  # create the folder if it does not exist


class CreateKnowledgeFolderRequest(Document):
    path: KnowledgeFolder  # relative to the root; its parent must exist


class KnowledgeFolderView(Document):
    """One folder of the knowledge root, for reading (D.5): what it holds, and its _index.md."""

    path: str  # relative to the root, "." for the root
    folders: list[str]  # names of its sub-folders (not hidden, not "_")
    notes: list[str]  # names of its markdown files, _index.md excluded
    index: str | None = None  # the text of its _index.md, if any


class KnowledgeNote(Document):
    path: str  # relative to the root
    text: str


class CreateDirectoryRequest(Document):
    """Folder picker (UI): create one new folder `name` in `parent`, inside the allowed roots."""

    parent: AbsolutePath
    name: Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[^/\\\x00]+$")]


class Health(Document):
    status: Literal["ok"]
    version: str
    display: bool = False  # a Wayland display was found, for agents that ask for one (A.6)


MAX_REQUEST = 200_000


# who started a session: the web UI, the CLI, an editor (handler acp), a paired phone, an
# automation's agent run (I.3), an app on a person's request (H.11)
SessionOrigin = Literal["ui", "cli", "editor", "phone", "automation", "app", "check", "ask"]


class SessionSubject(Document):
    """What a run works on (D.18): the skill its form's skill field named, as it saw it."""

    skill: SkillName
    digest: str  # the skill's when the run started (D.17)


class SessionAppDraft(Document):
    """A session working on a draft of an app's code (H.15): its folder, kept by Handler, starts
    as a copy of `app`'s code, or empty for a new app (none). Used (`POST
    /v1/apps/from-draft/{session}`), its code becomes the app's next version, or a new app."""

    app: AppName | None = None


class SessionInput(Document):
    """What a session of an agent with an interface is started with (D.18): a job's run, a
    brief's session."""

    fields: dict[str, Any] = {}  # valid against its interface's `fields`


class SessionOutput(Document):
    """A run's result (D.18), taken from its final message once its turn ended."""

    valid: bool  # the value matches its interface's `result`
    value: Any = None  # the parsed result (valid or not, when it parsed)
    error: str | None = None  # why it is not valid


class Check(Document):
    """A run of a job kept with its right answer (D.20): run again with its input, it passes when
    every field of `compare` comes back as in `answer`."""

    id: str  # "c_" + 8 hex
    name: Annotated[str, Field(min_length=1, max_length=200)]
    input: dict[str, Any] = {}  # its form's values
    answer: dict[str, Any]  # the right result, whole (the run's it was kept from)
    compare: Annotated[list[str], Field(min_length=1)]  # the result's fields that must come back
    from_run: str | None = None  # the run it was kept from
    created_at: Timestamp
    problem: str | None = None  # why it cannot run now: its agent's form or result changed


CheckState = Literal["waiting", "running", "passed", "failed", "error"]


class CheckResult(Document):
    """One check in a check run (D.20)."""

    check_id: str
    name: str  # as it was when it ran
    state: CheckState
    session_id: str | None = None  # its run (origin "check")
    got: dict[str, Any] | None = None  # what came back, of the fields it compares
    why: str | None = None  # failed: which fields differ; error: why the run did not end well


class CheckRun(Document):
    """An agent's checks run once, one after another (D.20)."""

    id: str  # "k_" + 8 hex
    started_at: Timestamp
    ended_at: Timestamp | None = None
    results: list[CheckResult]


class AgentChecks(Document):
    """An agent's checks, its last check run, and what changed in it since (D.20)."""

    checks: list[Check]
    comparable: list[str] = []  # its result's fields a check may compare (not free text)
    last: CheckRun | None = None
    # what was changed in the agent since its last check run ("its instructions"); None: nothing
    # or never run
    changed: list[str] = []


class KeepCheckRequest(Document):
    """A run of the agent kept as a check (D.20)."""

    from_run: NonEmpty
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None  # default: its title
    compare: list[str] | None = None  # default: the result's fields that are not free text


class CheckUpdateRequest(Document):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    compare: Annotated[list[str], Field(min_length=1)]


UseKind = Literal[
    "agent",
    "skill",
    "knowledge",
    "addon",
    "account",
    "provider",
    "automation",
    "app",
    "project",
    "handler",
]


class UseRef(Document):
    """A thing at the other end of a use (D.22), and how it is used, in words."""

    kind: UseKind
    id: str  # an agent's id; a skill's, an addon configuration's, an account's, a provider's,
    # an automation's, an app's name; a knowledge folder's path in the root; a
    # project's id; "handler": the name of one of its needs (D.18)
    label: str  # how it is shown
    how: str  # "picks it", "runs on it", "given by its project", "runs it"…


class Uses(Document):
    """What a thing uses and what uses it (D.22)."""

    uses: list[UseRef] = []
    used_by: list[UseRef] = []


class AgentsFileCheck(Document):
    """A check that comes with an agents file's agent (D.20, D.23): copied to each agent set
    up."""

    name: Annotated[str, Field(min_length=1, max_length=200)]
    input: dict[str, Any] = {}
    answer: dict[str, Any]
    compare: Annotated[list[str], Field(min_length=1)]


class AgentsFileAgent(Document):
    """One of an agents file's agents (D.23): its definition and the checks that come with it."""

    part: SkillName  # its name in the file: the end of its agents' origin
    definition: AgentDefinition
    checks: list[AgentsFileCheck] = []


class AgentsFile(Document):
    """Agents written so they can be set up again in another project (D.23): their definitions
    without what is yours (the models they run as, their folder, the addon configurations and
    knowledge folders they were given), with what they need instead."""

    name: SkillName
    description: str | None = None
    version: Annotated[int, Field(ge=1)]  # 1 for an export
    # where it is set up by default: a project (its agents work in its folder), or outside
    # projects (folderless agents)
    place: Literal["project", "outside"] = "project"
    agents: Annotated[list[AgentsFileAgent], Field(min_length=1)]


class ExportAgentsRequest(Document):
    """`POST /v1/agents-files/export`: agents of one project written as one file (D.23)."""

    name: SkillName  # the file's: its agents' origins keep it
    description: str | None = None
    project_id: str
    agent_ids: Annotated[list[str], Field(min_length=1)]
    dry_run: bool = False  # say what would be in it (`AgentsExport`), make no file


class AgentsExport(Document):
    """What an agents file holds (`dryRun`), and what of yours it leaves out."""

    file: AgentsFile
    # what was yours and what it becomes: "Dev: runs on account claude-pro → its model, chosen at
    # set-up"
    replaced: list[str] = []


ImprovementState = Literal["running", "done", "stopped", "failed"]
AttemptState = Literal["writing", "checking", "done", "error"]


class Attempt(Document):
    """One version of a job's instructions in an improvement, and how its checks went (D.21)."""

    n: int  # 0: the instructions the improvement started from
    instructions: str
    change: str | None = None  # the prompt writer's line: what it changed
    state: AttemptState
    why: str | None = None  # error: why it has no result
    writer_run: str | None = None  # the prompt writer's run that wrote it
    results: list[CheckResult] = []
    passed: int = 0


class Improvement(Document):
    """A job's instructions rewritten by the prompt writer, again and again, judged by its checks,
    until they all pass or the budget is spent (D.21). Nothing changes until an attempt is kept."""

    id: str  # "i_" + 8 hex
    agent_id: str
    goal: str  # what to improve, the person's words
    max_attempts: int
    max_minutes: int
    state: ImprovementState
    why: str | None = None  # why it ended
    attempts: list[Attempt]
    best: int = 0  # the attempt with the most checks passing (a tie: the earlier)
    kept: int | None = None  # the attempt kept, once kept
    started_at: Timestamp
    ended_at: Timestamp | None = None


class StartImprovementRequest(Document):
    goal: Annotated[str, Field(min_length=1, max_length=4000)]
    max_attempts: Annotated[int, Field(ge=1, le=10)] = 5
    max_minutes: Annotated[int, Field(ge=1, le=240)] = 15


class KeepAttemptRequest(Document):
    attempt: Annotated[int, Field(ge=0)]


class CreateSessionRequest(Document):
    agent_id: NonEmpty  # an agent of a project, or an ad-hoc one
    # resume this ACP session of the agent instead of a new one
    acp_session_id: NonEmpty | None = None
    # the first request: the daemon sends it (after an agent's instructions) once the agent runs
    prompt: Annotated[str, Field(min_length=1, max_length=MAX_REQUEST)] | None = None
    input: SessionInput | None = None  # an agent with a form: a job's run, a brief's session (D.18)
    from_skill: SkillName | None = None  # a folderless agent: its folder starts as this skill's
    app_draft: SessionAppDraft | None = None  # a folderless agent: its folder is an app's draft
    # any model its project's area allows (D.19), the agent's or not; default: the agent's
    model: ModelAccess | None = None
    origin: SessionOrigin = "ui"


SessionLifecycle = Literal["starting", "running", "stopped", "failed"]


class Session(Document):
    """A daemon-held chat session (F.1): one sandbox, outliving the clients attached to it."""

    id: str
    agent_id: str
    project_id: str | None = None  # its agent's project, as of now
    harness: str | None  # the model it was started with (its agent's or one picked for it):
    # the harness (None: the model alone, D.18)...
    account: str | None = None  # ...and the account...
    provider: str | None = None  # ...or the provider...
    model: str | None = None  # ...and the model, when one was named
    scope: AbsolutePath
    acp_session_id: str | None = None
    title: str | None = None
    state: SessionLifecycle
    busy: bool = False
    pending_permissions: int = 0
    attached: int = 0
    # reachable from paired devices (docs/dev/design/remote.md); off after a stop
    remote: bool = False
    can_resume: bool = False
    error: str | None = None
    # its last start was refused: an image it needs is not built. The build that makes it (D.4:
    # a harness, "addon:<name>", "network-filter"); it starts once that image is built
    missing_image: str | None = None
    harness_version: str | None = None  # what the harness image had installed (B.6)
    origin: SessionOrigin = "ui"
    app: str | None = None  # origin "app": the app that started it (H.11)
    # a run waiting for its agent's run in progress (D.18: one at a time per agent): that one
    waiting_for: str | None = None
    last_stop_reason: str | None = None  # how its last turn ended (end_turn, cancelled, timed_out…)
    answer: str | None = None  # a run's (D.18): the agent's last message, once it ended
    input: SessionInput | None = None  # started from its agent's form: a run, a brief's (D.18)
    unattended: bool = False  # a run of a job (D.18): no one prompts it, it ends with a result
    subject: SessionSubject | None = None  # the skill it works on, set by handlerd (D.18)
    output: SessionOutput | None = None  # its result, once its turn ended (D.18)
    app_draft: SessionAppDraft | None = None  # its folder is a draft of an app's code, not used yet
    created_at: Timestamp
    last_activity_at: Timestamp
    acp_url: str


FileChangeKind = Literal["added", "modified", "deleted"]


class SessionFileChange(Document):
    path: str  # relative to the session's folder, "/"-separated
    change: FileChangeKind
    at: Timestamp | None = None  # when it was last modified; None once deleted


class SessionChanges(Document):
    """What changed in a session's folder since the session started (F.8), most recent first."""

    since: Timestamp  # when the session started: its folder as it was then is the baseline
    git: bool  # the folder was a git repository then: the earlier versions are its last commit's
    files: list[SessionFileChange] = []
    not_followed: str | None = None  # why its changes are not followed (files is then empty)


class SessionMount(Document):
    """What the session's sandbox sees of the host (F.8): a folder or file of it, or an addon's
    tools (an image)."""

    target: AbsolutePath  # where the agent sees it
    # scope: the session's folder; config: a skill; state: the agent's own (its harness's
    # settings, history, the account's sign-in); tools: an addon's image
    kind: MountKind | Literal["tools"]
    read_only: bool
    source: str  # the host path, or the addon's image
    browsable: bool  # read here (folder, file with `mount`): not the agent's state nor caches


class SessionMounts(Document):
    """Everything of the host a session's sandbox sees, as of its last start (F.8)."""

    started_at: Timestamp | None = None  # None: not recorded (only its folder is known)
    mounts: list[SessionMount]


class RevealRequest(Document):
    """Show a file or folder of a session in the desktop's file manager (F.8)."""

    path: str = ""  # relative to the session's folder or the mount, "" for it
    mount: str | None = None  # the target of a browsable mount; default the session's folder


class SessionFolderEntry(Document):
    name: str
    kind: Literal["file", "folder", "link"]  # a link is listed, never followed
    size: int | None = None  # a file's, in bytes
    target: str | None = None  # where a link points


class SessionFolder(Document):
    """One folder of a session's folder (F.8): folders first, then by name."""

    path: str  # relative to the session's folder, "" for the folder itself
    entries: list[SessionFolderEntry]


class SessionFound(Document):
    """The files of a session's folder that a search finds (F.8), the best first."""

    paths: list[str]  # relative to the session's folder
    not_followed: str | None = None  # why nothing was searched (too many files)


class SessionFile(Document):
    """One file of a session's folder (F.8), for reading. At most one of `text` and `image`: a
    file that is neither (binary, too large) has only its size."""

    path: str
    size: int | None = None  # None once deleted
    change: FileChangeKind | None = None  # since the session started
    text: str | None = None  # UTF-8 text, up to 1 MB
    image: str | None = None  # a data: URL (PNG, JPEG, GIF, WebP), up to 1 MB
    before: str | None = None  # its text as of the last commit when the session started (git)


class SetSessionRemoteRequest(Document):
    """Switch remote access to a running session on or off (docs/dev/design/remote.md §5)."""

    enabled: bool


RemoteLight = Literal["off", "idle", "ok", "unreachable", "unauthorized"]
"""The remote connector's light (D.7): off = no gateway set; idle = no session shared, so it does
not poll; ok = the last poll succeeded; unreachable; unauthorized = the gateway refused the host
token."""


# Who uses a device (docs/dev/design/apps.md §8): "owner" is the person running handler; others
# are family.
PersonName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,29}$")]
DeviceScope = Literal["all", "apps"]
"""What a paired device reaches: all = shared sessions and apps; apps = apps only."""


class RemoteDevice(Document):
    """A paired device (D.7). Its key never leaves the daemon after pairing."""

    id: str
    name: str
    person: PersonName = "owner"
    scope: DeviceScope = "all"
    created_at: Timestamp
    last_seen_at: Timestamp | None = None  # its last envelope the daemon accepted
    attached: list[str] = []  # the sessions it is attached to now


class RemoteStatus(Document):
    """The remote connector (D.7)."""

    gateway_url: str | None = None
    host_id: str | None = None
    light: RemoteLight
    detail: str | None = None  # why it is unreachable or unauthorized
    since: Timestamp | None = None  # when the light last changed
    shared_sessions: list[str] = []  # sessions with remote access on
    devices: list[RemoteDevice] = []


class SetRemoteGatewayRequest(Document):
    # https: handlerd sends its host token on each poll; plain http only to this computer (a
    # gateway run next to it, for development)
    gateway_url: Annotated[
        str,
        Field(
            pattern=r"^(https://[^\s/]+|http://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?)(/[^\s]*)?$"
        ),
    ]
    host_token: Annotated[str, Field(pattern=r"^h_[0-9a-f]{16}\.[A-Za-z0-9_-]{20,}$")]


class PairDeviceRequest(Document):
    name: Annotated[str, Field(min_length=1, max_length=60)]
    person: PersonName = "owner"
    scope: DeviceScope = "all"


class RemotePairing(Document):
    """A new device (D.7): `pairingUrl` carries its key in the fragment — shown once, as a QR
    code."""

    device: RemoteDevice
    pairing_url: str


AppState = Literal["stopped", "starting", "running", "failed"]
"""An app's backend (H.5): started on demand, stopped when idle; failed = it did not start or
exited on its own (see its log)."""


class AppDeployment(Document):
    """One installed version of an app (H.6)."""

    version: str
    deployed_at: Timestamp
    needs: AppManifestNeeds


class AppSource(Document):
    """The app's source folder as it is now: what Deploy would install (H.6)."""

    version: str | None = None
    description: str | None = None
    error: str | None = None  # the manifest is missing or invalid, or names another app
    added_needs: list[str] = []  # what it may reach that the current version cannot
    # what it may reach (the install page says it before Deploy)
    needs: AppManifestNeeds | None = None


class AppSecret(Document):
    """A secret an app declares (current or source version): whether it has a value. The value
    itself never leaves the daemon (H.2)."""

    name: str
    set: bool


class AppFileNeed(Document):
    """A folder an app needs (current or source version, H.2), and the one given for it."""

    name: str  # the app's word for it: `needs.files.<name>`
    description: str | None = None
    mode: Literal["ro", "rw"]
    path: AbsolutePath | None = None  # given; None: not yet


class AppAgentNeed(Document):
    """An agent an app needs (current or source version, H.2), the one given for it, and the
    person's agents that fit it (D.18: its form takes what the app sends, its result gives what
    the app reads; it works in the folder given for `worksIn`)."""

    name: str  # the app's word for it: `needs.agents.<name>`
    description: str | None = None
    works_in: str | None = None  # the files need whose folder it works in
    definition: AgentDefinition | None = None  # the source's (None: it cannot be read)
    origin: AgentOrigin  # what an agent set up from the definition gets as its origin
    agent_id: str | None = None  # given; None: not yet
    problem: str | None = None  # the agent given no longer fits (deleted, its form changed…)
    fits: list[str] = []  # ids of the agents that fit, the one given among them


InboxStatus = Literal["ok", "attention", "failed"]


class InboxMessage(Document):
    """What handler tells a person (the person's inbox, like mail): an app's notification
    (H.9), an automation's result or failure (I.3). Shown on the computer and pushed to the
    person's phones (content-free: the text travels encrypted when the phone asks for it)."""

    id: str
    source: Literal["app", "automation"]
    name: str  # the app's, the automation's
    agent: str | None = None  # an automation's agent run: the agent's name
    person: str  # "owner", or one an app is shared with
    title: str
    status: InboxStatus | None = None  # an automation's run (an app's notification: none)
    summary: str | None = None  # an app's body; an agent run's own summary; a failure's error
    data: Any = None  # an agent run's whole result (D.18), shown from its interface's schema
    run_id: str | None = None  # an automation's run
    session_id: str | None = None  # an agent run's session
    app: str | None = None  # the app it opens: an app's own, or the one its automation names
    at: Timestamp
    read: bool = False


# ── sources (D.26) ──────────────────────────────────────────────────────

SourceId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
SourceKind = Literal["app", "agents", "addon"]
OFFICIAL_SOURCE = "official"  # the source Handler reads by default, its own (D.26)
SOURCE_API_VERSION = "handler.source/v1"
SOURCE_MANIFEST = "handler-source.toml"  # at the root of a source's repository


class SourceManifest(StrictDocument):
    """`handler-source.toml` at the root of a source's repository (D.26)."""

    api_version: Literal["handler.source/v1"]
    name: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(max_length=1000)] | None = None


class SourceNote(Document):
    """One thing a source's item does, in a few words, for its card (D.26): "uses 1 folder of
    yours", "reaches 2 sites"."""

    text: str
    weakens: bool = False  # what runs on this computer reaches more (a site, an image built)


class SourceItem(Document):
    """Something a source offers (D.26): an app (`apps/<name>/`), agents (`agents/<name>/`, an
    agents file's content) or an addon (`addons/<name>/`)."""

    kind: SourceKind
    name: str
    description: str | None = None
    version: str | None = None  # an app's; an agents file's (its integer); an addon has none
    installed: bool = False  # an app or an addon of that name is installed (wherever from)
    update: bool = False  # installed from this source, which now holds other content
    error: str | None = None  # it cannot be read (by this Handler): never offered
    notes: list[SourceNote] = []  # what it does, from its manifest, the weakening ones first


class Source(Document):
    """A git repository Handler reads to offer things to install (D.26). The official one is
    Handler's; any other was added by the person, who trusts it."""

    id: SourceId  # its name in Handler: "official", or made from its URL
    url: str
    official: bool = False
    name: str | None = None  # its manifest's
    description: str | None = None
    commit: str | None = None  # the commit read last
    fetched_at: Timestamp | None = None
    error: str | None = None  # the last fetch's, or its manifest's; its items: what was read before
    items: list[SourceItem] = []


class SourceItemDetail(Document):
    """`GET /v1/sources/{id}/{apps|agents|addons}/{name}`: an item's page (D.26), before
    anything is installed: its README, and what its kind's manifest says it may touch."""

    source: Source  # without its items
    item: SourceItem
    readme: str | None = None  # its README.md, as written
    app: AppManifest | None = None
    agents: AgentsFile | None = None
    addon: AddonPreview | None = None  # what installing it would bring (G.5)


class AddSourceRequest(Document):
    url: Annotated[str, Field(pattern=r"^https://[^\s]+$", max_length=2048)]


class App(Document):
    """An app (H): its code kept by Handler (H.15), what is installed, its backend's state."""

    name: AppName
    description: str | None = None
    url: str  # its own origin, http://<name>.localhost:<port>/ (opened through POST …/open)
    state: AppState
    error: str | None = None
    current: AppDeployment | None = None  # None: registered, never deployed
    previous: AppDeployment | None = None  # what a rollback returns to
    source: AppSource
    secrets: list[AppSecret] = []
    files: list[AppFileNeed] = []
    agents: list[AppAgentNeed] = []
    # the automations the version a deploy would install suggests (I.1): made from its page
    suggests: list[AppManifestSuggestedAutomation] = []
    persons: list[str] = []  # who may use it from a paired device (H.8); none: local only
    last_used_at: Timestamp | None = None
    # the source its code came from (D.26; "official": Handler's); None: a file or a draft
    from_source: SourceId | None = None
    # its actions, what you can ask it (H.12): the installed version's (before a first deploy,
    # its source's)
    actions: list["AppAction"] = []
    askable: bool = True  # its actions are offered to Ask (D.24); off: tried from its page only


class AppAction(Document):
    """One of an app's actions (H.12), as its page and Ask's router see it."""

    name: NeedName
    description: str
    examples: list[str] = []
    by: Literal["code", "agent"]  # its code answers at once; its agent's run takes a while
    # its form: the route's, or the agent's (its definition's); None: it takes nothing
    fields: dict[str, Any] | None = None


class ActionRequest(Document):
    """`POST /v1/apps/{name}/actions/{action}`: the action's form, filled."""

    fields: dict[str, Any] = {}


ActionState = Literal["running", "succeeded", "failed"]


class ActionRun(Document):
    """An action, done or under way (H.12)."""

    app: AppName
    action: NeedName
    state: ActionState
    result: ActionResult | None = None  # succeeded
    error: str | None = None  # failed: why
    run_id: str | None = None  # an agent's action: its run (H.11), read again until it ends
    session_id: str | None = None  # an agent's action: its run's session


class SetAppAskableRequest(Document):
    askable: bool


# ── D.24 Ask: what the person says, routed to one of their apps' actions ─────


class AskTurn(Document):
    """One turn of an exchange with Ask: the person's words, or what Handler answered."""

    who: Literal["you", "handler"]
    text: Annotated[str, Field(min_length=1, max_length=2000)]


class AssistantRequest(Document):
    """`POST /v1/ask`: the exchange so far, the person's words last. Stateless: the client
    sends it whole each time (a reply to a question is one more turn)."""

    turns: Annotated[list[AskTurn], Field(min_length=1, max_length=20)]
    timezone: str | None = None  # IANA, where the person is (the device's); else the host's


class ActionOption(Document):
    """One action Ask can pick: which app's, and what it does."""

    app: AppName
    action: NeedName
    description: str


AssistantKind = Literal["pick", "needs", "none"]


class AssistantAnswer(Document):
    """What Ask did with what was said (D.24)."""

    kind: AssistantKind  # pick: an action was run; needs: a question; none: no action does it
    summary: str  # one sentence: what was picked, the question, or that none fits
    app: AppName | None = None  # pick, needs: the app
    action: NeedName | None = None
    why: str | None = None  # pick: why this one, in a few words
    fields: dict[str, Any] | None = None  # pick: its form, as filled
    run: ActionRun | None = None  # pick: the action, done or under way (H.12)
    question: str | None = None  # needs
    actions: list[ActionOption] = []  # none: what can be asked
    router_run: str | None = None  # the router's run (its session), to read how it decided


# ── D.25 Voice: speaking to Ask (transcribe/v1, I.11) ─────────────────────────


class VoiceSettings(Document):
    """`PUT /v1/voice`: what writes down what you say, and when answers are read aloud."""

    model: LlmModel | None = None  # "provider/model", a speech model; None: off (no microphone)
    read_aloud_spoken: bool = True  # an answer to what you said aloud: read by the device
    read_aloud_typed: bool = False  # an answer to what you typed


class SpeechModelInfo(Document):
    """A provider's speech model (`speech = true`), one Voice can use."""

    model: LlmModel  # "provider/model"
    name: str
    provider: str
    local: bool  # served on this machine: the recording does not leave it


class Voice(VoiceSettings):
    """`GET /v1/voice`: the settings, and the speech models there are to choose from."""

    models: list[SpeechModelInfo]
    problem: str | None = None  # the chosen model can no longer be used: why


class SpeechRequest(Document):
    """`POST /v1/voice/transcribe` (and the device's `transcribe`): a recording to write down
    with the chosen model, never kept."""

    audio: Annotated[str, Field(min_length=1)]  # base64, at most MAX_AUDIO bytes once decoded
    format: AudioFormat
    language: Annotated[str, Field(pattern=r"^[a-z]{2}$")] | None = None


class Transcription(Document):
    text: str  # what was heard; empty when nothing was


class DraftCopy(Document):
    """What an opened draft works on instead of the real thing (H.16)."""

    what: str  # "its data", "folder calendar"
    path: str | None = None  # a folder you gave the app: where it is
    # copy: a copy made when opened (size: its bytes); read-only: too large to copy, the real
    # folder read-only; empty: nothing yet (a new app's data, a folder not given)
    how: Literal["copy", "read-only", "empty"]
    size: int | None = None


class DraftPreview(Document):
    """`POST /v1/apps/from-draft/{session}/open`: the draft's code running at its own address
    (`<app>--draft.localhost`), on copies, until it is used, thrown away or closed (H.16)."""

    app: AppName
    url: str  # a one-time link that opens it (H.4)
    copies: list[DraftCopy]


class SetAppSecretRequest(Document):
    value: SecretValue


class SetAppFileRequest(Document):
    """The folder (or file) given for one of an app's files needs (H.2)."""

    path: HostPath
    create: bool = False  # a folder that does not exist yet is made (else: 409)


class SetAppAgentRequest(Document):
    """The agent given for one of an app's agents needs (H.2): one that fits."""

    agent_id: Annotated[str, Field(min_length=1)]


class SecretSent(Document):
    """The latest request a sandbox's proxy gave a secret to (A.3 `injected`)."""

    t: Timestamp
    host: str


class SecretInfo(Document):
    """A secret handler uses (D.14), described: a value in its store, or one an account, a provider
    or a binding references where the person keeps it. The value never leaves the daemon."""

    path: SecretPath  # in the store; a reference's: the path it would have there
    # where its value is: the store, handlerd's env, a file, a command
    source: SecretKind = "secret"
    has_value: bool = True  # a command is not run to know: true
    description: str | None = None
    created_at: Timestamp | None = None  # the store's
    updated_at: Timestamp | None = None
    # what it belongs to: "accounts/<name>", "providers/<name>", "bindings/<name>", "apps/<app>";
    # none: a value nothing uses
    used_by: list[str] = []
    agents: list[str] = []  # the agents whose sandboxes get it ("<project> · <agent>"…)
    hosts: list[EgressEntry] = []  # where their proxies give it (E3, A.3)
    visible: str | None = None  # why the process gets the value itself, when it does
    last_sent: SecretSent | None = None  # since handlerd started, from its agents' recent events


class PutSecretRequest(Document):
    """Set a secret's value and description (replacing them)."""

    value: SecretValue
    description: str | None = None


class SetAppPersonsRequest(Document):
    persons: Annotated[list[PersonName], Field(max_length=20)]


class AppLink(Document):
    """A one-time link that opens the app in a browser (valid 2 minutes, H.4)."""

    url: str


class AppLog(Document):
    """The end of an app's log: its last deploy, then its backend's output."""

    text: str


class Problem(Document):
    """RFC 9457 problem details, used for every Control API error."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
