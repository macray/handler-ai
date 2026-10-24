# Handler — Architecture

The *why* and the big picture. The *what* (normative formats and guarantees) is
[`contracts.md`](contracts.md); where each block lives in the tree is [`code-map.md`](code-map.md);
every concept and its rules in [`model.md`](model.md) (as users see them:
[`../user/concepts.md`](../user/concepts.md)).

## 1. Goal

Run AI agent harnesses (Claude Code, Codex, Mistral Vibe, pi) on one machine, for one user, with:

- **isolation** of disk, process and network: each agent runs in a rootless Podman sandbox that
  sees only its folder, with an egress allow-list;
- **interaction** through one harness-agnostic protocol, ACP (Agent Client Protocol), from the web
  UI, the `handler` CLI, editors (`handler acp`), or a paired phone;
- **configuration** through named accounts and providers, and each agent's own settings.

ACP is the abstraction layer: every harness speaks it (natively or through an adapter), so clients
contain no harness-specific code and unattended runs work the same for every harness.

## 2. Use cases

| # | Use case |
|---|---|
| UC1 | Chat with an agent in a sandbox from the web UI, supervised (permission prompts, network panel) |
| UC2 | Run an agent unsupervised on a project folder, on an account (subscription) or a provider (API) |
| UC3 | Run an agent with an interface on a form or a Handler object, unattended, and get a result of a known shape |
| UC4 | Several harnesses and settings on the same project, and several projects at once |
| UC5 | Follow and drive shared sessions from a phone, through a gateway that cannot read them |
| UC6 | Let agents write small web apps that a person deploys and uses |
| UC7 | When a session stops, run your own script on its conversation, unattended, and append what it finds to a note (automations) |
| UC8 | At a time (every hour, every weekday at 08:30), run one of your agents or an app's route, and be told the result in an inbox |

Constraints: single user, local machine, rootless Podman. Folders are **bind-mounted directly**
(no copy, no git gate) at the **same absolute path** as on the host, inside the machine's work
folders.

## 3. Concepts

