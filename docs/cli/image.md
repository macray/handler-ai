# handler image

List the images agents run in, and rebuild one.

## When to use it

- A new Claude Code or Codex release: `handler image rebuild claude-code`.
- System updates in every image: `handler image rebuild toolbox --update`.
- After editing a tool, or your toolbox's lines ([`handler toolbox`](toolbox.md)).
- To see which version of a harness your agents get, or whether an image is not built.

## Usage

```
handler image list
handler image rebuild NAME | tool:NAME | toolbox [--update] | network-filter [--verbose]
```

The images are built on this machine: the **toolbox** (the system every agent works in, [`handler toolbox`](toolbox.md)),
one image per harness and per tool on top of it, and the **network filter** (the proxy that
checks where agents connect and adds your secrets to their requests).

## Subcommands

| Subcommand | |
|---|---|
| `list` | every image: name, image reference, the harness's version (or `not built`), when it was built |
| `rebuild NAME` | one agent program's image (`claude-code`, `codex`, `vibe`, `pi`), with its latest release; also its first build |
| `rebuild tool:NAME` | a tool's image (also its first build) |
| `rebuild toolbox` | the toolbox with what changed in it (system packages turned on or off, your lines), then every agent program and tool image already built on top of it: all switch, or none |
| `rebuild toolbox --update` | the same with the system's updates: everything downloaded and built again |
| `rebuild network-filter` | the network filter; the daemon builds it itself when it is missing |

A rebuild checks the new image, then switches agents to it. It prints one line per image with a
time estimate (`toolbox 1/2 · ~3 min`) and writes the full log to a file it names; `--verbose`
streams the log to the terminal instead. Ctrl-C cancels and nothing switches. Running sessions keep the image they started on.

## See also

[`toolbox`](toolbox.md) · [`tool`](tool.md) · [`setup`](setup.md)
