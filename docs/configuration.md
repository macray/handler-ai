# Where things are kept

Everything you set up in the web UI or with `handler` ends up in a few folders of your home. Most
are plain TOML you can read, back up, or write by hand from the [examples](../examples);
unknown keys are errors, so a typo never goes unnoticed. What each thing is:
[concepts](concepts.md).

| What | What it answers | Where | Changed from |
|---|---|---|---|
| **Account** | *whose* subscription a harness logs in with (Claude Pro, a ChatGPT subscription) | `~/.config/handler-ai/accounts/<name>.toml`; its login kept by Handler | Settings → Model access, `handler account` |
| **Provider** | *where model calls go*: endpoints, a key, the models (a local llama.cpp, the Anthropic API) | `~/.config/handler-ai/providers/<name>.toml`; its key in the secret store | Settings → Model access (from a template), `handler provider` |
| **Agent** | *what, where and how*: its model, its folder, its network, permissions and confinement, its tools, skills and notes | `~/.local/state/handler-ai/agents.json` | its project's page, `handler agent`, `handler run` flags |
| **Project** | a code folder, its agents, the skills it gives them, its caches, its area | `~/.local/state/handler-ai/projects.json` | the home page and each project's settings, `handler project` |
| **Work folders** | *where agents may work at all*: a project's or a session's folder must be inside one | `~/.config/handler-ai/folders.toml` | Settings → Folders |
| **Tool** | programs, skills and hosts for one kind of system | `~/.config/handler-ai/tools/<name>/` (yours), `tools.lock.toml` (where each came from) | Library → Tools, `handler tool` |
| **Connection** | one set of a tool's settings and secrets, what an agent is given  | `~/.config/handler-ai/connections/<name>.toml` | Library → Tools → its name → Connect, `handler connection` |
| **Skill** | instructions any agent can be given | `~/.config/handler-ai/skills/<name>/` | Library → Skills |
| **Notes root** | where your [notes folders](notes.md) are | `~/.config/handler-ai/notes.toml` | Library → Notes |
| **Toolbox** | the system every agent works in: Handler's base, the system packages you turn on, your own lines | `~/.config/handler-ai/toolbox/` (`toolbox.toml`, written by Handler; `custom.containerfile`, your lines); your own system packages in `~/.config/handler-ai/system-packages/<name>/` | Settings → Expert → Sandboxes → Under the hood, `handler toolbox` |
| **Automation** | *when this happens, run that* | `~/.config/handler-ai/automations/<name>/`; on or off, and its runs, in `~/.local/state/handler-ai/automations/` | Library → Automations, `handler automation` ([guide](automations.md)) |
| **Secrets** | tokens and keys you gave Handler | `~/.local/share/handler-ai/secrets.json` (only you can read it) | Settings → Expert → Secrets, `handler secret` |
| **Apps** | deployed versions and their data | `~/.local/share/handler-ai/apps/<name>/` | Library → Apps, `handler app` ([guide](apps.md)) |
| **Container runtime** | what agents' sandboxes run in: podman on Linux and Apple's `container` on a Mac unless you choose another (`docker`) | `~/.config/handler-ai/runtime.toml` (`name = "podman"`) | Settings → Expert → Sandboxes, `handler runtime` |
| **Caches** | what toolchains keep between sessions (`~/.cargo`, `~/.npm`, …) | `~/.cache/handler-ai/` (shared) or each project's own | Settings → Expert → Caches (sizes, emptying, each project's choice) |

No sandbox ever sees any of these, except the folders made for it: an agent's own folder, the
notes folders and skills it is given, read-only.

## Elsewhere

- The daemon's token (what the CLI and the web UI use to talk to it): `~/.config/handler-ai/token`.
- Each session's log, replayed when you come back to it: `~/.local/state/handler-ai/sessions/`.
- Each folder can be moved with an environment variable of the daemon: `HANDLER_CONFIG_DIR`,
  `HANDLER_STATE_DIR`, `HANDLER_DATA_DIR`, `HANDLER_CACHE_DIR`, `HANDLER_NOTES_DIR`, and within the
  configuration folder `HANDLER_ACCOUNTS_DIR`, `HANDLER_PROVIDERS_DIR`, `HANDLER_TOOLS_DIR`,
  `HANDLER_CONNECTIONS_DIR`.

## The daemon's environment

