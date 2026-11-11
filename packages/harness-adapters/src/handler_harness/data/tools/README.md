# Built-in tools (data)

One directory per tool: programs, skills and the slots an agent needs to use a kind of system,
without growing the toolbox (contract G; every key of `tool.toml`:
`schemas/handler.tool.v1.schema.json`). In the code a tool is an `Addon`.

```
tools/<name>/
├── tool.toml         manifest, contract G.1 (handler.tool/v1) — validated by handler_contracts
├── Containerfile     the tool's image: built in the toolbox, shipped FROM scratch (only with `image`)
├── skills/<skill>/   skills (each with a SKILL.md), mounted read-only in the harness's skills folder
└── PROVISIONING.md   how to create the least-privilege account a connection needs
```

A tool is generic. To use one that has settings, write a **connection** in
`~/.config/handler-ai/connections/<name>.toml` (`handler.connection/v1`: the tool, its settings,
secret references; example in `docs/cli/connection.md`) and give it to an agent (web UI: **Tools**
in its form; CLI: `--tool NAME=CONNECTION`).

Built in (always loaded: the web UI's Apps page needs it):

| Tool | Image | Commands | Slots |
|---|---|---|---|
| `app-builder` | none (Bun is in the toolbox) | none | none: writes apps with its skill and template |

The others come from a source (contract D.26, G.5), loaded only once the user installs them.
Installing and writing tools, for users: `docs/tools.md`.

How an agent gets it (G.4): the image is mounted read-only at `/opt/tools/<name>` (pinned to the
image id when the agent starts), its `bin/` is **appended** to `PATH` (the toolbox's commands
win), its env, settings and secrets go to the env, its egress to the allow-list, its skills next to
the agent's and its project's, its MCP server (`[mcp]`) to every session of the agent.

Images and updates (contract G.4, same as harness images):
- `tool.toml` names the image without a tag; agents mount `:latest`.
- Build or update: `handler image rebuild tool:<name>` or **Rebuild** in the web UI (Settings →
  Expert → Sandboxes). The daemon builds an untagged image, checks it (mounted into the toolbox, no
  network: `bin/` holds exactly `commands`, none of them is already in the toolbox, every command
  of `needs` is, `version` is readable, `check` exits 0), then tags it `:latest`. A toolbox
  rebuild also rebuilds every tool image already built.
- Each `Containerfile` writes one line to `/opt/tools/<name>/version`, and fails the build if it
  cannot.

A new tool goes in a source, not here, unless Handler itself needs it loaded. Writing one:
`docs/tools.md` (no checkout needed: a tool of the user's folder works the same).
