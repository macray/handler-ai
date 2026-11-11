# handler automation

Create, try, turn on and follow an automation: when a session stops or at a time you set,
Handler runs your script in a sandbox, one of your agents, or a route of one of your apps.

## When to use it

- To see what runs on its own: which automations are on, when, how their last run went.
- To start an automation from an example Handler ships.
- To try it on a real session before turning it on.
- To follow its runs, read a script's output, stop a run.

Each automation is a folder, `~/.config/handler-ai/automations/<name>/` (`automation.toml` and its
scripts): you edit its files in your editor. A script may call the models you chose, and what it
writes is added to a note; an agent's result goes to your [inbox](inbox.md).

## Usage

```
handler automation list
handler automation examples
handler automation new NAME --from EXAMPLE
handler automation show NAME
handler automation try NAME [--session ID|last]
handler automation enable NAME [--yes]
handler automation disable NAME
handler automation delete NAME [--yes]
handler automation runs NAME
handler automation log RUN
handler automation cancel RUN
```

## Subcommands

| Subcommand | |
|---|---|
| `list` | every automation: on or off, when it runs, what it runs, its last run, its problems |
| `examples` | the examples Handler ships |
| `new NAME --from EXAMPLE` | copy an example into a new automation, turned off |
| `show NAME` | what it may touch, its files, its problems, its next run |
| `try NAME` | run it now, on or off. One that runs when a session stops runs on a session's whole conversation: `--session ID`, or `last` (the default: the session that stopped last). A script's try adds nothing to the note |
| `enable NAME` | turn it on: shows what it may touch and asks first; `--yes` does not ask |
| `disable NAME` | turn it off |
| `delete NAME` | delete its folder and its runs; asks first, `--yes` does not |
| `runs NAME` | its runs, most recent first, with their ids |
| `log RUN` | a script run's output |
| `cancel RUN` | stop a run |

## Example

```bash
handler automation examples
handler automation new env-issues --from env-issues
$EDITOR ~/.config/handler-ai/automations/env-issues/automation.toml
handler automation try env-issues          # on the session that stopped last
handler automation enable env-issues
handler automation runs env-issues
```

## See also

[`inbox`](inbox.md) · [automations guide](../automations.md)
