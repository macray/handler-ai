# A browser for your agents

The `playwright` addon gives an agent a web browser (Chromium, driven through Playwright MCP): it
opens pages, clicks, types, reads them and takes screenshots. A local preview the agent runs in its
sandbox works with any network setting; other sites go through the agent's network filter like
everything else it reaches.

## Install it

```bash
handler addon add playwright
cp examples/bindings/browser.toml ~/.config/handler-ai/bindings/   # a configuration with no login
```

Or Settings → Addons → Available to install → playwright, then Configure (no setting needed).
Select the configuration in the agent's settings, or:

```bash
cd ~/code/my-theme && handler run claude-perso --binding browser
```

## Watch it

By default the browser is headless: you see its screenshots in the session. To watch it work, turn
on **Show windows on my screen and paste images** in the agent's settings (`--display`): the browser
opens as a window on your desktop, which you can also use. The sandbox gets your Wayland display
and its clipboard, nothing else of your desktop. `settings = { headless = "1" }` in the
configuration keeps it headless anyway.

Needs a Wayland session (GNOME, KDE…). Not available on macOS, where the setting is greyed out.

## Sites that need a login

What limits an agent on a site is the **account it logs in with**, so never give it your own
session: create an account for it with only the rights it needs, log in with it once, and save
that session as a secret of a second configuration. Every session of the agent starts logged in,
and nothing it does is saved back. The steps:
[the addon's PROVISIONING.md](../../packages/harness-adapters/src/handler_harness/data/catalog/playwright/PROVISIONING.md).

## See also

[addons](addons.md) · how it is built: [browser design](../dev/design/browser.md)
