# handler tool

List, install and remove tools: programs for the agent's sandbox (Playwright's browser, the GitHub
CLI) with the hosts, secrets and skills it needs.

## When to use it

- To see what you can give an agent besides its folder, and whether an update is available.
- To add a tool a [source](source.md) offers (Handler's offers Playwright for a browser, among others).
- To install a tool you wrote, from a folder or an archive.
- To update an installed tool.

## Usage

```
handler tool list
handler tool add NAME|FOLDER|URL [--from SOURCE] [--yes] [--verbose]
handler tool rm NAME
```

## Subcommands

| Subcommand | |
|---|---|
| `list` | the installed tools: where they come from (built-in, `source:SOURCE/NAME`, a folder; `update: handler tool add NAME --from SOURCE` when its source has a newer one), their commands, their state (`ready`, `preparing`, `failed`, `installed`: not ready, and why), image version, the settings and secrets they need, errors |
| `add NAME\|FOLDER\|URL` | show what it brings (hosts, secrets, commands, MCP server, skills, what it uses from the toolbox, the system packages it adds there and what nothing gives), then, once you agree, install it: the toolbox rebuilt first when it adds system packages, then its image. NAME: a tool a source offers (`handler source list`), Handler's unless `--from` says another; or a folder, or an `https://` `.tar.gz`. On an installed tool: updates it |
| `rm NAME` | remove it; refused while an agent, a project or a connection uses it |

| Option | |
|---|---|
| `--from SOURCE` | `add` NAME from that source (its id in `handler source list`) |
| `--yes` | `add` without asking |
| `--verbose` | `add`: the build's full log on the terminal, instead of one line per image and the log in a file |

## Examples

```bash
handler tool list
handler source list                       # what the sources offer
handler tool add playwright
# its connection: Library → Tools → playwright → Connect, named browser
cd ~/code/my-site && handler run claude-perso --tool playwright=browser --display
```

## See also

[`connection`](connection.md) · [`source`](source.md) · [`image`](image.md) · [tools guide](../tools.md) ·
[writing a tool](../tools.md#writing-one)
