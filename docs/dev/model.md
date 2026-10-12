# Domain model

Every concept Handler is built on, with its rules: what it owns, how it relates to the others,
how it behaves (states, resolution, limits). The reference for contributors and agents changing
Handler; the formats and guarantees are [`contracts.md`](contracts.md), why it is built this way
[`architecture.md`](architecture.md) §3.

Users read the short version, [concepts](../user/concepts.md): what each word is for, in the
words of the UI. The two are kept in step: a concept users meet is named the same in both, said
there in a few lines and in full here; a rule is written here only.

## The layers

Handler is built in layers. Each one uses only the layer below it.

| Layer | Question it answers | Concepts |
|---|---|---|
| 1. Run | which agent program, and how to talk to it | harness, harness image, ACP |
| 2. Contain | what the agent can reach | sandbox, confinement, network, permissions, work folders, ACP policy |
| 3. Equip | what the agent runs as and what it gets | account, provider, addon, addon configuration, skill, knowledge folder |
| 4. Use | what you work on, and how you reach agents | project, context, agent, ad-hoc agent, session, attachment, remote device |
| 5. Delegate | (not built) you ask, Handler picks the project, agent and prompt | — |
| Separate | small personal tools | mini app, person |
| Separate | what Handler does by itself when something happens, and what it tells you | automation, inbox |

```
 account ◄──────────┐ a subscription one harness logs in with (brings its harness)
 (claude-pro…)      │ either one
 provider ◄─────────┤ endpoints by protocol, key, models; files for a harness
 (llamacpp…)        │
                    │ 1..n (its models; a session runs with 1)
 project ──────────►┌┴─────────────────────────────────────────┐
 folder (in a work  │ agent (of a project, or ad hoc), 1 goal: │
 folder), caches,   │ models (harness + account or provider +  │
 skills (given to   │ model, the first by default),            │
 all its agents),   │ name, description, instructions; its own │
 1..n agents        │ sandbox: network, hosts, log-only,       │
                    │ permissions, confinement, display; its   │
                    │ addons, knowledge, skills; its history;  │
                    │ an interface (runs unattended)           │
                    └──────────────────┬───────────────────────┘
                                       │ 0..n
                    ┌──────────────────▼───────────────────────┐
                    │ session: 1 of its agent's models,        │
                    │ 1 sandbox (+1 proxy if filtered), 1 ACP  │
                    │ conversation, started                    │
                    │ with a request, an input (a run), or     │
                    │ empty; origin                            │
                    └──────────────────┬───────────────────────┘
                                       │ 0..8
                attachments: browser tabs, phones, the terminal client
```

## 1. Run

**Harness.** The agent program: Claude Code, Codex, Mistral Vibe, pi. A descriptor
(`handler_harness/data/harnesses/<name>/harness.toml`), an ACP adapter and a container image. An account brings its
own; an agent on a provider names one that speaks the provider's protocol.

**Harness image / toolbox.** The toolbox image is the shared dev environment (toolchains); each
harness image is built on it. Rebuilt from Settings → Images or `handler image rebuild <name>`; the new image
is checked before agents switch to it.

**Network filter.** Part of Handler, between agents and the internet: it lets an agent reach only its
allowed hosts and adds its secrets to its requests. Its image is built on each computer (by
`handler setup`, or by handlerd when it is missing) and updated with the others; until then, agents with
a network allow-list or a secret do not start. Shown in Settings → Images.

**ACP (Agent Client Protocol).** The protocol between Handler and every harness. Because of it, the web
UI, the phone client, the terminal client and Zed contain no harness-specific code.

## 2. Contain

**Sandbox.** Where an agent runs: a rootless Podman container, always. The project
folder is mounted read-write at the same path as on the host; nothing else of your home is visible
unless the agent is given it (knowledge folders, its addons).

**Confinement.** How strict the container is: `strict` (default), `nested` (the agent may run podman
itself), `privileged` (last resort, shown with a warning). An agent setting.

**Network.** Three modes: `none`, `filtered` (a proxy container lets only the allowed hosts
through) and `open`. In filtered mode, **log-only** lets everything
through but logs what would be denied, to discover what a project needs. Allowed hosts add up:
the agent's own, plus those its account or provider and its addons require (shown "required by
X"). Hosts and log-only change live in running sessions (the
session's network panel); the mode applies to new sessions.

**Permissions.** The agent's starting mode: `ask` (you answer each request in the session),
`accept-edits` (file edits allowed, the rest asked) or `bypass` (unsupervised). Set on the
agent; the session's mode selector changes it for that session.

