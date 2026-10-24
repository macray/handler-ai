# Configuration: who, where, with what

Why the configuration is split the way it is, and what was left out on purpose. What each thing
is and where it is kept, as users see it: [where things are kept](../../user/configuration.md).

## Why this split

- An **account** is only the login (a token or a login file): it holds no state, and only the
  harnesses that run on a subscription need one. Its file names the harness; the harness's
  `[login]` says how the login is obtained, what it leaves and the hosts it needs.
- A **provider** is written once (endpoints by protocol, a key, the models) and used by every
  harness that speaks one of its protocols (`llamacpp` serves Codex, pi and Vibe); a small adapter
  per harness turns it into the harness's own config (`handler_harness/providers.py`), and it carries
  the config files a harness needs to talk to it (`[files.codex]`).
- An **agent** names its harness, account or provider and model directly, with nothing in
  between; it owns the harness's history (an ad-hoc agent shares one per harness and account or
  provider) and how it is contained. Each value has one owner (owned, derived or copied:
  [`architecture.md`](../architecture.md) §3): the agent owns its network mode, hosts, log-only,
  permission mode, confinement and display, starting from a preset copied at creation (Locked
  down, Guarded, Open); the hosts its account or provider and its addons need are derived and
  shown "required by X"; the **machine** owns the work folders; the **project** chooses whether
  its agents keep their own caches or use the global ones. A save that widens what an agent may do is confirmed.
- Network hosts belong to what the traffic is for: the login's hosts, the provider's endpoint,
  the addons', the agent's own. An agent uses an account or a provider, never both: a
  subscription's token must not travel to a third-party endpoint.
- A **project** (`~/.local/state/handler-ai/projects.json`, [`contracts.md`](../contracts.md) §D.8) holds a
  code folder, its skills (given to all its agents) and its caches setting; each of its agents has
  a `projectId` and settings all its own (no project defaults: a new agent copies a preset or
  another agent). An agent without a project is **ad hoc**, made by `handler run`, `handler acp` and
  `handler terminal` outside projects.

## Decisions

- **Agents are editable, with a stable id.** Their id used to be a hash of their settings, so
  "editing" meant creating another. Ids are random. An ad-hoc agent is its folder and its name
  (2026-10-08; before, its settings, so each new flag made one more and they piled up): the CLI
  finds it again and saves the flags that differ once confirmed. A name makes another ad-hoc
  agent in the same folder: one per use case, instead of one mixing every possibility.
- **The agent is what you pick**: in a project, from its page; recorded last use (by the
  daemon, not the browser) orders projects and agents.
- **Network per agent.** Mode (none / filtered / open), log-only and the agent's own
  allowed hosts. Hosts and log-only apply to running agents at once (A.4), so the session's
  network panel edits the agent's hosts live; the mode applies to new sessions. The
  account's, the provider's and the addons' hosts are shown "required by" them.
- **Podman in podman is an agent setting** ("Runs containers", `--containers`).
  It is no weaker than before: the same `nested` confinement (A.5), chosen per agent, visible as
  a badge on it. `privileged` is an agent setting too, shown with a warning and confirmed. Not an
  addon: addons add image mounts, env and hosts, never sandbox capabilities — a binding must not
  be able to loosen the sandbox.
- **Accounts, providers and bindings stay TOML** in `~/.config/handler-ai/`, written by the web UI's
  forms (Settings → Model access: an account from its login, a provider from a template;
  Library → Addons) and still readable by hand (unknown keys are errors).
- **Harness ≠ addon** in the words used everywhere: a harness is the agent program (Claude Code,
  Vibe, pi), chosen by the agent; an addon is programs and skills any agent can be given, through
  one of its configurations (a binding). Settings → Images groups them apart (agent programs,
  addons, shared base).
- **Switching harness** is picking another harness in the agent. Its past conversations stay
  with what they were started with: the daemon refuses to resume a session once its agent runs
  another harness, account, provider or folder, saying so.

## Left out (for now)

- Agents as TOML files in `~/.config/handler-ai/`: the daemon rewrites them (last use, live
  switches), which a hand-edited file should not see; the JSON is still one readable file.
