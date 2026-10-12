# Handler — Contracts

Status: **draft v1**, 2026-09-23.
Companion to `architecture.md`, which explains the *why*. This document defines the *what*:
the data formats and behaviours each block must honour so any block can be replaced.

## 0. Conventions

- **MUST / MUST NOT / SHOULD** are normative.
- Contracts are **data across process boundaries** (JSON, TOML, NDJSON, HTTP). No block imports
  another block's code. Types below use TypeScript notation for readability only; the JSON Schemas
  in `schemas/` are the language-neutral form.
- Every document carries an `apiVersion` (`handler.<contract>/v<N>`). A consumer MUST reject a major
  version it does not know. Additive fields are allowed within a major version; consumers MUST
  ignore unknown fields. **Exception: accounts and providers (E)** are hand-written, so unknown
  keys are errors (typo protection).
- Reference implementation of every type: `packages/contracts` (Python, pydantic, `handler_contracts`).
  JSON Schemas in `schemas/` are generated from it (`uv run python -m handler_contracts.schemas`); CI
  fails if they drift. TypeScript clients generate their types from `schemas/`.
- All host paths are **absolute** and canonical (symlinks resolved) before any check.
- Host paths in hand-written documents (providers, bindings) may start with `~/` (or be `~`):
  expanded to the home of the user running Handler when the document is read. `~user` is not
  supported. Sandbox-side paths (e.g. a cache `target`) keep `~` = the harness home.

## 1. Blocks and flow

```
 Web UI / CLI
   │  (D) Control API: create an agent          (C) ACP over WebSocket: /v1/agents/{id}/acp
   ▼
 CONTROL PLANE ── resolves (E) AgentSpec ── calls (B) Harness adapter.render ── builds (A) SandboxSpec
   │                                                                         │
   │  ACP policy pipeline (C) ◄──── NDJSON stdio ◄──── (A) Sandbox.launch ◄───┘
```

One ACP connection, end to end:

1. The client creates (or reuses) an **Agent** = its models (each a harness on an account or
   provider) × scope × settings (D). No container exists yet.
2. The client opens the Agent's ACP WebSocket (C).
3. The control plane resolves the model the connection runs with (its first for a plain
   connection; a session's own, F) with its account or provider (E) and calls the harness
   adapter (B) to get a `HarnessLaunch`.
4. The control plane merges the agent's settings + launch into a `SandboxSpec` (A) and
   launches it. The
   sandbox's stdio **is** the agent's ACP stream.
5. Messages flow through the policy pipeline (C) until either side closes. Closing the WebSocket
   kills the sandbox; the sandbox exiting closes the WebSocket.

**Lifecycle rule: one sandbox instance per ACP connection, ephemeral** (`--rm`).
Persistence (sessions, history) lives only in the agent's state mounts (E6).

**Daemon-held sessions (F)** relax this for interactive chats: a **Session** owns one
sandbox, which outlives the WebSocket attached to it (reload, another tab). Plain agent connections (C)
keep the rule above; editors (`handler acp` outside projects) and `handler terminal` use them.

---

## E. What an agent runs as — Account `handler.account/v1` · Provider `handler.provider/v1`

**Owner:** the user (TOML, written through the Control API or by hand: accounts D.9, providers
D.12). **Consumer:** control plane only.
**Location:** `~/.config/handler-ai/accounts/<name>.toml` and `~/.config/handler-ai/providers/<name>.toml` (one
per file, name = file stem; `HANDLER_ACCOUNTS_DIR`, `HANDLER_PROVIDERS_DIR`).

An agent (D.1; of a project, D.8, or ad hoc) runs a **harness** (B) whose model calls
use **one** account **or one** provider (never both, never none), with a **model**:

- An **account** is a subscription one harness logs in with (a Claude Pro or personal
  subscription, a ChatGPT plan, a Mistral account's Vibe key): the credential was issued for that
  harness, through its login (B.1 `login`). The file holds its harness, a description, its plan,
  whether its connectors are used, and a token login's `token` (a reference: the person's own
  token, D.9); a file login's credential file is kept by Handler. An account brings its harness. A general-purpose API key is not an account: it is a provider's.
- A **provider** is where model calls go: an endpoint for each protocol the server speaks
  (`anthropic`, `openai-chat`, `responses`), an optional key, the models it serves, and the
  config files some harness needs to talk to it (`[files.<harness>]`, e.g. Codex's system prompt
  for a model it does not know). Any harness that accepts one of its protocols (B,
  `providerProtocols`) may use it; the agent says which.

`AgentSpec` is that, resolved: the harness, the account's login file and plan and connectors, or
the provider and its files for this harness, and the model. It is what `render` takes (B.3).
Skills, tools and how the agent is contained (network, permission mode, confinement) are the
agent's own (D.8, D.17, G.3); the folders agents may work in are the machine's (D.13).

```ts
type Account = {
  apiVersion: "handler.account/v1";
  harness: string;                      // a harness with a `login` (B.1), e.g. "claude-code", "codex"
  description?: string;                 // e.g. the email it was made with: shown by `handler terminal`
  plan?: string;                        // its subscription's plan, one of its harness's
                                        // `login.plans` (else invalid): given to the harness in
                                        // `login.planEnv`; what the file says, not checked
  connectors?: boolean;                 // its harness may use the account's own connectors
                                        // (claude.ai MCP servers), where it has some (B.1
                                        // `accountConnectors`, else invalid); default false
  token?: SecretRef;                    // a token login's token (D.9), a reference (E2):
                                        // `{ secret = "accounts/<name>/token" }` when pasted
                                        // through handler, else where the person keeps it (`env`,
                                        // `file`, `command`); none until logged in; invalid for
                                        // a file login (its file is kept by handler, D.9)
  contexts?: string[];                  // the project contexts it may be used in (D.19): their
                                        // names, or "any"; none: only projects without a context
};

type Provider = {
  apiVersion: "handler.provider/v1";
  description?: string;
  endpoints: Partial<Record<Protocol, string>>;  // ≥ 1: http(s) URL to give a harness that speaks it
  apiKey?: SecretRef;                   // none for a local server
  models: ProviderModel[];              // ≥ 1, unique ids
  files?: Record<string, Record<string, FileSource>>;  // harness → its config file slot (B.1
                                        // configFiles) → content source
  contexts?: string[];                  // the project contexts it may be used in (D.19), as an
                                        // account's
};
type Protocol = "anthropic" | "openai-chat" | "responses";
type ProviderModel = {
  id: string; name?: string; contextWindow?: number; maxOutput?: number;
  reasoning?: boolean; images?: boolean; temperature?: number;
  native?: Record<string, Record<string, unknown>>;  // per harness: merged into the entry written for it
};                                      // how each field reaches each harness: B.4

type AgentSpec = {                      // resolved by the control plane, given to render (B.3)
  harness: string;
  account?: string; provider?: string;  // exactly one
  accountLogin?: string;                // the account's credential file handler keeps (a file login)
  accountPlan?: string;
  providerSpec?: Provider;
  files?: Record<string, FileSource>;   // the provider's files for this harness
  config: NeutralConfig;                // { model?, accountConnectors } (B.2)
};

type SecretRef =
  | { secret: string }                  // handler's secret store (D.14), e.g. "providers/openrouter/apiKey"
  | { env: string }                     // read from the control plane's environment
  | { file: string }                    // read from a host file (first line, trimmed)
  | { command: string[] };              // stdout of a command (e.g. `pass show …`)

type FileSource =                       // a whole config file, e.g. Vibe's config.toml
  | { file: string }                    // a host file (≤ 1 MiB)
  | { env: string }                     // an environment variable of the control plane
  | { content: string };                // inline in the provider file
```

Example (the `claude-sandbox` function: an account; its login is the token the person's own
`claude setup-token` prints, given to Handler, D.9; agents name it, `account = "claude-perso"`):

```toml
# accounts/claude-perso.toml
apiVersion = "handler.account/v1"
harness = "claude-code"
description = "Claude, personal account"
```

A local model (one provider serves Codex, pi and Vibe; Codex gets its system prompt from it):

```toml
# providers/llamacpp.toml
apiVersion = "handler.provider/v1"
[endpoints]
openai-chat = "http://127.0.0.1:3000/v1"
responses = "http://127.0.0.1:3000/v1"
[[models]]
id = "qwen3.8-27B"
contextWindow = 200000
reasoning = true
[files.codex]
instructions_md = { content = "You are Codex…" }
```

Rules:
- E1. The control plane MUST refuse to run an agent whose account or provider is missing or
  invalid, that names both or neither, whose harness is unknown or differs from its account's,
  whose provider has no endpoint for a protocol the harness accepts (B, `providerProtocols`), or
  whose model is not one of its provider's models; an account whose harness is unknown or has no
  `login` (B.1), or uses connectors its harness lacks, is invalid. An account that is not logged
  in stays valid, but no agent starts on it (D.9). Agent saves check all of it (400
  `model access unusable`).
- E2. Secrets MUST be references. A provider or an account containing a literal key or token is
  invalid (an account's token: `token`, D.9; a file login's file is kept by Handler). A `{ secret }`
  reference names a value in Handler's store (D.14); it is set there, never in the file.
- E3. **A secret reaches the sandbox as a phantom** (status: implemented 2026-10-08,
  `secrets.Delivery`, `launcher.py`): the control plane gives `render` a stand-in of the same
  length and form (a digit for a digit, a letter for a letter of the same case, other
  characters and a vendor's prefix such as `sk-ant-oat01-` kept when at least 24 characters
  follow it), random at each launch, and the sandbox's proxy an injection (A.3) that swaps it
  back towards the secret's hosts: an account's token towards its login's hosts (B.1
  `login.hosts`), a provider's key towards its endpoints' hosts, a binding's secret towards its
  addon's `egress` (G.1). Injections are named after the store's path for the secret, whatever
  its reference: `accounts/<name>/token`, `providers/<name>/apiKey`,
  `bindings/<name>/<slot>`. The sandbox gets the value itself only when it cannot be injected: no
  host to give it to (an addon without `egress`), or a value under 8 characters or with a
  character other than printable ASCII without space. Without network (`none`) it gets a phantom
  and no injection: nothing can be reached, and the value is never written to its folders.
  A file login's credential file (Codex's `auth.json`, Vibe's `.env`) is still the real one.
- E4. **Egress comes from where the traffic comes from**, never from the harness: the sandbox's
  allow-list is the union of the hosts of its harness's login when the agent uses an account
  (B.1 `login.hosts`), the provider's endpoint host (derived; the
  loopback of the machine is the container host's name in a container, `host.containers.internal`),
  the addons' hosts (G) and the agent's own (D.1). The first two are those of the model the
  sandbox runs with (one of the agent's, D.1), never of its other models. The first three are
  listed on each of the Agent's `models` as `requiredHosts`, each with what requires it.
- E5. A provider's key, like an account's token, reaches the harness only through an environment
  variable (B3), named by its adapter (the token: `login.token`), and every protection of the
  harness's secrets covers it (B.3: dropped from the MCP servers' environment); never a file.
- E6. The harness's own state (history, settings) is the agent's: `render` binds each state slot
  of the harness that is not a login file and not per-session (F.2) to
  `<data>/agent-state/<agent id>/<harness>@<account or provider>/<slot>`: each agent its own
  (one project's transcripts never reach another), one per model it runs with (another harness
  never reads them). Handler creates what is missing there: a folder, or a file with the
  slot's `initial` (default `{}` for JSON, else empty), never rewritten after.

---

## B. Harness adapter — `handler.harness/v1`

**Owner:** platform (one per harness). **Consumer:** control plane.
**Form:** a directory `harnesses/<name>/` of the platform's data (`handler_harness/data/`, shipped
read-only with Handler) with `harness.toml` (descriptor), an image recipe
(`Containerfile`), and optional templates. `render` is a **pure function** implemented by the control
plane from the descriptor; a harness MAY supply a `render` executable (stdin JSON → stdout JSON)
when templating is not enough.

### B.1 Descriptor

```ts
type HarnessDescriptor = {
  apiVersion: "handler.harness/v1";
  name: string;                         // "claude-code"
  product: string;                      // its product name, the one the UI shows: "Claude Code"
  image: string;                        // repository, no tag (B.6), e.g. "localhost/handler-ai-claude-code"
  acpCommand: string[];                 // argv speaking ACP on stdio, e.g. ["claude-agent-acp"]
  home: string;                         // in-sandbox HOME for the harness (e.g. "/home/agent"); the uid is the host user's (A3)

  stateSlots: Record<string, {          // three kinds: a login file, the session history, the rest
    target: string;                     // in-sandbox path, "~" = home
    kind: "dir" | "file";
    required: boolean;
    readOnly?: boolean;                 // default false: mounted read-only (e.g. a login file the
                                        // harness never rewrites)
    perSession?: boolean;               // the harness's session history (F.2): bound by the daemon
                                        // to the Session's own folder; at most one
    credential?: boolean;               // a login file (a file, not per-session): the one an
                                        // account's login leaves (`login.file`), kept by handler and
                                        // bound on top of the home; every other slot is the
                                        // agent's own state (E6): a folder handler keeps, or `state`
    initial?: string;                   // a file of the agent's own state: its content when handler
                                        // creates it (E6; default `{}` for JSON, else empty)
  }>;

  login?: {                             // how an account of it is logged in (D.9); none: providers only
    unattended: "allowed" | "check-terms" | "refused";   // whether the vendor's terms let an
                                        // automation run an agent on it (I.7); "check-terms":
                                        // unclear or not read yet, allowed with a warning
    terms: string;                      // https: the vendor's terms
    checked?: string;                   // "2026-10-05": when handler read them; absent: not yet
    subscription: string;               // what people call the plan it signs in to, e.g. "Claude
                                        // Pro or Max": how Model access offers it (D.9)
    // a token login (exactly one of `token` and `file`): the person runs `tokenCommand`
    // themselves, the vendor's own sign-in, and gives handler the token it prints; handler never runs it
    // nor reads its output (D.9)
    token?: string;                     // the env var the harness reads the token from
    tokenCommand?: string;              // what the person runs, e.g. "claude setup-token"
    tokenPrefix?: string;               // how its token starts: anything else (e.g. a code the
                                        // sign-in page shows) is refused when given and at launch
    tokenLifetimeDays?: number;         // how long a token lasts (`AccountInfo.expiresAt`)
    // a file login: handler runs `command` on the host and keeps the file it writes
    file?: string;                      // a credential state slot, its file name in `{dir}`
    command?: string[];                 // run interactively on the host (D.9): npx/uvx fetch it
    env?: Record<string, string>;       // for it; `{dir}`: a folder handler gives it for its state
                                        // instead of the person's home (required)
    hosts: string[];                    // what a session logged in with it reaches (E4)
    help?: string;                      // one line for the person logging in
    plans?: string[];                   // the subscription plans an account may name (E), and
    planEnv?: string;                   // the env var `render` gives it in (both or neither): a
                                        // login that does not tell the harness its plan
  };

  configFiles: Record<string, {         // config files the harness reads; content from a provider's [files.<harness>]
    target: string;                     // in-sandbox path, "~" = home
    required?: boolean;
    seed?: boolean;                     // the harness rewrites it → seeded copy (A.1), not a mount
  }>;

  providerProtocols?: ("anthropic" | "openai-chat" | "responses")[];
                                        // the protocols of the providers it can use, its first
                                        // choice first; none: it only runs on an account. Each
                                        // harness with some has, in handler_harness/providers.py,
                                        // the function writing a provider in its configuration
                                        // (env, config files). No `egress`: the hosts belong to the
                                        // account and the provider (E4)

  permissions: Partial<Record<"ask" | "accept-edits" | "bypass", PermissionMapping>>;
                                        // at least one; a mode left out is one the harness cannot
                                        // honour (pi never asks, codex never asks before an edit):
                                        // an agent asking for it is refused
  modelOption?: string;                 // ACP config option id that selects the model (NeutralConfig.model)
  skillsDir?: string;                   // where the harness loads user skills, "~" = home (B.3 skills)
  mcpTransports?: ("stdio" | "http" | "sse")[];  // MCP servers it accepts in session/new
                                        // (B.3 mcpServers); default none
  mcpEnv?: "inherit" | "sandbox";       // the env it starts stdio MCP servers with: "inherit" =
                                        // its own minus its secrets (default); "sandbox" = any
                                        // other (reduced, or with its secrets): render wraps them
                                        // with handler-sandbox-env (B6)
  mcpConfigFile?: string;               // "~" = home: the harness ignores session/new's MCP
                                        // servers and reads them from this file (common mcp.json
                                        // format): render writes them there too, read-only (B7)

  env?: Record<string, string>;         // static env (e.g. NODE_USE_ENV_PROXY=1)
  writablePaths?: string[];             // in-sandbox paths needing a tmpfs when rootfs is read-only

  terminal?: {                          // its own terminal program, for `handler terminal` (D.16);
                                        // none: the harness has no terminal there
    command: string[];                  // e.g. ["claude"], run instead of acpCommand
    permissions: Partial<Record<"ask" | "accept-edits" | "bypass", string[]>>;
                                        // the flags of each mode ([]: its default matches);
                                        // exactly the modes `permissions` maps
    modelFlag?: string;                 // takes the model (NeutralConfig.model)
    modelEnv?: string;                  // or: the env var taking it (not both)
    mcpConfigFlag?: string;             // takes the file of MCP servers (B8)
    mcpServersEnv?: string;             // or: the env var taking them, JSON (B8; not both)
    instructionsFlag?: string;          // takes the agent's instructions (B8); none: an agent
                                        // with instructions has no terminal
  };
};

type PermissionMapping = {
  sessionMode?: string;                 // PREFERRED: ACP mode id set via session/set_mode after session/new (P7), e.g. "bypassPermissions"
  env?: Record<string, string>;         // fallback only when the harness exposes no ACP mode for it, e.g. VIBE_BYPASS_TOOL_PERMISSIONS=true
};
// Decision 4: explicit ACP set_mode beats hidden settings files. A harness uses `env` only if it
// has no equivalent ACP session mode; settings files are not used for permissions.
```

Reference values:

