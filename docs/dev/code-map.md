# Code map — where each block lives

The architecture ([`architecture.md`](architecture.md)) is made of blocks that talk through
contracts ([`contracts.md`](contracts.md)). Each block lives in its own directory, and the
dependency rules below are **checked by `tests/architecture/test_boundaries.py`**.

```
                   ┌──────────────────────────────────────────────┐
  clients          │  packages/cli (handler) · packages/web-ui · Zed  │
                   │  via `handler acp`                           │
                   └──────────────┬───────────────────────────────┘
                                  │ C: ACP over WebSocket · D: Control API (HTTP)
                   ┌──────────────┴───────────────────────────────┐
  composition      │  packages/control-plane   handler_control / handlerd  │
                   │  policy · relay · agents · sessions · api     │
                   └───┬──────────────────────┬───────────────────┘
          B: imports   │ catalog, render      │ A: executable, spec on fd 3
                   ┌───┴───────────────┐  ┌───┴──────────────────────────────┐
  blocks           │ harness-adapters  │  │ sandbox-podman                   │
                   │ handler_harness   │  │ handler-sandbox-podman (executable)  │
                   └───┬───────────────┘  └──────────────────────────────────┘
          reads data   │  platform data, read-only, in the package: handler_harness/data/
                   harnesses/<name>/  (descriptors + Containerfiles)
                   addons/<name>/       (built-in addons: manifests, tool Containerfiles, skills)
                   catalog/<name>/      (addons handler ships, loaded once the user installs them, G.5)
                   toolbox/             (the default toolbox, copied to the user's on first start)
                   handler-sandbox-env  (given to harnesses with mcpEnv = "sandbox")
  starting points  handler_control/data/templates/  (provider templates the forms start from)
  the user's       ~/.config/handler-ai/toolbox/ (their toolbox), ~/.config/handler-ai/addons/ (their addons)

  everything ──► packages/contracts  handler_contracts  (data definitions; the only shared library)
```

## Blocks

| Block | Directory | Contract | May depend on | Reached by others via |
|---|---|---|---|---|
| Contracts | `packages/contracts` | all (data) | — | import |
| Sandbox (the runtime) | `packages/sandbox-podman` | A (A.7: images, A.8: host check) | contracts | executable `handler-sandbox-podman`: the only block calling podman (checked) |
| Harness adapters | `packages/harness-adapters` (data: `handler_harness/data/`: harnesses, built-in addons, the default toolbox) | B, G.1 (addon catalog, images) | contracts | import (catalog, image names and build recipes, addon manifests, the pure `render`); CLI `handler-harness` |
| Control plane | `packages/control-plane` | composition; C, D | contracts, harness-adapters | HTTP / WebSocket (`handlerd`) |
| CLI | `packages/cli` | client of C, D | contracts | executable `handler` |
| Web UI | `packages/web-ui` (Svelte, TypeScript) | client of C, D | generated contract types (`schemas/`), acp-view | static files served by `handlerd` at `/` |
| Session view | `packages/acp-view` (Svelte sources) | — (rendering of C) | ACP SDK | compiled into the web UI and the remote client |
| Remote client | `packages/remote-client` (Svelte, TypeScript) | device side of D.7 (`docs/dev/design/remote.md`) | generated D.7 types (`schemas/handler.remote.v1.*`), acp-view | static files served by the gateway |
| Remote gateway | `remote-gateway/` (independent project) | the gateway of `docs/dev/design/remote.md` | — (no Handler import, checked) | HTTP, run on any machine |
| Mini apps (app host) | `packages/control-plane` (`apps.py`, `app_http.py`) + the `miniapp` addon | H (`docs/dev/design/miniapps.md`) | contracts, the sandbox executable | Control API `/v1/apps`; each app at `http://<name>.localhost:<port>/` |

## Where to look for…

