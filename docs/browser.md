# A browser for your agents

The `playwright` tool gives an agent a web browser (Chromium, driven through Playwright MCP): it
opens pages, clicks, types, reads them and takes screenshots. A local preview the agent runs in its
sandbox works with any network setting; other sites go through the agent's network filter like
everything else it reaches.

## Install it

```bash
handler tool add playwright
```

Or Library → Tools → Get more → playwright → Install. Then give it a connection: Library →
Tools → playwright → *Connect*, name it `browser`, no setting needed, *Save*. Select the
connection in the agent's settings, or:

```bash
cd ~/code/my-theme && handler run claude-perso --tool playwright=browser
```

## Watch it

By default the browser is headless: you see its screenshots in the session. To watch it work, turn
on **Windows on my screen** in the agent's settings (`--display`): the browser
opens as a window on your desktop, which you can also use. The sandbox gets your Wayland display
and its clipboard, nothing else of your desktop. `settings = { headless = "1" }` in the
connection keeps it headless anyway.

Needs a Wayland session (GNOME, KDE…). Not available on macOS, where the setting is greyed out.
Handler finds your display by itself; when it cannot, tell it where: `HANDLER_WAYLAND_SOCKET`
([the daemon's environment](configuration.md#the-daemons-environment)).

## Sites that need a login

What limits an agent on a site is the **account it logs in with**, so never give it your own
session: create an account for it with only the rights it needs, log in with it once, and save
that session as a secret of a second connection. Every session of the agent starts logged in,
and nothing it does is saved back. The steps:
[the tool's PROVISIONING.md](https://github.com/macray/handler-ai-registry/blob/main/tools/playwright/PROVISIONING.md).

## See also

[tools](tools.md)
