# handler connection

List the connections, a tool with its settings and secrets, ready to give to an agent, and check
one works. A tool without settings or secrets (`app-builder`) has none: an agent gets it by its
name.

## When to use it

- To find the name `--tool TOOL=CONNECTION` takes.
- To find why a connection fails (a missing secret, a tool not installed).
- To check one works (`check`): a connection you wrote by hand, or after changing its token.

## Usage

```
handler connection list
handler connection check NAME
```

`check` runs the tool's own check of a connection (the web UI runs it each time you save one),
as an agent of it would: its settings, a stand-in for each secret, only the tool's sites. It
prints `works` or why it fails, with what the check printed, and exits 1 when it fails. A tool
that has no check, or is not ready yet, says so.

A connection is what an agent gets: `github-agent` is the `github` tool as the account of one
token; `browser` is the `playwright` tool with its default settings. Make one in the web UI (Library → Tools → its name →
Connect); it is kept in `~/.config/handler-ai/connections/` ([where things are kept](../configuration.md)).

You can also write one by hand, `~/.config/handler-ai/connections/github-agent.toml` (the token
of an account made for the agent: `tools/github/CONNECT.md` of the tool's source):

```toml
apiVersion  = "handler.connection/v1"
tool        = "github"
description = "GitHub, as the agent's own account"
secrets     = { token = { command = ["pass", "show", "github/agent-token"] } }
```

`browser.toml` needs only the first three lines (`tool = "playwright"`), plus `settings = {
headless = "1" }` to keep it headless.

## Output

`list`: one line per connection: its name, its tool, its settings, the secrets it refers to, its
error if any. `check`: `NAME: works`, or `NAME: fails: why`, then the check's last lines.

## See also

[`tool`](tool.md) · [`secret`](secret.md) · [agent options](agent-options.md#what-it-gets)