The daemon runs as a user service: on Linux systemd's `handler-ai`, on a Mac launchd's
`ai.handler.handlerd` (`~/Library/LaunchAgents/ai.handler.handlerd.plist`). A service gets none of
your shell's environment, so `handler setup` (and `handler daemon install`) writes in it the
variables of the shell it runs in that say where Handler keeps its files and listens: every
`HANDLER_…` variable but `HANDLER_URL`, the `XDG_…_HOME` folders, `HOME` when it is not your
account's, and `DOCKER_HOST`. Run it again after changing one of them.

To give the Linux service another variable, `systemctl --user edit handler-ai`, add it under
`[Service]`, then restart the service:

```ini
[Service]
Environment=HANDLER_TERMINAL=kgx --
```

```bash
systemctl --user restart handler-ai
```

- `HANDLER_TERMINAL`: the terminal a login opens in (Settings → Model access, *Connect* for
  ChatGPT or Mistral), as a command line; the login's command is added at its end. Without it,
  Handler opens Terminal.app on a Mac, and elsewhere the first common terminal it finds; set it
  when it finds none, or to use another.
- `HANDLER_WAYLAND_SOCKET`: the path of your Wayland display's socket, for *Windows on my
  screen* and the login's terminal window. Without it, Handler takes `WAYLAND_DISPLAY`, else the
  only `wayland-N` socket in `XDG_RUNTIME_DIR`; set it when you have several displays, or when
  Handler finds none.
- The folders' variables above.

## Upgrading from 0.2.0

0.3.0 calls tools, connections and notes by the same names everywhere (0.2.0's *addons*,
*bindings* and *knowledge*), and Handler does not rename your files for you. Before you start
0.3.0 for the first time, stop the daemon (`systemctl --user stop handler-ai`; on a Mac,
`launchctl bootout gui/$(id -u)/ai.handler.handlerd`), update Handler, then, in
`~/.config/handler-ai/`:

1. **Tools**: rename the folder `addons/` to `tools/`, and in each tool's folder `addon.toml` to
   `tool.toml`, with `apiVersion = "handler.tool/v1"`. Rename `addons.lock.toml` to
   `tools.lock.toml`, and its tables `[addons.<name>]` to `[tools.<name>]`. A tool of your own
   whose `Containerfile` installs into `/opt/addons/<name>` installs into `/opt/tools/<name>` now
   ([writing one](tools.md#writing-one)).
2. **Connections**: rename the folder `bindings/` to `connections/`. In each file: `apiVersion =
   "handler.connection/v1"`, `tool = "…"` instead of `addon = "…"`, and `secret =
   "connections/…"` instead of `secret = "bindings/…"`.
3. **Secrets**: in the secret store, `~/.local/share/handler-ai/secrets.json`, the names
   starting with `bindings/` start with `connections/`.
4. **Notes**: rename `knowledge.toml` to `notes.toml`. Your notes were in `~/knowledge` (0.2.0's
   default, with no `knowledge.toml`)? Rename that folder `~/notes`: Handler keeps it as your
   notes root when it first starts (or, afterwards, Library → Notes → **Change** to its path).
   Agents now find their notes folders at `/notes/<name>` instead of `/knowledge/<name>`: change
   any instructions or skills naming the old path.
5. **Environment variables** you set for the daemon: `HANDLER_ADDONS_DIR` is `HANDLER_TOOLS_DIR`,
   `HANDLER_BINDINGS_DIR` is `HANDLER_CONNECTIONS_DIR`, `HANDLER_KNOWLEDGE_DIR` is
   `HANDLER_NOTES_DIR` (then run `handler setup` again, [above](#the-daemons-environment)).

Then `handler setup`, and rebuild each tool that brings a program: `handler image rebuild
tool:NAME` (its image is named `handler-ai-tool-<name>` now). On the command line, `handler addon`
is `handler tool`, `handler binding list` is `handler connection list`, `handler knowledge list`
is `handler notes list`, `--addon NAME=CONFIGURATION` is `--tool NAME=CONNECTION` and
`--knowledge` is `--notes`.

The rest is done by Handler at its first start: your agents keep their tools and notes folders,
and the toolbox's `toolbox.toml` is rewritten (Fedora, `podman` and `wl-clipboard` on, the caches
you had added kept); lines you had added to the toolbox's `Containerfile` go in
`~/.config/handler-ai/toolbox/custom.containerfile` now, by hand.
