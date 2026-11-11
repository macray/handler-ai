# handler connection

List the connections: a tool with its settings and secrets, ready to give to an agent. A tool
without settings or secrets (`app-builder`) has none: an agent gets it by its name.

## When to use it

- To find the name `--tool TOOL=CONNECTION` takes.
- To find why a connection fails (a missing secret, a tool not installed).

## Usage

```
handler connection list
```

A connection is what an agent gets: `github-agent` is the `github` tool as the account of one
token; `browser` is the `playwright` tool with its default settings. Make one in the web UI (Library → Tools → its name →
Connect); it is kept in `~/.config/handler-ai/connections/` ([where things are kept](../configuration.md)).

## Output

One line per connection: its name, its tool, its settings, the secrets it refers to, its error if
any.

## See also

[`tool`](tool.md) · [`secret`](secret.md) · [agent options](agent-options.md#what-it-gets)