| | claude-code | vibe | pi | codex |
|---|---|---|---|---|
| `acpCommand` | `["claude-agent-acp"]` | `["vibe-acp"]` | `["pi-acp"]` (spawns `pi --mode rpc`) | `["codex-acp"]` (drives `codex app-server`) |
| `stateSlots` | `config_dir → ~/.claude` (dir), `config_json → ~/.claude.json` (file, `initial` `{"hasCompletedOnboarding": true}`: its terminal's onboarding would ask to log in despite the token): the agent's own state | `env_file → ~/.vibe/.env` (`credential`, read-only); `sessions → ~/.vibe/logs/session` (`perSession`, F.2) | `sessions → ~/.pi/agent/sessions` (`perSession`, F.2) | `auth_json → ~/.codex/auth.json` (file, ChatGPT login: `credential`); `sessions → ~/.codex/sessions` (`perSession`, F.2) |
| `login` | plans `pro`, `max`, `team`, `enterprise` in `CLAUDE_CODE_SUBSCRIPTION_TYPE` (verified 2.1.286: a token login leaves the plan unknown, then it says "Claude API" and picks an API user's default model); a token login: the person runs `claude setup-token` (a one-year token, no refresh: any number of sandboxes share it) → `CLAUDE_CODE_OAUTH_TOKEN`; hosts `api.anthropic.com`, `platform.claude.com` | `uvx --from mistral-vibe vibe --setup` (sign in with the Mistral account; `VIBE_HOME={dir}`, no keyring: `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring`): `env_file` (`~/.vibe/.env`, read-only); host `api.mistral.ai` | none: no subscription of its own (its `/login` signs in to other vendors'), a provider only | `npx @openai/codex login` (file store, `CODEX_HOME={dir}`): `auth_json`; hosts `chatgpt.com`, `auth.openai.com` |
| `providerProtocols` | `anthropic` (`ANTHROPIC_BASE_URL`, key, model in env; the model is not chosen over ACP) | `openai-chat` (`[[providers]]` and `[[models]]` in `config.toml`) | `openai-chat` (`models.json` and `settings.json`) | `responses` (`config.toml` with a model provider, and the model catalog) |
| `permissions` ask / accept-edits / bypass | `sessionMode`: `default` / `acceptEdits` / `bypassPermissions` | `sessionMode`: `ask` / `accept-edits` / `auto-approve` (probed M2; no env needed) | `bypass = {}` only (pi never asks); `ask`, `accept-edits` left out | `sessionMode`: `accept-edits` → `read-only`, `bypass` → `agent-full-access`; `ask` left out (no mode asks before an edit) |
| `modelOption` | `model` | `model` | `model` (pi-acp's session modes are thinking levels) | `model` |
| `skillsDir` | `~/.claude/skills` (claude-agent-acp loads `settingSources: user`) | `~/.vibe/skills` (`GLOBAL_SKILLS_DIR`) | `~/.pi/agent/skills` | `~/.codex/skills` (`$CODEX_HOME/skills`) |
| `mcpTransports` | `stdio`, `http`, `sse` | `stdio` (no `mcpCapabilities` advertised) | `stdio`, `http`, `sse` (through pi-mcp-adapter; `sse` via its SSE fallback) | `stdio`, `http` (no `sse`) |
| `mcpEnv` | `inherit` (its env minus its token) | `sandbox` (it gives only `HOME`, `PATH` and the entry's env) | `sandbox` (it gives pi's env, provider keys included) | `sandbox` (Codex gives stdio servers a reduced env) |
| `mcpConfigFile` | — | — | `~/.config/mcp/mcp.json` (pi-acp ignores `session/new`'s `mcpServers`) | — |
| client `fs`/`terminal` delegation (blocked by P1/P4) | not tested; assume `["fs", "terminal"]` (the adapter advertises client terminals and edit review) | `["fs", "terminal"]` (verified in `acp-sandbox-filter.py`) | none (pi-acp: no fs/terminal delegation) | none |
| `env` | `NODE_USE_ENV_PROXY=1`, `DISABLE_AUTOUPDATER=1`; privacy: `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY=1` | privacy: `VIBE_ENABLE_TELEMETRY=false`, `VIBE_ENABLE_UPDATE_CHECKS=false`, `VIBE_ENABLE_AUTO_UPDATE=false` | `NODE_USE_ENV_PROXY=1`, `PI_ACP_PI_COMMAND=handler-pi` (pi + pi-mcp-adapter), `PI_SKIP_VERSION_CHECK=1`; privacy: `PI_TELEMETRY=0`, `PI_OFFLINE=1` | `CODEX_HOME=~/.codex`, `NO_BROWSER=1`, `DEFAULT_AUTH_REQUEST` (API-key login when there is no `auth_json`); privacy: `CODEX_PATH=handler-codex` (Codex with `-c analytics.enabled=false`, `feedback.enabled=false`, `check_for_update_on_startup=false`, `otel.metrics_exporter=none`) |
| `accountConnectors = false` → env | `ENABLE_CLAUDEAI_MCP_SERVERS=false` (verified) | n/a | n/a | n/a |
| `terminal` | `claude` (the SDK's native binary, linked by the image: the adapter's version), flags ask / accept-edits / bypass: `--permission-mode default` / `--permission-mode acceptEdits` / `--dangerously-skip-permissions`; `--model`, `--mcp-config` | `vibe`, flags ask / accept-edits / bypass: `--agent ask` / `--agent accept-edits` / `--agent auto-approve`; `VIBE_ACTIVE_MODEL`, `VIBE_MCP_SERVERS` (`VIBE_*` env overrides `config.toml`, its MCP servers are added to the config's; verified 2.25.8) | — | — |

### B.2 Neutral config

```ts
type NeutralConfig = {
  model?: string;                       // harness-specific id; validated by the adapter
  accountConnectors?: boolean;          // default false: hide account-level connectors (e.g. claude.ai MCP) from sessions
};
```

### B.3 `render`

```ts
render(input: {
  descriptor: HarnessDescriptor;
  agent: AgentSpec;                     // resolved and checked (E1)
  scope: string;                        // validated, canonical
  secrets: Record<string, string>;      // resolved values, slot → value
  skills?: string[];                    // the agent's and its addons' skill folders (D.17, G4), one
                                        // skill each (a SKILL.md inside): mounted read-only at
                                        // <skillsDir>/<folder name>; names must be unique. When a
                                        // state slot binds the folder around skillsDir (e.g.
                                        // claude-code's config_dir), podman leaves an empty mount
                                        // point <folder name> in that folder
  mcpServers?: McpServer[];             // its addons' (G4), same shape as ACP session/new
                                        // mcpServers; given to every session (P8). Names unique;
                                        // each transport must be in the descriptor's
                                        // mcpTransports (B5)
  terminal?: string[];                  // the terminal program instead of ACP (B8, D.16): its
                                        // arguments after the flags of its settings
  permissionMode: "ask" | "accept-edits" | "bypass";  // the agent's starting mode (D.8), one
                                        // the descriptor maps (B5)
  caches?: Record<string, string>;      // home path ("~" = the harness home) → host folder: the
                                        // toolbox's caches (B.6) as the agent's project shares
                                        // them (D.8), mounted read-write (kind "cache")
}) => HarnessLaunch

type HarnessLaunch = {
  apiVersion: "handler.harness-launch/v1";
  image: string;
  argv: string[];
  env: Record<string, string>;          // includes secret env vars and permission env
  home: string;                         // descriptor.home
  files: { target: string; content: string; mode?: string }[];  // generated config, mounted read-only
  mounts: Mount[];                      // state slots and caches resolved to host paths (A.2)
  writablePaths: string[];              // descriptor.writablePaths, expanded
  egress: string[];                     // the login's hosts (an account) or the provider's host (E4) + anything config implies (e.g. MCP URLs)
  sessionDefaults?: {                   // applied by the control plane to every session (C.4)
    modeId?: string;                    //   → session/set_mode after session/new|load (P7)
    configOptions?: Record<string, string>;  // → session/set_config_option (e.g. model) (P7)
    mcpServers?: McpServer[];           //   → added to session/new|load|resume (P8)
  };
};
```

Rules:
- B1. `render` MUST be deterministic and side-effect free (no container, network or host writes).
- B2. The adapter MUST NOT know or emit sandbox-implementation details (Podman flags, networks,
  proxies). It emits intent (mounts, env, egress); contract A implements it.
- B3. Secrets MUST only appear in `HarnessLaunch.env` or `files`, never in `argv` (visible in `ps`).
- B5. An input the harness cannot honour (e.g. `model` without `modelOption`, skills without
  `skillsDir`, an MCP transport it does not accept) MUST make `render` fail with an explicit error,
  never be silently dropped (same principle as A1).
- B6. Stdio MCP servers see the sandbox's environment whatever the harness passes them: for a
  harness with `mcpEnv = "sandbox"` in a container, `render` rewrites each stdio server to
  `/opt/handler/bin/handler-sandbox-env --drop <the account token's and the provider key's env> -- <command> <args>`,
  and adds that script to the launch's `files` (mode `0755`, platform data: no toolbox needs to
  carry it, only `python3`). It restores the sandbox's environment (A8), without the harness's own secrets;
  the entry's `env` wins. Verified by `tests/harness` (a stdio server started at `session/new`
  sees the filtering proxy, not the harness's key) for claude-code and vibe.
- B7. For a harness with `mcpConfigFile`, `render` also writes the MCP servers (after B6) to that
  file, `{"mcpServers": {<name>: {command, args, env} | {url, headers}}}`, each
  with `directTools: true` (pi-mcp-adapter: the server's tools are tools of their own, as with the
  other harnesses, not behind one `mcp` proxy tool), and `settings` `allowInstall: false`,
  `scriptMode: false` (no installing servers from the model, no `mcpScript` tool). Values are
  written as they are: pi-mcp-adapter expands `${VAR}` in them. `sessionDefaults` still
  carries the servers (P3, P8); pi-acp ignores them. A client's own `session/new` servers do not
  reach such a harness.
- B8. With `terminal` (D.16), `argv` is the descriptor's `terminal.command`, then the flags of the
  agent's permission mode, `modelFlag <model>` (when the model is chosen over ACP: not for a
  provider, whose model is in its configuration), `mcpConfigFlag <file>` when there are MCP
  servers (after B6), `instructionsFlag <the agent's instructions>` when it has some (none: an
  error, never instructions left out), then the given arguments. The file, `~/.handler/terminal-mcp.json`, read-only,
  is `{"mcpServers": {<name>: {type: "stdio", command, args, env} | {type, url, headers}}}`; a
  generated file needs a container (A1), so MCP servers without one are an error. A terminal
  without those flags takes them in `env` instead: `modelEnv` = the model, `mcpServersEnv` = the
  servers as a JSON list in Vibe's `mcp_servers` format, `[{name, transport: "stdio", command,
  args, env}]` (stdio only). Everything else (state, caches, skills, the rest of `env`, egress)
  is the ACP launch's; there are no `sessionDefaults`. A
  harness without `terminal`, or a model or MCP servers its terminal cannot take, is an error (B5).

### B.4 Provider models

How a provider (E) is written in a harness's own configuration is the adapter's knowledge
(`handler_harness/providers.py`, one function per harness with `providerProtocols`); the provider
knows nothing of harnesses.

- B9. Every field of the provider's model MUST reach the harness wherever it has a setting for it;
  one it has no setting for is listed below, never silently assumed. In particular the limits:
  `contextWindow` is the window the harness measures the conversation against (and reports), and
  the harness MUST compact early enough to leave room for a reply: `reserve` = the model's
  `maxOutput`, else 16384 tokens, at most half the window. Without `contextWindow` the harness's
  own default applies (shown below): a provider of a smaller model must give it.

| | window | room for the reply | `maxOutput` | `name` |
|---|---|---|---|---|
| vibe | no setting of its own: `auto_compact_threshold` = `contextWindow − reserve` is both where it compacts and the window it reports (without: 200000) | that threshold | no setting | `display_name` |
| pi | `contextWindow` in `models.json` (without: 128000) | `settings.json` `compaction.reserveTokens` = `reserve`, only with a `maxOutput` (pi's own default is 16384) | `maxTokens` | `name` |
| codex | `context_window` and `max_context_window` of the model catalog (without: 128000) | Codex's own | not written (not checked) | `display_name` |
| claude-code | no setting: it knows Claude models' | Claude Code's own | no setting | — |

Verified against mistral-vibe 2.25.8 (`ModelConfig`, its auto-compact middleware) and
pi-coding-agent 0.99.2 (`models.json` schema, `shouldCompact`: `tokens > contextWindow − reserveTokens`).

### B.6 Images and versions

- The descriptor's `image` names a repository without tag or digest; the platform owns the tags.
  Agents launch `<image>:latest` (`render` emits it), the only tag. A rebuild (D.4) builds an
  untagged image and tags it `:latest` once checked; there is no rollback.
- The `Containerfile` is built `FROM ${TOOLBOX_IMAGE}` (a build argument set by the platform).
  Agent programs that release often are **not version-pinned**: a rebuild without cache installs
  their latest release; the rebuild's check (D.4) keeps a broken release away from agents, and
  automatic updates (D.4) rebuild on a schedule. Slow-moving parts (base image, toolchains) may stay pinned.
- The image MUST record what it installed in `/usr/share/handler/version`
  (`handler_contracts.IMAGE_VERSION_FILE`): one line of text for people, e.g.
  `Claude Code 2.1.280 (claude-agent-acp 0.81.2)`. The build SHOULD fail if it cannot be read,
  so a package layout change is noticed. It is shown in the UI and recorded on Sessions and
  Executions (`harnessVersion`).
- The toolbox is the **user's**: `~/.config/handler-ai/toolbox/` (`$HANDLER_TOOLBOX_DIR`), copied by handlerd
  from the platform's default on its first start and never changed by Handler afterwards (edited from
  the web UI, `GET`/`PUT /v1/toolbox/containerfile`, or by hand). What Handler needs from it: a glibc
  system with `sh`, what the recipes install with (`npm`, `uv`, `jq`), `python3` for
  `handler-sandbox-env` (B6), podman with setcap'd `newuidmap`/`newgidmap` for `nested` (A.5). Nothing
  else of Handler is in it. A toolbox lacking something fails its rebuild: the images built on it
  are checked before any switches (D.4).
- The toolbox declares its toolchains' caches in its `toolbox.toml`
  (`ToolboxManifest`): a `[caches.<name>]` table per cache (`CacheDeclaration`): `target`, the
  home path it is mounted at (`"~/.cargo"`), `about`, what it holds (shown in Settings → Caches),
  and `general = true` for a folder any tool writes to (`~/.cache`, `~/.local`) rather than one
  tool's; the default also keeps inner podman's image store, `podman`,
  `"~/.local/share/containers/storage"`, A.5. Their state is
  never baked into an image; each project chooses where its agents keep it (D.8).

Conformance (`tests/harness/<name>/`): golden `render` fixtures; built image answers `initialize`
within 10 s; a `bypass` agent completes a tool-using turn with zero `request_permission`;
every mapped ACP session mode and the model option exist in a real `session/new` (the same
check gates a rebuild, D.4).

---

## A. Sandbox — `handler.sandbox/v1`

**Owner:** platform (one implementation: rootless Podman). **Consumer:** control plane.
**Binding:** executable `handler-sandbox-<impl> launch` reading a `SandboxSpec` JSON on fd 3; after
setup, its stdin/stdout **are** the sandboxed process's stdin/stdout (ACP NDJSON), stderr carries
logs. Exits with the sandboxed process's exit code. SIGTERM → stop and clean up everything.
With `tty` (A.1), its stdio is not the process's: after setup it prints the line `handler-ready` on
stderr and waits for `handler-sandbox-<impl> attach <name>`, run by the client on its own terminal
(D.16), which starts the process there (raw, resized with that terminal, its signals passed on)
and exits with its exit code; when the terminal goes away first, `attach` stops the sandbox.
`launch` waits 60 s for that `attach` (else exits `66`), then until the process ends, and cleans
up; the sandbox, not `launch`, holds the process's terminal, so whoever ran `launch` can go
away meanwhile.
A second verb, `handler-sandbox-<impl> set-egress <name> enforce|log-only`, changes a running
instance's enforcement, and `set-allow <name> [entry …]` replaces its allow-list, enforcement
kept (A.4; entries are validated as in A.3, exit `65` otherwise). Another, `sweep`, removes
resources left by launchers that died without cleaning up (the control plane runs it at startup),
never those of a live launcher, even one still setting its sandbox up.
The `image` verbs build and manage images (A.7), `check` says whether this host can run
sandboxes (A.8), and the `cache` verbs measure and empty cache folders (A.9): the executable is the platform's only way to the container engine, so another
runtime is another executable.
A launcher is known by its pid and start time (a pid alone is reused by later processes, after a
reboot from the first ones).

Exit codes before the sandboxed process starts: `64` unenforceable (A1), `65` invalid spec,
`66` setup failed. Otherwise the sandboxed process's exit code.

Egress events are reported on stderr, one per line:
`handler-egress {"decision": "denied"|"allowed"|"unlisted", "host": "<host>:<port>"}` (A.3
observability; the target as the entry that would allow it). `unlisted`: let through in log only
(`log-only`) although no entry allows it, what enforcing would deny; judged against the entries
and enforcement in force when the request comes (A.4). An injection (A.3) adds
`{"decision": "injected"|"leak", "host": …, "secret": "<its name>"}`: its value given to a
request to that host, or its phantom seen going to a host it is not for (refused).
Other stderr lines are free-form logs.

### A.1 SandboxSpec

```ts
type GeneratedFile = {
  target: string; content: string; mode?: string;
  seed?: boolean;   // false: mounted read-only · true: written into a writable path (the home or a
                    // writablePaths entry) before start, may be rewritten, discarded with the instance
};

type SandboxSpec = {
  apiVersion: "handler.sandbox/v1";
  name: string;                         // unique per instance, e.g. "handler-<agent>-<conn>"
  confinement?: "strict" | "nested" | "privileged";  // default "strict" (A.5)
  image: string;
  argv: string[];
  env: Record<string, string>;
  workdir: string;                      // = scope
  user: { mode: "host-user"; home: string };  // v1: only "host-user" (A3)
  mounts: Mount[];
  imageMounts?: { image: string; target: string }[];  // read-only image filesystems (A6)
  pathAppend?: string[];                // appended to the image's PATH; env must not set PATH then
  files: { target: string; content: string; mode?: string }[];
  writablePaths: string[];              // tmpfs; a mount inside one (e.g. ~/.vibe/logs/session) leaves
                                        // the directories around it writable by the sandbox user
  network: NetworkPolicy;
  resources?: { memory?: string; cpus?: string };
  display?: { mode: "wayland"; socket: string };  // A.6: a host Wayland socket the process may use
  labels?: Record<string, string>;      // agent id, connection: for listing and cleanup
  tty?: boolean;                        // default false: stdio is the agent's ACP stream; true:
                                        // the process runs on a terminal (D.16) of its own
                                        // (podman --tty), the client's through `attach` (above)
  injections?: Injection[];             // secrets its proxy gives, not the process (A.3)
};

type Injection = {
  name: string;                         // what egress events call it (e.g. a secret's path)
  phantom: string;                      // what the process holds: printable, no space, ≥ 8
  value: string;                        // the secret: printable ASCII, exactly as long as phantom
  hosts: string[];                      // allow-list entries (A.3) it is given to; at least one
};

type Mount = {
  source: string;                       // host path, absolute
  target: string;                       // sandbox path; scope mounts MUST use target = source
  readOnly: boolean;
  kind: "scope" | "state" | "cache" | "config" | "knowledge" | "app" | "subject";
                                        // knowledge: read-only (D.5); app: a mini app's code and
                                        // socket folder (H.3); subject: what a run works on,
                                        // read-only (D.18)
};

type NetworkPolicy =
  | { mode: "none" }
  | { mode: "open" }
  | { mode: "filtered"; allow: string[]; enforcement: "enforce" | "log-only" };
// log-only = every HTTP(S) destination allowed through the proxy, but still logged.
// Switchable live (A.4) without restarting the agent. Non-HTTP egress stays blocked.
```

### A.2 Guarantees (normative)

- A1. **No silent degradation.** An implementation MUST refuse (exit non-zero before starting the
  process) any spec it cannot fully enforce. (Optional OCI hooks, for example, fail open.)
- A2. Only the listed mounts are visible from the host filesystem. The scope is mounted at the
  **same absolute path** (ACP `cwd` and paths in agent output stay valid).
- A3. Hardening defaults (confinement `strict`, A.5): all capabilities dropped,
  `no-new-privileges`, read-only rootfs, rootless runtime. **User (decision 3):** the process MUST NOT run as root. It runs with the **host user's
  uid/gid** (`user.mode = "host-user"`; Podman: rootless `--userns=keep-id`), so it can read and run
  what is mounted (scope, caches, toolchains) and files it writes are owned by the host user.
  `HOME` MUST be forced to `user.home` (keep-id otherwise leaks the host `$HOME`), and that home
  MUST be writable by the host uid.
- A4. The instance is ephemeral: nothing survives it except writes to `scope`, `state` and `cache`
  mounts. On exit or SIGTERM the implementation MUST remove every resource it created (container,
  per-instance network or proxy).
- A5. stdout carries only the process's stdout. The implementation's own messages go to stderr.
- A6. Image mounts are read-only. The implementation MUST pin each one to the image id it resolves
  when the instance is created (a tag moved afterwards changes nothing), label the instance with
  `handler.image-mount.<id>` for each, and set `PATH` to the image's own `PATH` followed by
  `pathAppend`.
- A8. The sandboxed process is started by an init (PID 1) holding the same
  environment, readable by the sandbox user at `/proc/1/environ`, so a process of the sandbox
  given a reduced environment can restore it (B6).

### A.3 Network semantics

- `none`: no network interface except loopback.
- `open`: unrestricted egress.
- `filtered`: **fail-closed by construction**. The sandbox has no route to the outside; egress
  is only possible through an HTTP(S) proxy that allows listed destinations. An entry is always
  `HOST:PORT`, the port written out, never implied (443 for https, 80 for http, anything else as
  it is): `example.com:443` = exact host; `*.example.com:443` = subdomains only;
  `192.168.1.20:11434` = an IPv4 address (e.g. a model server on the LAN). A bare host is
  invalid, wherever it is written (descriptors' and addons' `egress`, the API, the UI).
  An entry allows that host on that port only, whichever way the client uses the proxy: a
  tunnel (`CONNECT host:port`, which Node's `fetch` also uses for `http://`) or a forwarded
  `http://` request. A service on the host itself is reached as `host.containers.internal`
  (Podman), e.g. `host.containers.internal:3000`. Where a URL is checked against the list (an
  HTTP MCP server, P3; render adding one to `egress`, B.3), the URL's port is used, or its
  scheme's when it has none, as the client connects: `https://mcp.example.org/x` needs
  `mcp.example.org:443`. The implementation MUST set
  `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY` (and lowercase variants) in the sandbox env. Non-proxied
  and non-HTTP traffic is blocked. A denied request MUST be observable (proxy log on stderr or a
  log file referenced by `labels`). **One proxy per sandbox instance (decision 5)**, created
  with it and removed with it (A4). Measured cost (2026-10-08, prebuilt proxy image, nested
  podman): a filtered sandbox starts in about 1.1 s against 0.2 s without network (0.6 s with
  the former tinyproxy); its proxy holds about 78 MB (56 MB of it its own, the rest shared).
