---
name: shopify
description: Work on the Shopify store bound to this agent with the Shopify CLI (`shopify theme …`) — list, pull, check and push themes safely. Use whenever the task involves the store's themes, Liquid files or the Shopify CLI.
---

# Shopify store

The Shopify CLI is installed (`shopify`), already configured for one store:

- `SHOPIFY_FLAG_STORE` names the store: every `shopify theme …` command uses it, so never pass
  `--store`.
- `SHOPIFY_CLI_THEME_TOKEN` authenticates theme commands: **never run `shopify auth login`**, and
  never print, echo or write the token anywhere.

## Safe commands (no confirmation needed)

| Goal | Command |
|---|---|
| list themes and their ids / roles | `shopify theme list` |
| download a theme into the current folder | `shopify theme pull --theme <id>` |
| lint the theme in the current folder | `shopify theme check` |
| upload to a **new unpublished** theme | `shopify theme push --unpublished` |
| upload to an existing **unpublished** theme | `shopify theme push --theme <id>` (check its role is `unpublished` first) |

Prefer working on a copy: pull the theme, change it, push it as a new unpublished theme, and give
the person its preview link.

## Ask the person first, always

- anything that changes what customers see: `shopify theme push --live`, `shopify theme publish`,
  pushing to the theme whose role is `live`;
- deleting a theme (`shopify theme delete`) or files on the store (`push` without `--nodelete`
  removes remote files that are missing locally);
- any `shopify app …` command that deploys or releases (`app deploy`, `app release`).

## Known noise

With a filtered network, the CLI may print a stack trace from its update check
(`onCancel handler…`) before the command's output: it is harmless, the command still ran.
`shopify theme dev` starts a local preview server; it needs the network and keeps running until
stopped, so prefer `push --unpublished` and a preview link.
