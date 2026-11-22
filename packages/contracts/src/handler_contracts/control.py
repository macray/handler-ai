"""Contract D — Control API (`handler.control/v1`)."""

from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, AwareDatetime, Field, field_validator, model_validator

from .addon import RESERVED_ENV, AddonName, BindingName, SlotName, reserved_among
from .agent_spec import HarnessName
from .app import (
    ActionResult,
    AppManifest,
    AppManifestNeeds,
    AppManifestNudgeRemind,
    AppManifestSuggestedAutomation,
    AppName,
    AppPage,
    JobAccess,
    NeedName,
)
from .automation import AudioFormat, LlmModel, Schedule
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
    EnvMap,
    EnvSecret,
    FileSecret,
    FileSource,
    HostDecision,
    HostPath,
    MountKind,
    NetworkMode,
    PermissionMode,
    RefusedHost,
    ResourceName,
    SchemaId,
    SecretPath,
    StrictDocument,
)
from .harness import (
    CacheDeclaration,
    FolderCaches,
    LoginRecipe,
    SystemPackageDaemon,
    SystemPackageName,
)
from .provider import Endpoint, Protocol, ProviderModel
from .sandbox import DISPLAY_ENV, RuntimeCheck

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
# a folder of the notes root (HANDLER_NOTES_DIR), as a path relative to it; "." is the root
KnowledgeFolder = Annotated[str, Field(min_length=1, max_length=1024, pattern=r"^[^/\x00]")]


class HarnessInfo(Document):
    """GET /v1/harnesses (D.2): what a harness's descriptor says (B.1), nothing of its image."""

    name: str
    product: str  # its product name ("Claude Code"): what the UI shows (B.1)
    image: str  # the repository; agents launch its ':latest'
    provider_protocols: list[Protocol] = []  # the providers it can use; empty: accounts only
    login: LoginRecipe | None = None  # how an account of it is made; none: providers only
    login_file: str | None = None  # a file login's: the file name it leaves in `{dir}`
    permissions: list[PermissionMode] = []  # the permission modes it offers
    # the ACP session mode each permission mode is, when it is one: how a session's mode
    # selector names the harness's modes as handler does
    session_modes: dict[PermissionMode, str] = {}
    account_connectors: bool = False  # its accounts may use their own connectors (B.1)


class HarnessImage(Document):
    """GET /v1/harness-images (D.2): a harness's image `:latest`, asked of the runtime (D.4)."""

    name: str  # the harness's
    image: str  # the repository
    image_present: bool
    version: str | None = None  # what the image installed (B.6), e.g. "Claude Code 2.1.280 (…)"
    built_at: Timestamp | None = None


MAX_CONTAINERFILE_BYTES = 256 * 1024


class ToolboxNeed(Document):
    """A command what is in use needs from the toolbox (B.6): one of `commands`, who needs it,
    and what gives it."""

    commands: list[str]  # one of them
    # "handler", "harness:<name>", "agent:<id>" (an ability its sandboxes have, A.8)
    needed_by: list[str]
    # "base", "system-package:<name>" (one turned on), "lines" (found in the toolbox built now,
    # from the user's lines); None: nothing gives it
    provided_by: str | None = None


class ToolboxSystemPackage(Document):
    """A system package turned on in the toolbox (B.7)."""

    name: str
    version: int | None = None  # its files'; None: no system package of that name
    built_version: int | None = None  # in the toolbox built now; None: not in it
    needed_by: list[str] = []  # who needs what it alone gives, as `ToolboxNeed.neededBy`


class ToolboxInfo(Document):
    """GET /v1/toolbox (D.2): the toolbox image, what it is made of, and who needs what."""

    image: str
    image_present: bool
    built_at: Timestamp | None = None
    directory: str  # the user's toolbox folder: toolbox.toml, custom.containerfile (B.7)
    distro: str | None = None  # None: toolbox.toml cannot be read (`problem`)
    system_packages: list[ToolboxSystemPackage] = []  # turned on, in their order
    commands: dict[str, str] = {}  # what the toolbox built now gives: command → its path
    needs: list[ToolboxNeed] = []  # of what is in use
    problem: str | None = None  # why it cannot be built as it is


class ToolboxRecord(Document):
    """`<state>/toolbox.json` (B.6): what the toolbox `:latest` gives, written when a build
    switches to it; every check of a need reads it."""

    image_id: str
    built_at: Timestamp
    distro: str
    system_packages: dict[str, int]  # name → version
    commands: dict[str, str]  # every command a need or a system package names, found → its path


class SystemPackageInfo(Document):
    """A system package Handler or the user has (B.7), as Settings → Sandboxes offers it."""

    name: str
    version: int | None = None
    description: str | None = None
    provides: list[str] = []
    caches: list[CacheDeclaration] = []
    daemons: list[SystemPackageDaemon] = []  # started in the sandboxes having their abilities
    distros: list[str] = []  # those it has an install script for
    builtin: bool  # shipped with Handler; else in the user's folder
    overrides_builtin: bool = False  # the user's, named as a built-in one, which it replaces
    directory: str
    error: str | None = None  # its files are wrong: it cannot be turned on


class SystemPackagesRequest(Document):
    """PUT /v1/toolbox/system-packages: the system packages on, in their order; those they
    depend on are turned on with them. Applied by the next toolbox build."""

    system_packages: list[SystemPackageName]


class ToolboxLines(Document):
    """The user's own lines of the toolbox (`custom.containerfile`, B.7), appended last."""

    content: Annotated[str, Field(max_length=MAX_CONTAINERFILE_BYTES)]


class ToolboxRebuildRequest(Document):
    """POST /v1/toolbox/rebuild: apply what changed (with the build cache: only the layers from
    the first changed one run), or `update`: pull the base and run every layer again (system
    updates)."""

    update: bool = False


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


class ToolboxContainerfile(Document):
    """The toolbox's generated Containerfile (B.7), read-only: what the next build builds."""

    content: str


class CacheInfo(Document):
    """A cache (B.6), as Settings → Caches shows it (D.8)."""

    name: str  # its host folder, named from its target
    target: str  # where agents find it: a home path ("~/.cargo")
    about: str  # what it holds
    general: bool = False  # a folder any tool writes to (~/.cache), not one tool's
    bin: str | None = None  # its folder of commands, on PATH ("bin": ~/.cargo/bin)
    kind: Literal["folder", "images"] = "folder"  # a container engine's images (B.6)
    # "base", "system-package:<name>", "addon:<name>" (for the agents using it), "user" (their
    # own, editable)
    declared_by: list[str]


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
    """PUT /v1/caches: the user's own caches, for what their own lines install, written to
    toolbox.toml (B.7). Applies to new sessions."""

    caches: FolderCaches


class CacheSizes(Document):
    """GET /v1/caches/sizes: bytes on disk of each folder of CachesInfo (0: not made yet)."""

    sizes: dict[str, int]


class AddonSlotInfo(Document):
    """A setting or secret slot of an addon (G.1), for the binding form."""

    name: str
    required: bool = False
    description: str | None = None


