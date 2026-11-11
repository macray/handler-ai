# control-plane — `handler_control`, `handlerd`

**Implements:** the composition of all blocks, contract C (ACP endpoint + policy) and contract D
(Control API), as the daemon `handlerd` (127.0.0.1 only, token-protected).
**Depends on:** `handler_contracts`, `handler_harness` (catalog, image tags, addon manifests, pure `render`). Sandboxes via their executables.
**Used by:** clients only over HTTP/WebSocket: `handler` CLI, web UI (M5).

This is the only block that knows the others exist. Everything else is replaceable behind it.

## Layers

A module imports only from its own layer or the ones below (checked by
`tests/architecture/test_boundaries.py`, `CONTROL_LAYERS`; a new module is given a layer there):

| Layer | Modules | Its job |
|---|---|---|
| surface | `api/`, `auth`, `webui`, `daemon` | HTTP and WebSocket translated into calls to the layers below |
| remote | `remote`, `remote_crypto`, `webpush`, `app_remote` | paired devices reach sessions and apps through the gateway (D.7) |
| features | runtime: `sessions`, `relay`, `policy`, `terminals` · `agent_service`, `save_rules` · `agent_checks`, `improvements` · `uses` · `plans` · images: `builds`, `image_check`, `image_updates` · apps: `apps`, `app_http`, `app_api`, `app_runs` · `automations`, `schedules`, `inbox` · Ask: `assistant`, `voice` | what the daemon does with agents, apps and automations |
| launch | `launcher`, `access`, `compose`, `addons` · services: `llm`, `transcribe`, `service_router` · `model_agent` | an agent turned into a running sandbox; the services a sandbox reaches; the model alone, with no sandbox |
| data | config: `accounts`, `providers`, `bindings`, `secrets`, `skills`, `skill_sources`, `interfaces`, `definitions`, `agents_files`, `handler_needs`, `folders`, `knowledge`, `config_files`, `automation_config`, `services` · `session_files`, `git_read` · registries: `agents`, `projects`, `agent_state`, `caches`, `toolbox` · `transcript` | what is configured and what is registered |
| host | `sandbox_process`, `runtime`, `display`, `desktop`, `terminal` | the machine: the sandbox's executable (sandboxes and images), the display, the desktop |
| migrations | `migrations/` | the user's files from an older format to the current one, before handlerd reads them: the only code that knows an older format |
| base | `settings`, `files` | where things live, how the daemon writes its own files |

So nothing below the surface knows the API, nothing below `remote` knows paired devices, and
the launch pipeline knows neither sessions nor apps.