**Work folders.** The folders agents may work in, owned by this computer (Settings → Folders,
`~/.config/handler-ai/folders.toml`, default `~/code`): a project's folder and an ad-hoc session's must be
inside one; Handler's own folders are always refused.

**Presets.** Locked down (no network, asks first), Guarded (filtered network, enforced: only its
allowed hosts, those its model and addons need included; never asks: the default of a new agent)
and Open (any host, never asks): values the UI copies into an agent, never linked to it. Log-only
is not a preset: the session's network panel turns it on to learn the hosts an agent needs
(*Learn hosts*), then allows them and enforces again in one click. A save that widens
what an agent may do (open network, containers, privileged, auto-approve) is confirmed.

**ACP policy.** What Handler itself enforces on the ACP traffic, whatever the client (P1–P9, contract
C.4): the agent cannot reach host files or terminals through ACP, the session folder must be the
agent's, MCP servers are checked, the agent's instructions go with a new session's first prompt.

## 3. Equip

**Account.** A subscription one harness logs in with (a Claude Pro or a personal subscription, a
ChatGPT plan, a Mistral account for Vibe). One TOML file per account in `~/.config/handler-ai/accounts/`
(e.g. `claude-perso`, `claude-pro`): its harness, a description (e.g. the email it was made with)
and, for Claude Code, its plan (`pro`, `max`…: its token does not tell Claude Code, which would
then say "Claude API" and pick an API user's default model). Its login: for Claude Code, the
token your own `claude setup-token` prints (Handler never runs that sign-in), kept in Handler's secret
store or where you keep it (the file says which); for Codex and Vibe, the file their login,
run by Handler on this computer, leaves. A subscription is for its owner's own use. The hosts it
needs come from the harness.
It may let Claude Code use the account's own connectors (claude.ai MCP servers: off by default,
they reach whatever the account connected). No history: that belongs to each agent. Settings →
Model access lists the subscriptions by name (Claude Pro or Max, ChatGPT, Mistral: the harness's
`login.subscription`); picking one creates an account (you name it), logs it in (Claude Code:
the token you give, pasted or where you keep it; the others: a terminal window opens with the
harness's own login, on this computer, or upload the file of a login done elsewhere), renames
and deletes it, and shows its use. A key for
an API is not an account: it is a provider's. It says which project **contexts** it is made for
(Work, Personal…, or any): see Context.

**Provider.** Where a harness sends its model calls: an endpoint for each protocol it speaks
(`anthropic`, `openai-chat`, `responses`), an optional key, the models it serves (a `llamacpp` on
this machine, the Anthropic API with a key, OpenRouter). One TOML file per provider in
`~/.config/handler-ai/providers/`, written once and used by every harness that speaks one of its
protocols; each harness turns it into its own configuration. It may carry config files for one
harness (`[files.codex]`: Codex's system prompt for a model it does not know; the llama.cpp
template has one). Its host is allowed in the sandbox's network by itself. Settings → Model access lists the
templates (Anthropic, OpenAI, Mistral, OpenRouter, llama.cpp, Ollama) with the harnesses that can
use each, or another API by its address; picking one creates a provider in a form, which edits,
renames and deletes it too; its key goes to Handler's secret store. Like an account, it says which
contexts it is made for (a local model: any).

One account or one provider is enough for agents to run; Model access says so, opens on the
ways to connect a model while there is none, and shows only the kinds there are.

**Addon.** What an agent can be given beyond its harness: programs (in its own image), the skills
that explain them, maybe an MCP server, and the hosts they need (`shopify`: the Shopify CLI;
`playwright`: a browser; `miniapp`). It asks for settings and secrets (a store, a token). Built in,
installed from Handler's catalog, a folder or an archive (Settings → Addons, `handler addon add`), in
`~/.config/handler-ai/addons/`. Not a harness: an addon never changes the sandbox's capabilities.

**Addon configuration.** One set of an addon's settings and secrets, named (`shopify-dev-shop`:
the shopify addon on one store; `browser`: playwright's, with no setting): what you give an agent,
shown as `addon: configuration` (`shopify: dev-shop`). Made in Settings → Addons (Configure), its
secrets kept in Handler's secret store. Every agent is offered every configuration: those used in
its project come first, the others say which projects use them. In the files, the API and the CLI it is a **binding**
(`~/.config/handler-ai/bindings/<name>.toml`, `--binding NAME`).

**Secret.** A key or a token: an account's, a provider's, an addon configuration's, an app's.
Kept by Handler (its secret store) or where you keep it (an environment variable, a file, a command
printing it). Agents never see it: an agent holds a stand-in of the same form, and Handler puts the
real value in the agent's requests to the secret's hosts only (the account's, the provider's, the
ones its addon names). A page or a file that tricks the agent cannot send the secret elsewhere:
Handler blocks a request carrying it to another host and the agent's network panel says so. It
stops the secret leaving, not its use: the agent can still call those hosts with it. Where that
cannot work (a tool that signs with the secret, or does not speak HTTP, as its addon says), the
agent reads the value itself. Settings → Secrets (`handler secret list`) lists every secret, what it
belongs to, the agents that use it, and whether they can read it.

**Skill.** A folder with a `SKILL.md`, mounted read-only where the harness looks for skills. In the
skill library (Skills in the main menu, `~/.config/handler-ai/skills/`) every skill is offered to every
agent: any number of projects may give it to all their agents, and any other agent may pick it
(a skill written for one project is found in the others). An edit reaches every agent that gets
it: *Save as a new skill* keeps a change to a copy, given to some of them only. An addon brings its own (listed on its card in Settings →
Addons). A skill is written there, on its own page (its name, when to use it, who gets it, its
instructions and files), or imported from a `.skill`/`.zip` archive or a URL (a skill's folder in a
GitHub repository); an imported skill does nothing until it is given to a project's agents or an
agent picks it.

**Knowledge folder.** A folder of notes under the knowledge root (default `~/knowledge`, set on the
Knowledge page), mounted read-only at `/knowledge/<name>`. Selected per agent.

## 4. Use

**Folder (scope).** The host directory the agent works in, read-write. Must be inside one of the
work folders.

**Project.** What you work on: a name, a description, a code folder (one project per folder),
its **context** (Work, Personal, a client; optional), the **skills** it gives to all its agents,
its **caches** (what toolchains download and build, `~/.cargo`, `~/.cache`, podman's images…:
its own, the default; global, used with the other projects choosing them and agents outside
projects — a write channel between them —; or off; Settings → Caches shows what is kept, then
where: the global folder and each project's own, cache
by cache, measured and emptied),
and its agents (at least one, one of them the default). Home page of the web UI: projects by
last use. A project's page: type what you want, pick the agent, *Start*; below, its live and recent
sessions, its agents, what it gives them. CLI: `handler project list` lists them, `handler project show NAME` their agents. Stored in
`~/.local/state/handler-ai/projects.json`.

**Agent.** Who works on a project, for one goal ("dev work", "review"): its **models**, each a
harness on an account or a provider with a model, the first by default; each session runs with
one of them, or with any other account or provider its project's context allows ("Run with": for
that session only, never saved to the agent; out of usage, a local model for privacy, trying a
new model), with every other setting the same. Another model is not another agent: an agent differs from another by what it is for or what it may do. Its name
is its goal ("Dev", "Review", "Contracts check"), required: a new project asks for its first
agent's (default "Dev"); then more about it,
optional instructions (sent before the request of each session started from the project page),
and what it may do and get, all its own: permission mode, network mode, its allowed hosts and
log-only, confinement, display (a new one starts from a preset, or is a duplicate of another),
bindings, knowledge folders, skills. From its project: the folder, caches and the
project's skills. It keeps its harness's own history and settings (Handler keeps them per
agent and per model, so one project's transcripts never reach another, and another harness never
reads them). The hosts a session's account or provider needs are allowed in that session only. Created, edited, duplicated and removed
from the project's page.

