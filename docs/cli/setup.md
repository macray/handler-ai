# handler setup

Turn an installed `handler` into a working one: start the daemon, check the machine, build the
images.

## When to use it

- Right after installing.
- Whenever something seems wrong: it is safe to run again, and says what the machine lacks.

## Usage

```
handler setup [--no-build] [--yes] [--program NAME] [--runtime NAME] [--engine podman|docker] [--verbose]
```

It goes through, in order:

1. installs `handlerd` as a user service and starts it (systemd; launchd on macOS) ([`daemon install`](daemon.md));
2. on a Mac, before the images are first built: asks where agents run, when more than one can run
   them there: Apple's `container` (the default, each sandbox a virtual machine of its own) and
   Docker (Docker Desktop or OrbStack, when it runs), each with what a sandbox is there. Enter
   keeps the one in use. Each builds its own images; change it later with
   [`handler runtime use`](runtime.md). On Linux, agents run in Podman unless you choose another;
3. checks the machine for that runtime (rootless Podman, `passt`…; with Docker, its `buildx`
   plugin, which Docker's packages install as `docker-buildx-plugin` but Arch's `docker` does not
   pull: `pacman -S docker-buildx`): fix each `FAIL` line, then run it again. A
   `warn` line names what only some agents need (fewer subordinate ids than 65535: agents that run
   containers, and apps), and setup goes on;
4. builds the network filter if it is missing (about 240 MB, a minute or two);
5. builds the images if the toolbox or no agent program is built yet: first asks which
   engine agents that run containers use, Podman (the default) or Docker, and which agent program
   you want first (Claude Code, Codex, pi or Mistral Vibe); then the toolbox and that program
   only: about 1 GB, from a minute on a fast network to a quarter of an hour on a slow one. It
   prints one line per image with a time estimate, `toolbox 1/2 · ~3 min`, and writes the full log
   to a file it names. Each other agent program is built the first time an agent needs it (the
   session's *Prepare now*), or in Settings → Expert → Sandboxes (`handler image rebuild NAME`);
6. prints where the web UI is.

Without a systemd user session (a server, `su`, a container, WSL without systemd), systemd only
keeps `handlerd` running for you: start `handlerd` yourself and keep it running (sessions live as
long as it does). `handler setup` then goes on with the one running; when none runs, it starts
one for the machine check only, and stops it after.

## Options

| Option | |
|---|---|
| `--no-build` | skip the images; build them later with `handler setup` again |
| `--yes` | build the images without asking (the runtime in use, unless `--runtime`; Podman for agents that run containers, unless `--engine`; Claude Code, unless `--program`) |
| `--program NAME` | the agent program to build first: `claude-code`, `codex`, `pi` or `vibe`. Used while no agent program is built yet; later, [`handler image rebuild NAME`](image.md) builds another |
| `--runtime NAME` | where agents run, chosen without asking: `apple` or `docker` on a Mac, `podman` or `docker` on Linux (`handler runtime list` names them; Docker needs its buildx plugin, [runtime](runtime.md)) |
| `--engine podman\|docker` | what agents that run containers use inside their sandbox (not where they run: `--runtime`), chosen before the first build; later, `handler toolbox add docker` and `rm podman` (or the reverse) |
| `--verbose` | the build's full log on the terminal, instead of one line per image |

## See also

[`daemon`](daemon.md) · [`image`](image.md) · [`ui`](ui.md)
