"""Contract D — Control API (`handler.control/v1`)."""

from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .addon import AddonName, BindingName, SlotName
from .agent_spec import HarnessName
from .common import (
    AbsolutePath,
    AccessContext,
    CacheSharing,
    CommandSecret,
    Confinement,
    ContextColor,
    ContextName,
    Document,
    EgressEntry,
    Enforcement,
    EnvSecret,
    FileSecret,
    FileSource,
    MountKind,
    NetworkMode,
    PermissionMode,
    ResourceName,
    SecretPath,
)
from .harness import CacheDeclaration, CacheName, LoginRecipe
from .miniapp import AppName, MiniAppNeeds
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
    source: str | None = None  # installed from (G.5): "catalog:<name>", a folder, an archive URL
    update_available: bool = False  # installed from the catalog, which now ships other content


AddonSource = Annotated[str, Field(min_length=1, max_length=2048)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AddonCatalogEntry(Document):
    """An addon handler ships but does not load until it is installed (G.5)."""

    name: str
    description: str | None = None
    installed: bool = False  # an addon of that name is in the user's folder


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
    """A source to look at (G.5): "catalog:<name>", an absolute folder path, an https:// URL of
    a .tar.gz archive."""

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
    contexts: list[str] = []  # the project contexts it may be used in, or `any` (D.19)
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
    contexts: list[AccessContext] = []  # the project contexts it may be used in, or `any` (D.19)


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
    files: list[str] = []  # the harnesses it has config files for (hand-written, E)
    contexts: list[str] = []  # the project contexts it may be used in, or `any` (D.19)


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
    contexts: list[AccessContext] = []  # the project contexts it may be used in, or `any` (D.19)


class ModelAccess(Document):
    """What an agent runs as (E): a harness and the account or the provider its model calls use
    (exactly one), and the model. An agent has one or more (D.1); a session runs with one."""

    harness: HarnessName | None = None  # an account's by default; required with a provider
    account: ResourceName | None = None
    provider: ResourceName | None = None
    model: Annotated[str, Field(min_length=1)] | None = None  # default: the harness's or provider's

    @model_validator(mode="after")
    def _account_or_provider(self) -> Self:
        if (self.account is None) == (self.provider is None):
            raise ValueError("name exactly one of 'account' and 'provider'")
        if self.provider is not None and self.harness is None:
            raise ValueError("a provider needs the harness that talks to it")
        return self


# a JSON Schema (draft 2020-12), checked by handlerd; at most this many bytes as JSON
JsonSchema = dict[str, Any]
MAX_SCHEMA_BYTES = 64 * 1024
SubjectKind = Literal["skill"]  # the handler objects a run can work on (D.18)
SUBJECT_ROOT = "/subject"  # where a run's subject is mounted, read-only: /subject/<name>


class AgentInterface(Document):
    """What a run of an agent takes and gives back (D.18): a form, a handler object to work on, and
    the result its final message holds. An agent with one runs unattended, so in permission mode
    `bypass`: no one is there to answer its requests."""

    fields: JsonSchema | None = None  # an object schema: the form filled to start a run
    subject: SubjectKind | None = None  # mounted read-only at /subject/<name>
    result: JsonSchema  # what its final message gives back
    timeout_sec: Annotated[int, Field(gt=0, le=86_400)] = 1800  # each turn


class BuiltinAgent(Document):
    """An agent handler ships (D.18), set up at most once: everything but what it runs as and where
    it works, its defaults; `skills` come with it, installed in the library when it is set up."""

    name: SkillName  # its name: the origin of the agent set up from it
    description: str  # what it is for
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
    agent_id: str | None = None  # the agent set up from it, once there is one


class AgentSettings(Document):
    """How an agent is set up, but where it works: what it may run as (its models), its sandbox,
    its permission mode, its tools, knowledge and display. Shared by the requests that create or
    change an agent and by the agent itself. The defaults are the preset of new agents (Guarded):
    filtered network, enforced (D.2, D.8)."""

    # what it runs as, the first by default; each session runs with one of them (D.1)
    models: Annotated[list[ModelAccess], Field(min_length=1)]
    network: NetworkMode = "filtered"  # A.4
    egress: Enforcement = "enforce"  # filtered: enforce, or only log to learn its hosts (A.4)
    allow: list[EgressEntry] = []  # filtered: its own hosts, besides the required ones (A.3)
    confinement: Confinement = "strict"  # nested: podman inside; privileged: last resort (A.5)
    permissions: PermissionMode = "bypass"  # its starting mode (one its harness offers)
    bindings: list[BindingName] = []  # its addons (G.3)
    knowledge: list[KnowledgeFolder] = []  # mounted read-only at /knowledge/<name> (D.5)
    display: bool = False  # its sandboxes get the host's Wayland display (A.6)
    interface: AgentInterface | None = None  # its runs are unattended (D.18)

    @field_validator("allow", "bindings", "knowledge")
    @classmethod
    def _as_set(cls, values: list[str]) -> list[str]:
        return sorted(set(values))

    @field_validator("models")
    @classmethod
    def _once_each(cls, values: list[ModelAccess]) -> list[ModelAccess]:
        if len({m.model_dump_json() for m in values}) != len(values):
            raise ValueError("a model is listed twice")
        return values


MAX_INSTRUCTIONS = 20_000


class AdHocAgentRequest(AgentSettings):
    """An ad-hoc agent (one without a project, D.1): the body of create (POST) and of a full
    update (PUT). Without a scope, a folderless agent: each of its sessions gets a folder of its
    own (D.18)."""

    scope: AbsolutePath | None = None
    name: str | None = None  # a label shown instead of its folder
    description: str | None = None  # what it is for
    instructions: Annotated[str, Field(max_length=MAX_INSTRUCTIONS)] | None = None
    skills: list[SkillName] = []  # skills it picks (D.17)
    # the built-in agent it is set up from (D.18): at most one agent each, kept for good
    origin: SkillName | None = None
    confirm_risks: bool = False  # save although it widens what the agent may do (D.8)


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
    """One of an agent's models (D.1): its harness resolved, and what it needs now."""

    harness: HarnessName  # resolved: an account's harness when none was named
    problem: str | None = None  # why a session cannot start with it now (E1)
    # filtered agents: what its account or provider, MCP servers and the agent's addons require
    # in a session running with it (E4), exactly the required part of that sandbox's allow-list
    required_hosts: list[RequiredHost] = []


class Agent(AgentSettings):
    """What sessions are opened on: a harness on an account or a provider (what, one of its
    models) working in a folder (where), with its settings. An agent of a project has a
    `projectId` (its settings all its own; its folder, caches and skills its project's); an
    ad-hoc one has none (`handler run`, `handler acp` and `handler terminal` outside projects)."""

    models: list[AgentModel]
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
    origin: str | None = None  # the built-in agent it is (D.18), at most one each
    remote_start: bool = False  # an agent's: paired devices (owner's) may start sessions with it
    skills: list[str] = []  # the skills it picked (D.17), names
    project_skills: list[str] = []  # given by its project to all its agents (D.17)
    context: str | None = None  # its project's context (D.19): the models its sessions may use
    acp_url: str
    connections: list[Connection]
    created_at: Timestamp
    last_used_at: Timestamp | None = None  # last session, connection or run


class AgentRequest(AgentSettings):
    """An agent of a project: its settings (all its own, never followed from its project; it
    works in its project's folder) and what it is in the project. The body of create (POST) and
    of a full update (PUT)."""

    # its goal ("Dev", "Review", "Contracts check"), unique in the project (case-insensitive); never
    # its model's: another model is not another agent (D.1)
    name: Annotated[str, Field(pattern=r"^\s*\S")]
    description: str | None = None  # what it is for
    instructions: Annotated[str, Field(max_length=MAX_INSTRUCTIONS)] | None = None
    default: bool = False  # becomes the project's default agent
    remote_start: bool = False  # your paired devices may start sessions with it (D.7)
    skills: list[SkillName] = []  # skills it picks; its project's come on top (D.17)
    confirm_risks: bool = False  # save although it widens what the agent may do (D.8)


class ProjectSettingsRequest(Document):
    """A project's own settings: the body of a full update (PUT). Nothing in it is an agent's:
    which skills it gives to all its agents is set on the skills (D.17)."""

    name: str | None = None  # default: the folder's name
    description: str | None = None  # what the project is
    folder: AbsolutePath  # its code folder, mounted read-write at the same path in its agents
    default_agent: str | None = None  # the agent a request goes to unless another is chosen
    # the toolbox's caches (B.6) for its agents: its own, the global ones (with other projects),
    # or none
    caches: CacheSharing = "project"
    # its context (D.19): only the accounts and providers made for it run its agents; none: any
    context: ContextName | None = None


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
    context: str | None = None  # its context (D.19)
    agents: list[Agent]  # default agent first, then by name
    created_at: Timestamp
    last_used_at: Timestamp | None = None  # its agents' last use


class ContextInfo(Document):
    """A project context (D.19): Work, Personal, a client. A project has at most one; accounts and
    providers say which they may be used in."""

    name: str
    color: ContextColor
    projects: list[str] = []  # the projects in it, by name
    accounts: list[str] = []  # the accounts made for it (not those for `any`)
    providers: list[str] = []  # the providers made for it (not those for `any`)


class ContextRequest(Document):
    """Create a context, or change its colour (PUT: the name is the path's)."""

    name: ContextName
    color: ContextColor


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


# who started a session: the web UI, the CLI, an editor (handler acp), a paired phone
SessionOrigin = Literal["ui", "cli", "editor", "phone", "automation"]


class SessionSubject(Document):
    """The handler object a run works on (D.18)."""

    skill: SkillName
    digest: str | None = None  # set by handlerd when the run starts: what it saw (D.17)


class SessionInput(Document):
    """What a run of an agent with an interface is started with (D.18)."""

    fields: dict[str, Any] = {}  # valid against its interface's `fields`
    subject: SessionSubject | None = None


class SessionOutput(Document):
    """A run's result (D.18), taken from its final message once its turn ended."""

    valid: bool  # the value matches its interface's `result`
    value: Any = None  # the parsed result (valid or not, when it parsed)
    error: str | None = None  # why it is not valid


class CreateSessionRequest(Document):
    agent_id: NonEmpty  # an agent of a project, or an ad-hoc one
    # resume this ACP session of the agent instead of a new one
    acp_session_id: NonEmpty | None = None
    # the first request: the daemon sends it (after an agent's instructions) once the agent runs
    prompt: Annotated[str, Field(min_length=1, max_length=MAX_REQUEST)] | None = None
    input: SessionInput | None = None  # an agent with an interface: a run (D.18)
    from_skill: SkillName | None = None  # a folderless agent: its folder starts as this skill's
    # any model its project's context allows (D.19), the agent's or not; default: its first
    model: ModelAccess | None = None
    origin: SessionOrigin = "ui"


SessionLifecycle = Literal["starting", "running", "stopped", "failed"]


class Session(Document):
    """A daemon-held chat session (F.1): one sandbox, outliving the clients attached to it."""

    id: str
    agent_id: str
    project_id: str | None = None  # its agent's project, as of now
    harness: str  # which of its agent's models it was started with: the harness...
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
    harness_version: str | None = None  # what the harness image had installed (B.6)
    origin: SessionOrigin = "ui"
    last_stop_reason: str | None = None  # how its last turn ended (end_turn, cancelled, timed_out…)
    answer: str | None = None  # a run's (D.18): the agent's last message, once it ended
    input: SessionInput | None = None  # a run of an agent with an interface (D.18)
    output: SessionOutput | None = None  # its result, once its turn ended (D.18)
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


# Who uses a device (docs/dev/design/miniapps.md §8): "owner" is the person running handler; others
# are family.
PersonName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,29}$")]
DeviceScope = Literal["all", "apps"]
"""What a paired device reaches: all = shared sessions and apps; apps = mini apps only."""


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
    gateway_url: Annotated[str, Field(pattern=r"^https?://[^\s/]+(/[^\s]*)?$")]
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
"""A mini app's backend (H.5): started on demand, stopped when idle; failed = it did not start or
exited on its own (see its log)."""