**Ad-hoc agent.** An agent without a project: made by `handler run`, `handler acp` and `handler terminal`
outside projects (or with `--anyway`), one per folder and `--name`: the same command in the
same folder always gives the same agent, made with the options typed the first time; the
account or provider named is its model for that session only (another one is not another
agent), and an option that differs from its settings is saved to it once you say yes (below).
Something to try once is another agent: `--name try-open`. The web UI lists its sessions under
"Outside projects"; `handler agent list` lists every agent with its id, `handler agent rm <id>` removes an
ad-hoc one. Agents of both kinds are stored in `~/.local/state/handler-ai/agents.json`. The web UI lists ad-hoc
agents on its Agents page: Handler's built-in ones, then yours, made there from scratch. An ad-hoc agent
may have no folder: each of its sessions then gets an empty folder of its own, kept with the
session (the skill creator works on a skill there, then *Save to library*).

**Agent interface.** What a run of an agent takes (a form, a Handler object such as a skill, mounted
read-only) and gives back (data of a known shape, shown as such). An agent with one runs
unattended: you start it with a button, watch it if you want (no one can prompt it),
and read its result on the run's page.

**Built-in agent.** An agent Handler ships, set up at most once (Agents → Built-in): you choose its
models, the rest starts from Handler's defaults and is yours to change, so there is one skill reviewer,
not one per model or per network setting. The **skill reviewer** reads a skill (never runs it) and
says what it makes your agents do and where it does not do what it says; the **skill creator**
writes or improves a skill with you. Its skills go to your library when you set it up. Deleted, it
can be set up again.

