# handler binding

List the bindings: an addon with its settings and secrets, ready to give to an agent.

## When to use it

- To find the name `--binding NAME` takes.
- To find why a binding fails (a missing secret, an addon not installed).

## Usage

```
handler binding list
```

A binding is what an agent gets: `shopify-dev-shop` is the `shopify` addon on one store with its
token; `browser` is the `playwright` addon. Make one in the web UI (Settings → Addons →
Configure), or copy a file from `examples/bindings/` to `~/.config/handler-ai/bindings/`
([where things are kept](../configuration.md)).

## Output

One line per binding: its name, its addon, its settings, the secrets it refers to, its error if
any.

## See also

[`addon`](addon.md) · [`secret`](secret.md) · [agent options](agent-options.md#what-it-gets)
