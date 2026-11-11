# handler runtime

See or change the container runtime your agents run in.

## When to use it

- To see what keeps a sandbox from your computer here: a container sharing your kernel, a
  virtual machine…
- After installing another runtime, to use it instead.

## Usage

```
handler runtime list
handler runtime use NAME
```

Handler runs agents with one runtime at a time: **podman** on Linux and **apple** on a Mac,
unless you choose another ([`handler setup`](setup.md) asks on a Mac). A runtime is
installed with Handler as a `handler-sandbox-<name>` program; `list` shows those it finds:

- `podman`: rootless Podman containers (Linux, WSL 2). Not offered on a Mac.
- `docker`: Docker containers: a rootful Docker Engine on Linux (its `check` warns that an agent
  escaping its sandbox would be root on your computer, and privileged sandboxes are not given),
  or Docker Desktop, OrbStack, Colima (each sandbox in Docker's virtual machine; windows on your
  screen, apps and automations whose scripts call models are not available there). A rootless
  Docker on Linux is refused: what agents write would not be yours. Handler builds its images
  with Docker's **buildx** plugin, which its check requires: Docker's own packages install it
  (`docker-buildx-plugin`), Docker Desktop and OrbStack have it, but some distributions' `docker`
  does not pull it (on Arch: `pacman -S docker-buildx`). Build the images again after switching
  to it.
- `apple`: Apple's `container` on macOS 26 (Apple silicon), a virtual machine per sandbox.
  **Experimental**: agents that run containers, privileged sandboxes and windows on your screen
  are not available there yet ([known limitations](../known-limitations.md)). Offered on macOS
  only: elsewhere `list` does not show it, and `use apple` answers that it is for macOS.

## Subcommands

| Subcommand | |
|---|---|
| `list` | the runtimes installed, the one in use marked, then what it gives on this computer: what each sandbox is, and what it does not give here (sandboxes that run containers, privileged sandboxes, windows on your screen; memory and CPU limits not applied); when it cannot run sandboxes here, what is missing and how to fix it |
| `use NAME` | use runtime NAME from now on, also after restarts, then print what it gives here (as `list`). Refused while agents, apps or an image build run. Each runtime has its own images: Handler builds at once the network filter and the tools' images your agents use when that runtime lacks them; build the toolbox and the agent programs again there (Settings → Expert → Sandboxes, [`handler image`](image.md)) |

The web UI shows the same in Settings → Expert → Sandboxes.
