# handler source

The git repositories Handler reads to offer apps, agents and tools: Handler's own, and any you
add. See [sources](../sources.md).

## When to use it

- To see what you can install, and whether something you installed has an update.
- To install from someone else's repository: add it first, then install from it.

## Usage

```
handler source list
handler source add URL [--yes]
handler source refresh [ID]
handler source rm ID
```

## Subcommands

| Subcommand | |
|---|---|
| `list` | each source (its id, address, whether it is Handler's, when it was read) and what it offers: kind, name, version, installed, an update, or why one is not offered |
| `add URL` | an `https://` git repository: says that Handler does not check what is in it and asks first, then reads it; it must have a `handler-source.toml` at its root |
| `refresh [ID]` | read it again (all of them without ID) |
| `rm ID` | remove a source you added; what you installed from it stays. Handler's cannot be removed |

| Option | |
|---|---|
| `--yes` | `add` without asking |

Install what a source offers with the command of its kind:
`handler app add NAME --from ID`, `handler tool add NAME --from ID`,
`handler project import-agents NAME --from ID` (ID `official`: Handler's).

## Examples

```bash
handler source list
handler source add https://github.com/acme/handler-tools
handler tool add notes --from handler-tools
handler source rm handler-tools
```

## See also

[`app`](app.md) · [`tool`](tool.md) · [`project`](project.md) · [sources](../sources.md)
