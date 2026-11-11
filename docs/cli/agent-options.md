# Agent options

The options [`run`](run.md), [`terminal`](terminal.md) and [`acp`](acp.md) share: how the agent
is contained and what it gets. They are the agent's settings, the same as in its form in the web
UI.

## How they apply

- **A new agent outside projects** (the first command in a folder) starts as any new agent: only
  the sites it needs (`--network filtered`), no containers, no display, permissions *bypass*.
  The options you type change that.
- **An existing agent** (in a project, or a folder used before): an option that differs from its
  settings is shown, and Handler asks "Save this to the agent?". Yes saves it for every later
  session, no starts nothing. Without a terminal to ask, add `--save`, else it is refused.
- `--allow`, `--keep-blocked`, `--tool` and `--notes` add to the agent's lists; they never
  remove (`--tool` with another connection replaces that tool's). A host is allowed or kept
  blocked, never both: `--allow` takes it off the hosts kept blocked, `--keep-blocked` off the
  allowed ones.
- A tool or an option that needs something the toolbox lacks (Chromium, podman) is asked
  before it is saved: Handler adds the system package to the toolbox, for every agent, and
  rebuilds it.
- An option that gives the agent more (`--network open`, `--log-only`, `--containers`) is printed
  on stderr: typing it is your confirmation.

## Which model

| Option | |
|---|---|
| `--harness NAME` | with a provider: the harness to run (`claude-code`, `codex`, `vibe`, `pi`), needed when several speak its protocol. In a project: which agent, the one running it |
| `--model MODEL` | the model (default: the harness's or the provider's). In a project: which agent, the one running it |
| `--name NAME` | outside projects: another agent for the same folder, e.g. one per use case or to try settings without changing the first. Refused in a project's folder (name an agent instead) |

The account or provider and the model are for this time only: never saved to the agent.

## Network

| Option | |
|---|---|
| `--network filtered` | only allowed hosts: those the account, provider and tools need, plus `--allow` (the default) |
| `--network none` | no network at all |
| `--network open` | any host |
| `--log-only` | with `filtered`: every host goes through and is logged, to learn what the agent needs; then allow them and enforce ([`agent network`](agent.md#learning-what-an-agent-needs)) |
| `--allow HOST:PORT` | one more allowed host; repeatable |
| `--keep-blocked HOST:PORT` | a host kept blocked: refused like any host not allowed, and the agent is told not to ask for it; repeatable. *Remove* in the session's network panel makes it undecided again |

## What it gets

| Option | |
|---|---|
| `--tool NAME[=CONNECTION]` | a tool by its name (`app-builder`), with a connection when it asks for settings and secrets (`playwright=browser`, `github=github-agent`); repeatable ([`tool list`](tool.md), [`connection list`](connection.md)) |
| `--notes FOLDER` | a notes folder, read-only at `/notes/<name>`; repeatable ([`notes list`](notes.md)) |
| `--containers` | the agent may run containers itself, inside its sandbox, with the toolbox's engine: Podman, or Docker when the toolbox has `docker` ([`toolbox`](toolbox.md)) |
| `--display` | your Wayland display and its clipboard: watch the agent's browser window. The agent can read what you copy |

## Permissions

| Option | |
|---|---|
| `--permissions bypass` | acts without asking (the default) |
| `--permissions accept-edits` | edits files without asking, asks for the rest |
| `--permissions ask` | asks before each action |

This is the starting mode; the session can change it.

## Saving

| Option | |
|---|---|
| `--save` | save the options that differ from the agent's settings without asking: for editors and scripts, where there is no terminal to answer |