| File | Role |
|---|---|
| **composition** | |
| `access.py` | contract E: an agent's harness + account or provider + model resolved into an `AgentSpec`, readable errors |
| `secrets.py` | the secret store (D.14) and secret references → values (never logged) |
| `files.py` | the daemon's own files: written whole, atomically, 0600; why one is invalid, in one line; a zip unpacked safely, a folder zipped (an app's code, an agents file) |
| `terminal.py` | opening a terminal window on the desktop (`HANDLER_TERMINAL`, else a known one) |
| `compose.py` | scope check (work folders) + HarnessLaunch (B) + the agent's sandbox settings → SandboxSpec (A) — pure |
| `runtime.py` | images through the sandbox's executable (`image` verbs, A.7): inspect, the recorded version (cached per id), tag, remove, and the build and pull command lines `builds` and `apps` run; the caches' sizes and emptying them (`cache` verbs, A.9) |
| `sandbox_process.py` | sandboxes through the sandbox's executable: `launch` with the spec on fd 3 (sync and asyncio), `set-allow`/`set-egress` on a running sandbox (A.4), stopping it, its stderr (logs, egress events) |
| `launcher.py` | starting one connection's agent: agent spec → secrets → render → compose → sandbox |
| **daemon** | |
| `settings.py` | ports and paths (`HANDLER_*` environment variables) |
| `migrations/` | one module per format change of the user's files, run in order at handlerd's start; `<state>/format-version` counts those run |
| `data/templates/` | platform data: the provider templates the forms start from (D.12) |
| `auth.py` | token file (0600), bearer header / `bearer.<token>` subprotocol, Origin allow-list |
| `agents.py` | agent registry (persisted; each with its home: a project, an app or Chat, none), live connections and their network changes (A.4), recent egress events |
| `projects.py`, `accounts.py` | projects and their agents (D.8), accounts and their login (D.9) |
| `caches.py` | the caches (D.8), from who declares them (the base, system packages, the user): each project's mounts (shared, its own, none), the list as Settings → Caches shows it and saves the user's own, emptying them through `runtime` |
| `toolbox.py` | the toolbox as handlerd keeps it (B.6, B.7): its record (`<state>/toolbox.json`, what `:latest` gives), the needs in use (Handler, harnesses, saved agents' abilities) and what provides each, turning system packages on or off (refused while one alone gives a need in use) |
| `policy.py` | **P1–P9** as a pure state machine (message in → actions out), transport-free |
| `relay.py` | WebSocket ↔ agent stdio around the policy; framing, sizes, lifecycle (C.1, C.3) |
| `terminals.py` | a harness's own terminal program (D.16): its sandbox started out of handlerd's reach, the client attaching to it directly |
| `interfaces.py` | agent interfaces (D.18): their schemas checked, a run's input checked and its subject mounted read-only, its one request, its result parsed from the final message, the repair turn |
| `definitions.py` | agent definitions (D.18): a folder (`agent.toml`, `instructions.md`, `interface.json`, `skills/`) read and written, its skills into the library |
| `agents_files.py` | **agents files** (D.23): files being imported (`<state>/agent-imports/`), read; a project's agents exported as a zip (what is yours replaced by what they need, their checks); the origin `{kind: agents-file, name, version, agent}` |
| `handler_needs.py` | Handler's **needs** (D.18, `data/handler-needs/<name>/`: `need.toml` and the definition): its features that need an agent (the UI's helpers), the one given for each (`<state>/handler-needs.json`), which agents fit |
| `skill_sources.py` | skills from a URL (D.17): a GitHub repository's folder or a skill's archive, downloaded and unpacked with `skills` |
| `addon_install.py` | installing addons (G.5): sources (catalog, folder, archive), the staged preview and its digest, the lock, removing |
| `builds.py` | **image rebuilds** (D.4): one at a time, build → check → tag `:latest`, log on disk; the toolbox generated from its parts (B.7), applied with the build cache or updated, its needs in use checked, its record written when it switches |
| `image_updates.py` | automatic updates (D.4): every built harness and addon image rebuilt on a schedule and after a Handler upgrade, through `builds`; not the toolbox |
| `image_check.py` | starts a new harness image through the real pipeline and checks `session/new` against the descriptor; a new toolbox's system package checks and the commands it gives |
| `sessions.py` | **daemon-held sessions** (F): one sandbox each (none on the model alone: `model_agent`, behind the same `AgentLink`), outliving the WebSocket; attach = replay of the event log; several attachments; idle stop; per-session folder (a folderless agent's works there, D.18); unattended runs of agents with an interface, their output; runs of one agent take turns (one at a time, the others wait) |
| `plans.py` | **plans** (D.27): a plan file of an agent's folder read (no link followed) and parsed, approved by the digest read, its copy kept in `<state>/plans/<id>/` (never in a sandbox); the runner, one step after another, each a fresh unattended session of the plan's agent; the skill `handler-plan` (shipped with the plan builder, `data/handler-needs/plan-builder/`) installed in the library once |
| `plan_drafts.py` | **plan drafts** (D.27): plans being written, kept in `<state>/plan-drafts/<id>/` (`draft.json` apart, `draft/` the plan builder session's folder), saved by hand over the text read (never through a link); what the plan builder may have (no addon, a network reaching only its model's sites) and its session's brief |
| `session_files.py`, `git_read.py` | a session's folder (F.8): its files read without following links nor leaving it, what changed since the session started (the baseline); git's earlier versions read with dulwich in a child process |
| `automation_config.py` | automations as configured (I.1, I.7): the folders of `<config>/automations/`, their problems read from the folder alone, `state.json`, the shipped examples (`data/automations/`) |
| `transcript.py` | a session's event log slice as markdown (I.4), pure |
| `services.py` | service interfaces as data (`data/interfaces/`): loaded, checked (S2, S3, S5), their tools' validators |
| `llm.py` | the `llm/v1` connector: one model call on a provider (`openai-chat` or `anthropic`), the JSON checked, one repair turn; a conversation's next message (the model alone); never a tool: an answer calling one is refused |
| `voice.py` | Voice (D.25): the speech model chosen and when answers are read aloud (`<state>/voice.json`); a recording written down with it, never kept |
| `transcribe.py` | the `transcribe/v1` connector (I.11): a recording written down by a provider's speech model at its `transcriptions` endpoint; the speech models there are |

| `model_agent.py` | **the model alone** (D.18): an agent with no program and no sandbox, handlerd's own ACP agent behind a session, one model call per turn, its knowledge in the system prompt; text in, text out (no tools, no MCP servers, no client requests) |
| `service_router.py` | handlerd's side of a services socket: MCP (JSON-RPC lines), the caller's models and limits, `services.ndjson` |
| `automations.py` | **automations** (I): the stops that fire and the slots due, one queue, a script's folder and sandbox, an agent's run, an app's call, appends after success, the inbox told, what one does in sentences and its account's terms verdict, tries, runs and their records |
| `schedules.py` | a schedule's slots in local time: the latest one due, those missed, the next one (I.2), pure |
| `inbox.py` | the person's inbox (I.9): apps' notifications, agents' results (automations', apps'), kept, shown on the desktop, told to the phones |
| `app_runs.py` | runs of agents an app starts on its `handler.sock` (H.11): the jobs of its `needs.agents`, started while it answers the owner (the start token `apps.py` gives each owner's request), their state from their sessions, the inbox told when they end |
| `agent_service.py` | an agent made, changed and deleted, whatever its home (D.1, D.2): the rules of `save_rules` in order for its home, its project's default, the checks of what it is set up from; a deletion with all it involves (its connections and sessions stopped, its checks and improvements forgotten, Handler's needs it was given for left without it) |
| `save_rules.py` | the rules an agent or a project must pass before it is saved: model access, folder, tools, knowledge, display, permission mode, risks, skills, one project per folder, names (D.2, D.8, D.17) |
| `agent_checks.py` | **checks** (D.20): runs of a job kept with their right answer, run again when the person asks (one check run at a time, each check a run with origin `check`), what came back compared (never free text), what changed in the agent since |
| `improvements.py` | **improvements** (D.21): a job's instructions rewritten by the prompt writer (the agent given for one of Handler's needs), each attempt judged by its checks run with the attempt's instructions, until they all pass or the budget is spent; an attempt kept |
| `uses.py` | **what uses what** (D.22): every link between agents, skills, knowledge folders, addon configurations, accounts, providers, projects, automations, apps and Handler's needs, computed each time; a thing's uses and used-by |
| `api/` | FastAPI app, one module per contract section (catalog, accounts, providers, bindings, skills, folders, caches, secrets, toolbox, images, projects, agents, sessions, remote, apps, automations, inbox, ACP endpoints); `common.py`: problems, Context; routes parse, call the domain and map its errors |
| `daemon.py` | `handlerd` entry point: token, sweep, serve |

One ACP connection to an agent (C), the agent lives as long as the WebSocket:

```
WebSocket ─► api.acp (auth) ─► launcher.start ─► Relay ─┬─ policy.from_client ─► agent stdin
                                                      └─ policy.from_agent  ◄─ agent stdout
```

One session (F), the agent lives in the daemon; WebSockets attach and detach:

```
POST /v1/sessions ─► SessionStore.create ─► LiveSession.start: launcher.start (on the model alone:
               a ModelAgent, no sandbox), initialize, session/new
WebSocket ─► api.session_acp (auth) ─► ensure_running ─► LiveSession.attach
               initialize, session/load: answered by the daemon (cached result, event log replay)
               anything else: ids rewritten ─► policy ─► agent; agent ─► policy ─► log + client
```

Tests: unit in `tests/` here (policy, compose, secrets, access); black box in
`tests/acp_endpoint` (C), `tests/control` (D), `tests/e2e` (real harnesses through the daemon).
