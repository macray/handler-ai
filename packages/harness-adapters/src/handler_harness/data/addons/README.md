# Built-in addons (data)

One directory per addon: a tool, skills and the slots an agent needs to use a kind of system,
without growing the toolbox (design: `docs/dev/design/addons.md`; contract: `docs/dev/contracts.md` §G).

```
addons/<name>/
├── addon.toml        manifest, contract G.1 (handler.addon/v1) — validated by handler_contracts
├── Containerfile     the tool image: built in the toolbox, shipped FROM scratch (only with `image`)
├── skills/<skill>/   skills (each with a SKILL.md), mounted read-only in the harness's skills folder
└── PROVISIONING.md   how to create the least-privilege account a binding needs
```

An addon is generic. To use one, write a **binding** in `~/.config/handler-ai/bindings/<name>.toml`
(`handler.binding/v1`: the addon, its settings, secret references; example in `examples/bindings/`)
and give it to an agent (web UI: **Tools** in its form; CLI: `--binding NAME` for an ad-hoc agent).

Built in (always loaded: the web UI's Apps page needs it):

| Addon | Image | Commands | Slots |
|---|---|---|---|
| `app-builder` | none (Bun is in the toolbox) | none | none: writes apps (`docs/dev/design/apps.md`) with its skill and template |

The others are in the catalog (`../catalog/`, contract G.5): shipped with Handler, loaded only once the
user installs them. Installing and writing addons, for users: `docs/user/addons.md`.

How an agent gets it (G.4): the image is mounted read-only at `/opt/addons/<name>` (pinned to the
image id when the agent starts), its `bin/` is **appended** to `PATH` (the toolbox's commands
win), its env, settings and secrets go to the env, its egress to the allow-list, its skills next to
the agent's and its project's, its MCP server (`[mcp]`) to every session of the agent.

Images and updates (contract G.4, same as harness images):
- `addon.toml` names the image without a tag; agents mount `:latest`.
- Build or update: `handler image rebuild addon:<name>` or **Rebuild** in the web UI (Settings → Images). The
  daemon builds an untagged image, checks it (mounted into the toolbox, no network: `bin/` holds exactly
  `commands`, none of them is already in the toolbox, `version` is readable, `check` exits 0), then
  tags it `:latest`. A toolbox rebuild also
  rebuilds every addon image already built.
- Each `Containerfile` writes one line to `/opt/addons/<name>/version`, and fails the build if it
  cannot.

A new addon goes in the catalog (`../catalog/<name>/`), not here, unless Handler itself needs it
loaded. Writing one: `docs/user/addons.md` (no checkout needed: an addon of the user's folder works the
same).