AddonState = Literal["installed", "preparing", "ready", "failed"]


class AddonInfo(Document):
    """An addon (G.1) and, when it has a tool, its image (G.4)."""

    name: str
    # (G.5) ready: its tool built (when it has one) and its needs in the toolbox; preparing: a
    # build that will make it ready runs (its own, or the toolbox's it waits for); failed: its
    # last build failed; installed: neither (`stateDetail` says what it lacks)
    state: AddonState = "installed"
    state_detail: str | None = None  # why it is not ready: the build's error, a missing need
    description: str | None = None
    connect: str | None = None  # its CONNECT.md as written, shown at Connect (G.1)
    connection_check: list[str] | None = None  # what checks a connection to it works (G.2)
    image: str | None = None  # the repository its tool is built as. None: no tool
    image_present: bool = False  # built: its image extracted into the folder agents mount
    version: str | None = None  # what the image installed (G.4)
    built_at: Timestamp | None = None  # when that folder became the one agents mount
    commands: list[str] = []
    needs: list[str] = []  # commands it runs from the toolbox (B.6)
    caches: list[CacheDeclaration] = []  # what its tools keep between sessions (D.8)
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


class ToolboxAdd(Document):
    """A system package (B.7) a save or an install adds to the toolbox, for what it needs."""

    name: SystemPackageName
    description: str | None = None
    provides: list[str] = []  # the needs it answers
    # source:<source>/<name> (D.26): installed with the addon, from the addon's source; None:
    # one Handler or the user already has
    source: str | None = None
    script: str | None = None  # its install script for the toolbox's distro: runs as root


class AddonToolbox(Document):
    """What an addon needs from the toolbox (B.6), against what the toolbox gives (G.5)."""

    has: list[str] = []  # its needs the toolbox gives (or will: a system package on)
    adds: list[ToolboxAdd] = []  # installing turns these on, then applies the toolbox
    # its needs no system package provides: add them to your own lines; until then it stays
    # installed, not ready
    lacking: list[str] = []


class AddonPreview(Document):
    """What installing from `source` would add (G.5), shown before the user decides; `digest`
    names exactly this content: an install of other content is refused."""

    source: str
    digest: Digest
    name: str
    description: str | None = None
    image: str | None = None  # its Containerfile runs code when the image is built
    commands: list[str] = []
    needs: list[str] = []  # commands it runs from the toolbox (B.6)
    caches: list[CacheDeclaration] = []  # folders of its agents' homes it keeps (D.8)
    env: list[str] = []  # the variables it sets in agents' sandboxes
    settings: list[AddonSlotInfo] = []
    secret_slots: list[AddonSlotInfo] = []
    egress: list[str] = []  # hosts its agents may reach
    mcp: list[str] | None = None  # the MCP server it gives every session (P8)
    skills: list[str] = []
    replaces: Literal["builtin", "installed", "own"] | None = None  # what has that name now
    toolbox: AddonToolbox = AddonToolbox()


class AddonPreviewRequest(Document):
    """A source to look at (G.5): "source:<source>/<name>" (an addon of a source, D.26), an
    absolute folder path, an https:// URL of a .tar.gz archive."""

    source: AddonSource


class AddonInstallRequest(Document):
    source: AddonSource
    # from the preview: names the addon and the system packages coming with it from its source
    digest: Digest
    # the system packages the preview said it adds (`toolbox.adds`): 409 `toolbox changes not
    # confirmed` when they differ
    toolbox_adds: list[SystemPackageName] = []


class BindingCheck(Document):
    """A connection's check (G.2, D.15): its tool's `connectionCheck`, run as an agent of it gets
    the tool. Kept while handlerd runs, forgotten when the connection is saved again."""

    ok: bool  # it exited 0
    at: Timestamp
    output: str = ""  # its last lines (stdout and stderr), its secrets' values hidden
    error: str | None = None  # why not: its exit code, or why it could not run


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
    used_by: list[str] = []  # "agents/<project>/<agent>", "ad-hoc/<id>", "projects/<project>"
    checked: BindingCheck | None = None  # its last check since handlerd started


class BindingRequest(Document):
    """Create a binding, or replace one (and rename it). Secret values go to the secret store
    (`connections/<name>/<slot>`); a slot left out of `secrets` keeps what it has, unless it is in
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
    addons: list[str] = []  # the addons it builds (a toolbox build: those already built)
    harnesses: list[str] = []  # the harnesses it builds (a toolbox build: those already built)
    error: str | None = None
    started_at: Timestamp
    ended_at: Timestamp | None = None


class AddonInstalled(Document):
    addon: AddonInfo
    # its image's first build (G.4), or the toolbox's applying what it added (then its own)
    build: Build | None = None


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
    subscription: str | None = None  # which one it is, as the account file says (not checked)
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
    """Create an account, or rename it and change its description, subscription and connectors (not its
    harness)."""

    name: ResourceName
    harness: Annotated[str, Field(min_length=1)]
    description: str | None = None
    # which one it is: one of its harness's `login.subscriptions`
    subscription: Annotated[str, Field(min_length=1)] | None = None
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


class ProviderReach(Document):
    """What a provider's server answered (D.12): `ok` once every endpoint gave its model list."""

    ok: bool
    at: AwareDatetime
    urls: list[str]  # where it was asked, as agents reach it (`host.containers.internal`…)
    # what it serves: the ids, and the context when the server reports it
    models: list[ProviderModel] = []
    error: str | None = None  # why not: nothing answered, or what it answered
    hint: str | None = None  # what to do about it (a server on this computer listening on loopback)
    # an endpoint whose server redirects (`http://` to `https://`): where, to use instead; agents
    # are not redirected (Only these sites allows the endpoint's own host and port)
    redirects: dict[Protocol, str] = {}


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
    # its server is on this computer (an endpoint on its loopback or `host.containers.internal`):
    # shown ready only once a test reached it, from where a sandbox would
    local: bool = False
    # the last test of its endpoints since handlerd started (POST /v1/providers/test); none:
    # never tested
    reached: ProviderReach | None = None


class ProviderTestRequest(Document):
    """POST /v1/providers/test (D.12): ask a provider's server for its models, from where a
    sandbox would. The endpoints typed in a form, or a saved provider's; the key typed, or the
    saved provider's (sent only to its own endpoints' hosts)."""

    endpoints: Annotated[dict[Protocol, Endpoint], Field(min_length=1)] | None = None
    key: SecretValue | None = None
    provider: ResourceName | None = None  # a saved provider: its key, its endpoints by default

    @model_validator(mode="after")
    def _something_to_test(self) -> Self:
        if self.endpoints is None and self.provider is None:
            raise ValueError("give the endpoints or a provider")
        return self


class ProviderTemplate(Document):
    """A starting point for a provider (templates/providers/, D.12). A local server's has no
    model: they are picked from what it serves (`POST /v1/providers/test`)."""

    name: str
    description: str | None = None
    endpoints: dict[Protocol, str]
    models: list[ProviderModel] = []
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


