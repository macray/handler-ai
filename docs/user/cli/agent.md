# handler agent

List, inspect and delete agents, and watch or switch an agent's network.

## When to use it

- To find an agent's id, or see how each agent is contained.
- To clean up agents made outside projects in folders you no longer use.
- When an agent fails on blocked hosts: see what it reached, or let everything through for a
  while to learn what it needs.

Agents of projects are created and edited in the web UI. Agents outside projects are made by
[`run`](run.md), [`terminal`](terminal.md) and [`acp`](acp.md) in a folder.

## Usage

```
handler agent list
handler agent show ID
handler agent rm ID
handler agent network ID [log-only|enforce]
```

## Subcommands

| Subcommand | |
|---|---|
| `list` | every agent, most recently used first: id, project (`(ad hoc)` outside projects), name, what it runs on, its settings (what differs from the defaults), live sandboxes, folder |
| `show ID` | its settings in full: folder, models, network and hosts, permissions, bindings, knowledge, skills, containers, display, live sandboxes |
| `rm ID` | delete an agent outside projects and stop its sandboxes. The next `handler run` in that folder starts from the preset again. A project's agents are removed in the web UI |
| `network ID` | its network mode, its own hosts, and its recent connections |
| `network ID log-only` | a filtered agent: every host goes through and is logged, live, while it works |
| `network ID enforce` | back to blocking what is not allowed |

## Connections

`handler agent network ID` lists one line per event: time, decision, host, connection.

| Decision | |
|---|---|
| `allowed` | an allowed host |
| `denied` | blocked: not allowed |
| `unlisted` | in `log-only`: let through, but enforcing would block it. These are the hosts to allow |
| `injected` | Handler added one of your secrets to a request to that host (the agent only has a stand-in) |
| `leak` | a secret's stand-in sent to a host it is not for: refused |

## Learning what an agent needs

The web UI's *Learn hosts* does the same:

```bash
handler agent network a_12… log-only    # every host goes through, logged
# … let the agent do its task …
handler agent network a_12…             # the `unlisted` lines: the hosts to allow
handler agent network a_12… enforce
```

Allow them in the session's network panel, or with `--allow HOST:PORT` on the next `run`.

## See also

[`project`](project.md) · [agent options](agent-options.md#network)
