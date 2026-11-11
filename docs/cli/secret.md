# handler secret

Manage Handler's secret store: API keys, tokens, tool secrets.

## When to use it

- To set a tool's secret (a GitHub token) from a script or your password manager.
- To check which secrets agents can read in clear, and which they only see as a stand-in.
- To remove a secret nothing uses any more.

An app's secrets are set with [`handler app secret`](app.md), an account's token with
[`handler account token`](account.md).

## Usage

```
handler secret list
handler secret set PATH [--description TEXT]
handler secret rm PATH
```

A value is named by a path after what owns it, e.g. `providers/openrouter/apiKey` or
`connections/github-agent/token`. An account, provider or connection file refers to it as
`{ secret = "<path>" }`. Values are written, never read back.

## Subcommands

| Subcommand | |
|---|---|
| `list` | every secret Handler uses: where it comes from (the store, an env var, a file, a command), what it belongs to, and whether agents can read it. When they cannot, the network filter adds it to their requests to its hosts only |
| `set PATH` | set a value: asked for (hidden), or read from stdin. `--description` adds a note |
| `rm PATH` | forget PATH and everything under it; refused while something refers to it |

## Examples

```bash
pass show github/agent-token | handler secret set connections/github-agent/token
handler secret list
```

## See also

[`account`](account.md) · [`provider`](provider.md) · [`connection`](connection.md)
