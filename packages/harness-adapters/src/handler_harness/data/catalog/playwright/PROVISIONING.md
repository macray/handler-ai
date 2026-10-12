# Playwright addon — what a binding needs

Nothing, for pages that need no login: a local preview in the sandbox, public sites.

```toml
# ~/.config/handler-ai/bindings/browser.toml
apiVersion  = "handler.binding/v1"
addon       = "playwright"
description = "Web browser, no login"
```

## To watch the browser

Give the agent a display (web UI agent setting: **Show windows on my screen and paste images**; CLI:
`handler run … --display`). The daemon then gives the sandbox your Wayland session's socket, and
nothing else of your desktop (contract A.6); the browser opens as a window you can watch and use.
Without a display the browser is headless and the agent shows screenshots. `settings = { headless
= "1" }` keeps it headless even with a display.

## Sites that need a login

The agent is unsupervised: what limits it is the **account it logs in with** (`docs/dev/design/addons.md`
§8). Never give it your own session.

1. Create an account for the agent on that site, with the rights it needs only (for a Shopify
   admin: a staff account limited to themes, on a development store).
2. Log in with it once, in a Playwright browser on your machine, and save the session (cookies and
   local storage) to a file; close the window when logged in:

   ```bash
   npx playwright open --save-storage=agent-shop.json https://admin.shopify.com
   ```

3. Keep it in your password store, as one line (the sandbox env cannot hold newlines), and delete
   the file:

   ```bash
   jq -c . agent-shop.json | pass insert -m playwright/agent-shop && rm agent-shop.json
   ```

4. The binding:

   ```toml
   # ~/.config/handler-ai/bindings/browser-shop-admin.toml
   apiVersion  = "handler.binding/v1"
   addon       = "playwright"
   description = "Web browser logged in as the agent's staff account"
   secrets     = { storage_state = { command = ["pass", "show", "playwright/agent-shop"] } }
   ```

Every session starts from that state; nothing the agent does in the browser is saved back. When
the session expires, repeat step 2. The state is a secret: like every secret of a binding it is in
the agent's environment, and redacted from transcripts.
