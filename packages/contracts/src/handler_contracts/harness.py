"""Contract B — Harness adapter (`handler.harness/v1`) and render output
(`handler.harness-launch/v1`)."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from .common import (
    AbsolutePath,
    Document,
    EgressEntry,
    EnvMap,
    EnvName,
    GeneratedFile,
    HomePath,
    McpServer,
    McpTransport,
    Mount,
    PermissionMode,
    StrictDocument,
)
from .provider import Protocol

HARNESS_API_VERSION = "handler.harness/v1"
HARNESS_LAUNCH_API_VERSION = "handler.harness-launch/v1"

# B.6: every harness image records what it installed, one line of text, e.g.
# "Claude Code 2.1.280 (claude-agent-acp 0.81.2)".
IMAGE_VERSION_FILE = "/usr/share/handler/version"

NonEmpty = Annotated[str, Field(min_length=1)]


def _untagged_image(image: str) -> str:
    """B.6: the descriptor names the image repository; the platform owns the tags."""
    last = image.rsplit("/", 1)[-1]
    if ":" in last or "@" in last:
        raise ValueError("must not carry a tag or digest (launches use ':latest')")
    return image


ImageRepository = Annotated[str, Field(min_length=1), AfterValidator(_untagged_image)]


class PermissionMapping(Document):
    """How a neutral permission mode is applied. Decision 4: ACP session mode preferred;
    `env` only when the harness has no ACP mode for it. `{}` = harness default matches.
    A mode the harness cannot honour is left out of `permissions` (e.g. pi never asks)."""

    session_mode: NonEmpty | None = None
    env: EnvMap | None = None


class StateSlot(Document):
    target: HomePath
    kind: Literal["dir", "file"]
    required: bool
    read_only: bool = False
    per_session: bool = (
        False  # the harness's session history: bound per session by the daemon (F.2)
    )
    # the file an account's login leaves (`login.file`): handler keeps it and binds it. Any other
    # slot is the agent's own state (history, settings): a folder handler keeps
    credential: bool = False
    # a file of the agent's own state: what handler writes in it when it creates it (default `{}`
    # for JSON, else empty), e.g. Claude Code's ~/.claude.json marked as onboarded
    initial: str | None = None

    @model_validator(mode="after")
    def _initial_is_for_a_file_handler_creates(self) -> Self:
        if self.initial is not None and (
            self.kind != "file" or self.credential or self.per_session or self.read_only
        ):
            raise ValueError("'initial' is for a file of the agent's own state")
        return self


class ConfigFileSlot(Document):
    """A config file the harness reads; its content comes from the provider (`files.<harness>`),
    and it is mounted read-only at `target` (e.g. Vibe's ~/.vibe/config.toml)."""

    target: HomePath
    required: bool = False
    description: str | None = None
    seed: bool = False  # the harness rewrites the file (e.g. Vibe saves the chosen model)


Unattended = Literal["allowed", "check-terms", "refused"]


class LoginRecipe(Document):
    """How an account of this harness is logged in (D.9), one of two kinds:

    - a token login (`token`: the env var the harness reads it from): the person runs
      `tokenCommand` themselves, the harness's own sign-in, and gives handler the token it prints
      (pasted, or a reference to where they keep it). handler never runs that sign-in nor reads its
      output (Anthropic: sign-in through its own flow, credentials provisioned by the person).
    - a file login (`file`: a credential state slot, whose file name it has there): handler runs
      `command` interactively on the host (its browser, its callbacks), with `env`, where `{dir}`
      is a folder handler gives it for its state instead of the person's home; the file it writes
      there becomes the account's login."""

    subscription: NonEmpty  # what people call the plan it signs in to, e.g. "Claude Pro or Max"
    # whether the vendor's terms allow its subscription to run unattended (an automation's agent
    # run, I.7), as read in `terms` on `checked` (absent: not read yet): "allowed", "check-terms"
    # (unclear or not read yet: allowed with a warning), "refused"
    unattended: Unattended
    terms: Annotated[str, Field(pattern=r"^https://")]
    checked: date | None = None
    token: EnvName | None = None
    # a token login: what the person runs (e.g. "claude setup-token"), how its token starts (to
    # tell it from something else its sign-in shows, refused when given and at launch), and how
    # long it lasts
    token_command: NonEmpty | None = None
    token_prefix: NonEmpty | None = None
    token_lifetime_days: Annotated[int, Field(gt=0)] | None = None
    file: NonEmpty | None = None
    command: Annotated[list[NonEmpty], Field(min_length=1)] | None = None  # a file login's
    env: EnvMap = {}  # a file login's
    hosts: list[EgressEntry] = []  # what a session logged in with it reaches (A.3)
    help: str | None = None  # one line for the person logging in
    # the subscription's plans an account of it may name (`plan`), and the env var the harness
    # reads it from: a token login leaves it unknown to the harness (Claude Code then says
    # "Claude API" and picks an API user's default model)
    plans: list[NonEmpty] = []
    plan_env: EnvName | None = None

    @model_validator(mode="after")
    def _token_or_file(self) -> Self:
        if (self.token is None) == (self.file is None):
            raise ValueError("a login leaves exactly one of 'token' and 'file'")
        if self.token is not None:
            if self.token_command is None:
                raise ValueError("a token login says what the person runs: 'tokenCommand'")
            if self.command is not None or self.env:
                raise ValueError("handler runs no token login: no 'command' or 'env'")
        else:
            if self.command is None:
                raise ValueError("a file login has the 'command' handler runs")
            if any(
                v is not None
                for v in (self.token_command, self.token_prefix, self.token_lifetime_days)
            ):
                raise ValueError(
                    "'tokenCommand', 'tokenPrefix' and 'tokenLifetimeDays' are for a token login"
                )
            if not any("{dir}" in v for v in self.env.values()):
                raise ValueError("a file login writes its file into '{dir}': give it in 'env'")
        if bool(self.plans) != (self.plan_env is not None):
            raise ValueError("'plans' and 'planEnv' go together")
        return self

    @property
    def kind(self) -> Literal["token", "file"]:
        return "token" if self.token is not None else "file"


class TerminalCommand(Document):
    """The harness's own terminal program, run instead of its ACP adapter by `handler terminal`
    (D.16): the agent's settings are given to it as flags. `permissions`: the flags of each
    neutral mode (`[]`: its default matches); `modelFlag`, `mcpConfigFlag`: the flags taking the
    model and the file of MCP servers (Claude Code's `--mcp-config` format); or, for a program
    without them, `modelEnv`, `mcpServersEnv`: the env vars taking the model and the MCP servers
    (a JSON list in Vibe's `mcp_servers` format). `instructionsFlag`: the flag taking the agent's
    instructions, added to the program's system prompt; without it, an agent with instructions
    has no terminal."""

    command: Annotated[list[NonEmpty], Field(min_length=1)]
    permissions: dict[PermissionMode, list[NonEmpty]]
    model_flag: NonEmpty | None = None
    model_env: EnvName | None = None
    mcp_config_flag: NonEmpty | None = None
    mcp_servers_env: EnvName | None = None
    instructions_flag: NonEmpty | None = None

    @model_validator(mode="after")
    def _one_way_each(self) -> Self:
        if self.model_flag and self.model_env:
            raise ValueError("the model is given by 'modelFlag' or 'modelEnv', not both")
        if self.mcp_config_flag and self.mcp_servers_env:
            raise ValueError(
                "MCP servers are given by 'mcpConfigFlag' or 'mcpServersEnv', not both"
            )
        return self


class AccountConnectors(Document):
    off_env: EnvMap


CacheName = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")]


class CacheDeclaration(StrictDocument):
    """A cache of the toolbox (B.6): the home path it is mounted at, what it holds, and whether
    it is a general folder any tool writes to (`~/.cache`) rather than one tool's (`~/.cargo`)."""

    target: HomePath
    about: Annotated[str, Field(max_length=200)] = ""
    general: bool = False


class ToolboxManifest(StrictDocument):
    """`images/toolbox/toolbox.toml` (B.6): what the toolbox image declares besides its recipe.
    `caches`: the toolchains' state kept between sessions, by name (cargo → `~/.cargo`); each
    project chooses whether its agents keep their own or use the global ones (D.8)."""

    caches: dict[CacheName, CacheDeclaration] = {}


class HarnessDescriptor(Document):
    api_version: Literal["handler.harness/v1"]
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*$")]
    product: NonEmpty  # its product name, as people know it and the UI shows it ("Claude Code")
    image: ImageRepository
    acp_command: Annotated[list[NonEmpty], Field(min_length=1)]
    home: AbsolutePath
    state_slots: dict[str, StateSlot] = {}
    config_files: dict[str, ConfigFileSlot] = {}
    login: LoginRecipe | None = None  # none: it runs only on a provider
    # the protocols of the providers it can use, empty: it only runs on its account.
    # `handler_harness` holds, for each harness with some, how a provider is written in its
    # configuration
    provider_protocols: list[Protocol] = []
    permissions: dict[PermissionMode, PermissionMapping]
    model_option: NonEmpty | None = None  # ACP config option id used for NeutralConfig.model
    skills_dir: HomePath | None = None  # where the harness loads user skills (agents', addons')
    mcp_transports: list[McpTransport] = []  # MCP servers it accepts in session/new (B.2)
    # the environment it starts stdio MCP servers with: "inherit" = its own, minus its secrets;
    # "sandbox" = anything else (a reduced one, or with its secrets): `render` wraps them with
    # handler-sandbox-env, which gives them the sandbox's environment without the harness's secrets
    mcp_env: Literal["inherit", "sandbox"] = "inherit"
    # the harness ignores session/new's MCP servers and reads them from this file instead (the
    # common mcp.json format): `render` writes it, read-only
    mcp_config_file: HomePath | None = None
    env: EnvMap | None = None
    writable_paths: list[HomePath] | None = None
    account_connectors: AccountConnectors | None = None
    terminal: TerminalCommand | None = None  # none: no `handler terminal` for it

    @model_validator(mode="after")
    def _some_permission_mode_mapped(self) -> Self:
        if not self.permissions:
            raise ValueError("permissions must map at least one mode")
        return self

    @model_validator(mode="after")
    def _terminal_has_the_same_modes(self) -> Self:
        if (
            self.terminal is not None
            and self.terminal.permissions.keys() != self.permissions.keys()
        ):
            raise ValueError("terminal.permissions must map the same modes as permissions")
        return self

    @model_validator(mode="after")
    def _credential_slots_are_files(self) -> Self:
        for name, slot in self.state_slots.items():
            if slot.credential and (slot.per_session or slot.kind != "file"):
                raise ValueError(f"state slot '{name}': a credential is a file, not per-session")
        return self

    @model_validator(mode="after")
    def _login_file_is_a_credential_slot(self) -> Self:
        if self.login is not None and self.login.file is not None:
            slot = self.state_slots.get(self.login.file)
            if slot is None or not slot.credential:
                raise ValueError(f"login.file '{self.login.file}' is not a credential state slot")
        return self

    @model_validator(mode="after")
    def _one_per_session_slot(self) -> Self:
        if len([s for s in self.state_slots.values() if s.per_session]) > 1:
            raise ValueError("at most one state slot may be perSession")
        return self


class SessionDefaults(Document):
    """Applied by the control plane to every session: MCP servers added to `session/new`,
    `session/load` and `session/resume` (P8); mode and options right after `session/new` (P7)."""

    mode_id: NonEmpty | None = None  # → session/set_mode
    config_options: dict[str, str] | None = None  # → session/set_config_option, one per entry
    mcp_servers: list[McpServer] | None = None  # → params.mcpServers (P8)


class HarnessLaunch(Document):
    """Output of `render` (B.3): intent only, no sandbox implementation details (B2)."""

    api_version: Literal["handler.harness-launch/v1"]
    image: NonEmpty
    argv: Annotated[list[NonEmpty], Field(min_length=1)]
    home: AbsolutePath
    env: EnvMap
    files: list[GeneratedFile]
    mounts: list[Mount]
    writable_paths: list[AbsolutePath] = []
    egress: list[EgressEntry]
    session_defaults: SessionDefaults | None = None