**Session.** One conversation with an agent, held by the daemon: one sandbox (two containers when
the network is filtered: the agent and its proxy), one ACP session, one folder
`~/.local/state/handler-ai/sessions/<id>/` with the event log. Started from a project's page with a
request (sent by the daemon as the first turn, after the agent's instructions; its first line is
the title), or empty.

- States: `starting` → `running` → `stopped` (stop, 30 min idle, agent exit, daemon restart) →
  `starting` again when you attach (resumed with `session/load` if the harness supports it);
  `failed` if the first start failed.
- The agent keeps running when no one is attached; a reload re-attaches and replays the log.
- Nothing deletes a session but you. Stopped sessions are listed on their project's page
  ("Recent", *Resume*); open ones in the sidebar under their project, and in "Needs you" when they
  wait for an answer or replied.
- Web UI status: starting, working, needs you (a permission prompt), replied, idle, elsewhere,
  stopped.
- **Files** (on its page): its folder, and what the agent created, changed or deleted there since
  the session started. In a git repository, a changed file shows what it was in the last commit
  then. Read-only; files ignored by `.gitignore` are left out. **Access** lists everything of your
  computer the agent sees (its folder, knowledge folders, skills, its own settings, caches), each
  read-only or not; knowledge folders and skills can be opened there too. A file or folder can be
  shown in your file manager (selected, not opened).

**Attachment.** A client connected to a session: a browser tab, a paired phone. Up to 8 at once;
they all see the same conversation and any of them can prompt.

**Context.** What a project is for: Work, Personal, a client (Settings → Contexts, each with its
colour, shown on its projects, sessions and tags). A project has at most one; accounts and
providers say which contexts they are made for, or any (a local model). A project with a context
runs only the accounts and providers made for it, so a work account never works on a personal
project; one without a context runs any. Nothing else is split by context: knowledge folders,
addon configurations and skills stay shared (a work agent may read your personal calendar).

**The folder decides the project.** In a project's folder (or below), `handler run`, `handler terminal`
and `handler acp` use the project's agents with their own settings: the agent named (its first model),
or the one listing the account or provider named among its models, with that model (the default
agent first; `--harness`, `--model` choose among its models), else the default agent on the
account or provider named, for that session only, or the default agent when none is named.
An agent option that differs from the agent's settings (`--network open`, `--allow`…) is never
ignored, here or outside projects: Handler says what differs and asks "Save this to the agent?";
yes saves it (and confirms what it widens), no starts nothing; without a terminal to ask (an
editor, a script), `--save` saves it, else it is refused. An account or provider not made for the
project's context is refused, saying how to run it anyway: `--anyway` runs it there outside the
project (ad hoc), once you type `yes` to its warning (in a terminal only). The web UI has no such
way: its model choice says what it hides and gives the command.

**Ad-hoc session.** `handler run [account|provider] [--harness h] [--model m] [options]` outside
projects (or with `--anyway`): a session there, with that harness on that account or provider and
the options given over the preset (filtered network, enforced; `--log-only` to learn its hosts), no project (an ad-hoc agent). Its history is kept per harness and account or provider. Like
every session it is held by the daemon: the web UI lists it under "Outside projects", a phone can reach it
(`--remote`).

