# Addon catalog (data)

Addons Handler ships but does not load (contract G.5): an agent can get one only after the user
installs it (Settings → Tools → Add a kind of tool, `handler addon add NAME`), which copies it to
`~/.config/handler-ai/addons/<name>/` and records it in `~/.config/handler-ai/addons.lock.toml`. When Handler
ships other content for an installed one, Settings → Tools offers the update. Same layout as any
addon (`docs/user/addons.md`, contract G.1); `tests/` checks each one is valid.

| Addon | Image | Commands | Slots |
|---|---|---|---|
| `shopify` | `localhost/handler-ai-addon-shopify` | `shopify` | setting `store` (required), secrets `theme_token`, `partners_token` |
| `playwright` | `localhost/handler-ai-addon-playwright` | `playwright-mcp` (MCP server), `playwright-mcp-check` | setting `headless`, secret `storage_state`; no setting required |