# how an agent gets a notes folder (D.5): read-only, or read-write (it weakens the sandbox: the
# agent may change or delete any file of that folder)
KnowledgeAccess = Literal["read", "write"]


MAX_SMD_SCHEMA_BYTES = 256 * 1024  # a schema file of the Library


class KnowledgeUse(Document):
    """A schema an agent reads or writes (D.29): it gets that schema, read-only; its documents
    are in its notes folders. `write`: it may make and change documents of that schema (where:
    its read-write folders, D.5)."""

    schema_id: SchemaId
    access: KnowledgeAccess = "read"


def _one_use_per_schema(uses: list[KnowledgeUse]) -> list[KnowledgeUse]:
    """D.29: each schema once, sorted; read and write at once is refused."""
    by_id: dict[str, KnowledgeUse] = {}
    for use in uses:
        if by_id.setdefault(use.schema_id, use) != use:
            raise ValueError(f"schema {use.schema_id!r} is used both to read and to write")
    return [by_id[i] for i in sorted(by_id)]


KnowledgeUses = Annotated[list[KnowledgeUse], AfterValidator(_one_use_per_schema)]


class SchemaInfo(Document):
    """A schema of the Library (D.29): one kind of document, found by its `$id` alone. `error`:
    why no agent can use it (a file that is not a schema, an `extends` not there); `content`
    (its file) only when one is read."""

    id: str  # its `$id`; the file's name without `.schema.json` when it cannot be read
    title: str | None = None
    description: str | None = None
    extends: str | None = None  # the `$id` it starts from
    error: str | None = None
    content: str | None = None


class SchemaRequest(Document):
    """A schema into the Library (D.29), as its file's text. One with that `$id` already there
    and different is refused (409) unless `replace`; the same is kept as it is."""

    content: Annotated[str, Field(min_length=1, max_length=MAX_SMD_SCHEMA_BYTES)]
    replace: bool = False


class KnowledgeFolderUse(Document):
    """A notes folder an agent gets (D.5), at /notes/<its name>: read-only, or read-write."""

    folder: KnowledgeFolder
    access: KnowledgeAccess = "read"


class AgentDefinition(Document):
    """What an agent set up from it starts with (D.18): everything but what it runs as and where
    it works, its defaults; `skills` come with it, installed in the library when it is set up.
    An agents file's agents are definitions (D.23), and so are those Handler ships for its needs
    (D.18)."""

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
    # the schemas it reads or writes (D.29); those it ships (`schemas/`) join the Library
    schemas: KnowledgeUses = []
    display: bool = False  # its sandboxes get the host's Wayland display (A.6)
    env: EnvMap = {}  # its environment variables, plain values (D.8)
    model_alone: bool = False  # its agent has no program (D.18): it is set up on a provider

    @field_validator("env")
    @classmethod
    def _env(cls, env: dict[str, str]) -> dict[str, str]:
        return checked_agent_env(env)


class HandlerNeed(Document):
    """One of Handler's own features that needs an agent (D.18: the skill review needs a
    reviewer), given one by the person. Handler ships the definition
    an agent is set up from for it (`data/handler-needs/<name>/`). The UI calls the agent given a
    helper."""

    name: SkillName  # "skill-review"
    description: str  # what the agent does for Handler
    version: Annotated[int, Field(ge=1)]  # one more on each change of its definition
    definition: AgentDefinition  # what an agent set up for it starts with
    agent_id: str | None = None  # the agent given: Handler's feature uses it
    # the person's agents that may be given: a job's whose form and result fit, a chat's
    # set up for this need (nothing else says what it does)
    fits: list[str] = []


class SetHandlerNeedAgentRequest(Document):
    """The agent given for one of Handler's needs (D.18): one that fits."""

    agent_id: Annotated[str, Field(min_length=1)]


# what only an agent program's sandbox has: an agent on the model alone keeps their defaults
# (D.18)
SANDBOX_SETTINGS = (
    *("network", "egress", "allow", "blocked", "confinement", "permissions"),
    *("addons", "display", "env"),
)

# D.8: what an agent's own variables never set, in any case: what Handler sets in every sandbox
# (the proxy, the CA variables, PATH, HOME), a display's (A.6) and a terminal's (D.16). Those its
# harness, its tools and the toolbox's daemons set are refused when it is saved and when it
# starts (they depend on its model and its tools).
AGENT_RESERVED_ENV = RESERVED_ENV | DISPLAY_ENV | {"TERM", "COLORTERM"}


def checked_agent_env(env: dict[str, str]) -> dict[str, str]:
    """An agent's variables (D.8): none Handler sets itself."""
    if reserved := reserved_among(env, AGENT_RESERVED_ENV):
        raise ValueError(f"set by Handler, not by an agent: {', '.join(reserved)}")
    return env


class AddonUse(Document):
    """An addon an agent or a project uses (G.3): by its name, with the binding filling its
    slots when it has some (G.2); one without slots has no binding."""

    addon: AddonName
    binding: BindingName | None = None


def _one_use_per_addon(uses: list[AddonUse]) -> list[AddonUse]:
    """G3: one binding per addon; sorted by addon."""
    seen: set[str] = set()
    for use in uses:
        if use.addon in seen:
            raise ValueError(f"tool '{use.addon}' is used twice: one connection per tool")
        seen.add(use.addon)
    return sorted(uses, key=lambda u: u.addon)


AddonUses = Annotated[list[AddonUse], AfterValidator(_one_use_per_addon)]


