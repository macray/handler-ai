# Where things are kept

Everything you set up in the web UI or with `handler` ends up in a few folders of your home. Most
are plain TOML you can read, back up, or write by hand from the [examples](../../examples/);
unknown keys are errors, so a typo never goes unnoticed. What each thing is:
[concepts](concepts.md).

| What | What it answers | Where | Changed from |
|---|---|---|---|
| **Account** | *whose* subscription a harness logs in with (Claude Pro, a ChatGPT plan) | `~/.config/handler-ai/accounts/<name>.toml`; its login kept by Handler | Settings → Model access, `handler account` |
| **Provider** | *where model calls go*: endpoints, a key, the models (a local llama.cpp, the Anthropic API) | `~/.config/handler-ai/providers/<name>.toml`; its key in the secret store | Settings → Model access (from a template), `handler provider` |
| **Agent** | *what, where and how*: its model, its folder, its network, permissions and confinement, its addons, skills and knowledge | `~/.local/state/handler-ai/agents.json` | its project's page, `handler agent`, `handler run` flags |
| **Project** | a code folder, its agents, the skills it gives them, its caches, its area | `~/.local/state/handler-ai/projects.json` | the home page and each project's settings, `handler project` |
| **Work folders** | *where agents may work at all*: a project's or a session's folder must be inside one | `~/.config/handler-ai/folders.toml` | Settings → Folders |
| **Addon** | programs, skills and hosts for one kind of system | `~/.config/handler-ai/addons/<name>/` (yours), `addons.lock.toml` (where each came from) | Library → Addons, `handler addon` |
| **Addon configuration** | one set of an addon's settings and secrets, what an agent is given (a *binding* in the files) | `~/.config/handler-ai/bindings/<name>.toml` | Library → Addons → Configure, `handler binding` |
| **Skill** | instructions any agent can be given | `~/.config/handler-ai/skills/<name>/` | the Skills page |
| **Knowledge root** | where your [knowledge folders](knowledge.md) are | `~/.config/handler-ai/knowledge.toml` | the Knowledge page |
| **Toolbox** | the system and tools every agent works with | `~/.config/handler-ai/toolbox/` (`Containerfile`, `toolbox.toml`), copied from Handler's own on first start | Settings → Images → toolbox |
| **Automation** | *when this happens, run that* | `~/.config/handler-ai/automations/<name>/`; on or off, and its runs, in `~/.local/state/handler-ai/automations/` | the Schedule page, `handler automation` ([guide](automations.md)) |
| **Secrets** | tokens and keys you gave Handler | `~/.local/share/handler-ai/secrets.json` (only you can read it) | Settings → Secrets, `handler secret` |
| **Apps** | deployed versions and their data | `~/.local/share/handler-ai/apps/<name>/` | the Apps page, `handler app` ([guide](apps.md)) |
| **Caches** | what toolchains keep between sessions (`~/.cargo`, `~/.npm`, …) | `~/.cache/handler-ai/` (shared) or each project's own | Settings → Caches |

No sandbox ever sees any of these, except the folders made for it: an agent's own folder, the
knowledge folders and skills it is given, read-only.

## Elsewhere

- The daemon's token (what the CLI and the web UI use to talk to it): `~/.config/handler-ai/token`.
- Each session's log, replayed when you come back to it: `~/.local/state/handler-ai/sessions/`.
- Each folder can be moved with an environment variable of the daemon: `HANDLER_CONFIG_DIR`,
  `HANDLER_STATE_DIR`, `HANDLER_DATA_DIR`, `HANDLER_CACHE_DIR`, `HANDLER_KNOWLEDGE_DIR`.

Why the configuration is split this way: [configuration design](../dev/design/configuration.md).
