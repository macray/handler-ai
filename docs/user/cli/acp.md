# handler acp

Serve an agent to an editor over ACP (Agent Client Protocol), on stdin/stdout.

## When to use it

As the command of an agent server in an editor that speaks ACP, such as Zed: the editor shows
the conversation and diffs, the agent runs in its sandbox.

## Usage

```
handler acp AGENT|ACCOUNT|PROVIDER [FOLDER] [--anyway] [agent options]
```

- In a project's folder: a session of the project's agent (also shown in the web UI and on your
  phone).
- Elsewhere: an agent outside projects for that folder, one sandbox for this connection only.

## Options

| Option | |
|---|---|
| `FOLDER` | the folder (default: the current one, which is the editor's when it starts the command) |
| `--anyway` | in a project's folder, run outside the project; needs a terminal to type `yes`, so an editor cannot use it |
| agent options | [agent options](agent-options.md); there is no terminal to confirm a change, so add `--save` or it is refused |

## Example

In `~/.config/zed/settings.json` (the full path of `handler`: `which handler`):

```json
{ "agent_servers": { "handler · claude-perso": {
    "type": "custom",
    "command": "/home/you/.local/bin/handler",
    "args": ["acp", "claude-perso"]
} } }
```

More in [getting started](../getting-started.md#5-from-an-editor-zed).

## See also

[`run`](run.md) · [`terminal`](terminal.md) · [agent options](agent-options.md)