**Harness terminal.** `handler terminal <agent|account|provider> [options] [-- args]`: the harness's
own terminal UI (Claude Code's) in the sandbox the agent gets, instead of an ACP client.
Not a session: one sandbox for as long as the terminal is open. The web UI lists it with its
project's live sessions (with `--anyway`, marked "outside the project"; an agent outside projects:
on the Agents page's) and changes its network at once (learn hosts, allow one); its conversation
stays in the terminal. Restarting Handler leaves it running, but the restarted Handler no longer shows it.
Its history is the agent's, like its sessions'.

**Terminal client.** `handler run [agent] [-p request]` (in a project's folder: one of its agents by
name) and `handler attach [session]` use the session in the terminal, as one more attachment:
Ctrl-C cancels the turn or detaches, Ctrl-D detaches, the agent keeps running. `handler attach` on a
stopped session resumes it, when its harness can reload a conversation. `handler session list`
lists the running ones (`--all`: stopped ones too), `handler session stop` stops one. The web UI lists sessions started elsewhere without attaching to them until
you open one.

**Connection (`handler acp`).** For editors (Zed): `handler acp <name>` in a folder gives a stdio ACP
agent. In a project's folder, an agent of the project (see above): a daemon session per editor
thread, shown in the UI (the stdio bridge answers the editor's `session/new` with the session's
conversation; `handler attach --stdio <session>` is the same bridge for any ACP client). Elsewhere,
an account's or provider's name: one container per connection, killed when it closes, not shown
in the UI.

**Remote.** Reaching sessions and mini apps from a phone, through a **gateway** that relays
end-to-end encrypted messages (Handler only polls it outbound). A **device** is paired from Settings →
Remote with a QR code. A session is reachable only while its **Remote** switch is on (off by
default, reset when it stops). The phone lists the shared sessions grouped by project, and
starts a session of an agent marked "Can be started from your phone" (typed or dictated request;
your own devices only). See
[your phone](../user/phone.md).

**Origin.** Who started a session: you in the web UI, the terminal (`handler run`), an
editor (`handler acp`) or a phone. Shown on the project page.

## Separate: automations

How to write one: [`automations.md`](../user/automations.md).

**Automation.** *When this happens, run that*. When: a session stops, or a time comes (every
hour, every weekday at 08:30). That: your own script, one of your agents (one with an interface),
or a route of one of your mini apps. It is not a pipeline: when the work has several parts, the
script runs them and passes the data along. It is a folder in
`~/.config/handler-ai/automations/<name>/` (`automation.toml` and its scripts), shown on the Automations
page and by `handler automation list`; made there (**New automation**), from an agent's settings (**Save and run
it on a schedule…**), or from an example for a script. Examples: when a session of *my-app* stops, read what was said
since the last time, ask a model which tools, permissions or hosts the agent lacked, and add the
findings to the knowledge note `handler/env-issues.md`; every hour, the *reviewer* agent reviews
*my-app*'s code.

- **At a time.** Handler itself runs it (no OS timer), while Handler runs. After the computer was off over
  several times, only the latest runs; the run says how many it missed.
- **A script's run.** In a sandbox of its own with no network: it reads the session's
  conversation (`transcript.md`, secrets removed) and writes its output. It calls a model with
  `handler-llm`, through Handler's `llm` service: only the models the automation lists, on a provider (an
  API key or a local model, never a subscription); the key never reaches it. When it succeeded,
  Handler adds a file it wrote to a knowledge note. Nothing else is written; repeated findings are
  kept (what comes back often is what to fix).
- **An agent's run.** A session of the agent with its form filled in, started by the automation:
  unattended, in the agent's own sandbox with its settings. Its result says how it went
  (`status`) and what it found (`summary`): both go to your inbox. On a subscription it runs only
  when its vendor's terms allow it (the accounts screen says, per vendor).
- **On and off.** It is off until you turn it on: that is your approval (only you can: never an
  agent, never from a sandbox). Its page says what it does in sentences; your edits of its files
  apply at its next run.
- **Try.** Runs it now: a script on a session you choose, writing nothing (you see what it would
  add); a scheduled one at once (an agent's or an app's try is a real run).
- **Its runs** are listed on its page: what each was for, its log, the models' tokens, the agent's
  session; a session's page lists the runs on it.

**Inbox.** What Handler tells you, like mail: your apps' notifications, your agents' results, failed
runs. The Inbox page, `handler inbox`, your phone (pushed, content-free). Nothing in a sandbox writes
to it.

## Separate: mini apps

**Mini app.** A small web app (Svelte UI + Deno backend + SQLite) an agent writes with the `miniapp`
addon, that you deploy from the Apps page (`handler app`) and open at `http://<name>.localhost:7430/` or
from a paired phone. **Installed app**: a deployed version plus its data, which survives updates.
Started on demand, in its own sandbox. See [mini apps](../user/mini-apps.md).

**Person.** Who uses an app: `owner` (you: sessions and apps) or a family member (apps only). Each
paired device belongs to one person; each app lists the persons it is shared with.

## Words that are easy to mix up

The glossary users read is the table at the end of [concepts](../user/concepts.md). The words only
contributors meet:

| Words | Difference |
|---|---|
| folder / scope | The folder is the path; scope is its name in the API. |
| session / connection / attachment | A session is held by the daemon and survives clients; a connection (`handler acp <account>`) dies with its client; an attachment is one client of a session (a tab, a phone, the terminal client, the stdio bridge). |
| harness session history / session log | The harness keeps its own history (for `session/load`); Handler keeps the event log it replays to clients. |
