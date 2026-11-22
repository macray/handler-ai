# Changelog

What each release lets you do, grouped by what you do. One release is one commit in the public
repository ([`CONTRIBUTING.md`](CONTRIBUTING.md)).

## 0.4.0

An alpha: formats may still change from one release to the next. **Your files of 0.3 are not
carried over**: move `~/.config/handler-ai/` and `~/.local/state/handler-ai/` aside and start
with empty ones ([upgrading from 0.3](docs/configuration.md#upgrading-from-03)).

### New

- **Running**: every running session side by side (Grid, Columns or One), answered and typed in
  where it is, filtered, reordered, full screen; **+** starts one there.
- **Apps bring their jobs**: what an app needs a model for is one of its jobs, with its
  instructions, form and what it may reach; you choose who works on it (an account or an API
  key, and a model), and each run says what started it. Replaces the agents apps brought.
- **An app's page: Activity and Settings**: its runs, the changes to its folders (**Undo**), what
  it sent you, its versions; then everything you chose for it.
- **Updating an app takes one click**: **Update to** tests and deploys the new version, saying
  what it changes and what it may now reach; **Go back** returns to the one you had.
- **Undo what an agent or an app changed in your notes**: a folder it can write (**Can write**,
  `--notes FOLDER=write`) keeps its history out of their reach, each change with its lines and
  **Undo**.
- **Schemas**: documents of a known shape in your notes (a CV, contacts), read and written by
  agents (the `knowledge` tool, `handler-smd`) and apps without inventing anything.
- **Ask keeps its history**: every ask from anywhere, what came of it, **Open** where the app
  did it; failures come to your inbox. `handler ask --listen` asks by voice, `--toggle` from a
  key such as a Stream Deck's.
- **An app asks you at your time**: a nudge may come "Fridays at 16:00", each can be turned off,
  its reminders a plain choice.
- **The phone has a new look**: tabs at the bottom, a light theme, pairing in three steps, safe
  permissions answered on the card and risky ones with a slide, notifications when a shared
  session needs you, and the last Home shown without a network.
- **An agent's own environment variables** (`--env NAME=VALUE`), going with it when exported.
- **Connecting a tool** shows how to get what it asks for (its `CONNECT.md`), and checks the
  connection works.
- **On a Mac with Apple's `container`, agents can run containers**, each in its own virtual
  machine, their images shared through a cache.
- **Automations every N days** (`every = "1d"`).

### Changed

- **The web UI says it in the person's words**: one name per thing (*Who works*, *On your
  phone*), a disabled button says why and where to fix it, Who works is one control (account,
  program, model), a model is connected from where you are, and *Set up Handler* guides you to
  your first project.
- **Apps is a launcher**, Library lists *Yours · Community*, an app is set up on its install page
  in steps, its automations installed with it, and each of its actions in Ask or not.
- **A new app starts with a finished look**: the app-builder's template styles plain HTML, light
  and dark.
- **Your notes are in `~/notes`**, no longer in Handler's data folder; an app can be given one
  of your notes folders.
- **A site you keep blocked stays blocked**, even under a wider site you allowed.
- An account says its *subscription* (`--subscription`, was `--plan`).
- **For app makers** (breaking): `[jobs.<name>]` and `runJob` replace `[needs.agents]` and
  `runAgent`; new: `title`, `changes`, a nudge's `when`, `schemas`, `history()`, `listRuns()`,
  `answeredNudge()`, `askedVia()` and an action's `open`.

### Fixed

- Handler stops at once with a page of the web UI open.
- On a Mac: Apple's container service starts with Handler, `handler setup` runs again without
  leaving Handler stopped, and the install script runs.
- A failed image build, install or update says why, where it failed.
- A session waiting for its program starts by itself once it is built; `handler run` prepares
  it.
- `--from` takes a source's URL; `handler app list` says where each app comes from; the command
  line says times in your time zone.
- The Podman cache no longer grows with every session, and agents running containers no longer
  see each other's networks.
- Many smaller fixes in the web UI, the phone, the command line and setup.

## 0.3.2

### Fixed

- A toolbox build whose check could not start sometimes said only "its check exited with 66",
  not why.

### Changed

- **Connection examples are in the docs** ([`handler connection`](docs/cli/connection.md)): the
  `examples/` folder is gone.

## 0.3.1

### Fixed

- On Debian and Ubuntu, no agent, app or check started ("Bad fd number").
- With Docker 28, an agent with a filtered network, or given secrets, did not start ("user
  specified IP address is supported only when connecting to networks with user configured
  subnets").

### Changed

- **A shorter README**: what Handler does, how to install it, then the docs.

## 0.3.0

An alpha: formats may still change from one release to the next. Coming from 0.2.0, some files
are renamed by hand first: [upgrading from 0.2.0](https://github.com/macray/handler-ai/blob/v0.3.0/docs/configuration.md#upgrading-from-020).

### New

- **macOS (experimental)**: agents run with Apple's `container`, a virtual machine per session,
  or with Docker Desktop or OrbStack; `handler setup` asks which. Apps run with Apple's
  `container` too.
- **Docker**: as the runtime on Linux (`handler runtime use docker`), and inside a sandbox for
  agents that run containers (`--engine docker`).
- **Windows**: a guide to install Handler in WSL 2, from scratch.
- **Blocked hosts, answered where you are**: a card in the session (*Allow for this agent* or
  *Keep blocked*), the agent waiting a few seconds for your answer and told of it afterwards; in
  your inbox when you were away, for sessions, plans and automations.
- **The toolbox, made of what you choose**: a smaller base and system packages you turn on;
  toolchains (Go, Java, Rust, Bun) come as tools of Handler's source,
  [handler-ai-registry](https://github.com/macray/handler-ai-registry).
- **Local models tested before use** (*Test*, `handler provider test`), and a model that does not
  answer is said in the session.
- **Settings → Caches** shows what each cache takes on your disk, and frees it.

### Changed

- **One word each, everywhere**: tools (were addons), connections (bindings) and notes
  (knowledge), in the web UI, the command line, the files and the docs.
- **`handler setup` builds one agent program** (about 1 GB), the others when first needed.
- **Notes need no setup**: a default notes root, created by Handler.
- **A short menu on a new install**, growing as you use Handler.
- **The web UI stays signed in**: `handler ui` once, then a bookmark works.
- **Docs**: upgrading from 0.2.0, Docker and the Mac in getting started, each runtime's
  isolation and limits, the command line's pages matching its commands.

### Fixed

- A session started before its program was built lost your request; it now starts by itself
  once the build ends.
- A large download could take down a filtered agent's network.
- A sandbox whose network filter stopped went on with every request failing; it is now ended,
  saying why.
- A tool's MCP server could see a Claude Code agent's provider key.
- `handler run` showed a traceback, or waited forever, when a session did not start.
- `handler terminal` lost its program's exit code on Linux.
- `handler setup` ignored `--program` and `--engine` after a first setup.
- Phone notifications never showed on Android with Firefox.
- Many smaller fixes on macOS, in builds, Discover and the web UI.

### Format changes

- **By hand, from 0.2.0**: `addons/` → `tools/`, `bindings/` → `connections/`, `knowledge.toml` →
  `notes.toml`, with their contents and environment variables, and `~/knowledge` → `~/notes`
  before 0.3.0 first starts (renamed later: Library → Notes → **Change** to `~/notes`); then
  rebuild your tools' images.
  Every step: [upgrading from 0.2.0](https://github.com/macray/handler-ai/blob/v0.3.0/docs/configuration.md#upgrading-from-020).
- **By Handler, at its first start**: the toolbox's `toolbox.toml` is rewritten; lines you had
  added to its `Containerfile` go in `custom.containerfile`, by hand.

## 0.2.0

- **Apps and sources**: Apps are now first-class (replacing mini apps), can be installed from git repositories (sources), run on Bun instead of Deno, and are fully managed by Handler
- **Security**: Multiple security fixes including message expiration, HTTPS-only remote gateways, and filtered network enforcement for plain HTTP
- **Chat**: Dedicated Chat feature for conversational agents, with voice input/output support
- **Project management**: Improved project workflow with agent export/import (agents files), and better organization
- **Agent improvements**: Agents now have a single model, can run as "model alone", support checks for validation, and improved session management
- **Configuration format change**: Configuration and state format changed from 0.1.0 - start fresh with empty config directories

## 0.1.0

The first public release (alpha, Linux only).

- **Agents in sandboxes.** Claude Code, Codex, Mistral Vibe and pi, each in its own rootless
  Podman container that sees only its project's folder, on your subscription, an API key,
  OpenRouter or a local model.
- **A network you can see.** No network, open, or filtered to the hosts you allow, changed live;
  *Learn hosts* shows what a project would need. Provider API keys and Claude Code tokens stay
  out of the sandbox: it holds a stand-in, and the network filter puts the real value into the
  requests to their hosts. Other secrets (a ChatGPT or Mistral login, addons' secrets) can be read
  inside it.
- **Projects, agents, sessions.** A project is a folder and its agents (roles with their models,
  instructions and settings); the daemon keeps each session, which you follow from the web UI,
  the terminal (`handler run`, `handler attach`, `handler terminal`), Zed (`handler acp`) or your
  phone.
- **Addons and skills.** Tools with their credentials and hosts (a browser, the Shopify CLI); a
  skill library with a reviewer that tells you what a skill would make your agents do.
- **Mini apps** an agent writes and you run locally, and **automations**: when a session stops
  or at a time, run your script, an agent or an app's route; results come to your inbox.
- **Phone access** through an end-to-end encrypted gateway you host.
