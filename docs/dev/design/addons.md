# Handler — Addons

Status: **implemented** (2026-09-25). Normative: `contracts.md` §G (the `handler.addon/v1` and
`handler.binding/v1` contracts). As users see it, installing and writing one:
[addons](../../user/addons.md).

## 1. Goal

Give agents the ability to **act on a broader world** (a store, a CI server, a log cluster, a test
environment, internal APIs) without baking every tool into the toolbox image, and without handing
an unsupervised agent more power than its role needs.

The toolbox stays the shared development environment. A tool used a few times a year must not grow
it, nor force a rebuild of every harness image when it changes.

## 2. Use cases

| # | Use case | What the agent needs |
|---|---|---|
| UA1 | Work on a Shopify theme with the Shopify CLI | a tool (the CLI), a store, a token, egress to Shopify, a skill |
| UA2 | Read the logs of our services in OpenSearch | no tool (`curl` is in the toolbox), an endpoint, a login, a skill (indices, query syntax) |
| UA3 | Push a branch, wait for Jenkins, deploy to dev, test the deployed API | git, Jenkins, a deployment target, the app's API, each with its own access |
| UA4 | Role agents: dev, QA, security | the same systems as UA3, with different rights per role |

UA1 is about **packaging a tool**. UA2 to UA4 are about **granting access**: the hard part there
is credentials and permissions, not binaries.

## 3. Concepts

An addon packs everything that makes a capability usable. Its parts are not all of the same kind:

| Part | Shopify (UA1) | OpenSearch (UA2) | Jenkins (UA3) | Generic or yours? |
|---|---|---|---|---|
| **Tool** (binaries) | Shopify CLI | none, or an MCP server | often none (`curl`) | generic, **optional** |
| **Skill** (knowledge) | theme workflow, what is safe to run | index names, query syntax, how to find a service's logs | job names, how to wait for a build | generic, plus your conventions |
| **Egress** | `*.myshopify.com:443`, `*.shopify.com:443` | the cluster | the Jenkins host | generic pattern, your hosts |
| **Settings** (non-secret) | the store | the cluster URL | the Jenkins URL | **yours** |
| **Credential** | theme token | login / password | API token | **yours** |
| **Rights** | development store only | read-only on `logs-*` | build `app-dev` only | **yours, per role** |

This gives three layers, each defined in one place:

| Layer | Where | What it holds | How many |
|---|---|---|---|
| **Addon** | a folder `<name>/`: built-in (`handler_harness/data/addons/`) or the user's (`~/.config/handler-ai/addons/`) | how to use a kind of system: tool image (optional), skills, env, setting and secret slots, egress pattern, provisioning recipe. Generic, shareable, versioned. | one per kind of system: `shopify`, `opensearch`, `jenkins` |
| **Binding** | `~/.config/handler-ai/bindings/<name>.toml` | one addon bound to one instance of the system: settings, credential references (and, later, access method). Its rights are those of the dedicated account behind the credential (§8.1). | one per system instance: `shopify-dev-shop`, `jenkins-dev`, `jenkins-prod-readonly` |
| **Selection** | the agent | a list of binding names | per agent |

Why selection is per agent, not per account: addons follow the **project** (Shopify matters for
the theme repository, not for this one), and an agent works on one project (or ad hoc in one
folder). Binding them to accounts would need an account for every combination of login and
project.

Why credentials are not typed into the agent: the same shop would be re-entered for every
project that uses it, and credentials would be scattered across `agents.json`. A binding
defines each credential once, named and reviewable; an agent only names bindings.

The same addon can back several bindings (Jenkins dev with build rights, Jenkins prod
read-only).

## 4. Packaging: the addon image

### 4.1 Layout

One directory per addon, built-in (`handler_harness/data/addons/`, next to `harnesses/`) or the
user's (`~/.config/handler-ai/addons/`):

```
addons/<name>/
├── addon.toml      manifest (handler.addon/v1)
├── Containerfile   what gets installed; optional (an addon may have no tool)
├── skills/
│   └── <skill>/
│       └── SKILL.md how the agent uses it
└── PROVISIONING.md how to create the least-privilege account the addon expects (§8.1)
```

