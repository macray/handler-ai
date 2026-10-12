# Shopify addon — the account an agent needs

An agent is unsupervised: what limits it is the **account behind its token**, not the skill
(`docs/dev/design/addons.md` §8). So give it a store where mistakes are cheap, and a token that can only do
theme work.

## 1. A development store

Create the store the agent works on, rather than giving it your real shop:
Shopify Partners dashboard → **Stores** → **Add store** → **Create development store**. Copy your
real theme into it if the agent should start from it (`shopify theme pull` from the real store with
your own login, `shopify theme push --unpublished` into the development store).

If the agent must work on the real store anyway, it still only gets a Theme Access password (2),
and the skill tells it never to touch the live theme without asking. That rule is not enforced.

## 2. A Theme Access password

On the store the agent works on:

1. Install the **Theme Access** app (Shopify App Store, published by Shopify).
2. In the app, **Create password**, for an email address that stands for the agent (e.g.
   `agent+shop@…`); the password arrives by email: `shptka_…`.
3. Keep it in your password store, never in a file under `~/code` (agents can read project
   folders):

   ```bash
   pass insert shopify/dev-theme-token
   ```

A Theme Access password is limited to theme operations (no orders, customers or settings). Revoke
it from the app at any time.

App commands (`shopify app …`) need a Partners CLI token instead (`partners_token` slot): create it
only if the agent works on apps, in Partners → **Settings** → **CLI tokens**.

## 3. The binding

```toml
# ~/.config/handler-ai/bindings/shopify-dev-shop.toml
apiVersion  = "handler.binding/v1"
addon       = "shopify"
description = "Development store, Theme Access token"
settings    = { store = "my-dev-shop.myshopify.com" }
secrets     = { theme_token = { command = ["pass", "show", "shopify/dev-theme-token"] } }
```

Then give `shopify-dev-shop` to an agent (web UI: **Tools** in the agent's form, or
`handler run … --binding shopify-dev-shop` outside projects).
