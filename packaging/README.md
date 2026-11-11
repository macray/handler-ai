# Handler

**Handler**: every agent needs one.

Run coding agents in containers on your Linux machine. Each agent (Claude Code, Codex, Mistral
Vibe or pi) runs in its own rootless Podman container that sees only its project folder and reaches
only the hosts you allow. A daemon keeps the sessions, which you follow from a web UI, the
terminal, your editor (over ACP) or your phone.

## Install

**You need:** Linux with rootless Podman, `passt` and a systemd user session, and about 3 GB of
disk for the images, built on your machine.

```bash
uv tool install handler-ai   # or: pipx install handler-ai
handler setup                # starts handlerd as a user service, checks this machine, builds the images
handler ui                   # opens the web UI
```

The first `handler setup` downloads and builds the images, the toolbox and the agent program you
choose: about 1 GB, from a minute to a quarter of an hour.
Without uv: `curl -fsSL https://github.com/macray/handler-ai/releases/latest/download/install.sh | sh`
installs it, then Handler. To update: `uv tool upgrade handler-ai`.

## More

- [README](https://github.com/macray/handler-ai#readme): what Handler does, compared with other
  sandboxes, and a first session.
- [Documentation](https://macray.github.io/handler-ai/)
- [Changelog](https://github.com/macray/handler-ai/blob/main/CHANGELOG.md) ·
  [Issues](https://github.com/macray/handler-ai/issues)
