# handler session

List, inspect, stop and share sessions: conversations with an agent, each in its own sandbox,
held by the daemon.

## When to use it

- To find a session's id for [`attach`](attach.md), or see which agents are working or waiting
  for you.
- To stop a session you are done with, freeing its sandbox; its conversation is kept.
- To share a running session with your phone after it started.

Sessions are started with [`run`](run.md) (or in the web UI, on your phone, by an automation, by
one of your apps). A job's run waiting for the agent's other run says `waiting`.

## Usage

```
handler session list [--all]
handler session show SESSION
handler session stop SESSION
handler session share SESSION [--off]
```

## Subcommands

| Subcommand | |
|---|---|
| `list` | running sessions, most recently active first: id, state (`starting`, `running`, `working`, `needs you` when it waits for your answer), project and agent, title, folder. `--all`: stopped ones too |
| `show SESSION` | what it runs on, its folder, when it started and from where, how many clients are attached, whether it is shared, how to resume it once stopped, its link in the web UI |
| `stop SESSION` | stop its sandbox. The conversation and the folder stay: [`attach`](attach.md) resumes it |
| `share SESSION` | share a running session with your paired devices (as `run --remote`); `--off` stops sharing. Sharing ends when the session stops |

## Examples

```bash
handler session list
handler session show s_4f2a…
handler session share s_4f2a…        # follow it from your phone
handler session stop s_4f2a…
handler attach s_4f2a…               # later: restarted with its conversation
```

## See also

[`attach`](attach.md) · [`run`](run.md) · [phone](../phone.md)
