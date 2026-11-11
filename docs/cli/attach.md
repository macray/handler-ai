# handler attach

Come back to a session in this terminal: join it while it runs, or resume it once it stopped.

## When to use it

- After detaching (Ctrl-D, `--detach`) or closing the terminal: the session kept running.
- To continue in the terminal a session started in the web UI, on your phone, or by an automation.
- To pick up a conversation that stopped (idle, `handler session stop`, the daemon restarted):
  it is restarted with its conversation.
- `--stdio`: to drive a session from another ACP client.

## Usage

```
handler attach [SESSION] [--stdio]
```

SESSION is an id from [`handler session list --all`](session.md). Without it: the most recently
active session whose folder is the current one (not a parent), running ones first.

A **running** session is joined: the agent may have kept working meanwhile. A **stopped** one is
resumed: a new sandbox starts and the agent reloads the conversation. That needs a harness that
can reload one, and the agent still set up as it was (same folder, same account or provider);
`handler session show` says whether it can.

## Options

| Option | |
|---|---|
| `--stdio` | the session as a plain ACP agent on stdin/stdout, for another client (no terminal UI) |

## Examples

```bash
cd ~/code/my-app && handler attach     # the last session in this folder
handler session list --all             # find an id
handler attach s_4f2a…
```

## Good to know

Several clients can be attached at once (this terminal, a browser tab, your phone): they all see
the same conversation and any of them can send a request. In the session, Ctrl-D detaches and
`/stop` stops it.

## See also

[`session`](session.md) · [`run`](run.md)
