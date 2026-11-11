# handler account

Connect a subscription (Claude Pro or Max, ChatGPT, Mistral) and manage its login, for your own
use.

## When to use it

- To connect a subscription from the terminal instead of the web UI.
- To renew a login: a new Claude token after a year, a new Codex login.
- To keep the token in your own password manager: Handler reads it when an agent starts.

API keys, OpenRouter and local models are [providers](provider.md).

## Usage

```
handler account list
handler account add NAME HARNESS [--plan PLAN] [--description TEXT] [--area AREA …]
                   [--token | --token-env VAR | --token-file PATH | --token-command CMD]
handler account token NAME [--env VAR | --file PATH | --command CMD]
handler account login NAME [--keep-open]
handler account import NAME FILE
handler account rm NAME
```

Each harness logs in its own way:

- **Claude Code: a token.** You run `claude setup-token` yourself (Anthropic's sign-in, in your
  browser) and give Handler the token it prints. Handler never runs that sign-in. The token lasts
  a year.
- **Codex, Mistral Vibe: a file.** Handler runs the harness's own login on your computer (fetched
  by npx or uvx) and keeps the credential file it leaves.

## Subcommands

| Subcommand | |
|---|---|
| `list` | the accounts: harness, its subscription (`PLAN`), login state, areas, agents using it |
| `add NAME HARNESS` | a new account for `claude-code`, `codex` or `vibe`. NAME is what agents and commands use (`claude-perso`) |
| `token NAME` | Claude Code: give the token (pasted, hidden, or from stdin), kept in Handler's secret store |
| `login NAME` | Codex, Vibe: run the harness's login here |
| `import NAME FILE` | Codex, Vibe: a login done elsewhere, e.g. `~/.codex/auth.json` after `codex login` |
| `rm NAME` | the account and its login; refused while an agent uses it |

## Options

| Option | For | |
|---|---|---|
| `--plan PLAN` | `add` | which subscription it is (`pro`, `max`…). Claude Code cannot learn it from a token and would think it is an API account |
| `--description TEXT` | `add` | a note, shown with the account (e.g. "work, Team subscription") |
| `--area AREA` | `add` | an area it is made for (`Work`, `Personal`…: made in the web UI, Settings → Expert → Areas; or `any`); repeatable. None: refused in every project that has an area |
| `--token` | `add` | ask for the token right away (as `token NAME`) |
| `--token-env VAR`, `--env VAR` | `add`, `token` | read the token from an environment variable of the daemon's service (not your shell's) |
| `--token-file PATH`, `--file PATH` | `add`, `token` | read it from the first line of a file |
| `--token-command CMD`, `--command CMD` | `add`, `token` | run a command that prints it, each time an agent starts |
| `--keep-open` | `login` | wait for Enter at the end (for a window the web UI opened) |

With `--env`, `--file` or `--command`, Handler keeps only where the token is, not the token.

## Examples

```bash
claude setup-token                                          # yourself, then copy the token
handler account add claude-perso claude-code --plan max --area Personal --token
handler account add claude-work claude-code --plan pro --area Work \
    --token-command 'pass show claude-work'
handler account token claude-perso                          # a year later: the new token

handler account add codex-perso codex && handler account login codex-perso
handler account list
```

## See also

[`provider`](provider.md) · [`secret`](secret.md) · [getting started](../getting-started.md#2-connect-claude-code-to-your-claude-subscription)
