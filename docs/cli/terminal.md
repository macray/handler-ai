# handler terminal

Run a harness's own terminal UI (Claude Code's, Codex's…) in a sandbox.

## When to use it

- You want the tool exactly as you know it: its slash commands, `--resume`, its keyboard
  shortcuts, its own way of showing things.
- As a drop-in replacement for the command you type today, contained and on the account you chose
  (see the shell function below).

Unlike [`run`](run.md), this is not a session: it is not kept by the daemon nor shown as a
conversation in the web UI, and it ends when you exit. The web UI shows it to change its network.

## Usage

```
handler terminal AGENT|ACCOUNT|PROVIDER [FOLDER] [--anyway] [agent options] [-- ARGS …]
```

- `AGENT|ACCOUNT|PROVIDER`: in a project's folder, one of its agents by name, or an account or
  provider (as for `run`). Elsewhere: an account or a provider.
- `FOLDER`: the folder the agent works in (default: the current one). In a project's sub-folder,
  the sandbox sees only that sub-folder, not the rest of the project.
- `-- ARGS …`: everything after `--` is given to the harness unchanged.

## Options

| Option | |
|---|---|
| `--anyway` | in a project's folder, run outside the project (an account its area does not allow); asks you to type `yes` |
| agent options | [agent options](agent-options.md) |

## Pasting an image

Copy an image, then press Ctrl+V in the program, as on your computer: `handler terminal` puts the
image where the program in its sandbox reads its clipboard, then passes the key on. The sandbox
gets only what you paste, when you paste it. It reads your clipboard with `wl-paste` (Wayland),
`xclip` (X11) or `osascript` (macOS). Works with Claude Code; a program that reads the clipboard
another way (Codex) needs [`--display`](agent-options.md) for it.

## Your command, sandboxed

Put a shell function in `~/.bashrc` or `~/.zshrc`:

```bash
claude() { handler terminal claude-perso -- "$@"; }
vibe()   { handler terminal vibe-work -- "$@"; }
```

This works for Claude Code and Mistral Vibe. Codex and pi have no terminal UI in Handler yet: use
[`handler run`](run.md) for them.

`claude`, `claude --resume`, `claude -p "…"` then work as before, but the agent sees only the
current folder, reaches only allowed hosts, and runs on `claude-perso`. Name it `claude-sandbox`
to keep the plain command too, or make one per account (`claude-work`, `claude-perso`). Add the
options you always want:

```bash
claude() {
  handler terminal claude-perso --display --tool playwright=browser -- "$@"
}
```

Leave `--anyway` out: in a *Work* project's folder, `claude-perso` is then refused instead of
running on your work code.

## Good to know

- The first line it prints says which account or provider it runs on, and its subscription
  (as the account says it: `--plan` of [`account add`](account.md)).
- Restarting the daemon leaves it running.
- An agent outside projects is shared with `run` and `acp`: the same folder gives the same agent
  and settings.

## See also

[`run`](run.md) · [agent options](agent-options.md) · [`account`](account.md)
