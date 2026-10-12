# handler addon

List, install and remove addons: a tool for the agent's sandbox (Playwright's browser, the Shopify
CLI) with the hosts, secrets and skills it needs.

## When to use it

- To see what you can give an agent besides its folder, and whether an update is available.
- To add an addon from Handler's catalog (Playwright for a browser, the Shopify CLI).
- To install an addon you wrote, from a folder or an archive.
- To update an installed addon.

## Usage

```
handler addon list
handler addon catalog
handler addon add NAME|FOLDER|URL [--yes]
handler addon rm NAME
```

## Subcommands

| Subcommand | |
|---|---|
| `list` | the installed addons: where they come from (built-in, the catalog, a folder; `update: handler addon add NAME` when the catalog has a newer one), their commands, image version, the settings and secrets they need, errors |
| `catalog` | the addons Handler ships, installed or not |
| `add SOURCE` | show what it brings (hosts, secrets, commands, MCP server, skills), then, once you agree, install it and build its image. SOURCE: a catalog name, a folder, or an `https://` `.tar.gz`. On an installed addon: updates it |
| `rm NAME` | remove it; refused while a binding uses it |

| Option | |
|---|---|
| `--yes` | `add` without asking |

## Examples

```bash
handler addon list
handler addon catalog
handler addon add playwright
cp examples/bindings/browser.toml ~/.config/handler-ai/bindings/    # its binding
cd ~/code/my-site && handler run claude-perso --binding browser --display
```

## See also

[`binding`](binding.md) · [`image`](image.md) · [addons guide](../addons.md) ·
[writing an addon](../addons.md#writing-one)