class AgentSettings(Document):
    """How an agent is set up, but where it works: what it runs as (its model), its sandbox,
    its permission mode, its tools, knowledge and display. Shared by the requests that create or
    change an agent and by the agent itself. The defaults are what a new agent starts with: only
    the sites it needs (filtered network, enforced), strict, never asking (D.2, D.8)."""

    # what it runs as; a session may run with another, for that session only (D.1, D.19)
    model: ModelAccess
    network: NetworkMode = "filtered"  # A.4
    egress: Enforcement = "enforce"  # filtered: enforce, or only log to learn its hosts (A.4)
    allow: list[EgressEntry] = []  # filtered: its own hosts, besides the required ones (A.3)
    # filtered: the hosts the person keeps blocked, never also allowed: refused as unlisted ones,
    # the agent told not to ask for them (A.3)
    blocked: list[EgressEntry] = []
    confinement: Confinement = "strict"  # nested: podman inside; privileged: last resort (A.5)
    permissions: PermissionMode = "bypass"  # its starting mode (one its harness offers)
    addons: AddonUses = []  # its own addons; its project's come on top (G.3)
    knowledge: list[KnowledgeFolderUse] = []  # mounted at /notes/<name>, ro or rw (D.5)
    schemas: KnowledgeUses = []  # its knowledge uses: the schemas it gets, read-only (D.29)
    display: bool = False  # its sandboxes get the host's Wayland display (A.6)
    # its environment variables, plain values: never a secret (a tool's connection gives those);
    # never one Handler, its harness, its tools or the toolbox's daemons set (D.8)
    env: EnvMap = {}
    interface: AgentInterface | None = None  # a form: a job (a result) or a brief (D.18)
    # no program: each session is a conversation with the model, on a provider; no sandbox, so
    # none of its settings (they keep their defaults), no tools of any kind (D.18)
    model_alone: bool = False

    @field_validator("allow", "blocked")
    @classmethod
    def _as_set(cls, values: list[str]) -> list[str]:
        return sorted(set(values))

    @field_validator("knowledge")
    @classmethod
    def _one_use_per_folder(cls, uses: list[KnowledgeFolderUse]) -> list[KnowledgeFolderUse]:
        """D.5: each folder once, sorted; given both read-only and read-write is refused."""
        by_folder: dict[str, KnowledgeFolderUse] = {}
        for use in uses:
            if by_folder.setdefault(use.folder, use) != use:
                raise ValueError(f"notes folder {use.folder!r} is given read-only and read-write")
        return [by_folder[f] for f in sorted(by_folder)]

    @field_validator("env")
    @classmethod
    def _env(cls, env: dict[str, str]) -> dict[str, str]:
        return checked_agent_env(env)

    @model_validator(mode="after")
    def _who_works(self) -> Self:
        if both := sorted(set(self.allow) & set(self.blocked)):
            raise ValueError(f"allowed and kept blocked at once: {', '.join(both)}")
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
    """What an agent was set up from, kept for good: an agents file's agent (D.23), or the
    definition of one of Handler's needs (D.18). Only what it came from: where the agent lives is
    its home (`projectId`, `chat`)."""

    kind: Literal["agents-file", "handler-need"]
    name: SkillName  # the agents file's, Handler's need's
    agent: SkillName | None = None  # the file's agent (its part); a need's: none
    version: Annotated[int, Field(ge=1)]  # the file's, the need's

    @model_validator(mode="after")
    def _parts(self) -> Self:
        if (self.kind == "handler-need") == (self.agent is not None):
            raise ValueError("an agent for an agents file's, and only then")
        return self


