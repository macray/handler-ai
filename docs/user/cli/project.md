# handler project

List projects, see their agents, and move agents from one project to another as a file.

## When to use it

- To find an agent's name for `handler run NAME` or `handler terminal NAME`.
- To see at a glance what each agent of a project runs on and how it is contained.
- To give a project's agents to another project, here or on another computer, or to someone:
  export them as a file, then import it.

A project is a folder and its agents. Projects are created and edited in the web UI; in a
project's folder, [`run`](run.md), [`terminal`](terminal.md) and [`acp`](acp.md) use its agents.

## Usage

```
handler project list
handler project show NAME
handler project export-agents NAME [--agent AGENT]... [-o FILE]
handler project import-agents FILE
handler project import-agents NAME --from SOURCE
```

## Subcommands

| Subcommand | |
|---|---|
| `list` | projects, most recently used first: name, area (Work, Personal…), agents, folder |
| `show NAME` | the project's agents: name (`*`: the default agent), id, what it runs on (harness · account or provider · model), its settings, live sandboxes |
| `export-agents NAME` | the project's agents (all, or those named with `--agent`) as one file, `NAME-agents.zip` (`-o`: another name): their names, instructions, form, settings, skills and checks. Never in it: the accounts or providers they run on, the folder, addon configurations, knowledge folders, conversations. Says what of yours it left out |
| `import-agents FILE` (or `NAME --from SOURCE`: agents a [source](source.md) offers) | reads the file and prints the address of the web UI's page where its agents are set up: where (a project), each one's model, what each will be allowed to do. The agents made are yours: nothing follows the file afterwards |

## Example

```bash
handler project show shop
cd ~/code/shop && handler run review -p "review the last commit"
handler project export-agents shop --agent review -o review.zip
handler project import-agents review.zip
```

## See also

[`agent`](agent.md) · [`run`](run.md)
