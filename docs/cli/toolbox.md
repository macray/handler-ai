# handler toolbox

What every agent's system is made of, and change it.

## When to use it

- An agent needs a compiler, a browser or podman: `handler toolbox add gcc`.
- Agents that run containers should use Docker rather than Podman: `handler toolbox add docker`,
  then `handler toolbox rm podman`.
- To see what Handler and your agents need from the toolbox, and what gives it.
- A tool no system package gives: `handler toolbox lines`, then `handler image rebuild toolbox`.

## Usage

```
handler toolbox
handler toolbox packages
handler toolbox add PACKAGE… [--verbose]
handler toolbox rm PACKAGE… [--verbose]
handler toolbox lines
```

The **toolbox** is the system every agent works in, the same for all of them. Handler builds it
from three parts: its own base (Fedora, with `git`, `curl`, Python and uv, Node and npm, the
usual command-line tools), the **system packages** you turn on (`podman` and `wl-clipboard` by
default: what agents that run containers or show windows need; `docker` instead of podman, `gcc`,
`chromium`; yours in
`~/.config/handler-ai/system-packages/`, and those installed with a tool from its source), and
your own lines (`~/.config/handler-ai/toolbox/custom.containerfile`), added last. Installing a
tool or saving an agent that needs one says so, and adds it once you agree. A system package's
install script runs as root when the toolbox is built, and every agent gets what it installs.
With `docker`, each sandbox of an agent that runs containers starts its own Docker daemon before
the agent (about half a second and 200 MB), reached through `DOCKER_HOST`; its images are that
sandbox's own, pulled again by the next one.

## Subcommands

| Subcommand | |
|---|---|
| (none) | the system packages on, who needs each; what Handler, the agent programs and your agents need from the toolbox, and what gives each |
| `packages` | every system package you can turn on: Handler's and yours (`~/.config/handler-ai/system-packages/`) |
| `add PACKAGE…` | turn system packages on (with those they need), then build the toolbox |
| `rm PACKAGE…` | turn them off, then build the toolbox; refused while one is the only thing giving what an agent needs |
| `lines` | edit your lines in `$EDITOR`; saved, not built: `handler image rebuild toolbox` builds them |

Building the toolbox also rebuilds and checks every agent program and tool image already built
on it: all switch, or none, and a toolbox lacking what is needed (podman for an agent that runs
containers) does not switch. It prints one line per image and writes the full log to a file it names
(`--verbose`: on the terminal); Ctrl-C cancels it.

## See also

[`image`](image.md) · [`setup`](setup.md) · Settings → Expert → Sandboxes in the web UI