class AgentRequest(AgentSettings):
    """An agent: the body of create (POST) and of a full update (PUT). Its home is one of: a
    project (`projectId`: it works in the project's folder), Chat (`chat`: someone you talk to,
    with no folder), or none (outside projects, in its own folder or a folder per session). The
    home is given at creation and never changes."""

    project_id: str | None = None
    chat: bool = False
    scope: AbsolutePath | None = None  # of no project: its folder (None: one per session)
    # its goal ("Dev", "Review"), required in a project and unique there (case-insensitive);
    # of no project, a label shown instead of its folder
    name: str | None = None
    description: str | None = None  # what it is for
    instructions: Annotated[str, Field(max_length=MAX_INSTRUCTIONS)] | None = None
    skills: list[SkillName] = []  # skills it picks; its project's come on top (D.17)
    origin: AgentOrigin | None = None  # what it is set up from (D.18, D.23), kept for good
    default: bool = False  # a project's: becomes its default agent
    remote_start: bool = False  # a project's: your paired devices may start sessions with it
    confirm_risks: bool = False  # save although it widens what the agent may do (D.8)
    # the system packages the save adds to the toolbox for what the agent needs (B.6), as the
    # 409 `toolbox changes not confirmed` named them: turned on, then the toolbox applied
    toolbox_adds: list[SystemPackageName] = []

    @model_validator(mode="after")
    def _one_home(self) -> Self:
        if self.project_id is not None and self.chat:
            raise ValueError("one home: a project or Chat")
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
    settings all its own; its folder, caches and skills its project's), Chat (`chat`: someone you
    talk to), or none (outside projects: made on the Other
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
    chat: bool = False  # its home: Chat, someone you talk to (D.1)
    origin: AgentOrigin | None = None  # what it was set up from (D.18, D.23)
    remote_start: bool = False  # an agent's: paired devices (owner's) may start sessions with it
    skills: list[str] = []  # the skills it picked (D.17), names
    project_skills: list[str] = []  # given by its project to all its agents (D.17)
    project_addons: list[AddonUse] = []  # given by its project to all its agents (G.3)
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
    # the addons it gives to all its agents (G.3); an agent that picked one itself drops it
    addons: AddonUses = []
    toolbox_adds: list[SystemPackageName] = []  # as an agent's (AgentRequest), for its agents


PinKind = Literal["project", "app"]


class Pin(Document):
    """A project or an app in the web UI's menu (D.28); Chat is no pin, it has its own entry."""

    kind: PinKind
    id: str  # the project's id, the app's name


class Pins(Document):
    """The web UI's menu's Pinned (D.28): projects and apps mixed, in the person's order; the
    same on every browser. PUT replaces the whole list (pin, unpin and reorder are one call)."""

    items: list[Pin]


class CreateProjectRequest(ProjectSettingsRequest):
    """A new project, alone or with its first agents."""

    agents: list[AgentRequest] = []


class Project(Document):
    """What you work on: a code folder, its caches and skills, and its agents."""

    id: str
    name: str
    description: str | None = None
    folder: AbsolutePath
    branch: str | None = None  # the git branch checked out in it; None: not git, or detached
    default_agent: str | None = None
    caches: CacheSharing = "project"  # the toolbox's caches for its agents (B.6)
    area: str | None = None  # its area (D.19)
    skills: list[SkillName] = []  # the skills it gives to all its agents (D.17)
    addons: list[AddonUse] = []  # the addons it gives to all its agents (G.3)
    apps: list[str] = []  # the apps given its folder, or one inside it (H.14), by name
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
    # held: a request to `host` waits for the person's answer, its decision follows (A.3);
    # injected: a secret given by the proxy to a request to `host`; leak: a secret's phantom seen
    # going to `host`, which it is not for (refused); reached, unreached: how a connection to
    # `host` let through went, once per connection (A.3)
    decision: Literal[
        "allowed", "denied", "unlisted", "held", "injected", "leak", "reached", "unreached"
    ]
    host: str
    secret: str | None = None  # injected, leak: its name (D.14 path)
    wait: int | None = None  # held: how many seconds at most
    error: str | None = None  # unreached: why ("connection refused", "host not found"…)


class DirectoryEntry(Document):
    name: str
    path: AbsolutePath
    # the recent folders only (New project): its git branch, and when it last changed
    branch: str | None = None
    changed_at: AwareDatetime | None = None


class DirectoryListing(Document):
    """Folder picker (UI): sub-directories of a path inside the work folders, or the folders in
    them changed last (D.13)."""

    path: AbsolutePath | None  # None: the listing of the work folders themselves
    parent: AbsolutePath | None = None  # None when at a work folder
    entries: list[DirectoryEntry]


class KnowledgeListing(Document):
    """The knowledge root and its folders that can be selected (D.5)."""

    root: AbsolutePath
    # where the root comes from: HANDLER_NOTES_DIR (not changeable through the API), the root
    # set through the API, or the default (~/notes, made when missing)
    source: Literal["env", "config", "default"]
    exists: bool  # False: the root folder does not exist (yet), `folders` is empty
    folders: list[str]  # relative to the root, parents before children


class KnowledgeRootCheck(Document):
    """A folder that could become the knowledge root (D.5), checked before it is saved: what the
    web UI's Change button says (Use this folder / Create this folder)."""

    root: AbsolutePath  # "~" expanded, symlinks kept
    state: Literal["folder", "missing", "not-a-folder"]


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


# ── the notes history (D.5) ─────────────────────────────────────────────

NotesCommitKind = Literal["first", "changes", "while-off", "undo"]
NotesChange = Literal["added", "changed", "deleted"]


class NotesWriter(Document):
    """An agent, or an app, that could write the folder and ran in a commit's lapse (its name
    then): `agentId` for an agent, `app` for an app."""

    agent_id: str | None = None
    app: str | None = None
    name: str


class NotesFileChange(Document):
    path: str  # relative to the folder
    change: NotesChange
    link: bool = False  # a link, kept as a link: its target is never read
    # what changed in its lines, when it is text (not a link, not too large): how many added
    # and removed, and the heading they are all under (the nearest above them), if one; in a
    # commit's list, said for its first files only (FILES_SAID), None for the others
    added: int | None = None
    removed: int | None = None
    under: str | None = None


class NotesCommit(Document):
    """One state of a read-write notes folder kept by Handler (D.5): `first`, the history's
    start (its files not listed); `changes`, what changed in a lapse (~5 min), with the agents
    that could write then; `while-off`, what changed while handlerd was not running; `undo`,
    a change put back."""

    id: str
    at: Timestamp
    kind: NotesCommitKind
    could_write: list[NotesWriter] = []
    undoes: str | None = None  # an undo's: the change it put back
    files: list[NotesFileChange]
    file_count: int  # the first's too


class NotesHistory(Document):
    # as asked: relative to the notes root (as agents keep it), or a full path (an app's folder)
    folder: str
    commits: list[NotesCommit]  # newest first, the last 100


class NotesFileDiff(NotesFileChange):
    link_target: str | None = None  # a link's: where it points (never followed)
    # what changed in its lines (a unified diff without its header); None: not text, or too
    # large to show
    diff: str | None = None


class NotesCommitDiff(Document):
    commit: NotesCommit
    files: list[NotesFileDiff]


class NotesUndoRequest(Document):
    folder: NonEmpty
    commit: NonEmpty


class NotesUndo(Document):
    """An undo's result: its commit (None: the files were already as before), and the files
    left as they are because a link or a folder is on their way."""

    commit: NotesCommit | None
    skipped: list[str] = []


class CreateDirectoryRequest(Document):
    """Folder picker (UI): create one new folder `name` in `parent`, inside the allowed roots."""

    parent: AbsolutePath
    name: Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[^/\\\x00]+$")]


class SandboxRuntime(Document):
    """A sandbox runtime installed here (A, D.2): its executable is `handler-sandbox-<name>`."""

    name: str  # "podman"
    current: bool  # the one handlerd uses: every sandbox and image is its
    # its host check (A.8), what it would give here; None: it could not say
    check: RuntimeCheck | None = None


class ChooseRuntimeRequest(Document):
    """The runtime handlerd uses from now on (D.2)."""

    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")]


class Health(Document):
    status: Literal["ok"]
    version: str
    display: bool = False  # a Wayland display was found, for agents that ask for one (A.6)


MAX_REQUEST = 200_000


# who started a session: the web UI, the CLI, an editor (handler acp), a paired phone, an
# automation's agent run (I.3), an app on a person's request (H.11), a plan's step (D.27)
SessionOrigin = Literal["ui", "cli", "editor", "phone", "automation", "app", "check", "ask", "plan"]


class SessionPlan(Document):
    """The plan a session is a step of (origin "plan", D.27)."""

    id: str
    step: Annotated[int, Field(ge=1)]


class SessionPlanDraft(Document):
    """The plan draft a plan builder's session writes (D.27): its folder is the draft, its
    project's folder seen read-only, at its own path."""

    id: str
    project_id: str
    folder: str  # the project's


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
    "schema",
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
    id: str  # an agent's id; a skill's, an addon's, an account's, a provider's,
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
    without what is yours (the models they run as, their folder, the connections and notes
    folders they were given), with what they need instead."""

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
    # the first request: the daemon sends it (after an agent's instructions) once the agent runs
    prompt: Annotated[str, Field(min_length=1, max_length=MAX_REQUEST)] | None = None
    input: SessionInput | None = None  # an agent with a form: a job's run, a brief's session (D.18)
    from_skill: SkillName | None = None  # a folderless agent: its folder starts as this skill's
    app_draft: SessionAppDraft | None = None  # a folderless agent: its folder is an app's draft
    # the plan builder: its folder is this plan draft, its project seen read-only (D.27)
    plan_draft: NonEmpty | None = None
    # any model its project's area allows (D.19), the agent's or not; default: the agent's
    model: ModelAccess | None = None
    origin: SessionOrigin = "ui"


SessionLifecycle = Literal["starting", "running", "stopped", "failed"]


class Session(Document):
    """A daemon-held chat session (F.1): one sandbox, outliving the clients attached to it."""

    id: str
    agent_id: str | None = None  # none: a job's run (H.11), which no agent runs
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
    # reachable from paired devices (remote design); off after a stop
    remote: bool = False
    can_resume: bool = False
    error: str | None = None
    # its last start was refused: an image it needs is not built. The build that makes it (D.4:
    # a harness, "addon:<name>", "network-filter"); it starts once that image is built
    missing_image: str | None = None
    # the request it was created with, not sent yet (its start waits for an image): sent as its
    # first turn once it starts
    request: str | None = None
    harness_version: str | None = None  # what the harness image had installed (B.6)
    origin: SessionOrigin = "ui"
    app: str | None = None  # origin "app" (or "automation"): the app that started it (H.11)
    job: str | None = None  # a run of that job of `app` (H.11): no agent runs it
    # a run waiting for its agent's run in progress (D.18: one at a time per agent), or a job's
    # run for the run writing a folder it writes (H.11): that one (or the one before it)
    waiting_for: str | None = None
    last_stop_reason: str | None = None  # how its last turn ended (end_turn, cancelled, timed_out…)
    answer: str | None = None  # a run's (D.18): the agent's last message, once it ended
    input: SessionInput | None = None  # started from its agent's form: a run, a brief's (D.18)
    unattended: bool = False  # a run of a job (D.18): no one prompts it, it ends with a result
    subject: SessionSubject | None = None  # the skill it works on, set by handlerd (D.18)
    output: SessionOutput | None = None  # its result, once its turn ended (D.18)
    app_draft: SessionAppDraft | None = None  # its folder is a draft of an app's code, not used yet
    plan: SessionPlan | None = None  # origin "plan": the plan and the step it is (D.27)
    plan_draft: SessionPlanDraft | None = None  # a plan builder's: the draft it writes (D.27)
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
    """Switch remote access to a running session on or off (remote design §5)."""

    enabled: bool


RemoteLight = Literal["off", "idle", "ok", "unreachable", "unauthorized"]
"""The remote connector's light (D.7): off = no gateway set; idle = no session shared, so it does
not poll; ok = the last poll succeeded; unreachable; unauthorized = the gateway refused the host
token."""


# Who uses a device (apps design §8): "owner" is the person running handler; others
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
    computer_name: str  # what the phones call this computer (default: its hostname)
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


class SetComputerNameRequest(Document):
    """What the phones call this computer: given to each phone paired from now on."""

    computer_name: Annotated[str, Field(min_length=1, max_length=60)]


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
    changes: str | None = None  # what this version changes, its manifest's
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
    """A folder (or a file) an app needs (current or source version, H.2), and the one given."""

    name: str  # the app's word for it: `needs.files.<name>`
    description: str | None = None
    mode: Literal["ro", "rw"]
    path: AbsolutePath | None = None  # given; None: not yet
    # the path given is a file: the app keeps the one it started with if an editor replaces it
    file: bool = False


InboxStatus = Literal["ok", "attention", "failed"]


# H.17: a nudge's life, and how the person wants its reminders (per app and nudge's name)
NudgeState = Literal["open", "done", "dismissed", "expired"]
NudgeSetting = Literal["default", "once", "silent"]  # its reminders: the app's, none, no alert


class InboxNudge(Document):
    """What makes an inbox message a nudge (H.17): something an app asks the person to do, open
    until its action succeeds, its app says it is done, the person dismisses it, or it expires."""

    name: NeedName  # the app's nudge (`nudges.<name>` in its manifest)
    key: str | None = None  # this one among its name's (`2026-11-12`): one open per name and key
    state: NudgeState = "open"
    action: NeedName | None = None  # the action whose form a click opens, or
    open: str | None = None  # the page of the app a click opens: its path, `?nudge=<id>` added
    form: dict[str, Any] | None = None  # the action's form (its JSON Schema), when it was sent
    fields: dict[str, Any] | None = None  # that form, filled in by the app beforehand
    until: Timestamp | None = None  # expired then, when still open
    remind: AppManifestNudgeRemind | None = None  # its reminders as its app says them
    setting: NudgeSetting = "default"  # how you want them, for its app's nudge of that name
    when: Schedule | None = (
        None  # when handlerd sends its name's, as the app says (kept up to date)
    )
    own_when: Schedule | None = None  # yours, replacing the app's (kept up to date)
    off: bool = False  # you turned its name's off: none comes, this one reminds no more
    if_ignored: str | None = None  # what the app says happens then
    alerts: int = 0  # alerts so far (its first one, then reminders)
    next_alert_at: Timestamp | None = None  # its next reminder; none: no more
    run_id: str | None = None  # its action's agent run, while it runs
    ended_at: Timestamp | None = None


class InboxMessage(Document):
    """What handler tells a person (the person's inbox, like mail): an app's notification
    (H.9), an automation's result or failure (I.3), a plan stopped or a step that completed
    with hosts refused (D.27), the hosts refused to a session while nobody could answer (F.9),
    documents of a read-write notes folder not as their schema says (D.5), an ask that failed
    or that no app does (D.24).
    Shown on the computer and pushed to the person's phones (content-free: the text travels
    encrypted when the phone asks for it)."""

    id: str
    source: Literal["app", "automation", "plan", "session", "notes", "ask"]
    # the app's, the automation's, the plan's title, the session's title; notes: the folder (D.5);
    # ask: "Ask" (an ask that failed or that no app does, D.24)
    name: str
    agent: str | None = None  # an agent's run or session: the agent's name
    agent_id: str | None = None  # whose hosts `refused` are: answered for that agent
    plan_id: str | None = None  # a plan's: the plan, and its step
    step: int | None = None
    # the hosts the network filter refused, neither allowed nor kept blocked then (F.9): a
    # session's while nobody could answer, a run's, a step's
    refused: list[RefusedHost] = []
    said: str | None = None  # what the agent's last message says of them, when it does
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
    kind: Literal["message", "nudge"] = "message"  # a nudge: something to do (H.17)
    nudge: InboxNudge | None = None  # with kind "nudge"


# ── sources (D.26) ──────────────────────────────────────────────────────

SourceId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]


class AppOffered(Document):
    """The version the source an app came from offers, as read last (D.26), while it differs
    from its kept code's: Update takes it, then deploys it (H.6)."""

    source: SourceId
    version: str
    changes: str | None = None  # what it changes, its manifest's
    added_needs: list[str] = []  # what it may reach that the installed version cannot


# a system package (`system-packages/<name>/`, B.7) is installed with the addons that need it
SourceKind = Literal["app", "agents", "addon", "system-package"]
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
    agents file's content) or a tool (`tools/<name>/`)."""

    kind: SourceKind
    name: str
    title: str | None = None  # an app's (its manifest's `title`, H.1); none: its name
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
    # what it is called for the person (its manifest's `title`, H.1: the installed version's,
    # before a first deploy its source's); none: its name
    title: str | None = None
    description: str | None = None
    url: str  # its own origin, http://<name>.localhost:<port>/ (opened through POST …/open)
    state: AppState
    error: str | None = None
    current: AppDeployment | None = None  # None: registered, never deployed
    previous: AppDeployment | None = None  # what a rollback returns to
    source: AppSource
    # the version its source offers (Update), while it differs from its kept code's
    offered: AppOffered | None = None
    secrets: list[AppSecret] = []
    files: list[AppFileNeed] = []
    # the automations the version a deploy would install suggests (I.1): made at Install, or
    # later from its page
    suggests: list[AppManifestSuggestedAutomation] = []
    persons: list[str] = []  # who may use it from a paired device (H.8); none: local only
    last_used_at: Timestamp | None = None
    # the source its code came from (D.26; "official": Handler's); None: a file or a draft
    from_source: SourceId | None = None
    # its actions, what you can ask it (H.12): the installed version's (before a first deploy,
    # its source's)
    actions: list["AppAction"] = []
    # its nudges, what it may ask you to do (H.17), with how often each one alerts you
    nudges: list["AppNudge"] = []
    who_works: "WhoWorks | None" = None  # who runs its jobs (H.2); none: not chosen yet
    jobs: list["AppJob"] = []  # its jobs (H.1): the installed version's, else its source's


class WhoWorks(Document):
    """Who runs an app's jobs (H.2): a program (a harness) on an account or a provider, and a
    model; no program: the model alone, on a provider (D.18), for a job reaching no folder, tool
    or host. One per app, chosen by the person, and maybe one of a job's own."""

    program: HarnessName | None = None  # none: the model alone
    account: ResourceName | None = None
    provider: ResourceName | None = None
    model: Annotated[str, Field(min_length=1)] | None = None  # default: the program's or provider's

    @model_validator(mode="after")
    def _access(self) -> Self:
        if (self.account is None) == (self.provider is None):
            raise ValueError("name exactly one of 'account' and 'provider'")
        if self.program is None and self.provider is None:
            raise ValueError("the model alone runs on a provider: name a program for an account")
        return self

    @property
    def model_access(self) -> ModelAccess:
        """As an agent's model (E): its program the harness."""
        return ModelAccess(
            harness=self.program, account=self.account, provider=self.provider, model=self.model
        )


class AppJobCanDo(Document):
    """What a job reaches (H.1), its declaration's: the folders given to the app's files needs it
    reads or writes, those it works in, its schemas, its hosts."""

    files: dict[NeedName, JobAccess] = {}
    works_in: list[NeedName] = []
    schemas: list[SchemaId] = []
    egress: list[EgressEntry] = []


class AppJob(Document):
    """One of an app's jobs (H.1), as its page shows it: what it does and reaches, who runs it."""

    name: NeedName
    description: str
    can_do: AppJobCanDo
    who_works: WhoWorks | None = None  # its own, else the app's; none: nobody chosen yet
    own: bool = False  # `whoWorks` is the job's own, not the app's
    problem: str | None = None  # why it cannot run now (rule app-job.runs-as-its-who-works)


class AppNudge(Document):
    """One of an app's nudges (H.17), as its page shows it: what it asks, what a click opens,
    its reminders as the app says them and as you set them."""

    name: NeedName
    description: str
    action: NeedName | None = None
    open: str | None = None
    remind: AppManifestNudgeRemind | None = None
    if_ignored: str | None = None
    setting: NudgeSetting = "default"
    when: Schedule | None = None  # when handlerd sends it, as the app says; none: its code does
    own_when: Schedule | None = None  # yours, replacing the app's
    next_at: Timestamp | None = None  # its next slot, with a `when`
    prepared: bool = False  # its app's code prepares each one (`prepare`), or skips it
    off: bool = False  # you turned it off: none comes, its `prepare` is not called


class AppAction(Document):
    """One of an app's actions (H.12), as its page and Ask's router see it."""

    name: NeedName
    description: str
    examples: list[str] = []
    # its code answers at once; its job's run takes a while
    by: Literal["code", "job"]
    # its form: the route's or the job's; None: it takes nothing
    fields: dict[str, Any] | None = None
    # offered to Ask (D.24), yours per action; off: still tried on its page and opened by a nudge
    in_ask: bool = True


class ActionRequest(Document):
    """`POST /v1/apps/{name}/actions/{action}`: the action's form, filled; from a nudge (H.17),
    which it makes done when it succeeds."""

    fields: dict[str, Any] = {}
    nudge: str | None = None  # the inbox message of an open nudge pointing at this action


class NudgeSettingRequest(Document):
    """`PUT /v1/apps/{name}/nudges/{nudge}`: how that nudge reminds you (H.17)."""

    setting: NudgeSetting


class NudgeOffRequest(Document):
    """`PUT /v1/apps/{name}/nudges/{nudge}/off`: that nudge turned off (none comes, its app's
    `prepare` not called; its open ones stay, reminding no more) or on again (from its next
    slot) (H.17)."""

    off: bool


class NudgeWhenRequest(Document):
    """`PUT /v1/apps/{name}/nudges/{nudge}/when`: when handlerd sends that nudge (H.17), yours
    replacing the app's; null: as the app says."""

    when: Schedule | None


class NudgeFillRequest(Document):
    """`POST /v1/inbox/{id}/fill`: what the person said (written down, D.25), to fill the form
    of the nudge's action (H.17)."""

    said: Annotated[str, Field(min_length=1, max_length=2000)]
    timezone: str | None = None  # the device's (`Europe/Paris`): dates worked out from it


class NudgeFill(Document):
    """The nudge's form as what was said fills it (Ask's router, its action alone offered):
    never sent; `question` when it could not be filled."""

    said: str
    fields: dict[str, Any] | None = None
    question: str | None = None


ActionState = Literal["running", "succeeded", "failed"]


class ActionRun(Document):
    """An action, done or under way (H.12)."""

    app: AppName
    action: NeedName
    state: ActionState
    result: ActionResult | None = None  # succeeded
    error: str | None = None  # failed: why
    run_id: str | None = None  # a job's action: its run (H.11), read again until it ends
    session_id: str | None = None  # a job's action: its run's session


class AppAskRequest(Document):
    """`PUT /v1/apps/{name}/ask`: the actions of the app you take out of Ask (D.24); the others
    are offered to it."""

    not_in_ask: list[NeedName]


# ── D.24 Ask: what the person says, routed to one of their apps' actions ─────


class AskTurn(Document):
    """One turn of an exchange with Ask: the person's words, or what Handler answered."""

    who: Literal["you", "handler"]
    text: Annotated[str, Field(min_length=1, max_length=2000)]


# where an ask comes from: Chat's Ask tab, a paired phone, `handler ask`, a key (`--listen --toggle`)
AskVia = Literal["web", "phone", "cli", "key"]


class AssistantRequest(Document):
    """`POST /v1/ask`: the exchange so far, the person's words last. The client sends it whole
    each time (a reply to a question is one more turn); Handler keeps each ask in Ask's history."""

    turns: Annotated[list[AskTurn], Field(min_length=1, max_length=20)]
    timezone: str | None = None  # IANA, where the person is (the device's); else the host's
    via: AskVia = "web"
    spoken: bool = False  # said aloud, then written down (D.25); else typed


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


# how an ask ended: the app's answer (done, done with something to read, failed), its job still
# running, a question back, no app for it; failed also when Ask or the speech model could not answer
AskOutcome = Literal["done", "attention", "failed", "running", "question", "none"]


class AskRecord(Document):
    """One ask Handler received, kept in Ask's history (D.24): what was said, where it went,
    how it ended."""

    id: str
    at: Timestamp
    via: AskVia
    spoken: bool  # said aloud, then written down (D.25)
    # the exchange, your words last; empty: what you said could not be written down
    turns: list[AskTurn]
    outcome: AskOutcome
    summary: str  # the app's answer, the question, why no app fits, or what went wrong
    answer: AssistantAnswer | None = None  # none: Ask could not answer


class AskHistorySettings(Document):
    """`PUT /v1/ask/history`: whether Handler keeps what you ask (off: it is emptied)."""

    keep: bool


class AskHistory(AskHistorySettings):
    """`GET /v1/ask/history`: the asks kept, newest first (the last 200, 30 days at most)."""

    asks: list[AskRecord]


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
    with the chosen model, never kept (its text is, once asked: Ask's history)."""

    audio: Annotated[str, Field(min_length=1)]  # base64, at most MAX_AUDIO bytes once decoded
    format: AudioFormat
    language: Annotated[str, Field(pattern=r"^[a-z]{2}$")] | None = None
    via: AskVia = "web"  # when it cannot be written down, Ask's history says where it came from


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
    # what it belongs to: "accounts/<name>", "providers/<name>", "connections/<name>", "apps/<app>";
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


class AppOpenRequest(Document):
    """`POST /v1/apps/{name}/open`: the page of its UI to open (what an action did, H.12)."""

    path: AppPage = "/"


class UiOpenRequest(Document):
    """`handler ui`: a one-time link opening the web UI, on a page of it or its first."""

    then: str | None = Field(default=None, pattern=r"^/([^/#?\s][^#?\s]*)?$")  # as `/setup/x`


class UiLink(Document):
    """A one-time link that opens the web UI in a browser and signs it in there (valid 2
    minutes): the browser keeps its cookie, so the UI opens from a bookmark afterwards."""

    url: str


class AppLog(Document):
    """The end of an app's log: its last deploy, then its backend's output."""

    text: str


# ── D.27 Plans: steps an agent wrote, approved by you, run one after another ─────

PlanState = Literal["running", "done", "stopped"]
PlanStepState = Literal["waiting", "running", "done", "failed", "cancelled"]


class PlanStep(Document):
    """One step of a plan (D.27): a goal, and how the step itself knows it is done."""

    n: Annotated[int, Field(ge=1)]
    title: str
    goal: str  # with any other text written under the step, as written
    done_when: str


class PlanStepResult(Document):
    """What a step's session ends with, in its `handler-result` block (D.27)."""

    status: Literal["done", "failed"]
    summary: str
    notes: str | None = None  # for the steps after it: they read it, never its session


class PlanRunner(Document):
    """An agent working in a plan's folder that may run its steps (D.27): offered on review."""

    id: str
    name: str
    bypass: bool  # False: it runs steps once switched to the mode bypass


class PlanRead(Document):
    """`POST /v1/plans/read`: a plan file of an agent's folder, read and parsed (D.27). It can be
    approved only with no problem, by sending back its digest."""

    path: str  # relative to the agent's folder
    digest: str  # sha256 of the bytes read, hex
    title: str | None = None
    agent: str | None = None  # the name its `Agent:` line gives
    # the agent that runs its steps: the runner chosen (`runnerId`), else the one of that name
    agent_id: str | None = None
    runners: list[PlanRunner] = []  # the agents working in its folder that may run its steps
    project_id: str | None = None  # the folder's project: where a plan runner is created
    context: str | None = None
    step_timeout_sec: int  # each step's turn: its `Step time limit:` line, or the default
    steps: list[PlanStep] = []
    problems: list[str] = []  # approval is refused while there is one
    # its agent runs on a subscription whose terms ask for an API key when unattended (E):
    # recommended, not refused
    recommendation: str | None = None
    text: str  # the file, as read


class PlanStepView(PlanStep):
    state: PlanStepState
    session_id: str | None = None  # its session, once started
    summary: str | None = None  # its result's
    notes: str | None = None  # its result's: what the next steps read
    error: str | None = None  # why it failed, when its result does not say
    started_at: Timestamp | None = None
    ended_at: Timestamp | None = None
    refused: list[RefusedHost] = []  # hosts the network filter refused to it (F.9)
    said: str | None = None  # what its agent's last message says of them, when it does


class PlanView(Document):
    """A plan you approved (D.27): Handler's own copy, run one step after another, each a fresh
    session of its agent, stopped at the first step not done."""

    id: str  # "p_" + 16 hex
    title: str
    source: str | None = None  # the file it was read from, relative to its folder; or…
    draft_id: str | None = None  # …the draft it was approved from
    folder: str  # the folder its steps work in: the file's, or the draft's project's
    digest: str  # the file's, as approved
    agent_id: str
    agent: str | None = None  # its agent's name, as of now; None once deleted
    context: str | None = None
    step_timeout_sec: int
    approved_at: Timestamp
    state: PlanState
    stopped_because: str | None = None
    steps: list[PlanStepView]


class ReadPlanRequest(Document):
    """A plan (D.27): a file in the folder of an agent, or of a session's agent (`agentId` or
    `sessionId`, and its `path`), or a draft (`draftId`); `runnerId` who runs it."""

    agent_id: NonEmpty | None = None
    session_id: NonEmpty | None = None
    path: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    draft_id: NonEmpty | None = None
    # the agent that runs its steps, chosen on review: instead of its `Agent:` line
    runner_id: NonEmpty | None = None

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        named = [n for n in (self.agent_id, self.session_id, self.draft_id) if n is not None]
        if len(named) != 1:
            raise ValueError("name exactly one of 'agentId', 'sessionId' and 'draftId'")
        if (self.path is None) != (self.draft_id is not None):
            raise ValueError("a file's 'path' goes with 'agentId' or 'sessionId', not 'draftId'")
        return self


class ApprovePlanRequest(ReadPlanRequest):
    """`POST /v1/plans`: approve the file as read, and run it (D.27)."""

    digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]  # the one `PlanRead` gave


class PlanDraft(Document):
    """A plan being written (D.27), kept by Handler, never in a folder of yours: changed by its
    builder session or by hand, approved into a plan (a new one each time)."""

    id: str  # "d_" + 16 hex
    project_id: str
    folder: str  # its project's, where its plan's steps will work
    title: str | None = None  # its `# Plan:` line, as it is now
    digest: str  # sha256 of its text as it is now, hex: saving an edit sends it back
    created_at: Timestamp
    changed_at: Timestamp  # its text's last change
    session_id: str | None = None  # its plan builder session, once started
    from_plan: str | None = None  # Edit as a new draft: the plan it started as a copy of


class CreatePlanDraftRequest(Document):
    """`POST /v1/plan-drafts`: an empty draft for a project, or a copy of an approved plan."""

    project_id: NonEmpty | None = None
    from_plan: NonEmpty | None = None

    @model_validator(mode="after")
    def _project_or_plan(self) -> Self:
        if (self.project_id is None) == (self.from_plan is None):
            raise ValueError("name exactly one of 'projectId' and 'fromPlan'")
        return self


class SavePlanDraftRequest(Document):
    """`PUT /v1/plan-drafts/{id}`: its text, edited by hand, over the one read (its digest)."""

    text: Annotated[str, Field(max_length=256 * 1024)]
    digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RunPlanRequest(Document):
    """`POST /v1/plans/{id}/run`: run it again from a step (D.27)."""

    from_: Annotated[int, Field(ge=1, alias="from")]
    # *Allow and run again*: hosts refused to that step, allowed for its agent first (F.9)
    allow: list[str] = []


class InboxAnswerRequest(Document):
    """`POST /v1/inbox/{id}/answer`: hosts of a message's `refused` allowed or kept blocked for
    its agent (F.9); a session's agent is told; `again` (allowed only) runs its plan from its
    step, or its automation, again."""

    decision: HostDecision
    hosts: Annotated[list[str], Field(min_length=1)]
    again: bool = False


class Problem(Document):
    """RFC 9457 problem details, used for every Control API error."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    # 409 `toolbox changes not confirmed`: the system packages the save adds, to send back
    toolbox_adds: list[str] | None = None