class AppDeployment(Document):
    """One installed version of a mini app (H.6)."""

    version: str
    deployed_at: Timestamp
    needs: MiniAppNeeds


class AppSource(Document):
    """The app's source folder as it is now: what Deploy would install (H.6)."""

    version: str | None = None
    description: str | None = None
    error: str | None = None  # the manifest is missing or invalid, or names another app
    added_needs: list[str] = []  # what it may reach that the current version cannot


class AppSecret(Document):
    """A secret an app declares (current or source version): whether it has a value. The value
    itself never leaves the daemon (H.2)."""

    name: str
    set: bool


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
    at: Timestamp
    read: bool = False


class App(Document):
    """A registered mini app (H): its source folder, what is installed, its backend's state."""

    name: AppName
    description: str | None = None
    source_dir: AbsolutePath
    url: str  # its own origin, http://<name>.localhost:<port>/ (opened through POST …/open)
    state: AppState
    error: str | None = None
    current: AppDeployment | None = None  # None: registered, never deployed
    previous: AppDeployment | None = None  # what a rollback returns to
    source: AppSource
    secrets: list[AppSecret] = []
    shortcut: str | None = None  # the GNOME keyboard shortcut that opens it (H.7)
    persons: list[str] = []  # who may use it from a paired device (H.8); none: local only
    last_used_at: Timestamp | None = None


class AddAppRequest(Document):
    source_dir: AbsolutePath  # a folder with an app.toml


class SetAppSecretRequest(Document):
    value: SecretValue


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


# GNOME accelerator syntax: modifiers, then one key: <Super>n, <Primary><Alt>F5
ShortcutKeys = Annotated[
    str,
    Field(
        pattern=r"^(<(Super|Primary|Control|Ctrl|Alt|Shift)>)+"
        r"([A-Za-z0-9]|F[1-9]|F1[0-2]|space|Return|period|comma|slash|minus|equal)$"
    ),
]


class SetAppPersonsRequest(Document):
    persons: Annotated[list[PersonName], Field(max_length=20)]


class SetAppShortcutRequest(Document):
    shortcut: ShortcutKeys | None  # null: no shortcut


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
