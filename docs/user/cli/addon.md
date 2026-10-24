# handler addon

List, install and remove addons: a tool for the agent's sandbox (Playwright's browser, the Shopify
CLI) with the hosts, secrets and skills it needs.

## When to use it

- To see what you can give an agent besides its folder, and whether an update is available.
- To add an addon a [source](source.md) offers (Handler's: Playwright for a browser, the Shopify CLI).
- To install an addon you wrote, from a folder or an archive.
- To update an installed addon.

## Usage

```
handler addon list
handler addon add NAME|FOLDER|URL [--from SOURCE] [--yes]
handler addon rm NAME
```

## Subcommands

| Subcommand | |
|---|---|
| `list` | the installed addons: where they come from (built-in, `source:SOURCE/NAME`, a folder; `update: handler addon add NAME --from SOURCE` when its source has a newer one), their commands, image version, the settings and secrets they need, errors |
| `add NAME\|FOLDER\|URL` | show what it brings (hosts, secrets, commands, MCP server, skills), then, once you agree, install it and build its image. NAME: an addon a source offers (`handler source list`), Handler's unless `--from` says another; or a folder, or an `https://` `.tar.gz`. On an installed addon: updates it |
| `rm NAME` | remove it; refused while a binding uses it |

| Option | |
|---|---|
| `--from SOURCE` | `add` NAME from that source (its id in `handler source list`) |
| `--yes` | `add` without asking |

## Examples

```bash
handler addon list
handler source list                       # what the sources offer
handler addon add playwright
cp examples/bindings/browser.toml ~/.config/handler-ai/bindings/    # its binding
cd ~/code/my-site && handler run claude-perso --binding browser --display
```

## See also

[`binding`](binding.md) · [`source`](source.md) · [`image`](image.md) · [addons guide](../addons.md) ·
[writing an addon](../addons.md#writing-one)