| Concept | Definition |
|---|---|
| **Harness** | An agent program, its ACP adapter and its image (`handler_harness/data/harnesses/<name>/`) |
| **Account** | A subscription one harness logs in with; Handler keeps its login |
| **Provider** | Where model calls go: endpoints by protocol, a key, the models; usable by every harness speaking one of its protocols |
| **Agent** | What runs (a harness on an account or a provider, with a model) × where (a folder) × its own settings (network, confinement, permission mode, tools, skills, knowledge, display). A registered endpoint with a stable id; it starts nothing by itself |
| **Project** | A code folder, its caches and skills, and its agents |
| **Session** | A conversation held by the daemon: it owns one sandbox, which outlives the clients attached to it; it has an event log |
| **Addon + configuration** | An addon brings programs, skills and egress for one kind of system; a configuration (a binding in the files) is one set of its settings and credentials, what an agent is given |
| **App** | A small web app (Bun backend + UI) an agent writes and a person deploys; it runs in its own sandbox |
| **Automation** (I) | *When this happens, run that*: when a session stops or at a time, a script in its own sandbox (calling models through handlerd's `llm` service), an agent's run or an app's route; only the owner turns one on |
| **Inbox** (I.9) | What Handler tells the person: apps' notifications, automations' results and failures; written by handlerd only |

Granularity rules:

- **Never** share one agent process between clients. A plain ACP connection to an agent gets one
  ephemeral sandbox, killed when it closes. A session owns one sandbox, stopped when the session
  is stopped or idle.
- One goal, one agent: a new agent means a different goal or different access, never only a
  different model (an agent has a list of models, each session picks one).

Design rules (decided 2026-10-02 and 2026-10-04, when profiles and policies were removed):

- **Owned, derived or copied, no cascading.** Every value an agent runs with is *owned* (set on
  exactly one object, edited only there: an agent's allowed hosts), *derived* (a live consequence
  of a choice, never typed, shown "required by X": `api.anthropic.com` for a Claude account, an
  addon's hosts) or *copied* (starting values copied once, never linked: the presets, "Duplicate
  this agent"). No global → profile → project → agent cascade, no "apply to all".
- **Optional parts, not kinds.** An interface, no project, no folder are optional parts of one
  agent, not kinds of agents. A helper (skill reviewer, skill creator) is the agent given for
  one of Handler's needs, as for an app's: you set one up from the definition Handler ships for
  it (choosing its model), or give one that fits.
- **Triggers live on automations**, never on agents: "run this agent every Monday" is an
  automation whose run is that agent: what does the work and how it starts are two questions.

## 4. Blocks

```
 Clients     web-ui · handler CLI · editors (handler acp) · remote-client (phone, via remote-gateway)
               │  D: Control API (HTTP)        C/F: ACP over WebSocket
 ┌─────────────┴─────────────────────────────────────────────────────────────┐
 │ CONTROL PLANE  handlerd (127.0.0.1, token)                                 │
 │  config stores · agents, projects · launch pipeline · ACP policy           │
 │  sessions · image builds · remote connector · apps                    │
 └──────┬──────────────────────────────┬──────────────────────────────────────┘
        │ B: import                    │ A: executable, SandboxSpec on fd 3
   HARNESS ADAPTERS                SANDBOX
   catalog (harnesses, addons,     handler-sandbox-podman: rootless container,
   toolbox) · render · images      confinement, egress allow-list proxy
        │ reads
   data/: harnesses/ · addons/ (built-in) · toolbox/ (default)
   ~/.config/handler-ai/: toolbox/ · addons/ (the user's)
```

| Block | One sentence |
|---|---|
| contracts | Every exchanged data shape, as pydantic models; JSON Schemas and TypeScript types are generated from them |
| sandbox-podman | Turns a `SandboxSpec` into one confined container whose stdio is the agent's stream |
| harness-adapters | Knows the harnesses, addons and toolbox, and renders an agent into a harness-specific launch (pure) |
| control-plane | Composes the other blocks: stores configuration and agents, starts sandboxes, applies the ACP policy, holds sessions, serves the API |
| cli, web-ui | Clients of handlerd over HTTP and WebSocket only |
| acp-view | The session view shared by the web UI and the phone client |
| remote-client, remote-gateway | A phone client, and a relay of end-to-end encrypted envelopes (independent project) |

### Dependency rules

1. Blocks exchange **data**, not code. `handler_contracts` is the only shared library; the control
   plane also imports the harness adapters. Checked by `tests/architecture/test_boundaries.py`.
2. The sandbox knows nothing about harnesses, ACP or agents, and is reached only through its
   executable. The harness adapters know nothing about the sandbox. Clients know nothing about
   either.
3. Harness-specific knowledge lives only in the harness adapters and their data
   (`handler_harness/data/harnesses/<name>/`); addon-specific knowledge only in the addon's folder.
4. The container engine is reached only through the sandbox's executable: containers that run
   something (agents, apps, the check of an addon image) with `launch`, images (build, inspect,
   read their version file, tag, remove, pull) with its `image` verbs (A.7). The harness adapters'
   `images` only says what to build and where an image records its version (`Recipe`,
   `version_file`); the control plane's `runtime` asks the executable. Checked by
   `test_only_the_sandbox_runs_podman`.
5. Every contract has a conformance test suite (`tests/sandbox`, `tests/harness`,
   `tests/acp_endpoint`, `tests/control`, `tests/addons`, `tests/remote`).

## 5. Flows

**Starting an agent** (`launcher.prepare`), for a connection or a session:

```
agent ─► access: account or provider resolved (E) ─► bindings (G), skills, knowledge
      ─► secrets and config files ─► render (B) ─► compose (B + G → A) ─► sandbox (A)
```

**ACP traffic**: every message between a client and the agent goes through the policy pipeline
(C.4, P1–P9) in the control plane, outside the sandbox: the client's `fs`/`terminal` capabilities
are removed, the agent's `fs/*` and `terminal/*` requests refused, session folders checked against
the agent's scope, the platform's MCP servers added and checked against the network policy, the agent's
instructions put before a new session's first prompt.

**Sessions** (F): the daemon starts the agent, answers `initialize` and `session/load` itself (from
its cache and event log), and relays the rest through the policy. Several clients may be attached;
the first answer to a permission request wins.

**Runs** (D.18): a run of an agent with an interface is a session started with an input; the
daemon answers its permission requests per the interface, cancels the turn after its timeout and
checks the result its final message holds.

**Automations** (I, [`docs/user/automations.md`](../user/automations.md)): when a session stops,
or when a schedule's time comes (handlerd's own scheduler, local time; after the computer was off,
only the latest missed time runs), handlerd starts the automations that are on and match it, one run
at a time. A script runs in a sandbox of its own with no network, reading the conversation since
its last run (`transcript.md`, secrets removed) and calling models only through handlerd's `llm`
service on a socket; once it succeeded, handlerd appends the file it wrote to a knowledge note. An
agent's run is a run (D.18) started by handlerd; its result (`status`, `summary`, the rest as data)
goes to the person's inbox, with failures and apps' notifications. On a subscription it runs only
when the vendor's terms allow it (a verdict per harness login, I.7).

**Remote control** (D.7, [`remote.md`](design/remote.md)): handlerd long-polls a gateway outbound and never
listens beyond loopback; devices and handlerd exchange envelopes the gateway cannot read or forge.

## 6. Security notes

| Risk | Current state |
|---|---|
| Agent runs commands on the host through ACP `fs`/`terminal` | refused by the policy pipeline in the control plane (P1, P4) |
| A web page drives the local WebSocket | 127.0.0.1 only, per-install token, Origin allow-list |
| Scope = blast radius (rw bind mount) | accepted; scopes must lie in the work folders; small scopes, git as safety net |
| Shared rw caches = a channel between projects | per project: its own (the default), global, or off |
| The agent can read its account's login and edit its harness's state | accepted; state is kept per agent |
| Egress | per agent: none, allow-list (enforced or log only, switchable live) or open; required hosts come from the harness, account or provider, and tools |
| Shared kernel (container escape) | rootless Podman, confinement `strict` by default (`nested`, `privileged` shown with a warning) |
| Agent output rendered in the browser | sanitizer (no raw HTML, safe URLs), DOMPurify, Content-Security-Policy |

## 7. Open points

- Vendors' terms for subscriptions driven through ACP adapters: checked for Anthropic
  (docs/dev/ui-ux.md "Vendors' terms", contracts I.7), to check for OpenAI and Mistral.
- Credentials the code cannot read (the credential proxy and connectors): next after
  automations.
