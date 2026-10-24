# Handler — Browser

Status: **implemented** (2026-09-26), except what §9 lists. Companion to `addons.md` (a browser is
an addon with an MCP server) and `contracts.md` (A.6 display, B.2 `mcpServers`, C.4 P8, G.1
`mcp`). As users see it: [a browser for your agents](../../user/browser.md).

## 1. Goal

Let an agent use a web browser — open pages, click, type, read, take screenshots — **and let the
person watch it** when that matters, without weakening the sandbox.

## 2. Use cases

| # | Use case | What it needs |
|---|---|---|
| UB1 | "Update the product page, show me the result": the agent runs `shopify theme dev` in its sandbox and shows the preview; the person looks and comments in the chat | a browser that reaches the sandbox's `127.0.0.1:9292`, **visible** to the person |
| UB2 | Check a web app the agent is building: open it, click through, look at the console | a browser in the sandbox, headless is enough |
| UB3 | Unattended task: screenshot a page at phone and desktop widths, compare | headless, screenshots kept with the task's transcript |
| UB4 | Act on a site with the person's own login (theme editor, SSO, 2FA) | the person's real browser, or a login done once by hand |

## 3. Choices

Browser automation for agents comes as an MCP server. Two were considered:

- **Browser MCP** (browsermcp.io): drives the person's own Chrome through an extension; its server
  listens on a fixed port (9009) and kills whatever holds it, so two agents cannot share it. Small,
  little maintained. **Not chosen.**
- **Playwright MCP** (`@playwright/mcp`, Microsoft, Apache-2.0): starts its own browser (headed or
  headless, `--isolated` in-memory profile), or drives the person's browser through an extension
  (`--extension`), or any browser over CDP (`--cdp-endpoint`). **Chosen.** Its README is explicit:
  "Playwright MCP is **not** a security boundary", and its origin filters "do not serve as a
  security boundary and do not affect redirects". The sandbox does the enforcing.

Where each part runs:

| Option | MCP server | Browser | Browser traffic under the sandbox's allow-list | Host files safe | Verdict |
|---|---|---|---|---|---|
| **C** — headed browser in the sandbox, window on the person's desktop | sandbox | sandbox | **yes** | **yes** | **default** (UB1–UB3) |
| **A** — hosted MCP server, the person's Chrome (`--extension`) | host, behind a handlerd gateway | host | no | mostly (tool filter, dedicated Chrome profile) | later, opt-in (UB4) |
| B — MCP server in the sandbox, host browser over CDP | sandbox | host | no | **no** (CDP reads `file://`, downloads anywhere) | rejected |

Option C does not cover UB4 yet: the browser starts logged out every session (§7).

## 4. Findings

A spike on the host (2026-09-26: Chromium in a throwaway image `FROM` the toolbox, with the flags
of a `strict` sandbox and no network) settled what the design relies on:

- headless Chromium renders a page served on the sandbox's `127.0.0.1`: an agent's browser
  reaches its local preview with any network mode;
- Chromium's own sandbox cannot start under `strict` (`Failed to receive hello message from
  zygote`): `--no-sandbox` is required (Playwright's default), the container is the boundary;
- mounting only the Wayland socket (`WAYLAND_DISPLAY` set to its absolute path, no `DISPLAY`, no
  `/tmp/.X11-unix`) is enough for a headed window (`--ozone-platform=wayland`, `--disable-gpu`):
  no X11, whose clients can read every keystroke;
- the distribution's Chromium driven by Playwright through `executablePath`: no
  Playwright-bundled browser needed.

A sandboxed Wayland client can open windows that look like other applications' (e.g. a fake
password prompt); it cannot read other windows or keystrokes. Screen capture goes through portals
over D-Bus, which is not mounted.

## 5. Architecture

Three independent pieces, each in the block that owns it:

```
 addon [mcp] (via bindings) ────► render (B): sessionDefaults.mcpServers (B5: harness must accept
                                  │           each transport, names unique)
                                  ▼
 any ACP client ─ session/new|load|resume ─► policy P8 adds them (outside the sandbox, for every
                                             client: web UI sessions, runs, `handler acp` editors)
                                  ▼
 sandbox: agent ──stdio──► playwright-mcp (addon image mount) ──► chromium (toolbox)
                                                                   │ window: Wayland socket (A.6)
                                                                   └ traffic: the sandbox's proxy
