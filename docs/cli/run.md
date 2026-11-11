# handler run

Start a session with an agent in the current folder, and talk to it in this terminal.

## When to use it

- Everyday work from a shell: ask something about the repository you are in, give it a task.
- A project with several agents (a *dev*, a *reviewer*): name the one you want.
- A one-shot request, or from a script: `handler run reviewer -p "…" --detach`.
- A folder that is not a project yet: name an account or a provider and Handler makes an agent for
  this folder.

The session is held by the daemon: closing the terminal does not stop it, and the web UI and a
paired phone show the same session.

## Usage

```
handler run [AGENT|ACCOUNT|PROVIDER] [-p REQUEST] [--remote] [--detach] [--anyway] [agent options]
```

Which agent runs:

- **In a project's folder** (or below): the project's agent named AGENT
  ([`project show`](project.md) lists them), or the one that uses ACCOUNT or PROVIDER (the default
  agent first). If none does, the default agent, on that account for this session only. No name:
  the default agent, on its own model.
- **Elsewhere**: the folder's agent outside projects, made the first time with the flags you
  typed. No name: the only account or provider that is ready; when there are several, it lists
  them and starts nothing.

## Options

| Option | |
|---|---|
| `AGENT\|ACCOUNT\|PROVIDER` | the project's agent to run, or what the model calls go through (for this session only) |
| `-p`, `--prompt REQUEST` | the first request, sent as the session starts (after the agent's instructions) |
| `--detach` | start the session and give the shell back; `handler attach` to join it |
| `--remote` | share the session with your paired phone ([`session share`](session.md) does it later) |
| `--anyway` | in a project's folder, run outside the project: the way to use an account its area does not allow. Asks you to type `yes` |
| agent options | network, tools, permissions… ([agent options](agent-options.md)) |

## Examples

```bash
cd ~/code/my-app
handler run                                        # the project's default agent
handler run reviewer -p "review the last commit"   # the project's agent named reviewer
handler run claude-work                            # the project's agent on claude-work

cd ~/code/scratch
handler run claude-perso -p "what does this repository do?"
handler run claude-perso --network open            # asks: save this to the agent?
handler run local-llama --harness pi --model qwen3 # a provider: which harness, which model
handler run claude-perso --name experiment --containers  # a second agent for this folder
```

## Good to know

- It prints the session's id and its link in the web UI.
- In the session: Ctrl-C cancels the current turn (or detaches when idle), Ctrl-D detaches.
- A flag that differs from the agent's settings is saved to the agent once you say yes, in a
  project too: that agent keeps it for every later session. To try something once, use `--name`
  for another agent (outside projects only).
- `HANDLER_ACP_CLIENT` replaces the built-in terminal client ([environment](index.md#environment)).

## See also

[`attach`](attach.md) · [`session`](session.md) · [`terminal`](terminal.md) (the harness's own
UI instead) · [agent options](agent-options.md)