Skills sit in `skills/<skill>/` rather than a single `skill/` folder: `render` names each mounted
skill after its folder, so every addon's skill would otherwise be called `skill`.

### 4.2 Containerfile

Two stages: install **at build time** in the toolbox (same Node, Python, glibc as the sandbox that
will run the tool), then keep only the installed tree in a `FROM scratch` image.

```dockerfile
ARG TOOLBOX_IMAGE=localhost/handler-ai-toolbox:latest
FROM ${TOOLBOX_IMAGE} AS build
ARG PREFIX=/opt/addons/shopify          # build at the path where it will be mounted
RUN npm install --prefix "$PREFIX" --no-fund --no-audit @shopify/cli \
    && npm cache clean --force \
    && mkdir -p "$PREFIX/bin" \
    && ln -s ../node_modules/.bin/shopify "$PREFIX/bin/shopify" \
    && echo "Shopify CLI $(jq -er .version "$PREFIX/node_modules/@shopify/cli/package.json")" > "$PREFIX/version" \
    && rm -rf /home/agent

FROM scratch
COPY --from=build /opt/addons/shopify /
```

Conventions:

- **Build at the mount path**, `/opt/addons/<name>`: any absolute path baked in at install time
  still resolves in the sandbox (the same idea as same-path scope mounts).
- **`bin/`** holds symlinks to the commands the addon provides. It is the only directory the
  launcher puts on `PATH`, whatever the packaging (npm prefix, uv venv, static binary).
- **`version`** at the root: one line for people, like `/usr/share/handler/version` for harness
  images (B.6). The build fails if it cannot be read.
- Install **at build time, never in an init script**: an install at boot needs network at every
  start, is slow, and changes version silently.

### 4.3 Mounting

```
podman run … \
  --mount type=image,src=<shopify image id>,dst=/opt/addons/shopify \
  --mount type=image,src=<httpie image id>,dst=/opt/addons/httpie \
  -e PATH=<the image's PATH>:/opt/addons/shopify/bin:/opt/addons/httpie/bin
```

Addons are mounted by image **id**, resolved from `:latest` when the agent starts, not by tag
(§4.5).

- Read-only, one mount per addon, each at its own path: addons never overwrite each other and can
  carry different versions of the same library.
- **Addons are appended to `PATH`**: the toolbox always wins, so an addon cannot replace `node` or
  `git`.
- Nothing is built at launch, and there is no image per combination of addons: an agent with five
  addons is five mounts.

### 4.4 Skills stay on disk

Skills are mounted read-only from `addons/<name>/skills/<skill>/`, like the skills of
`~/.config/handler-ai/skills/`, not copied into the image. Skills change far more often than tools, and
fixing a sentence must not need a rebuild.

### 4.5 Rebuilds

Same flow as harness images (D.4), with a new target `addon:<name>`:

1. build an untagged image without cache;
2. check: mount it into the toolbox with no network and run the manifest's `check` command
   (e.g. `shopify version`);
3. tag it `:latest` (the image it replaces is removed once unused).

Addons use the toolbox's runtimes, so **a toolbox rebuild also rebuilds and checks every addon
image already built** (one never built is not in use), and switches all of them or none, as it
does for harnesses.

Unlike a harness image, an addon image in use is not protected by podman: `podman image rm`
refuses to remove a container's own image, but not an image the container only mounts (found
2026-09-25: two switches while an agent had the addon mounted removed its image; the agent kept
running on the old files). So the sandbox mounts an addon by **image id**, not by tag, each
container is labelled with the ids of the addon images it mounts, and the runtime's `image remove`
(contract A.7) refuses an image a container's label says it mounts.

Addon images are built with `--no-intermediate` (podman `--layers=false`): with layer caching, the build stage of the two-stage
Containerfile stays behind as an untagged image after every build.

### 4.6 Why an image rather than a folder of binaries

At runtime an addon *is* a read-only folder with binaries and instructions, i.e. a skill with its
tools. The image is the better format to build and ship that folder:

