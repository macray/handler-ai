# handler image

List the images agents run in, and rebuild one.

## When to use it

- A new Claude Code or Codex release: `handler image rebuild claude-code`.
- System updates in every image: `handler image rebuild toolbox`.
- After editing an addon or the toolbox's files.
- To see which version of a harness your agents get, or whether an image is not built.

## Usage

```
handler image list
handler image rebuild NAME | addon:NAME | toolbox | network-filter
```

The images are built on this machine: the **toolbox** (the base every agent gets, with its tools),
one image per harness and per addon on top of it, and the **network filter** (the proxy that
checks where agents connect and adds your secrets to their requests).

## Subcommands

| Subcommand | |
|---|---|
| `list` | every image: name, image reference, the harness's version (or `not built`), when it was built |
| `rebuild NAME` | one harness's image (`claude-code`, `codex`, `vibe`, `pi`), with the harness's latest release |
| `rebuild addon:NAME` | an addon's image (also its first build) |
| `rebuild toolbox` | the toolbox (system packages, your `~/.config/handler-ai/toolbox/`), then every harness and addon image on top of it: all switch, or none |
| `rebuild network-filter` | the network filter; the daemon builds it itself when it is missing |

A rebuild checks the new image, then switches agents to it. The log streams to the terminal;
Ctrl-C cancels and nothing switches. Running sessions keep the image they started on.

## See also

[`addon`](addon.md) · [`setup`](setup.md)
