# Agent options

The options [`run`](run.md), [`terminal`](terminal.md) and [`acp`](acp.md) share: how the agent
is contained and what it gets. They are the agent's settings, the same as in its form in the web
UI.

## How they apply

- **A new agent outside projects** (the first command in a folder) starts from a preset: filtered
  network (allowed hosts only), no containers, no display, permissions *bypass*. The options you
  type change that preset.
- **An existing agent** (in a project, or a folder used before): an option that differs from its
  settings is shown, and Handler asks "Save this to the agent?". Yes saves it for every later
  session, no starts nothing. Without a terminal to ask, add `--save`, else it is refused.
- `--allow`, `--binding` and `--knowledge` add to the agent's lists; they never remove.
- An option that gives the agent more (`--network open`, `--log-only`, `--containers`) is printed
  on stderr: typing it is your confirmation.

## Which model

| Option | |
|---|---|
| `--harness NAME` | with a provider: the harness to run (`claude-code`, `codex`, `vibe`, `pi`), needed when several speak its protocol. In a project: which of the agent's models |
| `--model MODEL` | the model (default: the harness's or the provider's). In a project: which of the agent's models |
| `--name NAME` | outside projects: another agent for the same folder, e.g. one per use case or to try settings without changing the first. Refused in a project's folder (name an agent instead) |

The account or provider and the model are for this time only: never saved to the agent.

## Network

| Option | |
|---|---|
| `--network filtered` | only allowed hosts: those the account, provider and addons need, plus `--allow` (the default) |
| `--network none` | no network at all |
| `--network open` | any host |
| `--log-only` | with `filtered`: every host goes through and is logged, to learn what the agent needs; then allow them and enforce ([`agent network`](agent.md#learning-what-an-agent-needs)) |
| `--allow HOST:PORT` | one more allowed host; repeatable |

## What it gets

| Option | |
|---|---|
| `--binding NAME` | an addon with its settings and secrets, e.g. `browser` (Playwright) or a Shopify store; repeatable ([`binding list`](binding.md)) |
| `--knowledge FOLDER` | a knowledge folder, read-only at `/knowledge/<name>`; repeatable ([`knowledge list`](knowledge.md)) |
| `--containers` | the agent may run podman itself (containers inside its sandbox) |
| `--display` | your Wayland display and clipboard: watch the agent's browser window, paste images in `terminal`. The agent can read what you copy |

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