| | Folder (e.g. a skill with binaries) | Addon image |
|---|---|---|
| Where it is built | must be built in the toolbox anyway, then copied out | `podman build` does exactly that |
| Recipe | separate or implicit | the Containerfile, in git |
| Changes after install | a host folder can change mid-session | immutable, content-addressed |
| Update | manual | build → check → `:latest` |
| Another machine | copy and hope it matches | `podman push` / `pull` |

## 5. Manifest, bindings and selection

### 5.1 Addon manifest (`handler.addon/v1`)

Generic: it declares slots, a binding fills them.

```toml
# addons/shopify/addon.toml
apiVersion  = "handler.addon/v1"
description = "Shopify CLI: themes and apps"
image       = "localhost/handler-ai-addon-shopify"  # no tag: the platform owns :latest
commands    = ["shopify"]                        # exactly what bin/ provides (checked at build)
check       = ["shopify", "theme", "list", "--help"]   # offline: `shopify version` needs the network
env         = { SHOPIFY_CLI_NO_ANALYTICS = "1" }
egress      = ["theme-kit-access.shopifyapps.com", "*.shopify.com", "*.shopifycdn.com",
               "*.myshopify.com", "registry.npmjs.org"]   # seen in log-only mode

[settings.store]                                 # setting slot → env var
env      = "SHOPIFY_FLAG_STORE"
required = true

[secretSlots.theme_token]
env = "SHOPIFY_CLI_THEME_TOKEN"

[secretSlots.partners_token]
env = "SHOPIFY_CLI_PARTNERS_TOKEN"
```

Skills are found in `skills/`, no key needed. `commands` is declared so that name clashes can be
checked without opening images.

### 5.2 Binding (`handler.binding/v1`)

One file per binding in `~/.config/handler-ai/bindings/` (`$HANDLER_BINDINGS_DIR`), named after the
file, TOML like accounts and providers (unknown keys are errors):

```toml
# ~/.config/handler-ai/bindings/shopify-dev-shop.toml
apiVersion  = "handler.binding/v1"
addon       = "shopify"
description = "Development store, theme-only token"
settings    = { store = "my-dev-shop.myshopify.com" }
secrets     = { theme_token = { command = ["pass", "show", "shopify/dev-theme-token"] } }  # SecretRef (E2)
```

A binding is invalid if its addon is unknown, a slot it binds is not declared by the addon, or
a required setting or secret is missing. An invalid binding is listed with its error and cannot be
selected.

Two bindings of the same addon cannot be used by the same agent: they would set the same env
vars and mount the same image. Jenkins dev and Jenkins prod go to different agents.

### 5.3 Selection

- **Agent**: `bindings` in its settings (`AgentRequest`, D.8; `POST /v1/agents` for an ad-hoc
  one, CLI `--binding`); persisted in `agents.json`. In the web UI, **Addons** in the agent's form (`addon: configuration`).
- **Not in an account or provider**: they say how a harness reaches a model; which addons an agent
  gets is the agent's choice, so it is visible where the agent is set up.

Bindings are fixed when an agent starts (mounts are set when its container is created).
Changing an agent's bindings applies to the next session, not a running one.

### 5.4 Resolution

At each agent start, the control plane resolves the selected bindings into the `SandboxSpec`:
image mounts (by id), `PATH` suffix, env, settings, secrets (through the existing reference → env
path, with redaction, B3), egress merged into the allow-list, skills mounted read-only (added to the
skills `render` already mounts, so a harness without skill support fails with the existing B5
error).

Addons whose settings name hosts (OpenSearch, Jenkins) take their egress from those settings
rather than from a fixed list; the exact form is an open question (§11).

### 5.5 Not in the project folder

A file in the project (e.g. `.handler.toml` listing bindings) is tempting, but the project folder
is mounted **read-write** into the agent: it could add `opensearch-prod` to that file and get the
binding at its next start. At most such a file could *suggest* bindings that a person
confirms in the UI (§11).

## 6. Limits

