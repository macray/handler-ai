# handler project

List projects and see their agents.

## When to use it

- To find an agent's name for `handler run NAME` or `handler terminal NAME`.
- To see at a glance what each agent of a project runs on and how it is contained.

A project is a folder and its agents. Projects are created and edited in the web UI; in a
project's folder, [`run`](run.md), [`terminal`](terminal.md) and [`acp`](acp.md) use its agents.

## Usage

```
handler project list
handler project show NAME
```

## Subcommands

| Subcommand | |
|---|---|
| `list` | projects, most recently used first: name, context (Work, Personal…), agents, folder |
| `show NAME` | the project's agents: name (`*`: the default agent), id, what it runs on (harness · account or provider · model), its settings, live sandboxes |

## Example

```bash
handler project show shop
cd ~/code/shop && handler run review -p "review the last commit"
```

## See also

[`agent`](agent.md) · [`run`](run.md)
