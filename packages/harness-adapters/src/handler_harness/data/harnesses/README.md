# Harness adapters (data)

One directory per harness. **This is the only place with harness-specific knowledge.**

```
harnesses/<name>/
├── harness.toml     descriptor, contract B (handler.harness/v1) — validated by handler_contracts
└── Containerfile    FROM the toolbox image; adds only the agent program, unpinned (B.6)
```

The toolbox (`localhost/handler-ai-toolbox:latest`, the user's `~/.config/handler-ai/toolbox/`, seeded from
`../toolbox/`) is the shared development environment every harness image is built on. It lives
outside this directory on purpose: it is not a harness (no descriptor, no ACP, not chosen by an agent), while every directory here with
a `harness.toml` is a harness. Tools for all agents go in the toolbox; this directory only adds
the agent program.

| Harness | Image | ACP command | Bypass mode | Notes |
|---|---|---|---|---|
| `claude-code` | `localhost/handler-ai-claude-code` | `claude-agent-acp` | `bypassPermissions` | account: the token of `claude setup-token` (`[login]`, run on the host with npx); `config_dir` + `config_json` are the agent's own state; provider: `anthropic`; `[terminal]`: `claude`, the SDK's binary (`handler terminal`, D.16) |
| `vibe` | `localhost/handler-ai-vibe` | `vibe-acp` | `auto-approve` | account: the Mistral sign-in of `vibe --setup` (on the host with uvx; its `.env`); provider: `openai-chat`; `config.toml` via the `config_toml` config file |
| `codex` | `localhost/handler-ai-codex` | `codex-acp` | `agent-full-access` | Codex has no mode asking before every edit: agents in `ask` mode are refused (`accept-edits` = its `read-only` mode; in a container its own sandbox cannot start, so that mode asks before commands too); account: a ChatGPT login (`auth_json`, `codex login` on the host with npx), or a provider (`responses`); `config.toml` via the `config_toml` config file, model metadata and system prompt for a local model via `model_catalog_json` and `instructions_md` |
| `pi` | `localhost/handler-ai-pi` | `pi-acp` | pi's default (only mode) | pi never asks before a tool call: agents in `ask`/`accept-edits` mode are refused; no account (no subscription of its own): a provider (`openai-chat`); `settings.json`/`models.json` via config files |

Images and updates (contracts §B.6, §D.4):
- `harness.toml` names the image without a tag; agents launch `:latest`.
- The agent program is not version-pinned. Updating it is a rebuild of the files on disk:
  **Rebuild** in the web UI (Settings → Harness images) or `handler image rebuild <name>`. The daemon builds
  an untagged image, checks it (initialize, session/new, every mapped mode and the model option),
  then tags it `:latest`. There is no rollback: a failed check leaves `:latest` as it was.
- Each `Containerfile` writes what it installed to `/usr/share/handler/version` (shown in the UI,
  recorded on sessions and task executions), and fails the build if it cannot read it.

Adding a harness:
1. `harnesses/<name>/Containerfile` (`ARG TOOLBOX_IMAGE` / `FROM ${TOOLBOX_IMAGE}`, writes
   `/usr/share/handler/version`) + `harness.toml` (`image` without a tag).
2. `handler image rebuild <name>` (first build and later updates; the toolbox must exist: `handler image rebuild toolbox`).
3. `uv run pytest tests/harness` — checks that the image answers ACP and that every mapped
   permission mode and the model option exist in the real session.

A permission mode the harness cannot honour (e.g. `ask` for pi) is left out of `[permissions]`:
agents asking for it are refused, never run with wider permissions.

A harness with an account (`[login]`) says whether its vendor's terms let an automation run an
agent on that subscription unattended (contracts §I.7): `unattended = "allowed" | "check-terms" |
"refused"`, `terms` (the vendor's terms, https) and `checked` (the date Handler read them; absent: not
yet, so `check-terms`). Today: claude-code `refused` (a Claude subscription is for interactive use only), codex and
vibe `check-terms`. Change it only after reading the vendor's current terms, and set `checked`.