| Limit | Handling |
|---|---|
| **Tools must be self-contained** (npm, pip/uv, Go or Rust binaries). A pacman package with shared libraries in `/usr/lib`, a daemon or device access does not fit. | Put it in the toolbox if it is used often. Otherwise, a later addon kind (§7). A pacman install into a prefix plus `LD_LIBRARY_PATH` is possible but breaks on hard-coded `/usr/share` paths: not a foundation. |
| **Two addons provide the same command.** | The agent is rejected when it is saved, naming both addons (from their declared `commands`). |
| **An addon command is hidden by a toolbox command** (added later to the toolbox). | Caught by the addon's check, which also runs on every toolbox rebuild (§4.5). |
| **Shared dependencies are duplicated** between addons. | Accepted: tens of MB per addon. |
| **An addon depending on another addon.** | Not supported: an addon relies only on the toolbox. |

## 7. Alternatives considered

| Approach | pacman possible? | Built per combination? | Verdict |
|---|---|---|---|
| Put it in the toolbox | yes | no | right for tools used often; wrong for rare ones |
| **Addon image mount** (§4) | no, self-contained tools only | no | **chosen default** |
| Image built per combination (`FROM harness` + each selected addon's install step) | yes | yes, cached | the only way to allow pacman; a possible second addon kind, same manifest and bindings |
| Nix store mounted read-only | not needed: packages carry their dependencies, deduplicated | no | the most rigorous; kept in reserve if the self-contained limit is hit often |
| pixi / conda, Homebrew on Linux | partly | no | weaker versions of the Nix idea |
| Install at boot (npx, uvx, pacman in an init script) | yes | no | rejected: not explicit, network at every boot |
| Host folder / skill with binaries | no | no | same runtime as an image, weaker packaging (§4.6) |
| Agent runs a tool container itself (`nested`) | yes | no | loosens confinement to call a tool |
| Sidecar or MCP server outside the sandbox | yes | no | kept for credentials and narrow operations (§8.3), not for tools in general |

## 8. Access: credentials and rights

In `bypass` mode the agent acts unsupervised, and what it reads can steer it: a crafted line in the
logs it reads from OpenSearch is a prompt injection. An agent that holds a git token and has network
access can then leak data or push code. So:

- **A skill says what the agent should do. It enforces nothing.**
- **A wrapper inside the sandbox enforces nothing either**: the agent can call the real binary,
  or send the same request with `curl`. Enforcement can only happen where the credential is used:
  the gateway or the target system.

### 8.1 Rights live in the target system

A role's policy is **the accounts it has**. Each role gets a dedicated account in each system,
with only the rights it needs, enforced by the system itself:

| System | Native mechanism | Example for the dev role |
|---|---|---|
| git (GitHub / GitLab) | fine-grained token or deploy key per repository, branch protection | push to `agent/*`, never `main` |
| OpenSearch | security roles on indices and actions, field-level masking | read-only on `logs-*`, sensitive fields masked |
| Jenkins | matrix / project-based authorization | build `app-dev`, no configuration changes |
| Kubernetes / cloud | RBAC / IAM | the `dev` namespace only |
| Shopify | custom-app scopes, Theme Access | a development store, not the real shop |

Why the system rather than platform rules:

- it understands its own actions: HTTP rules cannot say "no live push" when everything goes
  through one `POST /graphql`;
- it maintains its own permission model: nothing to update when a CLI gains a command;
- it is an filtered: an account without a right cannot use it, whereas a wrapper that rejects
  known commands fails open on new ones;
- its own audit log attributes every action to the agent's account.

The maintenance moves from code that filters to a recipe that creates the right account: each
addon ships a **`PROVISIONING.md`** (the OpenSearch role definition, the Jenkins permission matrix,
the git branch protection rule). The account is created once; the system enforces it from then on.

### 8.2 When native rights are too coarse

In this order:

1. **Separate environments.** The agent only holds credentials for dev or staging: it cannot
   deploy to production because it has no production credential.
2. **Request, don't execute.** Dangerous actions stay behind existing processes: the agent pushes
   a branch and opens a PR, a human merges; the pipeline deploys, with a manual approval step where
   it matters.
3. **A narrow operation service**, only for what 1 and 2 do not cover: a small MCP server outside
   the sandbox with two or three allowed operations (e.g. `restart(service, env="dev")`), holding
   the credential itself. Closed by design, and small enough to maintain.

### 8.3 How a credential reaches the tool

From safest to weakest; each binding declares its method:

| Method | Fits | Secret in the sandbox? |
|---|---|---|
| **Gateway endpoint**: the agent calls `http://<name>.handler`, the gateway adds the credential and handles TLS outward | HTTP APIs: OpenSearch, Jenkins, internal APIs | no |
| **Phantom token**: the env holds a stand-in, the sandbox's proxy swaps it for the real value towards the secret's hosts (contracts E3, A.3). **What a binding's secrets get by default** | CLIs and APIs that call fixed HTTPS hosts (Shopify CLI); the sandbox trusts its proxy's CA | no |
| **Forwarded socket** (ssh-agent) | git over SSH | no: the key can be used, not read |
| **Operation service outside the sandbox** (§8.2, 3) | dangerous actions | no |
| **Env secret** (a secret slot's `delivery = "env"`) | a tool that signs with the secret or speaks something else than HTTP | **yes** |

### 8.4 What the gateway does, and does not do

The gateway is the per-sandbox proxy (A.3) and keeps a narrow job that does not depend on
what each system means:

- **inject credentials**: the agent cannot read a token, so it cannot leak it or use it elsewhere;
  the token only works through the gateway, toward its destination;
- **destination allow-list** (already in place);
- **audit log per session**, reviewable afterwards (possibly by a security agent reading the other
  agents' logs);
- **kill switch**: cut a binding live, like `set-egress` today;
- at most a **cheap safety net** such as "GET only" for a read-only binding.

It is **not** where policy lives (§8.1).

## 9. Roles

A role is **an agent and its bindings**: each project's agent for that role selects the bindings
of that project. The rights come from the accounts behind the bindings (§8.1):

| Role | git | Jenkins | Deployment | Test API | Logs |
|---|---|---|---|---|---|
| dev | push to `agent/*` | build `app-dev` | dev only | yes | read |
| QA | read | read | none | yes | read |
| security | read | none | none | read-only scan | read |

Each role has its own accounts, hence its own bindings (`jenkins-dev-build`,
`jenkins-dev-read`, …), so every system's audit log says which role did what.

Nothing restricts which bindings an agent may select: with a single user, a
restriction would only protect that user from themselves, at the cost of another list to maintain.
It can come back if bindings are ever shared between people.

## 10. Workflows (out of scope here)

"Push, wait for Jenkins, deploy, test, then QA and security review" is orchestration, not addons.
It needs, beyond today's unattended runs (D.18):

- **waiting without burning tokens**: the run ends, and an event (a Jenkins webhook, a finished
  build) starts the next one, instead of a model loop polling for 20 minutes;
- **handoff**: the next run receives structured inputs (branch, commit, deployed URL, report), not
  only a prompt;
- **human gates**: approving a deployment or a merge.

The direction: an event starts an **automation** (contracts §I: *when this
happens, run that*); a script orchestrates the parts and passes the data between them; a part
with other access is an agent run (an agent and its bindings) or a service, each in its own
sandbox; a human gate is a question in the person's inbox.

## 11. Open questions

1. Egress for addons whose hosts come from settings (OpenSearch, Jenkins): derive it from URL
   settings, or declare it explicitly in the binding?
2. Access method per binding (§8.3): chosen in the manifest, the binding, or both (manifest
   lists the supported ones, binding picks)?
3. MCP servers hosted outside the sandbox, behind a gateway (those in the sandbox are an addon's
   `[mcp] command`, `browser.md` §5.2).
4. A project file that *suggests* bindings, confirmed by a person in the UI (§5.5): useful once
   there are many projects?

Decided: addons are both built in and the user's own (`~/.config/handler-ai/addons/`, replacing a
built-in one of the same name; contract G.1); the name **binding** ("connection" already meant an
ACP connection).

## 12. Not built yet

- Gateway endpoints (§8.3, §8.4): the agent calls `http://<name>.handler` and the gateway adds the
  credential, for HTTP APIs whose hosts come from settings (OpenSearch, Jenkins).
- An audit log per session and a kill switch per binding (§8.4).
- Credential files kept out of the sandbox (phantoms cover env secrets only).