- **Injections** (status: implemented 2026-10-08 in `handler-sandbox-podman`): a secret the process
  never holds. It holds the `phantom`; its proxy puts the `value` in its place in requests to
  the injection's `hosts`, wherever the phantom is: header values, `Authorization: Basic`
  credentials (inside their base64), the URL (path and query), the body. A tunnel to one of
  those hosts is decrypted for that; every other tunnel stays relayed as it is, never
  decrypted. A request holding a phantom that goes to another host is refused (403) and
  reported (`leak`); the guarantee holds where it is not seen (a tunnel to another host): there
  the phantom is worthless, only this sandbox's proxy knows what it stands for. A value in a
  response from one of those hosts (headers, body, streamed or not) becomes the phantom again,
  so the process never receives it either; responses from them come uncompressed for that (the
  proxy drops the request's `Accept-Encoding`). Phantom and value have the same length, so no
  message changes length.
  - Trust: the proxy has its own CA, made when it starts, its key never leaving it. With
    injections the implementation gives the process a bundle of the system's roots and that CA
    at `/run/handler/ca-bundle.pem`, and points the runtimes' variables at it: `SSL_CERT_FILE`
    (OpenSSL, Python's `ssl` and httpx, Go, Rust with native roots), `NODE_EXTRA_CA_CERTS`
    (Node, Bun), `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `GIT_SSL_CAINFO`, `DENO_CERT`; `env`
    must not set them. A program with roots of its own (a JVM's, a Rust binary with bundled
    roots) fails towards the injections' hosts only. The bundle's roots are the proxy image's
    (Mozilla's), not the agent image's.
  - An `open` sandbox with injections gets a proxy too, filtering nothing and reporting nothing
    but its injections, besides its direct route (`set-egress`, `set-allow`: refused). `none`
    with injections is an invalid spec.
  - Not covered: a secret a client signs with instead of sending it (AWS SigV4), non-HTTP
    protocols, a value that is not printable ASCII; those need the value itself (the `env`).
    It stops a secret's exfiltration, not its use: the process can still call its hosts with it.

### A.4 Toggling network filtering

Filtering must be easy to switch on and off, at two levels:

| Level | How | Effect |
|---|---|---|
| **Per launch** | an agent's `network` (`PUT /v1/projects/{p}/agents/{a}`, `POST /v1/agents {…, network}`, CLI `--network open\|filtered\|none`, the agent editor) | changes the network topology of new connections: `open` = direct, `filtered` = proxy |
| **Live** | `set-egress <name> enforce\|log-only` (Control API: `PATCH /v1/agents/{id} {egress}`) | in `filtered` mode, flips the proxy between enforcing and log-only, **for running agents**, without restarting them |
| **Live allow-list** | `set-allow <name> [entry …]` (Control API: an agent's own hosts changed, D.2, D.8) | in `filtered` mode, replaces the entries the proxy allows, for running agents, without restarting them |

Live switching rewrites the instance's settings file, which the proxy reads again for the next
request (no signal, no restart). `log-only` is also how you discover which domains a harness
or project needs: run in log only, and the requests no entry allows are reported `unlisted` (A
events); add those domains to the agent.
Moving between `open` and `filtered` for a running agent is not supported (it changes the network
topology); it applies to the next connection.
An instance still starting (the control plane already counts it as a connection of the agent) is
waited for: `set-egress` and `set-allow` apply once its proxy answers (60 s at most).

Implementations (M1):

| Impl | sandbox | filtered network |
|---|---|---|
| `handler-sandbox-podman` | rootless container: keep-id, private 0700 tmpfs home (empty: `notmpcopyup`, never the image's content), read-only rootfs, `--init`, env via a 0600 env-file deleted after `podman create` | per-instance `--internal --disable-dns` network + `localhost/handler-ai-proxy:2` (mitmproxy with Handler's addon; built by `image build-proxy`, A.7, never by a launch: missing, the launch fails, `66`) on both networks: tunnels relayed undecrypted, decided on their `CONNECT` target |

The daemon's tests replace it with a stand-in (`HANDLER_TEST_SANDBOX`, `tests/support/fake_sandbox.py`)
that runs the fake test harness on the host and hands every other spec to `handler-sandbox-podman`:
it is not an implementation of this contract.

Conformance (`tests/sandbox/<impl>/`, run against every impl):
path outside mounts invisible; scope writable at the same path; `ro` mount not writable; allowed
domain reachable via proxy; non-allowed domain refused; direct egress (no proxy) fails;
`none` has no egress; stdio round-trips a 1 MB NDJSON line intact; SIGTERM leaves no container,
network or proxy behind; an unenforceable spec is refused; a display gives only its Wayland
socket, and nothing without one (A7).

### A.5 Confinement

How locked down the sandbox is. The agent chooses it (`confinement`, D.2, D.8;
widening it is confirmed); the default is the A3 hardening. The other levels exist for agents that must run containers themselves.

| Level | Podman | Use |
|---|---|---|
| `strict` (default) | `--cap-drop=all --security-opt=no-new-privileges --read-only` | everything else |
| `nested` | podman's default capabilities, no `no-new-privileges` (inner rootless podman needs `newuidmap`), `--device=/dev/fuse` (fuse-overlayfs), `--device=/dev/net/tun` (pasta), `--security-opt=unmask=/proc/*` (a new proc mount needs an unmasked `/proc`), `--security-opt=label=disable`, `--read-only`; `/etc/subuid` and `/etc/subgid` generated for the agent's uid/gid, and inner podman's `/etc/containers/storage.conf` (fuse-overlayfs) and `containers.conf` (cgroupfs, events and logs in files, no sysctls, the sandbox's UTS namespace, its container database and volumes in the sandbox's `/tmp`: the image store may be a cache shared with other sandboxes, D.8), read-only | podman in podman; the image needs podman, fuse-overlayfs and setcap'd `newuidmap`/`newgidmap` (the default toolbox has them) |
| `privileged` | `--privileged --read-only`; the same subordinate ids and inner podman configuration as `nested` | last resort: about as safe as no sandbox |

Every level keeps the rest of contract A: rootless keep-id user, the mounts, the network policy and
its proxy (the proxy container itself is always `strict`).
Clients SHOULD show a sandbox that is not `strict` as a warning (the web UI does). An implementation
that cannot provide a level MUST refuse the spec (A1); `handler-sandbox-podman` refuses `nested` when the
host has no `/dev/fuse` or `/dev/net/tun`.

The generated subordinate ids give inner podman every id of the sandbox's user namespace except the
agent's own (`<uid>:1:<uid-1>` and `<uid>:<uid+1>:<rest>`); they depend on the runtime uid, so they
cannot be baked into an image.

Verified (2026-09-25): `podman run alpine` (with network) works inside a `nested` toolbox container;
`--cap-drop=all` or `no-new-privileges` alone each make the inner `newuidmap` fail; without the
unmask, crun cannot mount the inner `/proc`; inner containers share the sandbox's UTS namespace
(the toolbox's `containers.conf`), as the sandbox's seccomp profile refuses `sethostname`.

### A.6 Display

`display` gives the sandboxed process one display to draw on, e.g. a browser window the person
watches (design: `browser.md`). Only Wayland: an X11 client can read every other window and
keystroke.

- A7. With `display`, the process gets `WAYLAND_DISPLAY` for that socket; without it, no
  `WAYLAND_DISPLAY` and no `DISPLAY`, even when the caller has them. The implementation sets
  `WAYLAND_DISPLAY` (and, if it needs to, `XDG_RUNTIME_DIR`); the spec's `env` MUST NOT set
  `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR` or `DISPLAY` then. This is also all it can reach: that
  one socket, no X11 socket, no other file of the host's runtime directory.
- A socket that does not exist, or is not a socket, is refused (A1, exit `64`), never a launch
  without the display asked for.
- The display is not egress: it works with every network mode, `none` included.
- The display brings its clipboard (Wayland has no other): the process can read what the person
  copies and write to it (the toolbox has `wl-paste`/`wl-copy`). Without a display it has no
  clipboard, so a harness's terminal UI (D.16) cannot paste images.

Who gets one: only an agent saved with `display: true` (D.2; CLI `--display`, web UI **Show
windows on my screen and paste images**). The daemon finds the socket at each agent start (a compositor restart may change it):
`HANDLER_WAYLAND_SOCKET`, else `WAYLAND_DISPLAY` (a name in `XDG_RUNTIME_DIR` or a path), else the
only `wayland-*` socket in `XDG_RUNTIME_DIR` (a systemd user service often lacks
`WAYLAND_DISPLAY`); none, or several without a choice, fails the start with a clear error.

| Impl | How |
|---|---|
| `handler-sandbox-podman` | the socket bind-mounted at `/run/handler/wayland-0`, `WAYLAND_DISPLAY=/run/handler/wayland-0` (an absolute path, which Wayland clients accept), `XDG_RUNTIME_DIR=/run/handler/runtime` on a private 0700 tmpfs. keep-id makes the sandbox user the socket's owner. |

Limit: with SELinux enforcing (Fedora…), a container cannot connect to the user's Wayland socket
without relabelling it or `label=disable`; `handler-sandbox-podman` does neither, so the display does
not work there yet (Arch has no SELinux).

Verified (2026-09-26, `browser.md` §4): headed Chromium and Playwright MCP draw on the host's
Wayland session from a `strict` sandbox with network `none`; Chromium needs `--no-sandbox` there
(its own sandbox cannot start under `strict`).

### A.7 Images

`handler-sandbox-<impl> image <verb>`: exit `0` when done, `1` otherwise (no such image or file, an
image in use, a failed build or pull) with the reason on stderr. The caller says what to build
(B.6, D.4, G.4); the runtime knows how.

| Verb | Does |
|---|---|
| `build CONTEXT --id-file FILE [--build-arg K=V …] [--pull] [--no-cache] [--no-intermediate]` | builds `CONTEXT/Containerfile` untagged and writes the image's id (hex, no `sha256:`) to `FILE`; its output is the build log, where lines `STEP <n>/<m>: …` mark progress. `--pull`: the base image again; `--no-cache`: every step runs again; `--no-intermediate`: only the final image is kept (no build stage left behind) |
| `inspect REF` | prints `ImageInfo` JSON: `{"id": "<hex>", "created": "<RFC 3339>"}` |
| `read REF PATH` | prints the regular file `PATH` of the image (at most 1 MiB), without running anything in it (an addon image has no shell); a folder is refused |
| `tag SOURCE TARGET` | points `TARGET` at `SOURCE` (a reference or an id) |
| `remove ID` | removes the image unless something uses it: a container running from it **or mounting it** (its A6 label), an image built on it |
| `pull REF` | pulls a published image (the mini apps' runtime, H.3) |
| `proxy` | prints `ProxyImage` JSON: `{"ref": "<its reference>", "image"?: ImageInfo}`, the egress proxy's image (A.3), `image` when it is built. Its recipe and name are the runtime's own |
| `build-proxy` | builds that image (its base pulled again, no cache: their security updates), checks that it starts, tags it as `ref`, and removes the image it replaces unless a running proxy uses it. Its output is the build log (`STEP <n>/<m>` lines). A launch never builds it: a sandbox needing its proxy (filtered, or with injections) fails setup (`66`) while it is missing |

Conformance (`tests/sandbox/test_images.py`): each verb on a `FROM scratch` image; `read`
refuses a folder; `remove` refuses an image a container mounts.

### A.8 Host check

`handler-sandbox-<impl> check` prints a `RuntimeCheck` and exits `0` when every required item is ok,
`1` otherwise. It starts nothing. Shown by `handler setup` and the web UI (Settings → Images) through
`GET /v1/runtime` (D.2).

```ts
type RuntimeCheck = { runtime: string; ok: boolean; items: RuntimeCheckItem[] };  // "podman 6.1.3"
type RuntimeCheckItem = { name: string; ok: boolean; required: boolean; detail: string };
// required: false = only some sandboxes need it; detail: what was found, or how to fix it
```

| `handler-sandbox-podman` item | Required | Ok when |
|---|---|---|
| `podman` | yes | `podman info` answers (only item when it does not, with install hints) |
| `rootless` | yes | podman runs as the user (A3); or the development mode (`HANDLER_SANDBOX_DEV_NO_KEEPID`) |
| `subordinate ids` | yes | at least 65536 in `/etc/subuid` and `/etc/subgid` (keep-id) |
| `network` | yes | netavark and pasta (allow-listed sandboxes, A.3) |
| `cgroups v2` | no | memory and CPU limits (`resources`) |
| `/dev/fuse` | no | `nested` confinement (A.5) |

### A.9 Caches

`handler-sandbox-<impl> cache <verb>`: the host folders handlerd mounts as caches (kind `cache`, D.8).
A sandbox writes there with its inner user ids too (inner podman's image store, A.5: the host's
subordinate ids), which the host user can neither always read nor remove; the runtime can. Exit
`0` when done, `1` otherwise with the reason on stderr.

| Verb | Does |
|---|---|
| `size PATH…` | prints `{"<path>": <bytes on disk>, …}` (JSON), every file counted, `0` for a path that does not exist |
| `clear PATH` | empties `PATH` (the folder stays). Refused while a sandbox (live or starting) mounts `PATH` or a folder inside it, and when `PATH` is or holds a mount point where the verb runs (run in a container, the sandboxes using a folder mounted from elsewhere may be invisible to it) |

Conformance (`tests/sandbox/test_caches.py`, throwaway folders only): sizes count inner ids'
files; `clear` removes them; refused while a sandbox mounts the folder or one inside it.

---

## C. ACP endpoint and policy — `handler.acp-endpoint/v1`

**Owner:** control plane. **Consumers:** any ACP client (web UI, CLI, editors).

### C.1 Transport (client side)

- WebSocket at `ws://127.0.0.1:<port>/v1/agents/{agentId}/acp`. The control plane MUST bind loopback only.
- The model the connection runs with: the agent's first, or the one the query names
  (`?account=…` or `?provider=…&harness=…`, `&model=…`: a `ModelAccess`, D.1), one of the agent's
  or any other (D.19, as for a session), checked before accepting: 400 when unusable, 409 when
  not made for its project's context. `handler acp` outside projects names the account or provider
  typed.
- Subprotocols: the client offers `acp.v1` and `bearer.<token>`; the server MUST reject (401)
  without a valid token and MUST answer with `acp.v1`.
- `Origin`, when present, MUST be in the configured allow-list (403 otherwise). Non-browser clients
  send no Origin.
- Framing: exactly **one JSON-RPC message per text frame**. Binary frames close the connection
  with 1003.
  The server MUST re-frame the agent's NDJSON line by line (raw chunk forwarding breaks
  messages over 256 KB).
- Max message size: 16 MiB (configurable); larger closes the connection with code 1009.

### C.2 Transport (agent side)

- The sandbox's stdio, NDJSON (one JSON message per `\n`-terminated line). stderr is logged,
  never forwarded to the client.

### C.3 Connection semantics

- One WebSocket = one sandbox instance = one agent process. Close → SIGTERM the sandbox;
  sandbox exit → close with 1011 and reason `agent exited (<code>)`.
- Resuming = new connection + `session/load`, only if the agent advertised `loadSession`
  (history lives in the agent's state mounts). No transparent reconnect.
- For reconnectable chats, use a Session (F) instead: its ACP endpoint has different lifecycle
  semantics (F.4) but the same transport (C.1) and policy (C.4).

### C.4 Policy pipeline (normative, applied in this order)

| # | Direction | Rule |
|---|---|---|
| P1 | client→agent `initialize` | Force `clientCapabilities.fs.readTextFile/writeTextFile = false` and `terminal = false`, whatever the client sent. |
| P2 | client→agent `session/new`, `session/load`, `session/resume` | `cwd` MUST equal the Agent's scope or be below it (canonical, no `..`). Otherwise answer JSON-RPC error `-32001 "cwd outside scope"` locally; the agent never sees it. |
| P3 | client→agent `session/new`, `session/load`, `session/resume` | If `mcpServers` (after P8) is non-empty and the network is not `open`, the MCP URLs MUST be allowed; otherwise error `-32002`. So the platform's own HTTP servers are checked too (e.g. refused with network `none`). |
| P4 | agent→client `fs/*`, `terminal/*` | Never forwarded. Answer the agent with JSON-RPC error `-32003 "not permitted by sandbox policy"`. |
| P5 | client→agent notifications starting with `$/` | Dropped (e.g. `$/ping` heartbeats). |
| P6 | both, methods starting with `_` | Forwarded unchanged (ACP extensions), logged. |
| P8 | client→agent `session/new`, `session/load`, `session/resume` | Add `HarnessLaunch.sessionDefaults.mcpServers` (its addons', G4) to `params.mcpServers`, after the client's own. A client server with the same name as a platform one is dropped (logged): the platform's wins. Applied before P2/P3. |
| P9 | client→agent the first `session/prompt` of a session started by this connection's `session/new` | Put the agent's `instructions` before the prompt's text, a blank line between them (one text block is added when it has none), as a daemon session does (F.3, which applies them itself: its policy has none). A loaded session got them when it started. |
| P7 | after a successful `session/new` or `session/load` | Apply `HarnessLaunch.sessionDefaults` **before** returning the response to the client (a loaded session runs in a new sandbox: the agent's mode applies again): `session/set_mode` for `modeId`, then `session/set_config_option` for each `configOptions` entry; patch `modes.currentModeId` and `configOptions` in that response. |

Policy errors use JSON-RPC codes in `-32001…-32099` with `data: { policy: "P<n>" }`:
`-32001` P2 cwd outside scope · `-32002` P3 MCP destination not allowed · `-32003` P4 not
permitted · `-32004` P7 session defaults could not be applied (the client gets this error
instead of the `session/new` result: a session in an unexpected mode is never handed out).

Conformance (`tests/acp-endpoint/`), using a fake agent + a probe client:
no token → 401; bad Origin → 403; P1–P9 each; 1 MB message intact; close → sandbox gone;
agent exit → 1011.

---

## D. Control API — `handler.control/v1`

**Owner:** control plane. **Consumers:** web UI, `handler` CLI, scheduler.
HTTP/JSON on `http://127.0.0.1:<port>/v1`, `Authorization: Bearer <token>` (browsers use `fetch`,
which can set headers). Errors are `application/problem+json` (RFC 9457).

Discovery (shared by daemon and clients, `handler_contracts.DEFAULT_PORT` / `TOKEN_FILE_NAME`): port
`$HANDLER_PORT` (default 7430); token in `$HANDLER_CONFIG_DIR/token` (default `~/.config/handler-ai/token`,
created 0600 by the daemon on first start). The OpenAPI description is served at `/openapi.json`.

The daemon also serves the web UI at `/` (static files, `Content-Security-Policy` restricting
scripts and connections to the daemon itself). Browsers receive the token in the URL
**fragment** (`/#token=…`, never sent to the server; `handler ui` opens it).

### D.1 Resources

```ts
type HarnessInfo = {
  name: string; product: string;        // product: "Claude Code", what the UI shows
  image: string;                        // the repository (B.6); agents launch its :latest
  imagePresent: boolean;
  version?: string;                     // what :latest installed (B.6)
  builtAt?: string;
  providerProtocols: string[];          // the providers it can use; empty: accounts only
  login?: HarnessDescriptor["login"];  // B.1: how an account of it is made
  loginFile?: string;                   // a file login's file name in its `{dir}` (D.9)
  permissions: ("ask" | "accept-edits" | "bypass")[];  // the permission modes it offers (B.1)
};
type ToolboxInfo = { image: string; imagePresent: boolean; builtAt?: string;
  directory: string };                  // the user's toolbox folder (B.6)
type ImageUpdates = {                 // D.4
  schedule: "off" | "daily" | "weekly"; running: boolean;
  lastRun?: string; nextRun?: string;   // nextRun: none when off; now after a handler upgrade
  lastFailed: string[];                 // targets whose rebuild failed in the last run
};
type ImageUpdatesRequest = { schedule: "off" | "daily" | "weekly" };
type ToolboxContainerfile = { content: string; defaultContent: string };  // B.6: the user's, the default
type ToolboxContainerfileUpdate = { content: string };  // at most 256 KiB
type AddonInfo = {                      // G.1; image fields as HarnessInfo, when it has an image
  name: string; description?: string;
  image?: string; imagePresent: boolean; version?: string; builtAt?: string;
  commands: string[]; skills: string[];
  settings: AddonSlotInfo[]; secretSlots: AddonSlotInfo[];  // what a binding fills
  egress: string[];                     // what its bindings' agents reach (its secrets' hosts)
  error?: string;                       // the addon's files are invalid
  directory: string;                    // where it is loaded from (G.1)
  builtin: boolean;                     // shipped with handler; else the user's
  overridesBuiltin: boolean;            // the user's, in place of the built-in addon of that name
  source?: string;                      // installed from (G.5)
  updateAvailable: boolean;             // installed from the catalog, which now ships other content
};
type AddonCatalogEntry = { name: string; description?: string; installed: boolean };  // G.5
type AddonPreview = {                   // G.5: what installing `source` would bring
  source: string; digest: string; name: string; description?: string;
  image?: string;                       // its Containerfile runs code when built
  commands: string[]; env: string[]; settings: AddonSlotInfo[]; secretSlots: AddonSlotInfo[];
  egress: string[]; mcp?: string[]; skills: string[];
  replaces?: "builtin" | "installed" | "own";
};
type AddonPreviewRequest = { source: string };   // catalog:<name>, an absolute folder, an https:// .tar.gz
type AddonInstallRequest = { source: string; digest: string };
type AddonInstalled = { addon: AddonInfo; build?: Build };
type AddonSlotInfo = { name: string; required: boolean; description?: string };
type BindingInfo = {                    // G.2; secret slot names only, never their references
  name: string; addon?: string; description?: string;
  settings: Record<string, string>; secrets: string[];
  handWritten: string[];                // bound secret slots with an env/file/command reference
  error?: string;                       // invalid: cannot be selected
  usedBy: string[];                     // the agents that picked it: "agents/<project>/<name>", "ad-hoc/<agent id>"
};
type BindingRequest = {                 // D.15: create or replace (and rename) a binding
  name: string; addon: string; description?: string;
  settings: Record<string, string>;
  secrets: Record<string, string>;      // new values, to the secret store; a slot left out keeps its own
  removeSecrets: string[];
};
type SkillInfo = {                      // D.17: a skill of the library
  name: string; description?: string;   // its SKILL.md's
  projects: string[];                   // the projects (ids) that give it to all their agents
  files: SkillFile[];                   // its folder's other files (no hidden ones, no links)
  error?: string;                       // invalid: no agent can use it
  usedBy: string[];                     // the agents that picked it: "agents/<project>/<agent>", "ad-hoc/<agent>"
  content?: string;                     // its SKILL.md, when one skill is read
  digest?: string;                      // when one skill is read: "sha256:…" of its files (D.18: what a review saw)
  scan?: SkillScan;                     // when one skill is read: what handlerd finds in its files, no model involved
};
type ScanHit = { path: string; line: number; text: string };  // a host, the line with its hidden characters shown, a blob's start
type SkillScan = {                      // D.17; ≤ 100 of each
  executables: string[];                // paths
  binaries: string[];                   // files that are not UTF-8 text
  hosts: ScanHit[];                     // URLs in its text, by host
  hiddenText: ScanHit[];                // invisible or bidirectional Unicode (format characters)
  blobs: ScanHit[];                     // long base64 or hex runs
};
type SkillRequest = { content: string; projects?: string[] };  // D.17: create or replace (and rename, give)
type CreateSkillRequest = SkillRequest & { copyOf?: string };  // D.17: a new one; copyOf: with that skill's other files
type SkillUrlRequest = { url: string };  // D.17: import from a URL (https://: a repository's folder, an archive)
type SkillFile = { path: string;        // D.17: relative to the skill's folder
                   size: number; executable: boolean;
                   text?: string };     // when one file is read and it is UTF-8 text
type SkillFileRequest = { text?: string; base64?: string;  // exactly one
                          executable?: boolean };

type Build = {                          // D.4
  id: string;
  target: string;                       // a harness name, "toolbox", or "addon:<name>"
  state: "running" | "succeeded" | "failed" | "cancelled";
  stage?: string;                       // e.g. "build vibe", "check vibe", "switch"
  step?: number; steps?: number;        // podman's STEP n/m of the current image build
  versions: Record<string, string>;     // harness → what its new image installed
  error?: string;
  startedAt: string; endedAt?: string;
};
type BuildLog = { text: string; nextOffset: number; complete: boolean };
type ModelAccess = {                    // what an agent runs as (E): exactly one of account and
  harness?: string;                     // provider; an account's harness by default, a provider
  account?: string; provider?: string;  // needs the harness that talks to it
  model?: string;                       // default: the harness's or the provider's
};
type AgentSettings = {                  // how an agent is set up, but where it works: shared by
                                        // AdHocAgentRequest, AgentRequest (D.8) and Agent
  models: ModelAccess[];                // 1..n, once each, the first by default: each session
                                        // runs with one (F.3), with every other setting below.
                                        // One goal, one agent: another model is not another agent
  // how it is contained: its own (never inherited from the project); left out, the preset of
  // new agents (Guarded): allow-list, enforce, strict, bypass
  network?: "none" | "filtered" | "open";
  egress?: "enforce" | "log-only";    // filtered only; live-switchable
  allow?: string[];                     // its own allow-list entries (A.3), on top of the required
  confinement?: "strict" | "nested" | "privileged";  // A.5; privileged is shown with a warning
  permissions?: "ask" | "accept-edits" | "bypass";   // its starting mode (one every harness of
                                        // its models offers)
  bindings?: string[];                  // its addons (G.3)
  knowledge?: string[];                 // knowledge folders (D.5), relative to the knowledge root
  display?: boolean;                    // its sandboxes get the host's Wayland display (A.6)
  interface?: AgentInterface;           // what a run takes and gives back; its sessions are
                                        // unattended (D.18)
};                                      // allow, bindings, knowledge: kept sorted, once each
type AgentModel = ModelAccess & {       // one of an agent's models, as it is now
  harness: string;                      // resolved
  problem?: string;                     // why a session cannot start with it now (E1)
  requiredHosts: { host: string; by: string }[];   // filtered only: what its account or provider,
                                        // the agent's HTTP MCP servers and its addons require in a
                                        // sandbox running with it (E4), e.g. by "addon playwright:
                                        // browser" (the addon, its binding): exactly the required
                                        // part of that sandbox's allow-list (A.3)
};
type Agent = AgentSettings & {          // what sessions open on: its models (what, one per
                                        // session) working in a folder (where), its settings
                                        // resolved. An agent of a project (D.8) has a projectId;
                                        // an ad-hoc one, none
  models: AgentModel[];
  scope?: string;                       // its folder; absent (only without a project): each of
                                        // its sessions works in a folder of its own (F.2)
  network, confinement, permissions;    // always sent; egress only for filtered
  id: string;                           // stable: kept when its settings change
  name?: string;                        // its name (optional for an ad-hoc agent: UIs fall back to the folder name)
  projectId?: string;                   // the project it is an agent of (D.8)
  description?: string;                 // an agent's: what it is for
  instructions?: string;                // an agent's: sent before a session's first request (F.3)
  origin?: string;                      // an ad-hoc agent's: the built-in agent it is (D.18)
  skills: string[];                     // the skills it picked (D.17)
  projectSkills: string[];              // given by its project to all its agents (D.17)
  context?: string;                     // its project's context (D.19): the models it may run with
  acpUrl: string;                       // C.1 URL: a plain connection runs with its first model,
                                        // or the one its query names
  connections: { id: string; sandbox: string; since: string;   // its running sandboxes (C, F, D.16)
                 terminal?: ModelAccess }[];  // a terminal's (D.16): the model it runs with
  createdAt: string;
  lastUsedAt?: string;                  // last session start/resume or connection
};

type KnowledgeListing = { root: string; source: "env" | "config" | "default";   // D.5
                          exists: boolean; folders: string[] };
type KnowledgeFolderView = { path: string; folders: string[]; notes: string[]; index?: string };
type KnowledgeNote = { path: string; text: string };

```

### D.2 Endpoints

| Method & path | Effect |
|---|---|
| `GET /v1/harnesses` | list harness adapters, with their image versions (B.6), the `permissions` modes they offer and `sessionModes`: the ACP session mode each of those modes is (B.3), so a session's mode selector names them as Handler does |
| `GET /v1/runtime` | can this host run sandboxes (`RuntimeCheck`, A.8) |
| `GET /v1/image-updates` · `PUT /v1/image-updates` · `POST /v1/image-updates/run` | automatic image updates (D.4): when, the last run and what failed (`ImageUpdates`) · change the schedule (`ImageUpdatesRequest`) · run now (202; 409 while one runs) |
| `GET /v1/toolbox` | the toolbox image and the user's toolbox folder (`ToolboxInfo`) |
| `GET /v1/toolbox/containerfile` · `PUT /v1/toolbox/containerfile` | the user's toolbox Containerfile and the default's (`ToolboxContainerfile`) · save it whole (`ToolboxContainerfileUpdate`; nothing is rebuilt: the next toolbox rebuild uses it), 404 when the folder lost it (B.6) |
| `POST /v1/harnesses/{name}/rebuild` · `POST /v1/toolbox/rebuild` · `POST /v1/network-filter/rebuild` | start a rebuild (D.4) → `Build` (202); 409 while another build runs |
| `GET /v1/network-filter` | the network filter: the egress proxy's image (A.3, A.7), whether it is built and when (`NetworkFilterInfo`, D.4) |
| `GET /v1/addons` · `GET /v1/bindings` | list addons with their image versions and slots (G.1, G.4) · list bindings (G.2) with what selects them; invalid ones carry their error. Bindings are written through D.15 |
| `GET /v1/addon-catalog` · `POST /v1/addons/preview` · `POST /v1/addons/install` · `DELETE /v1/addons/{name}` | the catalog Handler ships (`AddonCatalogEntry[]`) · what a source would bring (`AddonPreviewRequest` → `AddonPreview`) · install it (`AddonInstallRequest` → `AddonInstalled`, 201) · remove an installed addon (204) (G.5) |
| `POST /v1/addons/{name}/rebuild` | as for harnesses, target `addon:<name>` (G.4); 404 for an addon without an image |
| `GET /v1/builds`, `GET /v1/builds/{id}` | recent builds (newest first), one build |
| `GET /v1/builds/{id}/log?offset=N` | the log from byte `N`, in whole lines → `BuildLog`; poll from `nextOffset` until `complete` |
| `POST /v1/builds/{id}/cancel` | stop the build, wait for its end → `Build` (409 if not running) |
| `POST /v1/agents` `AdHocAgentRequest` = `AgentSettings & {scope?, name?, description?, instructions?, skills?, origin?, confirmRisks?}` | an **ad-hoc agent** (no project: `handler run`, `handler acp`, `handler terminal` outside projects, or made in the web UI, from scratch or setting up a built-in agent: `origin`, D.18). Validate what it runs as, each of its `models` (E1: an account, its harness by default; or a provider and the `harness` that talks to it; the model; 400 `model access unusable`, also for a model listed twice once its harness is resolved), the scope against the work folders (D.13, A2; 403 `scope not allowed`; without `scope`, a **folderless agent**: each session gets its own folder, F.2), the interface (D.18), the selected bindings (G3) and knowledge folders (D.5), and return the Agent (201). Its sandbox: `network`, `egress`, `confinement` (`strict`, `nested`, `privileged`) and `permissions` (the agent's starting mode, given to `render`, B.3; 400 `permission mode not offered` when a harness of its models has no such mode); left out, the **ad-hoc preset**: `filtered`, `enforce`, `strict`, `bypass` (the CLI's `--log-only` sets `log-only`). What it widens beyond the preset is confirmed (409 `risks not confirmed`, D.8). `allow` adds hosts to the required ones (E4); `bindings` are its addons; `display: true` gives its sandboxes the host's Wayland display (A.6; 409 `no display` when the daemon finds none, see below). An ad-hoc agent **is its folder and its name** (none: the unnamed one; names compared without case): 409 `agent exists` (saying which) when another has both, whatever its settings, so the same command in the same folder always gives the same agent (the CLI finds it and reuses it, saving the flags that differ once the person confirms, D.16) and a new name makes another one in the same folder. **Starts nothing.** |
| `PUT /v1/agents/{id}` (same body) | replace an ad-hoc agent's settings, checked as for `POST` (risks: beyond what it had; 409 `agent exists` when another has its new folder and name); the id stays → `Agent`. Its running filtered sandboxes get the new allow-list and enforcement at once (A.4; 502 when one could not be updated, the settings being saved); other changes apply to new connections. Sessions started with another harness, account, provider or scope are not resumable after it (F) |
| `GET /v1/knowledge` | the knowledge root and its folders that can be selected → `KnowledgeListing` (D.5) |
| `PUT /v1/knowledge/root` `{root, create?}` | set the root (`null`: the default) → `KnowledgeListing`; 409 when `HANDLER_KNOWLEDGE_DIR` sets it, 400 if not an absolute folder (unless `create`) |
| `POST /v1/knowledge/folders` `{path}` | create one folder (its parent must exist) → `KnowledgeListing` (201); 409 if it exists |
| `GET /v1/knowledge/browse?path=…` · `GET /v1/knowledge/note?path=…` | a folder (sub-folders, notes, its `_index.md` text) → `KnowledgeFolderView` · a `.md` note → `KnowledgeNote` (≤ 1 MiB); for reading in the web UI |
| `PATCH /v1/agents/{id}` `{egress}` | any agent: switch `enforce` ↔ `log-only` for all live and future connections of a `filtered` Agent (A.4; not confirmed, D.8) |
| `GET /v1/health` | `{status, version, display}`, **no auth** (liveness only; `display`: a Wayland display was found, for agents that ask for one) |
| `GET /v1/agents`, `GET /v1/agents/{id}` | every agent (of projects and ad hoc): list, inspect |
| `GET /v1/directories[?path=…]` | sub-directories (no dot-folders) of `path`, which must be inside the work folders (D.13; 403 otherwise); without `path`: the work folders. For folder pickers. |
| `POST /v1/directories` `{parent, name}` | create the folder `parent/name` (one level; `parent` inside the work folders, 403 otherwise; no hidden or path-like names; 409 if it exists) → its `DirectoryListing` (201). For "new project" in folder pickers. |
| `GET /v1/agents/{id}/egress-events` | recent `EgressEvent`s of the agent's sandboxes: hosts `allowed`, `denied`, or `unlisted` (log only: let through, but enforcing would deny them, A); a secret (`secret`, its D.14 path) `injected` into a request to a host, or a `leak`: its phantom seen going to a host it is not for, refused (A.3, E3) |
| `DELETE /v1/agents/{id}` | an ad-hoc agent: close all its connections (sandboxes stopped), stop its sessions and forget it. `PUT` and `DELETE` on an agent of a project: 409 `an agent of a project` (it is changed through its project, D.8) |
| `POST /v1/agents/{id}/terminal` | the harness's own terminal program: its sandbox, ready for the client to attach to (D.16) |

### D.4 Image rebuilds

A rebuild builds **only what is on disk** (the repository's `Containerfile`s): the client names a
target and nothing else (no path, recipe, tag or build argument), so what an image contains is
always explained by the files and their history. One build at a time.

- Harness: an untagged image `FROM` toolbox `:latest`, without cache (fetches the agent's latest
  release, B.6) → check → switch.
- Toolbox: an untagged toolbox (pull + no cache: system updates) → every harness image `FROM` it
  → check each → switch all of them, or none.
- Network filter (target `network-filter`): the egress proxy's image (A.3), part of Handler, not the
  user's: its recipe and name are the runtime's, so the build is its `image build-proxy` (A.7:
  pull + no cache, checked, switched). Agents, terminals and mini app backends needing it (a
  filtered network, or secrets to add, E3) do not start while it is missing: their start fails
  with "the network filter is not built yet". handlerd builds it as it starts when it is missing (a
  first start, a Handler upgrade naming a new image), whatever the schedule; `handler setup` follows
  that build. `GET /v1/network-filter` → `NetworkFilterInfo`.
- Check: the new image is started through the real pipeline (render → compose → sandbox) with no
  network and dummy credentials: a harness with a token login on an account (a dummy token), any
  other on a provider (a dummy key, endpoints for its protocols that nothing answers); it MUST answer `initialize` and `session/new`
  and offer every mapped session mode and the model option, and, for a harness taking stdio MCP
  servers, start the probe server given at `session/new` with the sandbox's environment and
  without the dummy secret (B6: addons' servers reach every session so, P8) — the credential-free
  part of the B conformance. Skills are not checked: nothing without a model turn shows a harness
  loaded them. A failure leaves `:latest` untouched and says what is missing; so `:latest` is
  always the last image that passed.
- Automatic updates: the network filter, then every harness and addon image already built, is
  rebuilt as above, one build after the other, on a schedule (`weekly` by default, `daily` or `off`) and once after a Handler
  upgrade (handlerd's version differs from the one that last ran them). The toolbox is not: it is the
  user's, and its rebuild is a system update. `GET`/`PUT /v1/image-updates` (`ImageUpdates`,
  `ImageUpdatesRequest`), `POST /v1/image-updates/run`; stored in
  `<state>/image-updates.json`, the period counting from handlerd's first start.
- Switch: the new image is tagged `:latest`; the one it replaces is removed when nothing uses it.
  Running agents keep the image they started with. There is no rollback.
- A failed or cancelled build removes the images it built. A build still `running` when the daemon
  stops is marked `failed` ("daemon restarted").
- The log holds the runtime's build output (A.7) and the check's lines (ANSI escapes removed, capped at 8 MiB);
  clients render it as text, never as markup.

### D.5 Knowledge folders

An agent may be given **knowledge folders**: folders of the daemon's knowledge root,
mounted **read-only** at `/knowledge/<folder name>`
(`Mount.kind = "knowledge"`, A.1). Selection is per agent only. Design: `docs/dev/design/knowledge.md`. The platform never reads what they hold; it writes to them only
by appending the notes an automation declares (§I.6).

- K1. A folder is given as a path relative to the root (`"."` is the root itself) or an absolute
  path inside it; it is stored relative, canonical, sorted and without duplicates.
- K2. The control plane MUST refuse (400 `knowledge unusable`) a folder that resolves outside the
  root (symlinks included), is not a directory, or has a hidden (`.`) component; two folders
  when one is inside the other, or when both would have the same `/knowledge/<name>`.
- K3. They are checked again when an agent starts: a folder removed since fails the start.
- K4. The root is `HANDLER_KNOWLEDGE_DIR` when set (then it cannot be changed through the API), else
  the root set through the API (`<config>/knowledge.toml`, `root = "…"`), else `~/knowledge`. It
  is read on every use: a change applies to the next check or agent start. Folders stay stored
  relative, so existing agents follow a new root.
- K5. Browsing, reading and creating are confined like K2: inside the root (symlinks resolved),
  no hidden component; created folder names cannot start with `.` or `_`. Notes are sent as
  text; clients MUST render them as untrusted markdown (the web UI uses the agent-output renderer,
  with plain relative links allowed so notes can link to each other).
- `GET /v1/knowledge` lists the root's folders three levels deep, parents first, leaving out names
  starting with `.` or `_`; `exists: false` when the root does not exist.

---

### D.7 Remote control

Design, threat model and envelope format: [`remote.md`](design/remote.md). The daemon still listens on
loopback only: the **remote connector** polls a gateway outbound, and paired devices reach
**shared** sessions as ordinary attachments (F.7), through the policy.

| Method & path | Effect |
|---|---|
| `GET /v1/remote` | `RemoteStatus`: `gatewayUrl`, `hostId`, `light` (`off` · `idle` · `ok` · `unreachable` · `unauthorized`), `detail`, `since`, `sharedSessions`, `devices` (`RemoteDevice`: `id`, `name`, `createdAt`, `lastSeenAt`, `attached`) |
| `PUT /v1/remote/gateway` `{gatewayUrl, hostToken}` | set the gateway (the token from `handler-gateway add-host`, `h_<16 hex>.<secret>`) → `RemoteStatus` |
| `DELETE /v1/remote/gateway` | forget it (devices are kept) → `RemoteStatus` |
| `POST /v1/remote/devices` `{name, person?, scope?}` | pair: a new device and its key → 201 `RemotePairing {device, pairingUrl}`; the key is in the URL fragment, shown once (QR code). `person` (default `owner`) is who uses it; `scope` `all` (sessions and apps) or `apps` (mini apps only, H.8); a person other than `owner` gets `apps` only (409 otherwise). 409 without a gateway |
| `DELETE /v1/remote/devices/{id}` | revoke: its attachments closed, its key deleted, the gateway told (204; 404 unknown) |
| `PUT /v1/sessions/{id}/remote` `{enabled}` | share a running session with the paired devices, or stop → `Session` (`remote`); 409 if it is not running. Off after the session stops |

Conformance (`tests/remote/`, a real gateway, a device in Python): the light follows sharing
(idle, ok, idle; unauthorized with a wrong token; off without a gateway); a device lists the shared
sessions only, attaches, prompts, answers a permission request, and a local tab sees its prompt;
not shared → -32020, not attached → -32021, anything outside the allow-list → -32022; unsharing
closes the device (4004); a stopped session is no longer shared and cannot be shared (409);
replayed, 10-minute-old, altered and reflected envelopes are refused (the old one reported as
expired); a revoked device gets 401 from the gateway.

### D.8 Projects

**Status:** implemented 2026-09-29 (`packages/control-plane/src/handler_control/projects.py`).
Why: [`architecture.md`](architecture.md) §3.

A **project** is what you work on: a code folder, its caches setting, the skills it gives to all its agents (D.17), and its agents (at least
one). An **agent** is one goal of the project: its models (each a harness on an account or provider, one per session), set up for the project: an Agent (D.1) with a `projectId`, the
same endpoints for sessions (F) and connections (C) as an ad-hoc one, so nothing below the control plane
knows about projects. Every setting of an agent is its own, never inherited (how it is contained,
its bindings, knowledge folders, skills); from its project it gets only its folder, the
caches setting and the project's skills. A new agent starts with the defaults of new agents
(a new project's first agent: with the preset chosen);
the web UI's *Duplicate* copies another agent's settings (`#/projects/<p>/agents/new?from=<a>`),
nothing linked. Stored in `<state>/projects.json`; agents in
`<state>/agents.json`, with the ad-hoc ones.

```ts
type Project = {
  id: string;                           // "p_" + 10 hex
  name: string;                         // default: the folder's name
  description?: string;
  folder: string;                       // one project per folder
  defaultAgent?: string;                // the agent a request goes to unless another is chosen
  caches: "project" | "global" | "off"; // the toolbox's caches (B.6) for its agents, see below
  context?: string;                     // its context (D.19): only the accounts and providers
                                        // made for it run its agents; none: any
  agents: Agent[];                      // default first, then by name
  createdAt: string; lastUsedAt?: string;  // its agents' last use
};
type AgentRequest = AgentSettings & {   // create (POST) and full update (PUT) of an agent; it
                                        // works in its project's folder
  name: string;                         // its goal ("Dev", "Review", "Contracts check"), never
                                        // its model's: required (422 when missing or blank), unique
                                        // in the project (case-insensitive)
  description?: string; instructions?: string;
  default?: boolean;                    // becomes the default agent
  remoteStart?: boolean;                // the owner's paired devices may start sessions of it (D.7)
  skills?: string[];                    // skills it picks, not its project's (D.17); default none
  confirmRisks?: boolean;               // save although it widens what the agent may do, below
};
```

**Risks**: a save that gives an agent — of a project or ad hoc (`POST`/`PUT /v1/agents`) — a
wider network (`none` < `filtered` < `filtered` in log only, which lets every host through <
`open`), confinement (`nested`, `privileged`) or permission mode (`bypass`) than it had — a new
agent: than the preset — is refused with 409 `risks not confirmed` (the detail says what) unless
`confirmRisks`. The web UI shows them and saves again once confirmed; the CLI's flags that widen
an agent (`--network open`, `--log-only`, `--containers`) are the confirmation, and it says on
stderr what they give. Switching enforcement alone (`PATCH /v1/agents/{id} {egress}`, the network
panel's *Learn hosts*, `handler agent network`) is not confirmed: that call is the switch itself. Presets (Locked down: `none`, `ask`;
Guarded: `filtered`, `enforce`, `bypass`, the defaults of new agents; Open: `open`, `bypass`) are
values the UI's new-project form copies into the project's first agent, never linked to it; the
agent form shows the settings themselves. Log only is not a preset: the session's network panel
switches to it to learn hosts (A events `unlisted`), then allows them and enforces again.

| Method & path | Effect |
|---|---|
| `GET /v1/projects` | list, most recently used first |
| `POST /v1/projects` `{folder, name?, description?, caches?, context?, agents: AgentRequest[1..]}` | every agent's resolved settings are checked as an ad-hoc agent's (scope D.13/A2, bindings G3, knowledge D.5, display, permission mode) and for risks before anything is saved → `Project` (201). 409 `folder already used`, 409 when agent names repeat; `context`: 400 `unknown context`, 409 `not for this project's context` for a model of an agent not made for it (D.19) |
| `GET /v1/projects/{id}` · `DELETE /v1/projects/{id}` | inspect · stop its agents' sessions and connections, forget it and its agents (204; the folder is not touched) |
| `PUT /v1/projects/{id}` `{folder, name?, description?, defaultAgent?, caches?, context?}` | replace its settings; its agents are checked again with them (their models in its `context`, as at creation), then follow at once (for new sessions). A new folder makes their past sessions not resumable (F) |
| `POST /v1/projects/{id}/agents` `AgentRequest` | add an agent → `Agent` (201); 400 `skills unusable` (unknown or invalid) or `skill of another project` (D.17); 409 `not for this project's context` for a model not made for it (D.19) |
| `PUT /v1/projects/{id}/agents/{agent}` `AgentRequest` | replace an agent's settings (same id; risks as above) → `Agent`; allow-list and enforcement applied live as for `PUT /v1/agents/{id}` |
| `DELETE /v1/projects/{id}/agents/{agent}` | stop its sessions, remove it (204); 409 `a project needs an agent` for the last one |

**Caches.** The toolbox declares its caches (B.6: a home path per name, what it holds); a project chooses for
its agents (`caches`, default `project`): `project`, its own (`<data>/caches/<project id>/<name>`,
emptied through the sandbox (A.9) and removed with the project; left, and logged, while a sandbox
still mounts it); `global`, one host folder per cache for every project choosing it
(`$HANDLER_CACHE_DIR/<name>`, default `~/.cache/handler-ai/<name>`) — a write channel between projects, as
the UI says; `off`, none. Missing folders are created at launch; the mounts reach `render` (B.3).
Ad-hoc agents (outside projects) use the global ones. Changes apply to new sessions. Settings → Caches shows what is kept (the declarations,
toolchains apart from general folders) and where (the global folder and each project's own, each
opened to show its caches' sizes) and edits them:

| Method & path | Effect |
|---|---|
| `GET /v1/caches` | `CachesInfo`: what is kept, the toolbox's `caches` in its order (`name`, `target`, `about`, `general`); where: the `global` folders (`folder`, `caches` {name: its folder}, `removed` {name: folder} the folders there of caches no longer declared, and the `projects` using them, by name; agents outside projects always do), each project keeping its `own` (`projectId`, `name`, `folder`, `caches`, `removed` likewise) and the projects with none (`off`) |
| `PUT /v1/caches` `CachesRequest` `{caches: {name: {target, about?, general?}}}` | write the list to the toolbox's `toolbox.toml` (its comments are Handler's) → `CachesInfo`; 400 `caches refused` for a cache at `~` or `/` (it would hide the harness's home) or two at one place; 422 a name or path that is not one. A removed cache's folders stay (listed as `removed`) |
| `GET /v1/caches/sizes` | `CacheSizes` `{sizes: {folder: bytes}}` for every cache folder and `removed` folder of `GET /v1/caches`, measured by the sandbox (A.9) on each call: may take seconds, so asked apart; 502 when it cannot |
| `DELETE /v1/caches/files` | empty the global folder: every global cache and what removed ones left (204); 409 `cache in use` while a sandbox mounts one |
| `DELETE /v1/caches/{name}/files` | empty a global cache's folder (204); 404 not declared; 409 `cache in use` while a sandbox mounts it |
| `DELETE /v1/projects/{id}/caches` | empty a project's own caches, and what removed ones left (204); 409 `cache in use` likewise |
| `DELETE /v1/projects/{id}/caches/{name}/files` | empty one of a project's own caches (204); 404 not declared; 409 likewise |

Conformance: `tests/control/test_projects.py`, `tests/control/test_caches.py`; unit tests of the
resolution: `packages/control-plane/tests/test_projects.py`, `test_caches.py`.

### D.9 Accounts

**Status:** implemented 2026-09-29, reworked 2026-09-30 and 2026-10-05 (token logins are the
person's own) (`packages/control-plane/src/handler_control/accounts.py`). An account (E) is a harness,
a description and maybe its plan, written here or by hand, and its login, of its harness's kind
(B.1 `login`):

- **A token login** (Claude Code): the person runs the vendor's sign-in themselves
  (`login.tokenCommand`, e.g. `claude setup-token`, in their browser) and gives Handler the token it
  prints: pasted, it goes to the secret store (`accounts/<name>/token`, D.14), or a reference to
  where they keep it (an env var of handlerd, a file, a command such as `pass show claude-pro`); the
  account's `token` says which (E). Handler never runs that sign-in nor reads its output: Anthropic
  permits a person signing in to the unmodified Claude Code with their own subscription, not a
  third party collecting the login. A subscription account is for its owner's own use.
- **A file login** (Codex, Vibe): Handler runs the harness's login on the host (below) and keeps the
  credential file it leaves in `<data>/accounts/<name>/credential` (0600), bound on top of the
  agent's home.

An agent does not start on an account that is not logged in, nor on a token it cannot read or
that does not start with its harness's `login.tokenPrefix` (a reference is checked at launch; a
pasted token also when given: 422).

| Method & path | Effect |
|---|---|
| `GET /v1/accounts` | `AccountInfo[]`: name, harness, description, `plan`, `login` (`token` or `file`: its harness's kind of login), `token` (a token login: where it comes from, `secret`, `env`, `file`, `command`), `loggedInAt` (when Handler was given it: a token in its store, a file login's file; none for a reference), `expiresAt` (a token in its store: `loggedInAt` + `login.tokenLifetimeDays`), `hosts` (the login's, E4), `connectors`, `contexts` (D.19), `status` (`ready`: logged in; `incomplete`: `problems` says what is missing, not logged in or a token past `expiresAt`; `invalid`: `error`, e.g. an unknown harness or one without a login), the `agents` using it ("<project> · <agent>", or an ad-hoc agent's name, else "an agent in <folder>" or "an agent with a folder per session"), and the daemon sessions on it: `sessions`, `lastUsedAt` |
| `POST /v1/accounts` `AccountRequest` `{name, harness, description?, plan?, connectors?, contexts?}` | create `accounts/<name>.toml` (0600) → `AccountInfo` (201); 409 exists, a harness that is unknown or has no login, or a plan it does not know |
| `PUT /v1/accounts/{name}` `AccountRequest` | its description, plan (409 for a plan its harness does not know), connectors (409 for a harness without) and contexts (400 `unknown context`, D.19), and its name (the file and its login follow) while no agent uses it (409 naming them); 409 for another harness; 404 |
| `DELETE /v1/accounts/{name}` | it and its login (204); the agents using it keep its name, a model that cannot start (its `problem`, E1) until they are given another account; 404 |
| `POST /v1/accounts/{name}/login/window` | a file login: open a terminal window on the desktop running `handler account login <name> --keep-open` (the terminal of `HANDLER_TERMINAL`, else the first found of `ghostty`, `xdg-terminal-exec`, `ptyxis`, `kgx`, `gnome-terminal`, `konsole`…) → `LoginWindow` `{terminal, command}` (201); 409 for a token login (the person's to run); 503 when there is none; 404 |
| `PUT /v1/accounts/{name}/login` `AccountLoginRequest` `{token}`, `{tokenRef}` or `{file}` | set its login: a token login's token, pasted (`token`: into the secret store) or where the person keeps it (`tokenRef`: `{env}`, `{file}`, `{command}`, written in the account file; a pasted one it had is deleted); a file login's credential file content (≤ 64 KiB), what `handler account login` got (below) or a login done elsewhere → `AccountInfo`; 422 the other kind, or a pasted token without its harness's `login.tokenPrefix` |
| `DELETE /v1/accounts/{name}/login` | forget its login (its token, its reference, its file) → `AccountInfo` |

**A file login** is the harness's own, on the host, as its authors meant it: it opens the
desktop's browser, sign-in pages call back to it on localhost, the person's terminal copies and
pastes. `handler account login NAME` (`account_commands.py`) runs `login.command`, fetched by `npx`
or `uvx` (the host needs Node.js with npm, and uv), found on PATH or else on the person's login
shell's (a window handlerd opened has handlerd's), with `login.env`, where `{dir}` is a new temporary
folder: the harness keeps its state there instead of in the person's home (its own install, if
any, is not touched). It runs on a terminal of its own relayed to this one (raw while it runs,
resized with it). When it ends, the file named `loginFile` in `{dir}` (`GET /v1/harnesses` gives
it) goes to `PUT …/login`, and the folder is removed. `--keep-open` waits for Enter at the end,
so an error stays readable. The web UI's Log in opens it in a terminal window (`…/login/window`)
and follows the account until its login changed (`loggedInAt`). For a token login the web UI
shows `login.tokenCommand` and takes the token or where it is kept; `handler account login` says what
to run instead of running it. `GET /v1/harnesses` gives each harness's `login` (its kind, its
command or token command, its hosts, a line of help). The secret store refuses writes under
`accounts/` (D.14): the token is set here. On the command line: `handler account list | add | token |
login | import | rm` (`add --token`, `--token-env VAR`, `--token-file PATH`, `--token-command
CMD`; `token NAME [--env | --file | --command]`).

Usage is what Handler itself records (the sessions on the account); token counts and costs need
the harnesses to report them over ACP, and are not collected.

### D.12 Providers

**Status:** implemented 2026-09-29, reworked 2026-09-30 (`packages/control-plane/src/handler_control/providers.py`).
A provider (E) is written here, from a template (`handler_control/data/templates/providers/`, platform
data; `HANDLER_TEMPLATES_DIR`) or
edited, or by hand. Through the API its key only ever goes to the secret store
(`providers/<name>/apiKey`, D.14, with the endpoints' hosts): the API never writes an `env`, `file`
or `command` key, and keeps one a hand-written file has.

| Method & path | Effect |
|---|---|
| `GET /v1/providers` | `ProviderInfo[]`: name, description, `endpoints` (protocol → URL), `models` (`ProviderModel`, E), `key` (`secret`, `env`, `file` or `command`: where it comes from, never its value; absent: none), `status` (`ready`: its key, if any, resolves — a `command` one is not run; `incomplete`: `problems`; `invalid`: `error`), the `agents` using it, the `harnesses` that speak one of its protocols, the harnesses it has `files` for (E), its `contexts` (D.19) |
| `GET /v1/provider-templates` | `ProviderTemplate[]`: name, description, endpoints, models, `needsKey` (a hosted API: the form asks for a key) |
| `POST /v1/providers` `ProviderRequest` `{name, description?, endpoints, models, key?, contexts?}` | create `providers/<name>.toml` (0600) → `ProviderInfo` (201); 409 exists; 422 an invalid endpoint or model; 400 `unknown context` (D.19) |
| `PUT /v1/providers/{name}` `ProviderRequest` (+ `removeKey`) | replace it; without `key`, its key is kept; a new `name` renames it and its key while no agent uses it (409 naming them); without `files`, its files are kept (a template's are given at creation); 404 |
| `DELETE /v1/providers/{name}` | it and its key in the store (204); the agents using it keep its name, a model that cannot start (its `problem`, E1) until they are given another provider; 404 |

`GET /v1/harnesses` lists each harness's `providerProtocols`. An agent's provider is checked when
the agent is saved and when it starts (E1); an Agent says why it cannot start (`problem`).
A provider written through the API loses the comments its file had.

### D.13 Work folders

**Status:** implemented 2026-10-02 (`packages/control-plane/src/handler_control/folders.py`). The
folders agents may work in, one allow-list owned by this computer (they replace the policies'
allowed roots): a project's folder and an ad-hoc agent's scope MUST be inside one
(`compose.check_scope`, symbolic links resolved; folders Handler keeps itself, D.11, are allowed
besides). Stored as written in `<config>/folders.toml` (`roots = ["~/code"]`); `~/code` when unset.
Edited in Settings → Folders.

| Method & path | Effect |
|---|---|
| `GET /v1/folders` | `WorkFoldersInfo`: `{folders: [{root, path, exists, projects}]}`, in their order: each as written (absolute, or `~/…`), where that is (`~` expanded, links resolved), whether it exists, and the names of the projects whose folder is inside it |
| `PUT /v1/folders` `{roots}` | replace them (duplicates dropped; at least one, 422 otherwise) → `WorkFoldersInfo`; 403 one that is not absolute, or is, contains or is inside the daemon's own folders (§2, invariant 5). The folders are the point of the call: no confirmation. Applies to new sessions: a project outside them can no longer start one |

The folder pickers list and create folders inside them (`/v1/directories`, D.2).

### D.14 Secrets

**Status:** implemented 2026-09-30 (`packages/control-plane/src/handler_control/secrets.py`). Handler's
store of secret values: providers and bindings reference one with `{ secret = "<path>" }` (E2), and
an account's pasted token (D.9) and a mini app's secrets (H.2) live there too. A value is named by a path after what owns it
(`providers/<name>/apiKey`, `bindings/<name>/<slot>`, `apps/<app>/<SECRET>`): segments of
`[A-Za-z0-9_.-]`, none starting with a dot. It is kept with a description. Where a secret may be
sent is not the store's: it is its owner's (E3: the login's hosts, the provider's endpoints, the
addon slot's `hosts`).

| Method & path | Effect |
|---|---|
| `GET /v1/secrets` | `SecretInfo[]` by path: every secret Handler uses, those in its store and those an account, a provider or a binding references elsewhere (listed under the path its owner's would have in the store). `source` (`secret`: the store; `env`, `file`, `command`), `hasValue` (a command is not run: true), `description`, `createdAt`, `updatedAt` (the store's), `usedBy` (what it belongs to: `accounts/<name>`, `providers/<name>`, `bindings/<name>`, `apps/<app>`; none: a stored value nothing uses), `agents` (whose sandboxes get it), `hosts` (where their proxies give it, E3), `visible` (why the sandbox gets the value itself, when it does: its addon slot says so, no host, a value the proxy cannot carry; an app's backend, H.2), `lastSent` (`{t, host}`: the latest `injected` event of its agents since handlerd started). Never a value |
| `PUT /v1/secrets/{path}` `PutSecretRequest` `{value, description?}` | set the value, replacing its description → `SecretInfo`; 400 invalid path; 409 under `apps/` (set through `PUT /v1/apps/{name}/secrets/{secret}`, which restarts the backend) and `accounts/` (`PUT /v1/accounts/{name}/login`) |
| `DELETE /v1/secrets/{path}` | forget the path and everything under it (204); 409 while one of them is referenced (the detail names what), 404 none |

No endpoint returns a value (invariant 4): a value leaves the daemon only into a sandbox, at launch.
Resolving a `{ secret }` that has no value fails the launch (`secret <path> is not set`) and makes
the account or provider `incomplete`. Storage: `<data>/secrets.json` (0600), plaintext — no weaker
than a `{ file }` reference, not a vault; another backend (the OS keyring) replaces the store, not
this API. Since the values reach sandboxes as phantoms (E3), a sandbox cannot read them. CLI: `handler secret list | set PATH | rm PATH`.

### D.15 Bindings

**Status:** implemented 2026-09-30 (`packages/control-plane/src/handler_control/bindings.py`). A binding
(G.2) is written here, from its addon's slots, or by hand. Through the API its secret values only
ever go to the secret store (`bindings/<name>/<slot>`, D.14, with the addon's `egress` as hosts),
and its settings are plain values: the API never writes an `env`, `file` or `command` reference
(which could bring host files or run a command on the host), and keeps one a hand-written file has.

| Method & path | Effect |
|---|---|
| `POST /v1/bindings` `BindingRequest` `{name, addon, description?, settings, secrets}` | create `bindings/<name>.toml` (0600) → `BindingInfo` (201); 409 exists; 422 an unknown addon, or slots it does not declare or a required one missing (G2) |
| `PUT /v1/bindings/{name}` `BindingRequest` (+ `removeSecrets`) | replace it; a secret slot not in `secrets` keeps its reference, unless in `removeSecrets`; a new `name` renames it and its secrets while nothing selects it (409 naming what does); its addon cannot change (422); 404 |
| `DELETE /v1/bindings/{name}` | it and its secrets in the store (204); 409 while an agent selects it; 404 |

A binding written through the API loses the comments its file had. Selecting it stays where it
was (G.3): an agent's own. Every valid binding is offered to every agent: pickers list those used
in the agent's project first, each saying which other projects use it (`usedBy`), so that another
project's configuration (its store) is picked knowingly.

### D.16 Terminal

**Status:** implemented 2026-10-01; the client attaches to the sandbox directly, so handlerd can
restart under it, 2026-10-05; shown in the web UI, 2026-10-08 (`handler_control/terminals.py`, CLI
`handler terminal`, web UI `TerminalView.svelte`). A harness's own
terminal program (Claude Code's UI) in the sandbox an agent gives it, instead of its ACP adapter:
for whoever prefers the harness's own interface to an ACP client. One sandbox per terminal,
stopped when it closes; not a session (F): no conversation to show in the web UI or on a phone,
no detach.

`POST /v1/agents/{id}/terminal` `TerminalStart` `{term?, colorterm?, args?, model?}`: the client's
terminal type (`term` and `colorterm` become `TERM`, `COLORTERM`; `[A-Za-z0-9._+-]{1,64}`), the
arguments for the program (B8) and the model it runs with (`ModelAccess`: one of the agent's or
any other its project's context allows, D.19; default: its first) → 201 `TerminalStarted`
`{sandbox, attach}` once the sandbox is ready; 400 `model access unusable`; 409 `not for this
project's context`; 404 unknown agent; 409 `the terminal cannot start` with the reason (a harness
without a terminal program, its account or provider unusable, the sandbox's own setup failing);
422 an invalid body.

handlerd renders the launch with `terminal` (B8), composes the spec with `tty: true` (A.1) and
starts its launcher out of its own reach: in a session of its own and, when handlerd runs as a
systemd unit, in a systemd scope of its own (`systemd-run --user --scope`), its output into a
file, not a pipe. The client then runs `attach` (the sandbox's executable and `attach <sandbox>`,
A), which puts the program on the client's own terminal; handlerd is not in between. So stopping or
restarting handlerd leaves the program running. The sandbox's secrets go from handlerd to the launcher
only (fd 3, A), as for every sandbox: the client gets the sandbox's name.

While handlerd runs, the sandbox is one of the agent's `connections`, with `terminal` (the model it
runs with): live egress switching (A.4) and egress events apply, and deleting the agent stops it.
The web UI lists it among its project's live sessions, also when its agent is outside projects
but works in the project's folder (`--anyway`, marked "outside the project"); one of an agent
outside projects is also live on the Agents page and on its agent's. Each has a page of its own
(`#/terminals/<agent>/<connection>`): its network, changed live.
A restarted handlerd does not know it any more: it is not listed, its egress cannot be switched live,
its egress events are not recorded.

Pasting an image in the program reads the clipboard: only with a display (A.6, `--display`).

Nothing crosses ACP, so the policy pipeline (C.4) has nothing to see: the program is contained by
the sandbox (A), the scope check (E1) and the network (A.3), which also filters MCP destinations
(P3 does not run). Its permission prompts are answered in the terminal.

The agent's state (E6) is the one its ACP sessions use, with its history: a conversation started
in the terminal can be resumed by its own means (`claude --resume`). The harness's own onboarding
is skipped where it would ask for a login the account already brings (claude-code's `initial`
state); what remains (Claude Code: trusting a folder, the bypass warning) is asked once and kept
there.

CLI: `handler terminal AGENT|ACCOUNT|PROVIDER [SCOPE] [agent options] [--anyway] [-- ARGS…]`: in
a project's folder, the project's agent of that name (its first model), or the one listing that
account or provider among its models, with that model (`--harness`, `--model` choose among
them), else its default agent on that account or provider, for this terminal only; one not made
for the project's context is refused (D.19); else the ad-hoc agent of the folder and `--name`, made the first time with
the agent options typed, running with that account or provider for this terminal only (as
`handler run`). Agent options (`run`, `acp`, `terminal`, in a project or not) that differ from the
agent's settings are never ignored: Handler says what differs and asks "Save this to the agent?
[y/N]" (yes saves it through `PUT`, the confirmation of what it widens, D.8; no starts nothing);
without a terminal (`handler acp` from an editor, a script) `--save` saves it, else it is refused,
saying what differs. A flag not typed changes nothing; `--allow`, `--binding`, `--knowledge`
add to the agent's lists. In a project's folder `--name` is refused (name one of its agents). Once the sandbox is ready, the CLI becomes its `attach` command: raw while it runs,
resized with the terminal; its exit code is the program's; closing the terminal stops the
sandbox. Before it starts, it says who the
program runs as, from Handler's files: the harness, its account with its description and plan (a
subscription), or its provider (no subscription). A token login cannot tell the harness more
(Claude Code's `setup-token` token may only call the model: not read the account's email).

### D.17 Skills

**Status:** implemented 2026-10-01 (`packages/control-plane/src/handler_control/skills.py`). The skill
library agents choose their skills from: `~/.config/handler-ai/skills/<name>/` (`$HANDLER_SKILLS_DIR`), one
folder per skill in the [Agent Skills](https://agentskills.io/specification) format, the one every
supported harness reads: a `SKILL.md` (a YAML frontmatter with `name`, the folder's name: 1–64
lowercase letters, digits and single hyphens; and `description`: 1–1024 characters, what it does
and when to use it; other fields are the harness's), then any other files (scripts, references,
assets). Written here: its `SKILL.md`, its other files one at a time, or a whole skill from a zip
archive; or by hand.

- **Who gets it:** every skill is offered to every agent; one folder for all, so names never
  clash. Any number of projects may give a skill to all their agents (a skill is text, it grants
  no access); which ones is stored with each project (`skills` in `projects.json`), written only
  here. Nothing hides a skill from a project: one written for project A is found, and given or
  picked, in project C.
- **Agents** pick skills (`AgentRequest.skills`, none by default; one their own project gives is
  refused with 400 `given by its project`) and get their project's (`Agent.projectSkills`). At
  launch both are mounted read-only in the harness's `skillsDir` (B.3, with the
  addons' skills, names unique), so the agent cannot change them; a skill missing or invalid
  at launch fails it (`skill '<name>': …`).
- **Changes while agents use a skill are allowed**: they follow a rename, and lose it when it is
  deleted; when their project starts giving it, their own pick of it is dropped (they get it from
  the project). Their running sandboxes keep what they mounted (an edit of its files shows at
  once, the folder being mounted; a new skill needs a new sandbox).
- **An edit reaches every agent that gets the skill.** To change it for some of them only, a new
  skill is made from it (`copyOf`: its other files copied, its own `SKILL.md`), then given to
  them; the web UI's skill page says whom saving changes it for, and offers *Save as a new skill*.

| Method & path | Effect |
|---|---|
| `GET /v1/skills` · `GET /v1/skills/{name}` | list the library's skills, invalid ones with their error (folders of other names are ignored) · one skill, with its `content`; 404 |
| `POST /v1/skills` `CreateSkillRequest` `{content, projects?, copyOf?}` | create `<name>/SKILL.md`, the name being the `content`'s, given to the agents of `projects`; `copyOf`: with that skill's other files → `SkillInfo` (201); 409 exists; 422 an invalid `SKILL.md`; 400 unknown project; 404 unknown `copyOf` |
| `PUT /v1/skills/{name}` `SkillRequest` | replace its `SKILL.md` (its other files stay) and the projects that give it (the full list); another `name` in the content renames it (its folder, and its agents' choice; 409 when taken) → `SkillInfo`; 404 |
| `DELETE /v1/skills/{name}` | its folder, and the agents' choice of it (204); 404 |
| `GET /v1/skills/{name}/files/{path}` | one of its files → `SkillFile` with its `text` (absent: binary); 404 |
| `PUT /v1/skills/{name}/files/{path}` `SkillFileRequest` | create or replace a file (≤ 5 MiB; `executable`: mode 755, else 644), its folders created → `SkillInfo`; 422 for its `SKILL.md` (written with the skill), a path that is absolute, has `..` or a hidden part, or goes through a symbolic link, or more than 500 files |
| `DELETE /v1/skills/{name}/files/{path}` | remove it and the folders it leaves empty → `SkillInfo`; 422 for its `SKILL.md`; 404 |
| `GET /v1/skills/{name}/archive` | the skill as a zip archive, `<name>/…` inside, with the executable bits (`application/zip`, as a `.skill` file is) |
| `POST /v1/skills/import[?project=…][&replace=true]` (body: a zip archive, ≤ 20 MiB) | a skill from an archive: its `SKILL.md` at the root or in a folder (the shallowest; two at that depth: 422 `several skills`), and the files under that folder (symbolic links, hidden files and archiver junk left out; ≤ 500 files, 20 MiB unpacked). Its name is its `SKILL.md`'s. New → `SkillInfo` (201), given to `project`'s agents (absent: to none yet); a skill of that name: 409, unless `replace`: all its files are replaced at once, it keeps its projects and agents (200). 422 `not a skill archive`, 413 too large |
| `POST /v1/skills/import-url[?project=…][&replace=true]` (`SkillUrlRequest`: `{ url }`, https:// only) | a skill from a URL, downloaded by handlerd (≤ 100 MiB): a folder of a GitHub repository (`https://github.com/<owner>/<repo>/tree/<ref>/<folder>`, a `…/blob/<ref>/<folder>/SKILL.md`, or the repository itself, its default branch; the first segment after `tree/` is the ref) is that folder of the repository's zip; any other URL is one skill's archive. Then as `import`: the same limits, 201/200/409; 422 `not a skill` (no such folder, several skills at its top, not https, cannot download) |

Scripts run in the agent's sandbox, with what its image and addons have (the skill's
`compatibility` field can say what it needs; Handler does not check it).

**Reviewing a skill** (implemented 2026-10-04). A skill imported from elsewhere is
someone else's instructions to your agents. An imported skill reaches no agent until it is given to
a project's agents or an agent picks it, so the library is where it waits; a review is optional. Two parts:

- the **scan** (`SkillInfo.scan`, `skill_scan.py`), computed by handlerd from the files: what a model
  reading the skill cannot be talked out of. Shown on the skill's page and given to reviewers;
- a **review**: a run of an agent whose interface takes a skill (D.18), e.g. the built-in
  `skill-review`. The skill's page offers *Review with…* for each such agent (the built-in one
  first); its
  sessions are listed there (`GET /v1/sessions?subject=skill:<name>`), the last one's result
  marked "changed since review" when the skill's `digest` is no longer the one it reviewed. A
  review advises, it never decides: no verdict blocks or allows anything.

The web UI imports a skill global, then opens its page saying it is already in the library (nothing
to save; a replace says that the agents that get it use the new version), with the next steps:
check it (what the scan found, a review) and choose who gets it. Who gets a skill is changed on its
own, apart from its SKILL.md's form.

Conformance: `tests/control/test_skills.py`; unit tests: `packages/control-plane/tests/test_skills.py`.

### D.18 Agent interfaces and built-in agents

**Status:** implemented 2026-10-04 (`packages/control-plane/src/handler_control/interfaces.py`,
`builtin_agents.py`, `skill_scan.py`; runs in `sessions.py`). An agent MAY have an
**interface**: what a run takes (a form, a Handler object to work on) and what it gives back (data
of a known shape), so it can be started from a button and its result shown and used as data.
Such an agent runs **unattended**; a conversation has no result. Any agent may have one, the
user's as well as Handler's built-in ones; nothing below the control plane knows about it
(the subject is one more read-only mount, kind `subject`, A.1).

```ts
type AgentInterface = {                 // checked when the agent is saved: 400 `interface invalid`
  fields?: JSONSchema;                  // an object schema (draft 2020-12): the form filled to start a run
  subject?: "skill";                    // the handler object a run works on (D.17), read-only at /subject/<name>
  result: JSONSchema;                   // what its final message gives back; each schema ≤ 64 KiB
  timeoutSec: number;                   // each turn; default 1800, ≤ 86 400
};
type SessionInput = {                   // POST /v1/sessions (F.3), for an agent with an interface
  fields?: Record<string, unknown>;     // valid against `fields`
  subject?: { skill: string;            // its name
              digest?: string };        // set by handlerd at the start: what the run saw (D.17)
};
type SessionOutput = {                  // F.1, once a run's turn ended
  valid: boolean;                       // the value matches `result`
  value?: unknown;                      // the parsed result (valid or not, when it parsed)
  error?: string;                       // why it is not valid
};
type BuiltinAgent = {                   // shipped with handler: handler_control/data/builtin-agents/<name>/
  name: string; description: string;   // its name (the origin of the agent set up from it), what
                                        // it is for
  agentName: string; agentDescription?: string; instructions?: string;
  network, egress, allow, confinement, permissions;   // as AgentSettings, its defaults
  skills: string[];                     // the skills that come with it (installed in the library)
  interface?: AgentInterface;
  agentId?: string;                     // the agent set up from it, once there is one
};                                      // no models, no folder: the user chooses them
```

- **A run** is a session (F) started with `POST /v1/sessions {agentId, input}`: `input` is
  required for an agent with an interface, `prompt` and `acpSessionId` refused (400 `input
  invalid` with the reason: a field, a missing or unexpected subject, an unusable skill), and
  `input` refused for others. handlerd mounts the subject read-only at `/subject/<name>`, records its
  digest, and sends one first turn: the agent's `instructions`, the input as JSON, where the
  subject is with handlerd's scan of it (D.17), then the result's schema and the rule: *end your final
  message with one fenced block `json handler-result` holding the result*. Its title: the agent's name
  (and the subject's).
- **Unattended**: no client is needed; the same sandbox, policy (C.4) and event log (F.5,
  secrets redacted) as a chat, no harness-specific flags. Clients may attach to watch; a prompt
  from them is refused (`-32012 "unattended"`).
  - No one is there to answer a permission request, so an agent with an interface has permission
    mode `bypass` (auto-approve; every harness offers it): saving it with another one is refused
    (400 `interface invalid`), its sandbox (network, confinement, read-only subject) is what limits
    it. A request its harness still sends is answered by the daemon with `allow_once` (else
    `allow_always`; no such option → outcome `cancelled`), logged (`lifecycle` event "permission
    answered").
  - After `timeoutSec` a turn is cancelled (`session/cancel`) and ends with `lastStopReason:
    "timed_out"`. `POST /v1/sessions/{id}/cancel` cancels it at once, as for any session.
- **The result**: when the turn ends (`end_turn`), handlerd takes the last `handler-result` block of the
  answer (the agent's message after the last prompt) and checks it against `result`. If it is
  missing or invalid, it sends one more turn with the error; then keeps `Session.output` whatever
  it got, keeps the answer (`Session.answer`), and stops the session. A run whose turn did not end
  (timed out, cancelled, failed) has no output. Opening it later (F.4) restarts it with
  `session/load`, to read it, for harnesses that can resume.
- **Shown from its schema** (web UI): fields by their `title`, lists, enums; two hints:
  `"x-handler": "code-ref"` on `{path, lines: [from, to]}` shows those lines read by handlerd from the
  subject now (not the agent's quote of them), `"x-handler": "verdict"` on an enum shows it as the
  run's outcome (its first value the best, its last the worst).
- **Folderless agents** (no `scope`, ad-hoc only): each session works in its own folder (F.2,
  `work/`, allowed whatever the work folders). Plain connections (C) and terminals (D.16) of one
  are refused ("works in sessions only"). `POST /v1/sessions {agentId, fromSkill}` starts that
  folder as a copy of a skill (its SKILL.md and other files; 400 for an agent with a folder or an
  unusable skill), and `POST /v1/skills/import-session/{sessionId}[?project=…][&replace=true]`
  brings the folder back into the library as an archive's import (D.17: the shallowest SKILL.md,
  hidden files and links left out, the same limits and answers; 409 `a session with a scope`).
- **Built-in agents** exist at most once each: one is set up by creating an ad-hoc agent
  (`POST /v1/agents`, D.2) with its name as `origin` (`AdHocAgentRequest.origin`, kept on the
  Agent): 400 `unknown built-in agent`, 409 `built-in agent already set up` while an agent has
  that origin (deleted, it can be set up again). The web UI fills the agent's form with the
  built-in's defaults and the user chooses its models; from then on its settings are the user's,
  nothing follows the built-in. An agent keeps its origin: a `PUT` with another one (or none for
  one that has one) is 409 `origin cannot change`. Its own skills (`skills/<name>/` in its folder)
  are installed in the library (global) before the agent is checked, unless a skill of that name
  is there (kept: it may be the user's); from then on they are the user's, edited and deleted
  like any other. Clients find the skill reviewer and the skill creator by their origin.

| Method & path | Effect |
|---|---|
| `GET /v1/builtin-agents` | the built-in agents Handler ships, each with the agent set up from it → `BuiltinAgent[]` |
| `GET /v1/sessions?subject=skill:<name>` | the runs on that skill, most recent first |
| `POST /v1/skills/import-session/{sessionId}` | the session's folder (a folderless agent's) as a skill, see above |

Built-in agents shipped (`handler_control/data/builtin-agents/`: `agent.toml`, `instructions.md`,
`interface.json`, `skills/`):

- `skill-review`: interface with `subject: "skill"`, field `expectation` (what you expect it to
  do), result `{verdict: "no-concerns" | "caution" | "do-not-install", summary, whenUsed,
  expectation?, capabilities: {commands, hosts, files, env}, mismatches, findings: [{severity,
  where: {path, lines}, text}]}`; a filtered network, enforced, with only the required hosts, strict, no
  bindings or knowledge, `ask` and `deny`: it reads, it cannot write or run anything (its
  harness asks before writing or running, and handlerd refuses at once; a model whose harness has no
  `ask` mode cannot be one of its models, 400 when saved). What it reviews is text maybe written to
  manipulate it: its verdict advises, the scan and the lines it cites are what to check. Its model
  credential is in its sandbox like any agent's (until the credential broker, §6).
- `skill-creator`: no interface (a conversation), with two skills: Anthropic's `skill-creator`
  (Apache-2.0, vendored unchanged) and `handler-skills` (where the skill goes, Handler's rules, Save to
  library). Skills offers *With an agent* (a session of it), a skill's page *Edit with
  an agent* (`fromSkill`), and the session's page *Save to library*.

Conformance: `tests/sessions/test_runs.py`; unit tests: `packages/control-plane/tests/test_interfaces.py`,
`test_skill_scan.py`.

### D.19 Project contexts

**Status:** implemented 2026-10-08 (`handler_control/contexts.py`, `api/contexts.py`). Why:
a person's day mixes work, personal use and clients, each with its own accounts (`docs/dev/ui-ux.md` "Low
friction first").

A **context** is what a project is for: Work, Personal, a client. A project has at most one
(`context`, D.8); an account or a provider says which it may be used in (`contexts`, E): their
names, or `any` (a local model). **The rule**: a project with a context runs only the accounts and
providers made for it or for `any`; a project without one, and an agent outside projects, run
any. An account without contexts runs only there. It guards against the wrong account (a work one
on a personal project), not a wall: knowledge folders, addon configurations and skills stay
shared by every context.

Applied (`contexts.check`): when a project's agents are saved, and when the project's context
changes (409 `not for this project's context`, its agents keep their settings); when a session or
a terminal starts or resumes (`launcher.prepare`: any model, the agent's or not); an agent's model
it no longer allows says so in its `problem`. Stored in `<config>/contexts.toml`, one table per
context: `[Work]` `color = "blue"`.

```ts
type ContextInfo = {
  name: string;                         // 1–32 letters, digits, spaces, - and _; never "any"
  color: "blue" | "violet" | "cyan" | "pink" | "slate";  // never the accent's nor a status's
  projects?: string[];                  // the projects in it, by name
  accounts?: string[]; providers?: string[];  // made for it (not those for "any")
};
```

| Method & path | Effect |
|---|---|
| `GET /v1/contexts` | `ContextInfo[]`, in the file's order |
| `POST /v1/contexts` `{name, color}` | add it → 201; 409 `context exists` (whatever the case); 422 a name `any`, an unknown colour |
| `PUT /v1/contexts/{name}` `{name, color}` | its colour; 409 `a context's name cannot change`; 404 |
| `DELETE /v1/contexts/{name}` | 204; 409 `context in use` while a project, an account or a provider names it; 404 |

**The CLI** (`handler run`, `handler terminal`, `handler acp` in a project's folder, D.16): an account or a
provider that none of the project's agents lists runs its default agent, for this session only,
when it is made for the project's context; otherwise it is refused, saying how to run it anyway:
`--anyway` runs it outside the project (an ad-hoc agent, its session under "Outside projects"),
after a warning the person acknowledges by typing `yes`; without a terminal to answer (a script,
`handler acp` from an editor), refused. The web UI does not offer it (a guard against mistakes, kept
out of the click path, `docs/dev/ui-ux.md`): its model choice says which accounts and providers it hides,
and the command.

## F. Sessions — `handler.session/v1`

**Owner:** control plane. **Consumers:** web UI, `handler` CLI.
**Status:** implemented 2026-09-24; **several attachments** (F.7: the same session live in two
tabs, or in a tab and on a paired phone) since 2026-09-27. It replaced the web UI's page-held
sessions, where a reload stopped the agent and lost the turn in progress.

A **Session** is one ACP conversation that the **daemon** holds: one sandbox, one ACP session,
one folder on the host. Clients **attach** and **detach**; the agent keeps running between them.

```
POST /v1/sessions {agentId} ─► mkdir <state>/sessions/<id> ─► sandbox ─► initialize ─► session/new (P7)
                                                                │ stdio
tab ─ WS /v1/sessions/<id>/acp ─► LiveSession ─► policy (C.4) ─► agent
 (reload = detach + attach)          └─ event log (replayed on attach)
```

Implementation: `packages/control-plane/src/handler_control/sessions.py`.

### F.1 Resource

```ts
type Session = {
  id: string;                           // "s_" + 16 hex; created by handler before any sandbox exists
  agentId: string;                      // the Agent it belongs to
  projectId?: string;                   // its agent's project (D.8), as of now
  harness: string; account?: string; provider?: string; model?: string;  // which of the
                                        // agent's models it was started with (F.3)
  scope: string;                        // its agent's folder (or its own, F.2) at creation:
                                        // resuming needs the same (F.3)
  acpSessionId?: string;                // the agent's id, known after session/new
  title?: string;                       // from session_info_update
  state: "starting" | "running" | "stopped" | "failed";
  busy: boolean;                        // a session/prompt is in progress
  pendingPermissions: number;           // session/request_permission awaiting an answer
  attached: number;                     // clients currently attached (F.7)
  remote: boolean;                      // reachable from paired devices (docs/dev/design/remote.md); off after a stop
  canResume: boolean;                   // the agent advertised loadSession (a stopped session can restart)
  error?: string;                       // why it is "failed", or why the last start or run failed
  harnessVersion?: string;              // what the harness image had installed at the last start (B.6)
  origin: "ui" | "cli" | "editor" | "phone" | "automation";  // who started it (clients say, F.3;
                                        // "automation": an automation's agent run, I.3)
  lastStopReason?: string;              // how its last turn ended: end_turn, cancelled, timed_out…
  answer?: string;                      // a run's (D.18): the agent's last message, kept when it ends
  input?: SessionInput;                 // a run of an agent with an interface (D.18)
  output?: SessionOutput;               // its result, once its turn ended (D.18)
  createdAt: string; lastActivityAt: string;
  acpUrl: string;                       // F.4 URL
};
```

States:

| State | Sandbox | Meaning | Next |
|---|---|---|---|
| `starting` | launching | container start, `initialize`, `session/new` or `session/load` | `running`, `failed` (first start), `stopped` (restart) |
| `running` | alive | ready; `busy` tells whether a turn is in progress | `stopped` (stop, idle timeout, agent exit, daemon restart) |
| `stopped` | none | the folder and the event log remain | `starting` (attach) |
| `failed` | none | the first start failed; never restarted | — (delete) |

### F.2 Storage

One folder per session: `$HANDLER_STATE_DIR/sessions/<id>/` (default
`~/.local/state/handler-ai/sessions/<id>/`), mode 0700.

| Path | Content |
|---|---|
| `session.json` | the record: the `Session` fields without the live ones (`busy`, `attached`, `pendingPermissions`, `acpUrl`), and the agent's own session id when it is not `acpSessionId` (F.6) |
| `events.ndjson` | the event log (F.5), append-only |
| `agent/` | bound to the harness's `perSession` state slot (B.1): the harness's own session history |
| `work/` | a folderless agent's (D.18): the session's folder, its scope (A2: same path in the sandbox), empty or a copy of a skill (`fromSkill`) |
| `baseline.json` | its folder as it was when the session first started, what its changes are compared with (F.8) |
| `mounts.json` | what its sandbox saw of the host at its last start (F.8) |

- **Per-session slot:** when the harness declares a `perSession` slot, the daemon binds
  `agent/` to it. The agent
  sees only its own session's history. Harnesses without one keep their history wherever the
  agent's state puts it; restarting them then depends on that state (as in C.3).
- Reference slots: vibe `sessions → ~/.vibe/logs/session` (declared). claude-code: none yet;
  candidate `~/.claude/projects`, **to verify** (a mount nested inside the `config_dir` mount,
  which keeps the shared login). Until then its history lives in the agent's `~/.claude`.
- The event log is written with secret values redacted (F.5).
- `DELETE` removes the whole folder. Nothing else removes it.

### F.3 Endpoints

| Method & path | Effect |
|---|---|
| `POST /v1/sessions` `{agentId, acpSessionId?, prompt?, input?, fromSkill?, model?, origin?}` (`input`, `fromSkill`: D.18) | create the folder and start the session in the background → `Session` (202, `state: starting`), running with `model`, one of the agent's or any other (`ModelAccess`, its harness may be left out for an account; 400 `model access unusable` when it cannot run, E1), never saved to the agent, default its first: its account or provider and its hosts (E4), its state (E6). It must be made for the agent's project's context (409 `not for this project's context`, D.19). It resumes with the same one, or, when that model of the agent was changed since, the agent's on the same harness and account or provider; a model the agent does not list (any more) resumes as it was, while its project's context allows it. With `acpSessionId`, the agent resumes that session (`session/load`) instead of starting one; this needs the agent's history to be reachable (its state, E6). With `prompt` (the request, ≤ 200 000 characters; 400 with `acpSessionId`), the daemon sends it as the first turn once the agent runs, as one text block after the agent's `instructions` (a blank line between them), like another client's prompt (F.7); the request's first line is the title until the agent gives one. Without `prompt` (and without `acpSessionId` or `input`), the instructions go the same way with the first prompt a client sends: before the text of its first text block (one is added when it has none). `origin`: `ui` (default), `cli`, `editor`, `phone` (`automation`: handlerd's own, I.3). 404 unknown agent. |
| `POST /v1/sessions/{id}/cancel` | `session/cancel` for its turn in progress (nothing when there is none) → `Session` |
| `GET /v1/sessions[?agentId=…][&subject=skill:<name>]` | list, most recent activity first (`subject`: the runs on that skill, D.18) |
| `GET /v1/sessions/{id}` | inspect |
| `POST /v1/sessions/{id}/stop` | stop the sandbox → `Session` (`stopped`); the folder remains |
| `DELETE /v1/sessions/{id}` | stop, delete the folder (204) |
| `WS /v1/sessions/{id}/acp` | attach (F.4) |
| `GET /v1/sessions/{id}/changes` · `…/mounts` · `…/folder?path=&mount=` · `…/file?path=&mount=` · `POST …/reveal` | its folder: what changed since it started; what else its sandbox sees; a folder, a file; one shown in the desktop's file manager (F.8) |

Deleting an agent (`DELETE /v1/agents/{id}`, or through its project) also stops its sessions.
They keep their folders and cannot be attached until an Agent with the same id exists again. A
session's sandbox is one of its Agent's `connections` (D.1): it gets the Agent's egress events and live egress switch
(A.4).

Daemon setting: `HANDLER_SESSION_IDLE_TIMEOUT` (seconds, default 1800), see F.6.

### F.4 Attach protocol

Transport: identical to C.1 (subprotocols, token, Origin, framing, size limits). Unknown session
→ 404 before accepting. The WebSocket is accepted, then the daemon makes sure the agent runs:
a `stopped` session is restarted (F.6), a `starting` one is waited for. If it cannot run
(`failed`, agent deleted, start error), the connection is closed with 1011 and the reason.

**Several attachments** (F.7), up to `HANDLER_SESSION_MAX_ATTACH` (default 8). Beyond it, the oldest
is closed with **4001 "attached elsewhere"**; that tab shows it and offers to re-attach.

The client speaks **plain ACP**, as if the agent were its own; the daemon answers the setup
messages itself:

1. `initialize` → the agent's cached `initialize` result. The agent never sees a client's
   `initialize` (the daemon sent its own, with P1 applied).
2. `session/load {sessionId: acpSessionId, cwd}` → P2/P3 apply. The daemon sends the event log
   (F.5) as `session/update` notifications, then the response with the current `modes` and
   `configOptions`, then `_handler/session_state`, then the pending `session/request_permission`
   requests. From then on the client gets live traffic. The client never needs `loadSession`
   support from the agent to attach.
3. Then any ACP message, with the rules below.

Client → agent:

- `session/new`, `session/resume`, or a `sessionId` other than the session's own: error
  `-32010 "one session per attachment"`. A second conversation means a second Session.
- `session/prompt` while `busy`: error `-32011 "turn in progress"`.
- `session/prompt` to a run of an agent with an interface: error `-32012 "unattended"` (D.18).
- Request ids are the client's own: the daemon rewrites them towards the agent and restores
  them on the response, which goes only to the client that sent the request. A response due to
  a client that has detached is dropped (the turn itself goes on).
- Answers to permission requests are forwarded once; answers to unknown requests are dropped.

Agent → client: notifications and permission requests go to every attached client (F.7). With
no client attached, permission requests wait (they are re-sent on the next attach).

Daemon → client (ACP extensions, P6 naming):

| Notification | When |
|---|---|
| `_handler/session_state {state, busy, turnStartedAt, pendingPermissions, attached}` | right after the `session/load` response, then on every change (F.7); `turnStartedAt`: when the turn in progress started (ISO 8601), `null` when not busy |
| `_handler/turn_ended {stopReason}` | a turn ended that this attachment did not start (another client's, or one started before a reload) |
| `_handler/permission_resolved {requestId, toolCallId, outcome}` | another client answered a permission request (F.7) |

Detaching (WebSocket closed) never affects the agent or the turn in progress.

Close codes: C.1's, plus **4001 "attached elsewhere"** (F.7), **4002 "session stopped"** (stop, idle
timeout, agent exit; the reason says which), **4003 "too slow"** (F.7) and **4004 "remote access
disabled"** (a remote attachment, docs/dev/design/remote.md). A stopped session can be re-attached, which
restarts it.

### F.5 Event log

`events.ndjson`, one line per event, `seq` strictly increasing from 1:

```ts
type SessionEvent =
  | { seq: number; t: string; kind: "update"; update: SessionUpdate }   // ACP session/update params.update
  | { seq: number; t: string; kind: "turn"; phase: "start" | "end"; stopReason?: string }
  | { seq: number; t: string; kind: "lifecycle"; event: "started" | "stopped"; detail?: string;
      how?: StopHow };                  // `stopped` only: how it stopped
type StopHow = "explicit" | "idle" | "exited" | "error" | "run_ended" | "daemon_restarted" | "deleted";
```

- The log is the **source of truth for history**. On attach, the daemon replays every `update`
  event as a `session/update` notification with `_meta: {"handler.dev/seq": n}`. A client MAY pass
  `_meta: {"handler.dev/afterSeq": n}` in `session/load` to receive only the events after `n`.
  `turn` and `lifecycle` events are for the daemon (and people reading the file).
- `how` (read by automations, I.2): `explicit` (a client's stop), `idle` (F.6.3),
  `exited` (the agent exited by itself), `error` (it was stopped for an error: a message too big, a
  failed start), `run_ended` (a run, D.18), `daemon_restarted` (F.6.5), `deleted`.
- Prompts are logged by the daemon, as `user_message_chunk` updates, when it forwards them
  (agents do not always echo prompts); a prompt's images as they were sent (base64, scaled down
  by the web UI to ~1568 px). The agent's own `user_message_chunk` during a turn is
  relayed but not logged.
- When the daemon restarts an agent with `session/load`, the agent's replay of the history is
  neither logged nor relayed if the log already has updates. When the log is empty (a session
  created with `acpSessionId`), the replay is the history: it is logged and relayed.

### F.6 Lifecycle guarantees (normative)

1. **At most one sandbox per Session.** Starting is single-flight: attaches during `starting`
   wait for the same start. The sandbox is named `handler-<agentId>-<sessionId>`, so a second start
   could not create it anyway (the name collides).
2. **Restart:** attaching to a `stopped` session launches a new sandbox with the same folder,
   sends `initialize`, then `session/load {acpSessionId}`, and applies the session defaults
   (P7): a new sandbox runs in the agent's mode. If the agent does not advertise
   `loadSession`, the start fails ("this agent cannot resume sessions"). A session stopped
   before its first turn has nothing to load (an agent may save a session only once a turn
   ends, e.g. Vibe): it is restarted with `session/new`. Its `acpSessionId` stays the one
   clients know; the daemon translates `params.sessionId` between it and the agent's new id.
3. **Idle stop:** a `running` session with no attachment, not `busy` and with no pending
   permission request for `HANDLER_SESSION_IDLE_TIMEOUT` seconds is stopped. A busy session is
   never stopped for being idle.
4. **Agent exit:** the session becomes `stopped` (with `error` when the daemon did not stop it
   and the exit code is non-zero); the attached client is closed with 4002. A turn in progress is
   logged as ended with `stopReason: "stopped"`.
5. **Daemon start:** sandboxes of the previous daemon are gone (their stdio died with it; the
   sandbox sweep removes leftovers). Every session that was `starting` or `running` is marked
   `stopped` (`failed` if it never got an ACP session), with a `lifecycle` event, and an open
   turn is logged as ended with `stopReason: "daemon_restarted"`.
6. The policy (C.4) applies once, between the daemon and the agent: P1 on the daemon's own
   `initialize`, P2/P3 on its `session/new` and `session/load` and on the client's
   `session/load`, P4–P6 on the traffic, P7 after the daemon's `session/new` or `session/load`.
   Clients cannot bypass it: they never reach the agent's setup.

### F.7 Several attachments

Implemented 2026-09-27. Every attached client is an `Attachment` with its own bounded queue
(10 000 messages): putting a message never waits, so a slow client cannot hold up the agent. One
that falls behind is closed with **4003 "too slow"**; it re-attaches with `afterSeq` and misses
nothing. With several clients attached:

- notifications and permission requests go to every client that has its replay;
- a permission request's **first** answer wins and goes to the agent; later answers are dropped,
  and the other clients get `_handler/permission_resolved {requestId, toolCallId, outcome}` (their
  prompt is withdrawn — a JSON-RPC error cannot answer a response);
- a prompt is shown to the others as `user_message_chunk` updates (with `handler.dev/seq`), followed by
  `_handler/session_state` (busy); its end as `_handler/turn_ended`;
- a mode or option change is shown to the others as `current_mode_update` /
  `config_option_update`;
- `_handler/session_state` is sent to every client on each change (turn, permissions, attachments);
- beyond `HANDLER_SESSION_MAX_ATTACH` clients, the oldest is closed with 4001.

Conformance (`tests/sessions/`, fake agent): create, attach, prompt, detach (the agent stays);
reload during a turn waiting for a permission → the re-attached client gets the replay, the
busy state and the pending request, and the turn completes; two attachments see each other's
prompt, turn end and mode change; the first permission answer wins and the other client gets
`_handler/permission_resolved`; beyond the limit the oldest is closed with 4001 and the agent has
one sandbox; a second prompt while busy → -32011; stop, then
attach → restarted with `session/load`, P7 applied, the history from the daemon's log (not the
agent's replay); idle stop, delete; 404 and 401; the folder is 0700. Browser (`tests/e2e`):
reload while the agent waits for a permission; close then resume from the project's page.

### F.8 Its folder

**Status:** implemented 2026-10-07 (`handler_control/session_files.py`, `git_read.py`; web UI
`SessionFiles.svelte`, the session page's Files pane). To follow what the agent does in the
session's folder (its scope, or its own, F.2) without leaving the page, and to read what it left,
also once the session is stopped. Read-only: the agent writes, its person reads.

**Baseline.** When a session first starts, before its sandbox, handlerd records its folder in
`baseline.json`: each file's size and modification time (regular files and links; not the `.git`
folders, not what the folder's `.gitignore` files and `.git/info/exclude` ignore), and, when the
folder is a git repository (`.git` a folder there), the commit HEAD is at. Beyond 50 000 files,
only that is recorded (`notFollowed`). Restarts keep the baseline: changes are always since the
session started.

| Method & path | Answer |
|---|---|
| `GET /v1/sessions/{id}/changes` | `SessionChanges` `{since, git, files: [{path, change: added\|modified\|deleted, at?}], notFollowed?}`: the files whose size or modification time differ from the baseline, the most recently modified first, then the deleted ones. `notFollowed` (and no files) when the baseline is missing or the folder holds more than 50 000 files. |
| `GET /v1/sessions/{id}/mounts` | `SessionMounts` `{startedAt?, mounts: [{target, kind, readOnly, source, browsable}]}`: everything of the host its sandbox saw at its last start (recorded then in `mounts.json`, F.2), in the spec's order: its folder (`scope`), a run's subject, knowledge folders, skills (`config`), the agent's own state (its harness's settings and history, the account's sign-in), caches, and addons' tools (`tools`: `source` is the image). `browsable`: its files can be read with `mount` below: the session's folder, a run's subject, knowledge folders and skills; never the agent's state (it holds the account's sign-in) nor caches. Before a first start, only its folder (no `startedAt`). The files handlerd generates for the harness (its config, A.1 `files`) are not host files and are not listed. |
| `GET /v1/sessions/{id}/folder?path=` | `SessionFolder` `{path, entries: [{name, kind: file\|folder\|link, size?, target?}]}`: folders first, then by name; `.git` and special files (FIFOs, sockets, devices) not listed; a link with its target, never followed. |
| `GET /v1/sessions/{id}/find?q=` | `SessionFound` `{paths, notFollowed?}`: at most 20 files of the session's folder (as the baseline walks it: not the ignored ones nor `.git`) whose path holds `q`'s letters in order, case aside: those whose name starts with `q` first, then whose name holds it, then whose path holds it, then the others, the shorter path first. Without `q`: the most recently modified. `notFollowed` (and no paths) beyond 50 000 files. For the composer's `@`. |
| `GET /v1/sessions/{id}/file?path=` | `SessionFile` `{path, size?, change?, text?, image?, before?}`: UTF-8 text up to 1 MB, or a PNG, JPEG, GIF or WebP image up to 1 MB as a `data:` URL, otherwise only its size. `change` against the baseline; `before`: its text at the baseline's commit, for a modified or deleted file. A deleted file is answered with `change: deleted` and `before`. |

| `POST /v1/sessions/{id}/reveal` `RevealRequest` `{path?, mount?}` | 204 once the desktop's file manager shows it: a file selected in its folder, a folder opened (freedesktop `FileManager1` over D-Bus, `ShowItems` / `ShowFolders`); without that service, `xdg-open` on its folder. **A file is never opened** (an agent's file may be a program: `.desktop`, a script). 409 `cannot show it` when nothing answered (no desktop session). The path is checked like a read (no link on the way; the link itself may be shown). |

`mount`: the `target` of a browsable mount, to read it instead of the session's folder (404
otherwise); changes are only the session's folder's (a mount read elsewhere is read-only to the
agent). `path` is relative to the session's folder or the mount (`/`-separated, `""` for it); 400 `path not
shown` for an absolute path, `.` or `..`, `.git`, a link (on the way or at the end) or what is not
a regular file; 404 when it does not exist (nor was deleted during the session).

**The folder is the agent's** (rules, normative):
- every path is opened one name at a time from the session's folder with `O_NOFOLLOW`, a file with
  `O_NONBLOCK` and read only if regular: no link leads out of the folder (`notes -> ~/.ssh/…`), a
  FIFO does not block handlerd; `.gitignore` files are read the same way, up to 1 MB;
- handlerd never runs git nor reads `.git` itself: its config can name programs (`core.fsmonitor`,
  diff drivers, filters) that git would run on the host. HEAD and a file's earlier version are read
  by `python -m handler_control.git_read` (dulwich, which runs nothing from the repository), a child
  process limited to 1 GB of memory that handlerd stops waiting for after 10 s: a malformed repository
  only costs that process, and gives no earlier version.

The earlier version is the last commit's when the session started: a file with uncommitted edits
then shows them in its changes too. Without git, handlerd keeps no earlier version: a modified file is
shown as it is now.

**Web UI.** The session page's **Files** button (closed by default; once opened, it stays open from
a session to the next) shows the number of changed files and a dot when some changed since the
pane was last seen; it fetches the changes every 10 s while the page is visible and soon after the
agent finishes a tool call or a turn (no file watcher). The pane (resizable; full screen on a
narrow window): **Changes** (the list, a file's changes as its earlier version and its text,
removed and added lines marked), **All files** (the folder, changed files marked), **Access** (what
the agent sees of the computer: the browsable mounts first, opened in All files, then the others,
each read-only or "can change"). In the composer, `@` lists the folder's files (`find`, the latest
changed first, then those matching what follows it); the one picked goes in the text as
`@<path>`, relative to the folder, the agent's working directory: every harness reads it.

Conformance: `packages/control-plane/tests/test_session_files.py` (links and paths that leave the
folder refused, FIFOs, ignored files, git's earlier versions even after the agent commits, a
repository whose config names a program or would block the reader, the mounts recorded and which
are browsable), `tests/control/test_session_files.py` (the endpoints on a running session, a
knowledge folder read through `mount`, a cache refused), `tests/e2e`
(`test_the_files_pane_follows_what_the_agent_changes`, `test_at_names_a_file_of_the_folder`).

## G. Addons and bindings — `handler.addon/v1`, `handler.binding/v1`

Design and rationale: `docs/dev/design/addons.md`. An **addon** says how to use a kind of system (a tool image,
skills, env, slots, egress). A **binding** is one addon bound to one instance of that system, with
its settings and secret references. An agent **selects** bindings.

### G.1 Addon

**Owner:** platform (one per addon, like harness descriptors). **Consumer:** control plane.
**Location:** two folders are loaded. The **built-in** addons are platform data
(`handler_harness/data/addons/`: `miniapp`, shipped read-only with Handler); the **user's** are in
`~/.config/handler-ai/addons/` (`$HANDLER_ADDONS_DIR`): their own, or installed (G.5, from the catalog Handler
ships in `handler_harness/data/catalog/`, which is not loaded, a folder or an archive). A user addon
named as a built-in one replaces it, and clients show it (`AddonInfo.overridesBuiltin`).

```
<name>/
├── addon.toml        the manifest below
├── Containerfile     the tool image, FROM ${TOOLBOX_IMAGE}; present iff `image` is set
├── skills/<skill>/   zero or more skills (each with a SKILL.md)
└── PROVISIONING.md   how to create the least-privilege account a binding needs
```

```ts
type AddonManifest = {
  apiVersion: "handler.addon/v1";
  name: string;                          // = directory name
  description?: string;
  image?: string;                        // repository, no tag (like B.6); absent: no tool
  commands?: string[];                   // exactly what the image's bin/ provides; required with image
  check?: string[];                      // argv run by a rebuild's check (G.4)
  env?: Record<string, string>;          // static env
  settings?: Record<string, AddonSlot>;  // slot → env var; a binding gives the value
  secretSlots?: Record<string, AddonSecretSlot>;
  egress?: string[];                     // allow-list entries (A.3), merged like harness egress
  mcp?: { command: string[] };           // a stdio MCP server; command[0] one of `commands`
};
type AddonSlot = { env: string; required?: boolean; description?: string };
type AddonSecretSlot = AddonSlot & {
  hosts?: string[];                      // where its value goes (E3): some of `egress`; default all
  delivery?: "proxy" | "env";            // default proxy: a phantom the sandbox's proxy swaps back
                                         // towards `hosts`; env: the value itself, for a tool that
                                         // signs with it or speaks something else than HTTP
};
```

The image holds only the installed tree (`FROM scratch`), built at its mount path
`/opt/addons/<name>`, with `bin/` (the commands) and a one-line `version` file at its root. `check`
runs without network, so it must not need it (e.g. `shopify version` looks up the latest release
and fails offline; `shopify theme list --help` does not).

Rules:
- G1. Env var names are unique across `env`, `settings` and `secretSlots`, and never `PATH`, `HOME`,
  the proxy variables or the CA ones (A.3: the platform owns them). `mcp.command` starts with one
  of the addon's own `commands`, so the server is installed at build time, never at start. A
  secret slot's `hosts` are some of the addon's `egress`, and only with `proxy` delivery.

### G.2 Binding

**Owner:** the user (written from the web UI's form through D.15, or by hand; unknown keys are
errors, like accounts). **Consumer:** control plane. **Location:** `~/.config/handler-ai/bindings/<name>.toml` (`$HANDLER_BINDINGS_DIR`; name = file
stem).

```ts
type Binding = {
  apiVersion: "handler.binding/v1";
  addon: string;
  description?: string;
  settings?: Record<string, string>;     // addon setting slot → value
  secrets?: Record<string, SecretRef>;   // addon secret slot → reference (E2, never a value)
};
```

Rules:
- G2. A binding is invalid if its addon is unknown or invalid, if it binds a slot the addon does
  not declare, or if a required slot is not bound. An invalid binding is listed with its error and
  cannot be selected.

### G.3 Selection and composition

The bindings of an agent are its own selection, without duplicates.
They are fixed when the agent is saved (D.2, D.8) and applied when
each agent starts.

- G3. Saving an agent MUST fail (400) if a selected binding is unknown or invalid (G2), if two selected bindings use the same addon, if two selected addons
  declare the same command.
- G4. At each agent start the control plane adds, per binding: an `imageMounts` entry
  (`<image>:latest` at `/opt/addons/<name>`) and its `bin/` to `pathAppend` (A.1) when the addon
  has an image; its `env`, its settings and its resolved secrets (B3) to the env; its `egress` to
  the allow-list; its skills to `render`'s skills (B.3, so a harness without skills fails with
  B5); its `mcp` server, as `{name: <addon>, command: mcp.command[0], args: the rest}`, to
  `render`'s `mcpServers` (B.3, so a harness that does not accept stdio servers fails with B5). Secret values of bindings are redacted like its account's or provider's (F.5).

### G.4 Addon images

Rebuilt like harness images (D.4), target `addon:<name>`: an untagged image `FROM` toolbox `:latest`,
without cache and without keeping intermediate images (`--no-intermediate`, A.7: the build stage
would otherwise stay behind after every build) → check → switch. A toolbox rebuild also rebuilds and checks every addon image already built (an addon
never built is not in use), and switches all the images, or none.

Check: the new image as agents get it, through the sandbox (A): the toolbox with the image mounted
at its mount path, confinement `strict`, the host user, no network. It MUST find that `bin/` holds
exactly `commands`, that none of them is also found on the toolbox's own `PATH`, that `version` is
readable, and that `check` (if any) exits 0 with the addon's `bin/` appended to `PATH`, as agents
have it.

Switch: as D.4. The old image stays while a container mounts it: podman itself would remove it
(§13 of `docs/dev/design/addons.md`), the runtime's `image remove` refuses (A.7).

Conformance (`tests/addons`): manifest and binding validation; selection errors (G3); composition
(G4) into a `SandboxSpec`; a built addon passes its check; switch keeps an image a container
mounts.

### G.5 Installing addons

**Status:** implemented 2026-10-03 (`handler_control/addon_install.py`, `api/addons.py`).
An addon is installed into the user's folder from a **source**: `catalog:<name>` (the catalog Handler
ships: `shopify`, `playwright`), an absolute folder path, or an `https://` URL of a `.tar.gz`
archive (at most 32 MiB and 2000 files, unpacked with no link out of it, no device, no absolute
path). `addon.toml` is at the top of the source or in its only folder (a forge's archive of an
addon's repository).

1. **Preview** (`POST /v1/addons/preview {source}` → `AddonPreview`): the source is copied to
   `<state>/addon-staging/<digest>/<name>/` and validated as G.1; a folder's symbolic links must
   stay inside it. The preview says everything it would bring: hosts, settings, secret slots, env,
   commands, MCP server, skills, its image (its Containerfile runs code when built), and what has
   its name now (`replaces`: built-in, installed, the user's own). `digest` names the content: every
   file's path, executable bit and bytes, every link's target.
2. **Install** (`POST /v1/addons/install {source, digest}` → `AddonInstalled`, 201): refused (422)
   unless the source still has that digest, and when the user's own addon has the name (Handler never
   replaces nor removes a folder it did not install). Copied to `~/.config/handler-ai/addons/<name>/`
   (replacing the installed one: an update), recorded in `~/.config/handler-ai/addons.lock.toml`
   (`[addons.<name>] source, digest, installedAt`); its image's first build starts (G.4) unless
   another build runs.
3. **Remove** (`DELETE /v1/addons/{name}`, 204): an installed addon only (409 for a built-in or the
   user's own), refused (409) while a binding uses it; its folder, lock entry and unused image go.

`AddonInfo.source` says where an installed addon came from; `updateAvailable`, that it came from the
catalog and Handler now ships other content (an upgrade): installing it again is the update, after its
preview. `GET /v1/addon-catalog` lists the catalog (`AddonCatalogEntry`: installed or not).
Clients: Settings → Addons (Available to install, then a Configure form for it; See the update,
Reinstall, Uninstall); `handler addon catalog | add NAME|FOLDER|URL [--yes] | rm NAME`. For users:
`docs/user/addons.md`.

Conformance (`packages/control-plane/tests/test_addon_install.py`, `tests/control/test_addon_install.py`,
`tests/cli/test_addon_cli.py`): preview then install from a folder, the catalog and an archive;
other content than the preview's is refused; a link out of the folder is refused; the user's own
addon is neither replaced nor removed; removal refused while a binding uses it.

---

## H. Mini apps — `handler.miniapp/v1`

Design and rationale: [`miniapps.md`](design/miniapps.md). A **mini app** is a folder an agent writes (a
manifest, a Deno backend, a built UI); a person registers and deploys it; handlerd runs its backend
on demand in a sandbox (A) and serves it at its own origin.

### H.1 Manifest

**Owner:** the app's author (an agent, with the `miniapp` addon). **Consumer:** control plane.
**Location:** `app.toml` at the root of the app's folder. Hand-written TOML, unknown keys are
errors (like accounts).

```ts
type MiniAppManifest = {
  apiVersion: "handler.miniapp/v1";
  name: string;              // ^[a-z][a-z0-9-]{0,29}$ — a DNS label (H.4)
  version: string;           // semver: 1.2.3, 1.2.3-rc.1
  description?: string;
  server?: { entry: string };   // default "server/main.ts"; inside a directory, which is
                                // installed whole (vendored dependencies included)
  ui?: { dir: string };         // default "ui/dist": built static files with an index.html
  needs?: {
    egress?: string[];       // allow-list entries (A.3) the backend may reach; default none
    secrets?: string[];      // env vars whose values the person enters in handler (H.2)
    files?: { path: string; mode?: "ro" | "rw" }[];  // host files or folders (H.9), ≤ 10
    notify?: boolean;        // it may send notifications (H.9)
  };
  routes?: Record<string, "sync" | "queued">;  // "POST /api/checkin": H.10 (POST PUT PATCH DELETE)
  resources?: { memory?: string; cpus?: string };  // default memory 512m
};
```

Rules: paths are relative and normalized; the server and UI directories do not overlap.

### H.2 Needs

What an app may reach beyond its data. A deploy that adds to them is flagged
(`App.source.addedNeeds`: `egress host:port`, `secret NAME`) and clients ask the person first.

- `egress`: the backend's allow-list, enforced by the sandbox's proxy and Deno's `--allow-net`.
- `secrets`: names matching `^[A-Z][A-Z0-9_]{0,63}$`, not `HANDLER_*`, `DENO_*`, `PATH`, `HOME`, the
  proxy variables, `NO_COLOR`, `TINI_SUBREAPER`. Values are set through the Control API only
  (never in the app's folder, so never seen by the agent writing it), stored in the secret store
  as `apps/<app>/<NAME>` (D.14; removed with the app), given to the backend as env vars — not to
  its tests. A
  deploy, and a start, fail while one the version declares has no value. Changing one stops the
  backend. The backend's output reaches the app's log with every secret value replaced by
  `[secret NAME]` (invariant 4).

### H.3 Runtime (sandbox)

The backend runs in `RUNTIME_IMAGE` (a pinned `docker.io/denoland/deno:distroless-<version>`),
confinement strict, built by `compose.app_sandbox_spec`:

| | |
|---|---|
| code | read-only at `/opt/app` (mount kind `app`) |
| data | `<data>/apps/<name>/data`, read-write at the same path (kind `scope`, the workdir) |
| socket folder | read-write at `/run/handler-app` (kind `app`) |
| network | none; with `needs.egress`, allow-list of exactly those entries, enforced |
| Deno | `run --cached-only --frozen --no-prompt`, read the code, the data and the socket folder, write the data and the socket folder, net: the socket and the egress hosts (all hosts, filtered by the proxy, when an entry is a wildcard), env |
| env | `HANDLER_APP_NAME`, `HANDLER_APP_VERSION`, `HANDLER_APP_DATA`, `HANDLER_APP_SOCKET` (`/run/handler-app/app.sock`), and the secrets (H.2) |

The backend MUST serve HTTP on `HANDLER_APP_SOCKET`, keep what it stores in `HANDLER_APP_DATA`, and answer
`GET /api/health` with 200 once ready. Tests (H.6) run `deno test` on the server directory with
the same permissions and an empty data folder.

### H.4 Serving

App `<name>` is served at `http://<name>.localhost:<port>/` by handlerd (Host header, exact port).
Other hosts reach Handler's own routes; `/v1` is not reachable on an app's origin.

| Path | |
|---|---|
| `/_handler/login?code=…` | redeems a one-time link (`POST /v1/apps/{name}/open`, valid 2 min, this app only): sets the cookie `handler_app` (HttpOnly, SameSite=Strict, HMAC of the daemon's token and the app's name), then loads `/` |
| `/api`, `/api/…` | the backend (started if needed), through its socket, streamed; the request gets `X-HANDLER-Person: owner` (any value sent by the client is dropped) and loses the `handler_app` cookie |
| anything else | `GET`/`HEAD` only: the current version's UI files; a path without an extension that matches no file gets `index.html` |

Rules: everything except the login needs the cookie (401). On `/api`: a request whose
`Sec-Fetch-Site` is present and neither `same-origin` nor `none` is refused (403), and so is one
with a method other than GET, HEAD, OPTIONS whose `Origin` is not the app's own. Every response
carries `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'
'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self';
frame-ancestors 'none'; base-uri 'none'; form-action 'self'`, replacing the backend's.

### H.5 Lifecycle

`AppState`: `stopped` · `starting` · `running` · `failed` (did not start, or exited on its own; the
next request tries again). Started by the first `/api` request, stopped after
`HANDLER_APP_IDLE_TIMEOUT` seconds (default 600) without one; a streamed answer counts as use. Deploy,
rollback and start are serialized per app.

### H.6 Endpoints

| Method & path | Effect |
|---|---|
| `GET /v1/apps` | `App[]`: `name`, `description`, `sourceDir`, `url`, `state`, `error`, `current` and `previous` (`AppDeployment`: `version`, `deployedAt`, `needs`), `source` (`AppSource`: `version`, `description`, `error`, `addedNeeds`), `secrets` (`AppSecret`: `name`, `set` — what the installed and the source version declare), `lastUsedAt` |
| `PUT /v1/apps/{name}/secrets/{secret}` `{value}` · `DELETE …` | set or forget a declared secret's value (one line) → `App`; 409 if the app declares no such secret |
| `POST /v1/apps` `{sourceDir}` | register the app whose `app.toml` is there → 201 `App`; 409 invalid or name taken |
| `GET /v1/apps/{name}` · `DELETE /v1/apps/{name}` | inspect; unregister (204): versions and backups deleted, the data folder kept |
| `POST /v1/apps/{name}/deploy` | install what the folder holds now → `App`; 422 `deploy failed` with the reason (details in the log). Steps: snapshot (`app.toml`, the server directory, the UI directory; symlinks must stay inside; 256 MiB max) → tests → stop the backend → back the data up → start the new version on a copy of the data until `/api/health` answers → switch. A failure changes nothing |
| `POST /v1/apps/{name}/rollback` | back to the previous version and the data backup taken before the current one was deployed → `App`; 409 if there is none |
| `POST /v1/apps/{name}/stop` | stop the backend now → `App` |
| `PUT /v1/apps/{name}/shortcut` `{shortcut}` | set (GNOME accelerator: modifiers then one key, e.g. `<Super>n`) or remove (`null`) the keyboard shortcut that opens the app (H.7) → `App` (`shortcut`); 409 if another app has it or GNOME cannot be reached |
| `POST /v1/apps/{name}/open` | `AppLink {url}`: a one-time link (H.4); 409 if not deployed |
| `GET /v1/apps/{name}/log` | `AppLog {text}`: the end of the app's log (deploys, backend output) |

Only clients holding the token deploy: agents never get it (§2, invariant 5), so only a person does.

### H.8 From paired devices

Design: `miniapps.md` §5.2. An app is used remotely by the persons it is shared with
(`PUT /v1/apps/{name}/persons {persons}` → `App.persons`; none by default), through the remote
connector (D.7), which polls while a session **or an app** is shared.

- Control channel: `_handler/remote/list_apps` → `{person, scope, apps: [{name, description,
  version}]}` (the apps shared with the device's person); `_handler/remote/apps_changed {apps}` from
  the host when that list may have changed. A device of scope `apps` lists no session and every
  session frame gets -32022.
- Channel `s: "app:<name>"` (requests answered as they finish, the poll goes on meanwhile):
  - `_handler/app/ui {have?}` → `{version, html}`: `index.html` with its scripts and stylesheets
    inlined and the files it names as `data:` URIs (2 MiB at most); `{version, unchanged: true}`
    when `have` is the current version.
  - `_handler/app/http {method, path, headers, body}` → `{status, headers, body}` (bodies base64;
    request 128 KiB, answer 4 MiB at most): only `/api` and `/api/…`; request headers kept:
    accept, accept-language, content-type, if-match, if-none-match, idempotency-key; answer
    headers kept: cache-control, content-type, etag, last-modified, location, retry-after. The
    backend gets `X-HANDLER-Person: <device's person>`.
  - Errors: -32020 not shared with this person (or not deployed), -32602 invalid, -32601 unknown
    method.
- On the device, the page runs in `/appframe.html` served by the gateway with `default-src
  'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src
  data:; media-src data: blob:; connect-src 'none'; frame-ancestors 'self'; base-uri 'none';
  form-action 'none'`, in an iframe `sandbox="allow-scripts allow-forms allow-modals"` (an opaque
  origin: no storage, nothing of the client's). Its only way out is `postMessage` to the client,
  which carries `window.__handlerFetch(path, init)` calls for `/api/…` of that app only.

### H.9 At a time, notifications, host files

- **At a time:** an app has no schedule of its own (since 2026-10-09: triggers live on
  automations only). An automation calls its route (I.1 `run = { app,
  call }`, I.3): `when = { at = "08:30", days = […] }` or `{ every = "30m" }`, as the owner,
  header `X-HANDLER-Automation: <name>`.
- **Notifications** (`needs.notify`): handlerd serves HTTP on `<socket folder>/handler.sock` (in the
  sandbox `/run/handler-app/handler.sock`, env `HANDLER_APP_API`), one per running backend, so the caller is
  known without a token: `POST /notify {title (≤ 120), body? (≤ 1000), person?}` → 200 `{id}` ·
  400 · 403 (a person the app is not shared with) · 429 (more than 30 an hour). A notification
  goes to the person's inbox (I.9: `source: "app"`, its body as `summary`; `GET /v1/inbox`), to
  the desktop when it is for `owner` (`notify-send`, else the freedesktop service over `gdbus`),
  and to the person's devices by Web Push (H.10). A deploy's trial run notifies nobody.
- **Host files** (`needs.files`): resolved (symlinks) at deploy and start; must exist, lie inside
  the home (not the home itself), and never inside or around `~/.ssh`, `~/.gnupg`,
  `~/.password-store`, `~/.local/share/keyrings`, `~/.pki`, `~/.aws` or handlerd's config, state and
  data folders. Mounted at the same path (`rw` only when asked), readable (and writable) by Deno;
  env `HANDLER_APP_FILES` = JSON list of the paths. Not given to tests.

### H.10 Queued calls and push (from devices)

- `list_apps` gives each app's `queued` routes. While the host is not seen, the client sends a
  call to such a route as an envelope to `POST /v1/device/queue` (the gateway keeps it on disk,
  7 days, 500 per host) and answers the app 202 `{queued: true, id}`; calls carry an
  `Idempotency-Key`. The host's poll answer says how many are `queued` (and a queued envelope
  ends a waiting poll); handlerd then lists them (`GET /v1/host/queue`), takes each **once** (ids kept
  8 days, and checked against the direct path's), refuses one older than 7 days (`rejected:
  expired`) and any frame that is not `_handler/app/http` to a route the installed version declares
  queued (-32022), runs the others as H.8 calls, answers the device (its request id,
  `q-<key>`), then deletes it at the gateway (`DELETE /v1/host/queue/{id}`).
- **Web Push:** `_handler/remote/push_key` → `{publicKey}` (handlerd's VAPID key, `<config>/vapid.json`,
  0600); `_handler/remote/push_subscribe {endpoint?}` (https; none: off) → `{subscribed}`;
  `_handler/remote/inbox` → `{messages}` (the device's person's inbox, I.9). handlerd pushes with no
  content (`TTL: 86400`, VAPID `sub` = `HANDLER_PUSH_CONTACT`, default `mailto:handler@example.invalid`)
  to the devices of an inbox message's person, and to a device whose queued call it just ran; a
  404 or 410 forgets the subscription. The client's service worker shows "Something new" and the
  text is read through the channel.

### H.7 Desktop

- **Shortcuts** are the person's choice, not the app's (an agent does not bind keys on your
  desktop): stored in the registry, written by handlerd with `gsettings` as a GNOME custom keybinding
  at `…/media-keys/custom-keybindings/handler-<name>/` (name `handler: <name>`, command
  `<handler> app open <name>`), added to the list without touching the person's own; removed with
  the app.
- **`handler app open`** mints a link (H.4) and opens it in an app window: Firefox with its own
  profile `<data>/firefox-apps` (toolbars hidden by a `userChrome.css`, window class `handler-apps`),
  else Chromium's `--app` mode (profile `<data>/chromium-apps`), else the default browser;
  `HANDLER_APP_BROWSER` forces one.

## I. Automations — `handler.automation/v1`

**Owner:** control plane. **Consumers:** web UI, `handler` CLI, the user's scripts (through `handler-llm`).
**Status:** implemented 2026-10-06 (specified 2026-10-05, revised 2026-10-06: one script per
run, models as the `llm` service); schedules, agent runs, app calls and the
inbox 2026-10-09 (the receipt approval dropped then: turning one on is the approval, I.7). User
guide: `docs/user/automations.md`. An **automation** is the link *when this happens, run that*:
*when a session stops* or *at a time*, *run this*: the user's script, an agent with an interface,
or a mini app's route. It is not a pipeline: when the work has several parts, the script
orchestrates them and passes the data between them. Examples: when a session of a project stops,
a script asks a model which tools, permissions or hosts the agent lacked and appends the findings
to `handler/env-issues.md`; every hour, an agent reviews a project's code and its result comes to the
person's inbox; every weekday at 08:30, a mini app's route reads the agenda and notifies.

### I.1 Definition

An automation is a folder `<config>/automations/<name>/` (`~/.config/handler-ai/automations/`): its
`automation.toml`, and the scripts, prompts and schemas its run uses. The folder is the truth:
handlerd reads it on every use; the web UI and the CLI show everything in it and drive it (on, off,
try, runs), the files are edited in the person's editor. Handler writes a folder only when the owner
makes one (an example copied, or the web UI's form written as `automation.toml`); never a
sandbox (§2 invariant 6). `<name>` matches
`^[a-z0-9][a-z0-9-]{0,63}$`. Hand-written: unknown keys are errors (as E).

```ts
type Automation = {                     // automation.toml
  apiVersion: "handler.automation/v1";
  description?: string;
  when: "session.stopped" | Schedule;   // I.2
  only?: { project?: string[];          // with "session.stopped": names; a stopped session
           agent?: string[] };          // matches when its project (or agent) is listed; absent: any
  run: string                           // a script: a command line (`sh -c`), in its folder
     | { agent: string; project?: string;   // an agent with an interface, by its name in that
         input?: { fields?: object;          // project (absent: an agent of no project), started
                   subject?: { skill: string } } }   // with that input (D.18)
     | { app: string; call: string };   // a mini app's route, "POST /api/…" (H)
  timeoutSec?: number;                  // a script's: default 600, ≤ 3600
  services?: { llm?: string[] };        // a script's: "provider/model", the models it may call (I.5)
  append?: Append[];                    // a script's: [[append]], done by handlerd once it succeeded (I.6)
};
type Schedule = {                       // one of `every` and `at`, local time
  every?: string;                       // "30m", "2h": at least 5m
  at?: string;                          // "08:30"
  days?: ("mon"|"tue"|"wed"|"thu"|"fri"|"sat"|"sun")[];   // with `at`; absent: every day
};
type Append = {
  from: string;                         // a file the run wrote, relative to its output folder
  to: string;                           // a markdown note of the knowledge root (D.5), relative
};
```

```toml
apiVersion = "handler.automation/v1"
description = "What my agents lacked in their environment"
when = "session.stopped"
only = { project = ["my-app"] }

run = "python3 extract.py"
services = { llm = ["mistral/mistral-large"] }

[[append]]
from = "note.md"
to = "handler/env-issues.md"
```

```toml
apiVersion = "handler.automation/v1"
description = "Review the code every hour"
when = { every = "1h" }
run = { agent = "reviewer", project = "my-app", input = { fields = { focus = "security" } } }
```

- **Problems** (`AutomationView.problems`), checked on every read: the file does not parse or
  validate (`only` without `session.stopped`; `timeoutSec`, `services` or `append` without a
  script); a `services.llm` model that is not a provider's model, or whose provider has no
  endpoint for a protocol the `llm` service speaks (`openai-chat`, `anthropic`); an `append.from`
  that is absolute or has a `..` component; an `append.to` that is not usable (outside the root
  with symlinks resolved, a hidden or `_` component, not `.md`, its folder missing: K2, K5); a
  name of `only` that is no project or agent (a problem, not an error: renamed things show up);
  an agent run's project or agent that does not exist (or two agents of that name), an agent
  with no interface, a result schema without a required `status` (an enum of some of `ok`,
  `attention`, `failed`) and a required `summary` (a string: I.3), an input its interface
  refuses, a model it cannot run with (D.19), or an account whose login refuses unattended use
  (I.7); an app call's app that is not registered. An automation with problems never runs.
- A script's models are providers' only (`services.llm`: an API key or a local server). An agent
  run uses its agent's first model; on an account, its login's verdict applies (I.7).
- Handler ships example automations (`handler_control/data/automations/<name>/`); `env-issues` is the
  first (`GET /v1/automation-examples`). `POST /v1/automations {name, from}` copies one into the
  config folder, off. `POST /v1/automations {name, definition, enable?}` writes `definition` as
  the `automation.toml` of a new folder (a header comment, then its keys), off, then turns it on
  when `enable` (I.7): the web UI's form, for an agent's run or an app's route; a script starts
  from an example. `POST /v1/automations/check {definition}` says before what it would do;
  `PUT /v1/automations/{name} {definition}` writes it over an automation's `automation.toml`
  (what was written there by hand, comments too, is replaced): an owner's edit, so one that is on
  stays on (I.7).

### I.2 When a session stops, when a schedule comes

**A session stops.** The trigger is read from the sessions' own event logs (F.5): no other log. A
`lifecycle` event `stopped` carries `how` (F.5): `explicit` (`POST …/stop`, the web UI, `handler`),
`idle` (F.6.3), `exited` (the agent exited by itself), `error`, `run_ended` (a run, D.18),
`daemon_restarted` (F.6.5), `deleted`.

- A stop **fires** an enabled `session.stopped` automation when: the session is a conversation
  (its agent has no interface: runs never fire), `how` is not `deleted` nor `daemon_restarted`,
  `only` matches the session's project and agent names at that time, it happened after the
  automation was enabled (`since`), and its log has a `turn` event after the automation's cursor
  for that session.
- **Cursor**: one per (automation, session), the last `seq` a run covered. A run reads the slice
  `seqFrom = cursor + 1` to `seqTo` = the log's last `seq` when the run starts. A session that
  stops, resumes and stops again is read in parts, each part once; the part before a
  `daemon_restarted` stop is read with the next stop that fires.
- **Coalescing**: at most one pending run per (automation, session); more stops before it starts
  add nothing (its slice grows).
- **At least once**: pending runs are not stored: at start, handlerd scans the logs written since each
  automation's `since` for stops that fire past the cursor, and queues them. The cursor moves when
  a run ends (`succeeded`, `failed`, `cancelled`), in the same write as its record; a run cut by
  handlerd stopping is `interrupted` and queued again. A crash between the appends and that write can
  append a run's notes twice.
- A stop is told to the runner by the session store (`SessionStore.stop_listeners`, the session's
  id only); the logs are read off the event loop. A pending run is checked again when it starts:
  an automation turned off or with problems meanwhile does not run (its stops are read once it is
  on again).

**A schedule comes.** handlerd's own scheduler: no OS timer (systemd, launchd). It looks every 20 s,
in local time (`handler_control/schedules.py`).

- Its **slots**: `every` counts from its last slot (or from when it was turned on: it does not run
  at once), so the cadence holds whatever the run's length; `at` is that time each day of `days`.
- A slot past its last one queues a run for it; **after the computer was off** (or asleep, or handlerd
  stopped) over several slots, only the **latest** runs, and its record says how many were
  `missed` before it. One pending run per automation: a slot coming while one waits replaces it.
- The slot is taken (`lastSlot` in `state.json`) when its run starts: a run cut by handlerd stopping
  is `interrupted` and not run again (the next slot runs).

### I.3 A run

One run at a time for the whole daemon (scripts, agent runs and app calls alike), in the order
queued: a run waiting says what it is behind (`behind`). At most 100 runs per automation per day
(UTC; counted in memory, and from the kept runs at start): past it, runs stay pending (shown
`capped`) until the next day, and a try is refused (429).

```
<state>/automations/<name>/
  state.json                 { enabled, since?, cursors: {sessionId: seq}, lastSlot? }
  runs/<runId>/              0700; the last 50 kept, none older than 30 days
    run.json                 the AutomationRun record (I.9)
    definition/              a script's: a copy of the automation's folder at its start (what ran)
    input/                   a script's: I.4, read-only to it
    output/                  a script's: written by it
    run.log                  a script's stdout and stderr, secret values redacted, ≤ 1 MiB
    services.ndjson          a script's service calls (I.5)
```

**A script** is one sandbox (A): the toolbox image, confinement `strict`, network `none`, the host
user, `sh -c <run>`; mounts at their host paths: `definition/` (read-only, the workdir, kind
`scope`), `input/` (read-only, kind `subject`), `output/` (read-write, kind `state`), Handler's
`data/automation/bin/` (read-only, on `PATH`: `handler-llm`) and, when the automation has `services`,
the folder of its services socket (I.5, `<runtime>/automations/<runId>/`). Environment:
`HANDLER_INPUT`, `HANDLER_OUTPUT`, `HANDLER_RUN` (the run's id), `HANDLER_TRY` (`1` in a try, else `0`),
`HANDLER_SERVICES` (the socket, when there is one). The sandbox is labelled `handler.automation`.

- The script exiting non-zero or passing its timeout ends the run `failed` (nothing is
  appended). The toolbox image missing fails the run at once ("toolbox not built: `handler image rebuild
  toolbox`").
- `POST …/runs/{id}/cancel` stops the script: `cancelled`.

**An agent run** is a run of the agent with an interface (D.18): a session started by handlerd with
`origin: "automation"`, its input, the agent's first model, its own sandbox and settings
(folder, network, confinement: what the agent's page shows; its folder read-write), unattended.
The run's record names it (`agentSessionId`); the session lists the run
(`GET /v1/sessions/{id}/automation-runs`). It ends when the session stops: `succeeded` with a valid
result, else `failed` ("no valid result: …": none, invalid, timed out, the agent crashed).
`…/cancel` stops its session.

**An app call** starts the app's backend if needed and calls `POST /api/…` of its installed
version as the owner (`X-HANDLER-Person: owner`, `X-HANDLER-Automation: <name>`, 5 min timeout): an HTTP
status ≥ 400 or no answer is `failed`. It is written in the app's log.

**The inbox** (`InboxMessage`, I.9) is told, as the owner's:

- an agent run's result (a try's too): `title` the automation's name, `agent`, `status` and
  `summary` from the result (which its schema requires, I.1), `data` the whole result,
  `sessionId` its session (its result is shown from the interface's schema, D.18);
- a failed run (not a script's or an app call's try: its page shows it): `status: "failed"`, the
  error as `summary`.

Nothing else is told: a script's success is its appends.

### I.4 Input

A script on a **stopped session** reads that session:

```
input/
  event.json      { type: "session.stopped", sessionId, agentId, agent, projectId?, project?,
                    how, seqFrom, seqTo, t }
  session.json    the Session (F.1), its agent's name and sandbox settings (network, allow,
                  confinement, permissions, bindings, knowledge)
  events.ndjson   the log's events seqFrom..seqTo, as in the log (F.5)
  transcript.md   the same slice for reading (below)
```

A script on a **schedule** reads only `event.json`: `{ type: "schedule", slot, missed, t }`. An
agent run's input is the automation's `run.input` (D.18).

- `transcript.md`: a header (agent, project, model, folder, sandbox settings, slice), then each
  event in order with its `seq`: the person's prompts, the agent's messages and thoughts (chunks
  joined), each tool call (title, kind, status, its input and output, each cut to its first 2 000
  and last 1 000 characters), permission answers, turn ends with their stop reason, starts and
  stops. The log is already redacted (F.5); the transcript and `events.ndjson` are redacted again
  with every value of the secret store (D.14): they go to another provider.
- The conversation holds text written by others (web pages, files, tool output): the scripts and
  the model must treat it as data. The model has no tools (I.5) and nothing it says is written
  anywhere but the run's folder and the notes of I.6.

### I.5 Model calls: the `llm` service and `handler-llm`

Models are the first **service** (`docs/dev/design/services.md`): the interface `llm/v1`
(`handler_control/data/interfaces/llm/v1/`), one tool `llm_complete`, served by handlerd's service router
on a socket mounted in the run's sandbox (`$HANDLER_SERVICES`, one per running automation run). Its
connector is built into handlerd and its bindings are the providers: `services.llm` selects the models
the script may call.

The socket speaks **MCP**: JSON-RPC 2.0, one message per line (decided 2026-10-06, so agents and
apps reach the same router later through a stdio bridge with no translation): `initialize`,
`ping`, `tools/list` (the interface's `tools.json`, nothing when the caller selected no model),
`tools/call {name: "llm_complete", arguments: LlmRequest}` → `{content: [{type: "text", text:
<JSON>}], structuredContent: LlmResponse, isError: false}`; an error of the interface is
`isError: true` with `{"error": code, "message"}` as its text. An input that does not match the
tool's input schema (or is too large, or a `schema` that is not a JSON Schema) is the JSON-RPC
error -32602; the output is checked against its output schema before it is sent (S2).

A script calls it with `handler-llm`, the command-line client of `llm/v1` (shipped by Handler, on the
run's `PATH`):

```
handler-llm --model mistral/mistral-large [--system FILE] --prompt FILE [--schema FILE] < input > out
```

```ts
type LlmRequest = { model: string;          // one of the automation's `services.llm`
                    system?: string; prompt: string; input?: string;   // ≤ 256 KiB in all
                    schema?: JSONSchema };  // ≤ 64 KiB: the answer is JSON valid against it
type LlmResponse = { valid: boolean; value?: unknown;   // with a schema: the parsed answer
                     text?: string;                     // without one, or not valid: the answer
                     error?: string;                    // why it is not valid
                     usage: { inTokens: number; outTokens: number }; ms: number };
// errors (the closed list of llm/v1, S3): refused (a model not selected), limit, unavailable
```

- handlerd calls the provider's endpoint (`openai-chat`: `<endpoint>/chat/completions`, else
  `anthropic`: `<endpoint>/v1/messages`) with its key resolved from its reference: the key never
  enters the sandbox, and the run has no network. An endpoint written for containers
  (`host.containers.internal`) is called on the loopback. `input` follows the prompt in
  `<input>…</input>`. With a schema, the schema and "answer with one JSON value only" go in the
  system prompt; handlerd takes the JSON from the answer (a fenced block, else from the first `{` or
  `[`), checks it, and asks once more with the error when it does not match.
- `refused`: a model not in `services.llm`. `limit`: past 120 s per call, one call at a time, 50
  calls per run. A provider failing or unreachable is `unavailable`.
- `handler-llm` prints `value` (JSON) or `text` and exits 0; on `valid: false` or an error it prints
  the error on stderr and exits 1.
- Each call is logged in `services.ndjson`: `{t, interface, model, inTokens, outTokens, ms,
  valid, repaired, error?}`; a run's totals are in its record. Handler calls a model only for a
  script: never on its own.

### I.6 Appends

Once a script's run succeeded (not in a try), handlerd appends each `from` file to its `to` note, in
order: the note (and nothing else) is created when missing; a `from` file that does not exist is
skipped (the script had nothing to add); one larger than 256 KiB, not a regular file, or resolving
outside the run's output folder (a symlink) fails the run, as a note no longer usable (K2, K5)
does. Every file and note is checked before anything is appended. Each block is:

```
<blank line>
<!-- handler automation <name> · run <runId> · session <sessionId> · <t> -->  (no session: a schedule)
<the file's content>
```

Knowledge stays read-only to every sandbox (D.5): only handlerd writes there, by appending. Notes are
read by agents later: what is appended came from a model reading untrusted text, and the comment
says where it came from.

### I.7 On and off: the owner's approval

An automation is **off** when created and runs only while on. Turning it on is the owner's
approval, the only one: the files of an automation are written by the owner only (no sandbox ever
reaches Handler's config, §2 invariant 6), so the owner's later edits apply at its next run, without
turning it off.

- **Only the owner turns it on or off**: through the Control API (its token: the web UI, `handler`),
  never from a sandbox. No service of the socket (I.5) enables, disables or changes an
  automation; a shipped example (or later the agent creator) proposes one, off.
- Turning it on (`POST …/enable`; 409 while it has problems) sets `since` to now when it was off:
  stops and slots before are not read. Turning it off drops its pending runs. Deleting it
  (`DELETE /v1/automations/{name}`, on or off) drops them too, cancels the one in progress (and
  waits for it to end), then removes its folder and its state (`<state>/automations/<name>/`:
  runs, logs, cursors): a later one of that name starts afresh. What it told the inbox stays.
- **What it does** (`AutomationView.permissions`): computed from its files on every read, in
  sentences: what starts it, what runs (a script without network and what it reads, its models,
  its notes; the agent, its folder read-write, its network, confinement and model; the app's
  route), where results go. Shown before it is turned on.
- **Unattended use of a subscription.** An agent run on an account is allowed by the verdict of
  that account's login (B: `unattended` of the harness's `[login]`, with the vendor's `terms` and
  when they were read, `checked`), set per vendor by Handler: `allowed` (no warning); `check-terms`
  (unclear or not read yet: `AutomationView.warnings` says "check your plan's terms … an API key
  (a provider) is recommended", with the terms' link); `refused` (a problem: the agent needs a
  provider first). Today: Claude Code's `refused` (a Claude subscription is for interactive use
  by its owner: `docs/dev/ui-ux.md` "Vendors' terms"), Codex's and Vibe's `check-terms`. A provider (an API key, a local server) has no
  verdict. The accounts screen shows each account's.

### I.8 Try

`POST /v1/automations/{name}/try {sessionId?}` runs it now, on or off (not with problems): on
that session for a `session.stopped` one (required; the slice is the whole log, its cursor is
neither read nor moved), with no session for a scheduled one (409 when it does not fit). The run
is `trial`. A script's try has `HANDLER_TRY=1` and appends nothing: its record lists what it would
append (`appended[].text`, the first 4 KiB each). An agent run's or an app call's try is a real
run (its result comes to the inbox). Tries count in the daily cap.

### I.9 Endpoints

```ts
type AutomationView = {
  name: string; description?: string; definition?: Automation;   // absent when it does not parse
  directory: string;                    // its folder, where its files are edited
  files: string[];                      // its folder's files, relative (hidden ones left out)
  problems: string[]; enabled: boolean;
  permissions: string[];                // what it does, in sentences (I.7)
  warnings: string[];                   // to know before turning it on (an account's terms, I.7)
  nextAt?: string;                      // a scheduled one's next slot, while on (past: due now)
  pending: number; capped: boolean;     // runs waiting; the daily cap reached
  behind?: string;                      // the automation running now, when its runs wait
  lastRun?: AutomationRun;
};
type AutomationCheck = {                // a definition not saved yet: what its view would say
  problems: string[]; warnings: string[]; permissions: string[];
  nextAt?: string;                      // a schedule's first slot if it were turned on now
};
type AutomationRun = {
  id: string;                           // "a_" + 16 hex
  automation: string; trial: boolean;
  sessionId?: string; seqFrom?: number; seqTo?: number;   // the stopped session it read
  slot?: string; missed: number;        // a schedule's slot, and the slots missed before it
  agentSessionId?: string;              // an agent run's session
  state: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
  exitCode?: number; ms?: number;
  llm: { calls: number; inTokens: number; outTokens: number };
  appended: { to: string; bytes: number; text?: string }[];      // text: a try's preview
  error?: string; createdAt: string; endedAt?: string;
};
type InboxMessage = {                   // the person's inbox (apps' notifications, H.9; I.3)
  id: string; source: "app" | "automation"; name: string;   // the app's, the automation's
  agent?: string;                       // an automation's agent
  person: string;                       // "owner", or a person an app is shared with
  title: string; status?: "ok" | "attention" | "failed";   // an app's notification: none
  summary?: string;                     // an app's body; an agent's summary; a failure's error
  data?: unknown;                       // an agent run's whole result
  runId?: string; sessionId?: string;   // an automation's run; an agent run's session
  at: string; read: boolean;
};
```

| Method & path | Effect |
|---|---|
| `GET /v1/automations` | every automation of the folder → `AutomationView[]` |
| `GET /v1/automation-examples` | the examples Handler ships → `{name, description?}[]` |
| `POST /v1/automations` `{name, from}` | a shipped example copied as `name`, off → `AutomationView` (201; 409 the name exists; 404 no such example) |
| `POST /v1/automations` `{name, definition, enable?}` | `definition` written as `name`'s `automation.toml`, off; with `enable`, then turned on (I.7) → `AutomationView` (201; 409 the name exists, or with `enable` it has problems: it stays, off; 422 an invalid definition, or both `from` and `definition`) |
| `POST /v1/automations/check` `{definition}` | what it would do → `AutomationCheck` (422 an invalid definition) |
| `PUT /v1/automations/{name}` `{definition}` | `definition` written over its `automation.toml`, on or off as it was → `AutomationView` (404 unknown; 422 an invalid definition) |
| `DELETE /v1/automations/{name}` | I.7: its runs stopped, its folder and its state removed → 204 (404 unknown) |
| `GET /v1/automations/{name}` | → `AutomationView` |
| `GET /v1/automations/{name}/files/{path}` | one of its files as text (≤ 1 MiB) |
| `POST /v1/automations/{name}/enable` · `…/disable` | I.7 → `AutomationView` |
| `POST /v1/automations/{name}/try` `{sessionId?}` | I.8 → `AutomationRun` (202) |
| `GET /v1/automations/{name}/runs` | most recent first → `AutomationRun[]` |
| `GET /v1/automations/{name}/runs/{id}` | → `AutomationRun` |
| `GET /v1/automations/{name}/runs/{id}/log` | a script run's log as text |
| `POST /v1/automations/{name}/runs/{id}/cancel` | I.3 → `AutomationRun` (409 when it ended); a run cancelled while it is set up never starts its sandbox or its agent's session |
| `GET /v1/sessions/{id}/automation-runs` | the runs on that session, or the one that started it (an agent run), most recent first → `AutomationRun[]` |
| `GET /v1/inbox` | the last 50 messages, newest first → `InboxMessage[]` (200 kept, `<state>/inbox.json`) |
| `POST /v1/inbox/{id}/read` | → `InboxMessage`, `read: true` (404 unknown) |

A message for the owner is also shown on the desktop (`notify-send`, else the freedesktop
service) and pushed, content-free, to the person's paired devices (H.10); a device reads its
person's messages with `_handler/remote/inbox` (docs/dev/design/remote.md).

CLI: `handler automation list` (on/off, when, what runs, last run, problems), `handler automation
show|new <name> --from <example>|examples|try <name> [--session id|last]|enable [--yes]|disable|delete [--yes]|
runs <name>|log <run>|cancel <run>`, `handler inbox`. Web UI: an Automations page (the list, a script
from an example), a New automation form (when: a time, with presets, or a stopped session; run:
an agent with an interface and its input, or an app's route; checked as it is filled in; Create
and turn on, or Create, off; Change, for one the form can say: not a script nor an `only` of
agents or several projects), reached also from an agent's settings ("Save and run it on a schedule…", once it runs
unattended, saved or not) and page ("Run it on a schedule…"); the settings list the automations that run it, and where agents are listed the ones
on show as badges), one page per automation (what it does in sentences, its
warnings, its next run, files, problems, Try, Turn on confirming what it does, Turn off, Delete saying what goes, runs with what they were for,
the slots they missed, the agent's run, a script's log); a session's page lists the runs on it
(its *Automations* panel); an Inbox page; the accounts screen says each account's verdict (I.7).

### I.10 Invariants

1. A run causes no events: an automation cannot set off another one, nor itself (a loop is not
   possible): an agent run's session is a run (D.18), and runs never fire (I.2). An event a run
   could cause needs a loop rule first.
2. A script has no network and no secret: models are reached through handlerd's `llm` service (I.5),
   only those its `services.llm` names, on providers only.
3. Only handlerd writes outside a script's run folder, and only by appending to the declared notes
   after the run succeeded (I.6); the inbox is written by handlerd only, never by a sandbox.
4. Nothing runs that is off; a try runs only when asked, and a script's writes nothing outside
   its run.
5. An agent run on an account whose login's verdict is `refused` never starts (I.7).

Conformance: unit tests `packages/control-plane/tests/test_transcript.py`,
`test_automation_config.py`, `test_automations.py` (the stop that fires past a cursor, the slot a
schedule queues and what it missed, appends, what the inbox is told, what an automation says it
does), `test_schedules.py`, `test_llm.py` (the connector against a stub provider speaking
`openai-chat` and `anthropic`, the router over its socket); `tests/automations/` with the fake
agent and the fake sandbox running the script on the host, `handler-llm` reaching a stub provider (a
stop → a run → the note appended once, the key only sent to the provider, the store's secrets
redacted; stops before `since`, `deleted` and turnless ones do not fire; resume + stop reads only
the new part; a try appends nothing; the owner's edits apply while on; a failing script appends
nothing; handlerd restarted mid-run → `interrupted`, run again; a schedule runs its latest slot once
with the missed ones counted; an agent run's result in the inbox, its failure too; the result
schema and the account's terms checked; the CLI); `tests/apps/test_apps_coach.py` (an app call);
one real-podman test of the script's sandbox (read-only input and definition, no network,
`handler-llm` on PATH; skipped without the toolbox); the web UI flow in `tests/e2e/test_web_ui.py`.

## 2. Cross-cutting invariants

1. Nothing an agent does can execute on, or read from, the host outside its mounts (A2, P1, P4),
   unless its agent explicitly opts out with confinement `privileged` (A.5, confirmed, D.8).
2. Clients never see or pass host details beyond the scope path: no image, container, network or
   proxy names (D exposes `sandbox` ids only as opaque strings).
3. How an Agent is sandboxed is visible in the Control API (its `network`, `confinement`,
   `permissions`, the harness) but **not** in ACP. ACP traffic is identical either way.
4. Secrets travel only as references (E2) until `render`, then only via env or files (B3), as
   phantoms where they can be (E3: the value only to the sandbox's proxy). Never in
   argv, logs or transcripts (the control plane MUST redact known secret values in logs).
5. Every control-plane listener binds loopback and requires the token. The token is as powerful
   as the user: it can edit accounts, providers and agents. It lives in a `0600` file that no
   sandbox gets: no API writes a host path that is, holds or is inside the daemon's own folders
   (the work folders, D.13).
   Mini apps' origins (H.4) take a per-app cookie derived from it instead, which opens that app
   only.
6. **No sandbox ever reaches Handler's own files**, read or write, by any feature and at any
   confinement: the token, the secret store (`<data>/secrets.json`), and the definitions Handler acts
   on (accounts, providers, bindings, `folders.toml`, automations and their `state.json`,
   `agents.json`, `projects.json`). A sandbox gets only a subfolder made for it (its session's
   `agent/` and `work/`, an account's harness state, a skill read-only as a run's subject, an
   automation run's copy of its folder and its `input/`, `output/`), never a folder holding one
   of those files. What Handler acts on is written by the owner only: through the Control API (the
   token) or by hand.

## 3. Conformance matrix

| Suite | Runs against |
|---|---|
| `tests/sandbox` | each sandbox impl |
| `tests/harness` | each harness adapter + image; rebuild, check, switch (D.4) |
| `tests/acp-endpoint` | control plane with fake agent |
| `tests/control` | control plane HTTP API |
| `tests/sessions` | control plane with fake agent (F) |
| `tests/addons` | addon and binding validation, composition (G), each addon image and its check (G.4) |
| `tests/apps` | mini apps (H): deploy, origin, cookie, same-origin rule, data across versions, rollback, idle stop, secrets and egress, shortcuts, host files, an automation's call, notifications — real podman |
| `tests/remote/test_remote_apps.py`, `test_remote_queue.py` | mini apps from devices (H.8, H.10): persons, scopes, the app channel, queued calls, push subscriptions |
| `tests/automations` (§I) | control plane with fake agent and fake sandbox: stops, runs, cursors, appends, try, the `llm` service through a stub provider, the CLI; the run's sandbox on real podman |
| `tests/e2e` | real Claude + Vibe agents, podman impl |

## 4. Decisions (2026-09-23)

| # | Question | Decision | Where |
|---|---|---|---|
| 1 | Account-level connectors (claude.ai MCP) in sessions? | Per-account setting (`connectors`), **off by default** | B.2 `accountConnectors` |
| 2 | Keep real credentials out of containers in v1? | **No, v2.** v1 mounts the state folder and injects env secrets. v2: phantom tokens via a broker in the egress hop, for **both** credential files and env-var secrets. Since 2026-10-08 the env-var secrets (accounts' tokens, providers' keys, bindings' secrets) are phantoms swapped at the sandbox's proxy (A.3, E3); credential files still to do | E `state`/`secrets`; the broker for credential files: not started |
| 3 | Which user runs the harness? | **Not root; the host user's uid/gid** (keep-id), so mounted tools and files are usable and owned correctly | A3 |
| 4 | How is the permission mode applied? | **Explicit ACP `session/set_mode`** after session creation (P7); env only when a harness has no ACP mode; no settings files | B.1 `PermissionMapping`, C.4 P7 |
| 5 | Proxy per container or shared? | **One per container** | A.3 |
| 6 | Who holds an interactive session? (2026-09-24) | **The daemon**, one sandbox per Session, with ids created by Handler, a folder per session and an event log; clients attach/detach, **one at a time** for now | F |

## 5. Verification status

1. ✅ Claude account connectors: `ENABLE_CLAUDEAI_MCP_SERVERS=false` → the session lists none
   (with `true`: "claude.ai Google Drive, claude.ai Claude Docs"). The Claude adapter maps
   `accountConnectors = false` to this env var.
2. ✅ Decision 3 on the host (2026-09-23, `scripts/host-check.sh`, rootless Podman 6.1.2):
   keep-id runs as `1000:1000`, not root; without forcing, `HOME` is `/`, so forcing it is required;
   a private home via `--mount type=tmpfs,destination=<home>,tmpfs-mode=0700,chown=true` works with
   `--read-only` (**chosen over mode 1777**); scope files and cache files are owned by your user;
   `~/.claude-perso` and `~/.claude-perso.json` are readable.
5. ✅ Rootless proxy topology: a container on the default (pasta) network cannot be joined to more
   networks later, so the proxy is created on both networks at once
   (`--network podman --network <internal>:ip=…`). Verified on the host: no direct egress,
   allowed domain reachable through the proxy, other domain refused.
3. ✅ Proxy per container: about 0.15 s setup and 0.15 s teardown with a prebuilt image.
4. ✅ Live egress toggle (tinyproxy filter rewrite + `SIGUSR1`): enforce → log-only → enforce
   applied to a running network without restarts.

6. ✅ Local model server on the host (2026-09-23, `host-check.sh --model-endpoint`, rootless
   Podman 6.1.2 + pasta): `host.containers.internal` resolves to `169.254.1.2` and reaches a server
   bound to the host's loopback (Ollama :11434), both with network `open` and through the
   allow-list proxy (entry `host.containers.internal`). Note: curl only honours lowercase
   `http_proxy`; sandboxes set both cases.
