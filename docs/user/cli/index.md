# Command line

`handler` is the command line client of `handlerd`, the daemon that runs your agents. The web UI
is where you set up projects, contexts and folders; the command line runs agents from a shell, an
editor or a script, and manages the rest. Each command has its own page, linked below;
`handler -h` and `handler <command> -h` print the same in short.

## How the commands are organised

- **Working with an agent** is a verb: `handler run`, `attach`, `terminal`, `acp`. These are the
  commands you type every day.
- **Everything you manage** is a noun followed by what to do with it: `handler session list`,
  `handler agent show ID`, `handler provider add …`. The same words come back everywhere: `list`,
  `show`, `add`, `rm`.
- **Handler itself**: `setup`, `daemon`, `ui`; `handler --version` prints the version installed,
  even when the daemon is down.

## Three ways to work with an agent

| | [`run`](run.md) | [`terminal`](terminal.md) | [`acp`](acp.md) |
|---|---|---|---|
| What you get | Handler's terminal client | the harness's own UI (Claude Code's, Codex's…) | the agent inside your editor (Zed) |
| A session, kept by the daemon | yes: survives the terminal, shown in the web UI and on your phone | no: gone when you exit | in a project: yes; elsewhere: no |
| Come back to it | [`attach`](attach.md), even once stopped | `--resume`, the harness's own | your editor's threads |

All three run the agent in its own container, seeing only its folder.

## Which agent runs: the folder decides

- **In a project's folder** (or below), commands use that project's agents with their settings:
  the one you name, or the one on the account you name, or the default agent.
- **Elsewhere**, name an account or a provider: Handler makes an *agent outside projects* for that
  folder, from a safe preset. The same command in the same folder finds the same agent again.

Projects are created in the web UI. [`project`](project.md) and [`agent`](agent.md) list
what exists.

## Rules every command follows

- **An option is never ignored.** When an [agent option](agent-options.md) differs from the
  agent's settings (`--network open` on a filtered agent), Handler says so and asks "Save this to
  the agent?". Yes saves it, no starts nothing. Without a terminal (an editor, a script): `--save`,
  else it is refused.
- **Contexts are enforced.** An account or provider not made for the project's context (a personal
  account in a *Work* project) is refused. `--anyway` runs it there outside the project, after you
  type `yes`: the only thing the command line can do that the web UI cannot.
- **What widens the sandbox is said.** `--network open`, `--log-only` and `--containers` are
  printed on stderr when the agent starts.

## I want to…

| | |
|---|---|
| install and start Handler | [`handler setup`](setup.md) |
| open the web UI | [`handler ui`](ui.md) |
| connect my Claude, ChatGPT or Mistral subscription | [`handler account add`](account.md) |
| use an API key or a local model | [`handler provider add`](provider.md) |
| ask an agent something in this folder | [`handler run`](run.md) |
| use one of a project's agents by name | [`handler run NAME`](run.md) |
| keep typing `claude`, but sandboxed | [`handler terminal`](terminal.md#your-command-sandboxed) |
| get back to a session, running or stopped | [`handler attach`](attach.md) |
| follow a session from my phone | [`handler session share`](session.md) |
| use an agent in Zed | [`handler acp`](acp.md) |
| give an agent a browser or the Shopify CLI | [`handler addon add`](addon.md), [`handler binding list`](binding.md) |
| find out why an agent cannot reach a host | [`handler agent network`](agent.md) |
| update Claude Code in the images | [`handler image rebuild`](image.md) |
| run something each time a session stops | [`handler automation`](automation.md) |

## Every command

**Working with an agent**

- [`run`](run.md): a session in the current folder
- [`attach`](attach.md): back to a session, running or stopped
- [`terminal`](terminal.md): the harness's own UI, sandboxed
- [`acp`](acp.md): an agent for your editor
- [Agent options](agent-options.md): what `run`, `terminal` and `acp` take to set up the agent

**What runs**

- [`session`](session.md) `list | show | stop | share`
- [`agent`](agent.md) `list | show | rm | network`
- [`project`](project.md) `list | show`

**Model access**

- [`account`](account.md) `list | add | token | login | import | rm`: subscriptions
- [`provider`](provider.md) `list | templates | add | rm`: API keys and local models
- [`secret`](secret.md) `list | set | rm`: the secret store

**What an agent can get**

- [`addon`](addon.md) `list | catalog | add | rm`
- [`binding`](binding.md) `list`: addons with their settings and secrets
- [`knowledge`](knowledge.md) `list`: knowledge folders

**Images, apps, automations**

- [`image`](image.md) `list | rebuild`
- [`app`](app.md) `list | add | deploy | rollback | open | shortcut | stop | log | secret | rm`
- [`automation`](automation.md) `list | examples | new | show | try | enable | disable | delete | runs | log | cancel`
- [`inbox`](inbox.md): what Handler told you

**Handler itself**

- [`setup`](setup.md): start the daemon, check the machine, build the images
- [`daemon`](daemon.md) `status | install | uninstall | log`
- [`ui`](ui.md): open the web UI

## Environment

| Variable | |
|---|---|
| `HANDLER_URL` | the daemon's address (default `http://127.0.0.1:<HANDLER_PORT>`) |
| `HANDLER_PORT` | its port, when `HANDLER_URL` is not set |
| `HANDLER_CONFIG_DIR` | where the UI's access token is read (default `~/.config/handler-ai`) |
| `HANDLER_ACP_CLIENT` | another terminal client for sessions, `{bridge}` standing for `handler attach --stdio <session>`: `HANDLER_ACP_CLIENT='toad acp "{bridge}"'` |
| `HANDLER_APP_BROWSER` | how [`app open`](app.md) opens an app: `firefox`, `chromium` or `default` |