| I want to… | Go to |
|---|---|
| change what an agent runs as (its models: harness, account or provider, model; resolved for `render`; the one a session runs with) | `packages/contracts/src/handler_contracts/agent_spec.py`, `packages/control-plane/src/handler_control/access.py`, `agents.py` (`RunsAs`, `runs_as`, `resumes_as`), `checks.py` (`checked_model`, `session_model`: any model a project's context allows) + `docs/dev/contracts.md` §E, §D.1, §F.3; web UI `ModelAccessPicker.svelte` (one model), `AgentEditor.svelte` (the list), `ModelChoice.svelte` (a session's), `lib/access.ts` |
| change what an account can contain, its status or how its login is kept | `packages/contracts/src/handler_contracts/account.py`, `packages/control-plane/src/handler_control/accounts.py` + `docs/dev/contracts.md` §E, §D.9; CLI `packages/cli/src/handler_cli/account_commands.py`; web UI `packages/web-ui/src/components/AccountsSettings.svelte` (in `ModelAccess.svelte`: the page, its "Connect a model" options; a secret pasted or referenced: `SecretSource.svelte`) |
| change how a harness's account is obtained (a token the person makes, or a login Handler runs; its hosts) | `[login]` in `handler_harness/data/harnesses/<name>/harness.toml` (contract B.1) |
| change an account's login (a file login run on the host, its terminal; a token given or referenced; what is kept) | CLI `handler account login` in `packages/cli/src/handler_cli/account_commands.py` (+ `docs/dev/contracts.md` §D.9, each harness's `[login]`); the terminal window handlerd opens: `packages/control-plane/src/handler_control/terminal.py` |
| change project contexts (Work, Personal: which accounts and providers a project runs; their colours) | `packages/control-plane/src/handler_control/contexts.py` (the rule, `contexts.toml`), `api/contexts.py`, `checks.py` (`check_context`), `launcher.prepare` (checked at every start) + `docs/dev/contracts.md` §D.19; CLI `session_commands.py` (`project_agent`, `acknowledge_outside`: `--anyway` typed `yes`); web UI `ContextsSettings.svelte`, `ContextsPicker.svelte` (accounts, providers), `ContextTag.svelte`, `lib/contexts.svelte.ts`, the `ctx-*` colours in `packages/acp-view/src/theme.css` |
| change the work folders (where agents may work) | `packages/control-plane/src/handler_control/folders.py` (+ `compose.check_scope`) + `docs/dev/contracts.md` §D.13; web UI `FoldersSettings.svelte` |
| change how an agent is contained (network, hosts, permissions, confinement, presets, risks) | `packages/control-plane/src/handler_control/agents.py`, `checks.py` (`checked_settings`, `agent_risks`), `launcher.py` (`required_hosts`) + `docs/dev/contracts.md` §D.2, §D.8; web UI `AgentEditor.svelte`, `lib/projects.svelte.ts` (`PRESETS`) |
| change the secret store or how a secret reference is resolved | `packages/control-plane/src/handler_control/secrets.py` (+ `SecretRef` in `packages/contracts/src/handler_contracts/common.py`, `docs/dev/contracts.md` §E2, §D.14); CLI `packages/cli/src/handler_cli/secret_commands.py` |
| change how secrets reach a sandbox (phantoms, which hosts get them) | `secrets.py` (`phantom`, `Delivery`, `visible`), `launcher.py` (`_deliver`), `addons.py` (`secret_env`) + `docs/dev/contracts.md` §E3; the secrets list: `api/secrets.py` (`secret_infos`) |
| change the sandbox's egress proxy (filter, events, secret injection, its CA) | `packages/sandbox-podman/src/handler_sandbox_podman/proxy/addon.py` (in the proxy: decisions, swaps), `egress.py` (its settings, secrets file, arguments, events), `launch.py` (`_network`), `proxy/Containerfile` (its image, the "network filter": built by `images.py` `build_proxy`, A.7; by handlerd as a D.4 target, `builds.py`, `image_updates.py` when missing) + `docs/dev/contracts.md` §A.3; tests `tests/sandbox/test_injection.py`, `packages/sandbox-podman/tests/` |
| change what a provider can contain, its status or its form | `packages/contracts/src/handler_contracts/provider.py`, `packages/control-plane/src/handler_control/providers.py` + `docs/dev/contracts.md` §E, §D.12; web UI `ProvidersSettings.svelte`, `ProviderForm.svelte` (in `ModelAccess.svelte`); templates `handler_control/data/templates/providers/` |
| change how a provider is written in a harness's config (env, config files) | `packages/harness-adapters/src/handler_harness/providers.py` (one function per harness) |
| change where an agent keeps its harness's history and settings | `packages/control-plane/src/handler_control/agent_state.py` (+ `render.state_mounts`), `docs/dev/contracts.md` E6 |
| add a tool for all agents | your toolbox: Settings → Images → toolbox → Edit, or `~/.config/handler-ai/toolbox/Containerfile` (its state kept between sessions: Settings → Caches, saved in `toolbox.toml` `[caches.<name>]` there); the default for new installs: `handler_harness/data/toolbox/` |
| change how caches are shared (per project: its own, global, off) | `packages/control-plane/src/handler_control/caches.py` (+ `render.cache_mounts`, `docs/dev/contracts.md` §D.8, §B.6); web UI `ProjectEditor.svelte` |
| change what Settings → Caches shows or does (sizes, emptying) | `packages/web-ui/src/components/CachesSettings.svelte`, routes `handler_control/api/caches.py`; sizes and emptying by the sandbox: `handler_sandbox_podman/caches.py` (`cache` verbs, contracts §A.9) |
| add a harness | `handler_harness/data/harnesses/<name>/` (see its `README.md`) |
| add an addon (a tool, skills, egress for one kind of system) | your own: `~/.config/handler-ai/addons/<name>/` (`docs/user/addons.md`); one Handler ships: `handler_harness/data/catalog/<name>/` (installable, G.5), built in only if Handler itself needs it: `handler_harness/data/addons/` |
| change how addons are installed (sources, preview, lock, remove) | `packages/control-plane/src/handler_control/addon_install.py` + `api/addons.py` (G.5); web UI `AddonInstaller.svelte`; CLI `handler_cli/addon_commands.py` |
| change what an addon or a binding can contain | `packages/contracts/src/handler_contracts/addon.py` + `docs/dev/contracts.md` §G |
| change how bindings are checked and added to an agent | `packages/control-plane/src/handler_control/addons.py` (+ `bindings.py`, `compose.py`) |
| change the skill library (the skills projects give to all their agents, those agents pick) | `packages/control-plane/src/handler_control/skills.py` (+ `skill_sources.py` for imports from a URL, `projects.py` for who uses them, `launcher.py` to mount them) + `docs/dev/contracts.md` §D.17; web UI `views/SkillsView.svelte` (the Skills page of the main menu) with `SkillLibrary.svelte` (list, new: write, import an archive or a URL), `views/SkillView.svelte` (one skill's page: its SKILL.md as a form, `lib/skillmd.ts`, its files, download, delete), `SkillPicker.svelte` (an agent's; `lib/projects.svelte.ts` `byUse`: used in its project first, the other projects named, as in `BindingPicker.svelte`), `lib/skills.ts` (who uses a skill, in words) |
| change a session's Files pane (its folder, what changed since it started, what its sandbox sees, F.8) | `packages/control-plane/src/handler_control/session_files.py` (the baseline, the mounts recorded at each start in `LiveSession.start`, safe reads, `.gitignore`), `git_read.py` (git objects in a child process), `desktop.reveal` (shown in the file manager), the baseline recorded in `sessions.py` (`_start`), routes in `api/sessions.py`; web UI `components/SessionFiles.svelte`, the Files button and refreshes in `views/SessionView.svelte` |
| change agent interfaces (a run's input, its request, its result parsed, the repair turn) or folderless agents | `packages/control-plane/src/handler_control/interfaces.py`, `sessions.py` (`create`, `read_output`, `work/`), `launcher.py` (`folder`, `subject`) + `docs/dev/contracts.md` §D.18; web UI `RunForm.svelte`, `OutputView.svelte` (a result from its schema, `CodeRef.svelte`), `lib/runs.ts`, `views/RunView.svelte`, `views/AgentView.svelte` (one agent's page, of a project or not: its run form and runs, or a new session and its sessions), `AgentEditor.svelte` (its interface as JSON, an ad-hoc agent's folder) |
| change the built-in agents Handler ships (skill reviewer, skill creator; each set up once) | `packages/control-plane/src/handler_control/data/builtin-agents/<name>/` (`agent.toml`, `instructions.md`, `interface.json`, `skills/`), loaded by `builtin_agents.py` (+ `api/builtin_agents.py`; set up once: `checks.check_origin`); web UI `views/AgentsView.svelte`, `AdHocAgentEditView.svelte` |
| change what handlerd finds in a skill's files (scan) or how a skill is reviewed and edited with an agent | `packages/control-plane/src/handler_control/skill_scan.py`, `skills.py` (`digest`, `copy`, `from_folder`) + `docs/dev/contracts.md` §D.17; web UI `components/SkillReview.svelte` (on a skill's page), `SaveSkillPanel.svelte` (a session's *Save to library*), `SkillLibrary.svelte` (*With an agent*) |
| change how bindings are written from the UI (form, secrets to the store) | `packages/control-plane/src/handler_control/bindings.py` + `docs/dev/contracts.md` §D.15; web UI `AddonsSettings.svelte`, `BindingForm.svelte` |
| change how images are rebuilt, checked, switched | `packages/control-plane/src/handler_control/builds.py` + `image_check.py` (contract D.4) |
| change when images update by themselves | `packages/control-plane/src/handler_control/image_updates.py` (D.4); web UI `HarnessImages.svelte` |
| change how an agent maps to a harness | `packages/harness-adapters/src/handler_harness/render.py` |
| change container isolation, confinement levels, network filtering | `packages/sandbox-podman/src/handler_sandbox_podman/` |
| change the format of a file users keep (config, state, data) | the new format where it is read and written, plus one migration in `packages/control-plane/src/handler_control/migrations/` (`CLAUDE.md`, design principles) |
| change how blocks are combined | `packages/control-plane/src/handler_control/compose.py` |
| change what the platform allows over ACP (P1–P9) | `packages/control-plane/src/handler_control/policy.py` |
| add an API route | `packages/control-plane/src/handler_control/api/<section>.py`, one module per contract section, wired in `api/__init__.py` (+ contract D); rules on what may be saved go to `checks.py`, not the route |
| change projects or their agents | `packages/control-plane/src/handler_control/projects.py` (+ `docs/dev/contracts.md` §D.8); web UI: `packages/web-ui/src/lib/projects.svelte.ts` |
| change the web UI | `packages/web-ui/src/` (views → components → `lib/`) |
| change the logo | `branding/` (the sources: `speech-case.svg` adapts to light/dark, `-light`/`-dark` fixed); copies: `packages/web-ui/public/favicon.svg`, `packages/remote-client/public/favicon.svg` (also the phone's home-screen icon), the sidebar's `packages/web-ui/src/components/Logo.svelte` (theme colors) |
| add or regroup a Settings page | `packages/web-ui/src/lib/settings.ts` (sections and groups of the settings nav), `views/SettingsView.svelte` (each page), `components/Sidebar.svelte` (the nav, its icons) |
| change how a session is shown (both web apps) | `packages/acp-view/src/` |
| change how agent output is rendered safely | `packages/acp-view/src/lib/render.ts` |
| change the phone's remote client | `packages/remote-client/src/` |
| add a CLI command, or change a flag | `packages/cli/src/handler_cli/cli.py` (the top level: verbs `run`, `attach`, `terminal`, `acp`; one `<noun>_commands.py` per noun, its subcommands `list`, `show`, `add`, `rm`…, registered in `NOUNS`) + its user page, `docs/cli/<command>.md` (listed in `docs/user/cli/index.md` and `docs-site/zensical.toml`) |
| change the terminal client, or the stdio bridge to a session | `packages/cli/src/handler_cli/terminal.py`, `session_bridge.py` |
| change `handler terminal` (a harness's own terminal UI in its sandbox) | `[terminal]` in `handler_harness/data/harnesses/<name>/harness.toml`, `render.terminal_command` (B8); `handler_control/terminals.py` (its sandbox, started out of handlerd's reach, D.16), `sandbox_process.start_detached`; `attach` in `handler_sandbox_podman/cli.py`, the `tty` wait in `launch.py`; CLI `packages/cli/src/handler_cli/terminal_client.py`; its page in the web UI (its network) `packages/web-ui/src/views/TerminalView.svelte` |
| change remote control (gateway config, devices, what a phone may do) | `packages/control-plane/src/handler_control/remote.py` (+ `remote_crypto.py`, envelopes) + `docs/dev/design/remote.md` |
| change what a phone and Handler say to each other (control channel, app channels) | `packages/contracts/src/handler_contracts/remote.py` (then `uv run python -m handler_contracts.schemas`, `bun run gen:types`) + `docs/dev/design/remote.md` |
| change the remote-control gateway | `remote-gateway/` (independent project, see its README) |
| change what a mini app's manifest can contain | `packages/contracts/src/handler_contracts/miniapp.py` + `docs/dev/contracts.md` §H |
| change how mini apps are deployed, started, stopped | `packages/control-plane/src/handler_control/apps.py` (+ `compose.app_sandbox_spec`) |
| change how mini apps are served (origin, cookie, proxy) | `packages/control-plane/src/handler_control/app_http.py` |
| change mini apps from phones (app channel, UI as one page) | `handler_control/app_remote.py`, `remote.py`; `packages/remote-client/src/lib/apps.ts`, `public/appframe.html` |
| change notifications, host files of mini apps, or how an automation calls an app | `handler_control/apps.py` (`AppStore.call`), `app_api.py`, `desktop.py`, `webpush.py` |
| change the person's inbox (apps' notifications, automations' results; contract I.9) | `handler_control/inbox.py`, `api/inbox.py`; the phone's `_handler/remote/inbox` in `remote.py`; CLI `handler_cli/inbox_commands.py`; web UI `views/InboxView.svelte`; the phone's list in `remote-client/src/views/SessionList.svelte` |
| change keyboard shortcuts, app windows | `handler_control/shortcuts.py`, `packages/cli/src/handler_cli/app_window.py` |
| change what agents know about writing mini apps | `handler_harness/data/addons/miniapp/skills/miniapp/` (skill + template) |
| change how unattended runs behave (policy answers, timeout) | `packages/control-plane/src/handler_control/sessions.py` (contract D.18) |
| change what users install (the `handler-ai` wheel: the five packages and the built web UI) | `packaging/pyproject.toml` (kept equal to the packages by `tests/architecture/test_packaging.py`), `scripts/build-wheel.sh` |
| change how Handler is installed or set up | `scripts/install.sh` (attached to each release, for people without uv), the PyPI page: `packaging/` (`pyproject.toml`, `README.md`), `packages/cli/src/handler_cli/setup.py` (`handler setup`), what the host check looks at: `handler_sandbox_podman/check.py` (A.8) |
| change automations (contract §I: `when` a session stops or a schedule comes → a script in a sandbox calling the `llm` service and appending to knowledge notes, an agent's run whose result goes to the inbox, or an app's route) | `packages/contracts/src/handler_contracts/automation.py`; control plane: `automation_config.py` (the folders in `~/.config/handler-ai/automations/`, their problems from the folder alone, `state.json`, a form's definition written as `automation.toml`), `schedules.py` (slots, missed slots, local time), `transcript.py` (a session's log slice → `transcript.md`), `automations.py` (the stops that fire, the slots due, the queue, a script's folder and sandbox, an agent's run, an app's call, appends, the inbox told, what it does in sentences, an account's terms verdict, tries, runs), `api/automations.py`; the verdicts: `unattended`, `terms`, `checked` of each harness's `[login]` (`harness.toml`); `compose.automation_run_spec`; the stop hook: `SessionStore.stop_listeners` and `how` in `sessions.py`; appends: `knowledge.append_note`; the shipped examples in `handler_control/data/automations/`; CLI `handler_cli/automation_commands.py`; web UI `views/AutomationsView.svelte`, `views/AutomationEditView.svelte` (the form, new or changed; read back from a definition by `formOf`; an agent's input with `components/RunFields.svelte`, shared with `RunForm.svelte`), `views/AutomationView.svelte`, `components/SessionAutomationRuns.svelte` (a session's panel), the automations that run an agent in `components/AgentEditor.svelte` and, as badges where agents are listed, `components/AgentSchedules.svelte`; `lib/automations.ts`; guide `docs/user/automations.md` |
| change services (what handlerd offers to what it runs: `llm/v1` first) or how a model is called for a script | the interfaces as data in `handler_control/data/interfaces/<name>/v<N>/` (`interface.toml`, `tools.json`), loaded and checked by `services.py`; the router on a sandbox's socket (MCP, JSON-RPC lines): `service_router.py`; the `llm` connector: `llm.py`; its client in the run's sandbox: `handler_control/data/automation/bin/handler-llm` + `docs/dev/design/services.md`, contracts §I.5 |
| change a release | `.github/workflows/release.yml` (checks, wheel, PyPI, GitHub release); the install it checks: `scripts/smoke-install.sh` |
| change how people give feedback | `CONTRIBUTING.md`, `SECURITY.md`, `.github/ISSUE_TEMPLATE/`, `.github/workflows/pull-requests.yml` (closes pull requests); what each release changed: `CHANGELOG.md` |
| change the documentation website (its pages, navigation, look) | `zensical.toml`, `scripts/build-docs-site.py` (gathers `README.md` and `docs/`), `.github/workflows/docs.yml` (GitHub Pages) |

## Tests

| Directory | Kind | Question it answers |
|---|---|---|
| `packages/*/tests` | unit | does this package's code do what it says? |
| `tests/sandbox` | conformance, contract A | does a sandbox implementation keep every A guarantee? |
| `tests/harness` | conformance, contract B | do real harness images behave as their descriptors claim? |
| `tests/acp_endpoint` | conformance, contract C | does a real `handlerd` enforce auth, framing, lifecycle and P1–P9? |
| `tests/control` | conformance, contract D | does the Control API (projects, agents, accounts) behave as specified? |
| `tests/sessions` | conformance, contract F, D.18 | daemon-held sessions (attach, replay, several clients, restart); folderless agents, runs of agents with an interface, built-in agents, skills from a session (`test_runs.py`) |
| `tests/addons` | conformance, contract G | are addon images built and checked, bindings selected, and addons given to live agents as specified? (`test_shopify.py`: opt-in, a real store) |
| `tests/remote` | conformance, D.7 | does remote control work end to end (real gateway, Python device), and are replayed, late, altered and reflected envelopes refused? |
| `tests/cli` | client | does `handler` (including the `handler acp` bridge) work against a real `handlerd`? |
| `tests/automations` | conformance, contract I | does a stopped session start the automations it matches, with the right slice, and are notes appended once, only after success? Does a schedule run its latest slot once, an agent's run reach the inbox, an account's terms verdict hold? (fake sandbox, fake agent, a stub provider; `test_podman.py`: the run's sandbox on real podman) |
| `tests/e2e` | end to end | real harness images through `handlerd`; the web UI, and a phone driving a shared session through a real gateway, in real browsers (Playwright container) |
| `packages/web-ui/tests` | unit (vitest) | session model, run status, projects, sanitizer, router, transport |
| `packages/remote-client/tests` | unit (vitest) | envelopes against the Python vectors, pairing links |
| `remote-gateway/tests` | unit (its own project) | gateway API: auth, mailboxes, limits, cursors |
| `tests/architecture` | architecture | are block boundaries respected, and the control plane's layers (its README)? does the wheel ship exactly the packages? |
| `scripts/smoke-install.sh` | install | does the wheel install with `install.sh` on a bare machine and run (handlerd, web UI, API, toolbox copy, `handler setup`)? |
| `tests/support` | helpers | ACP client (stdio/WebSocket), fake agent, fake sandbox (runs it, and automation runs, on the host: `HANDLER_TEST_SANDBOX`, tests only), test daemon (and its restart), stub model provider (`stub_llm.py`), dev settings |

Tests needing credentials are opt-in: `HANDLER_TEST_CLAUDE_CONFIG_DIR` (+ `_JSON`), `HANDLER_TEST_MISTRAL_API_KEY`,
`HANDLER_TEST_SHOPIFY_STORE` + `HANDLER_TEST_SHOPIFY_THEME_TOKEN`.