```

### 5.1 MCP servers reach the agent through ACP

Before this, a profile's `[config] mcpServers` were validated and their hosts added to the
allow-list, but every `session/new` carried `mcpServers: []`: no agent ever saw them.

They now go where ACP puts them, in `session/new`, `session/load` and `session/resume` (decision
4: explicit ACP beats harness settings files). `render` emits them in `sessionDefaults.mcpServers`
and the policy adds them to each such request (P8), so every client gets them without knowing
about them. A client's own server with the same name is replaced (logged). P3 then checks the
merged list: an HTTP server the network policy does not allow is refused, whoever asked for it.

A harness declares the transports it accepts (`mcpTransports`); a server with another transport
fails `render` (B5), never silently dropped. Declared for claude-code (`stdio`, `http`, `sse`),
vibe (`stdio`) and pi (`stdio`, `http`, `sse`). pi has no MCP of its own and pi-acp ignores
`session/new`'s servers: its image runs pi with the pi-mcp-adapter extension, and `render` writes
the same servers to the file that extension reads (`mcpConfigFile`, contracts B7).

### 5.2 Addons can bring an MCP server

`[mcp] command = [...]` in an addon's manifest: a stdio server started from the addon's own
`commands` (so it is installed at build time, `addons.md` §4.2). Resolving a binding adds
`{name = <addon>, command, args}` to the agent's MCP servers, as it adds skills. Hosted servers
(option A) are not built (§9).

### 5.3 A display, per sandbox (contract A.6)

`SandboxSpec.display = { mode = "wayland", socket = <host socket> }`: the implementation makes that
display usable by the sandboxed process, and only that. `handler-sandbox-podman` mounts the socket at
`/run/handler/wayland-0`, sets `WAYLAND_DISPLAY` to it and gives a private `XDG_RUNTIME_DIR`. A
missing socket fails the setup, never a launch without the display asked for.

Only an agent saved with `display: true` gets one (CLI `--display`, web UI **Show windows
on my screen and paste images**). The daemon finds the socket at each
agent start: `HANDLER_WAYLAND_SOCKET`, else `WAYLAND_DISPLAY`, else the only `wayland-*` socket of
`XDG_RUNTIME_DIR` (it runs as a systemd user service, which may lack `WAYLAND_DISPLAY`).

## 6. Packaging

- **Toolbox**: `chromium`, `ttf-liberation`, `ttf-dejavu` (a browser is common in web development
  anyway: e2e tests, `playwright test`; `addons.md` §6 puts often-used tools there).
- **the `playwright` addon** (`handler_harness/data/addons/playwright`): `@playwright/mcp` only (plain npm, self-contained; no Playwright browser
  download), with a Node wrapper `bin/playwright-mcp` (`handler/playwright-mcp.mjs`), the addon's
  `[mcp] command`:
  - the toolbox's Chromium, `--isolated` (in-memory profile);
  - **headed** (`--ozone-platform=wayland`) only when `WAYLAND_DISPLAY` is set, i.e. the sandbox
    was given a display, and the binding does not set `headless = "1"`; **headless** otherwise;
  - `--proxy-server "$HTTPS_PROXY"` and `--proxy-bypass "$NO_PROXY"` when set (read from the
    sandbox's env: `render` never learns proxy details, B2);
  - `--disable-gpu --disable-dev-shm-usage` (no GPU; podman's `/dev/shm` is 64 MB);
  - `--output-dir` in a private temporary folder, removed on exit.
- **Check** (`playwright-mcp-check`, offline): the installed Playwright launches the toolbox's
  Chromium headless and reads a page; a toolbox rebuild re-runs it (`addons.md` §4.5).

## 7. Logins

None built: the browser starts logged out every session (`--isolated`).

- **Storage state** (removed): cookies and local storage saved once from a dedicated account
  (`npx playwright open --save-storage=…`), given by a binding's secret. Removed, unused: a
  session saved on the host and replayed from the sandbox (another IP, another browser) is refused
  by many sites, it expires and must be saved again by hand, and the agent can read it (the
  secret's value, not a phantom: the browser reads it from a file, not from an HTTP header).
- **Kept profile** (not implemented): a binding's browser profile as a state mount; the person
  logs in once by hand in the headed window. One session at a time per profile (a profile is
  locked by its browser); bindings have no mounts today.

When one is built, the account is a dedicated one, with the rights the agent needs (`addons.md` §8.1).

## 8. macOS

Not tested; from how the pieces work. On macOS, podman runs containers in a Linux VM (`podman
machine`); the podman CLI on the Mac is a remote client.

| Piece | macOS |
|---|---|
| MCP delivery (P8), addon `[mcp]` | same as Linux: data in ACP, nothing platform-specific |
| Headless browser in the sandbox (UB2, UB3, and UB1 with screenshots) | should work as on Linux, inside the VM: local preview, proxy, screenshots in the web UI. But the toolbox is `archlinux:latest`, **x86_64 only**: on Apple Silicon every sandbox runs emulated (Rosetta in the VM), Chromium included: slow, and to be verified |
| Watching the browser (option C, A.6) | **no**: macOS has no Wayland, and a Unix socket of the Mac cannot be mounted into the VM's containers. It degrades cleanly: the daemon finds no display, `GET /v1/health` says `display: false`, the web UI disables **Show windows on my screen and paste images**, `--display` is refused (409) |

A portable way to watch, for later: a display inside the sandbox instead of the host's — a
headless compositor with a VNC server (e.g. `weston --backend=vnc`, or Xvfb + x11vnc) — relayed by
handlerd to a viewer in the web UI (noVNC). Same on Linux and macOS, and from another machine. The
contract has room for it: `display.mode` is a discriminator (`"wayland"` today, `"vnc"` then).

The rest of the platform has its own macOS gaps, outside this design: `handler daemon` uses a
systemd user unit (launchd on macOS); `nested` confinement reads subordinate ids
with `podman unshare` and checks `/dev/fuse` on the client, neither of which works with a remote
client; scopes must be in folders shared with the VM (`/Users` by default).

## 9. Not built yet

- Option A (§3): hosted MCP servers behind a handlerd gateway (per-session Unix socket, audit in
  the session log, kill switch, tool filter), and a sandbox→host port forward so the person's own
  browser can open the sandbox's local preview.
- Not yet seen with a real model: whether claude-agent-acp forwards an MCP tool's image content
  (screenshots) in its `tool_call_update`; the web UI shows it if it does.
- pi's MCP servers (through pi-mcp-adapter) were verified in a stand-in image only, not against a
  built `handler-ai-pi` image.
