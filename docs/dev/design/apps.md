# Apps — design

Status: **implemented** (2026-09-28), except what §11 lists. Normative: `contracts.md` §H. As
users see it: [apps](../../user/apps.md).
Tests: `tests/apps` (real podman), `tests/remote/test_remote_apps.py` and `test_remote_queue.py`
(a real gateway, Python devices), `tests/e2e/test_apps_ui.py` (Chromium: desk and phone),
`packages/control-plane/tests/test_{apps,webpush}.py`, the remote client's
vitest, the gateway's tests.

Small personal apps (a web UI + a small backend) that an agent writes in a sandbox and Handler runs
on this machine. The same app is used from the desktop (its own window) and from a phone or a
family member's phone (through the remote-control gateway, `remote.md`), with no difference
between the two: there is **one instance of each app, on the host, and no sync, ever**.

## 1. Use cases

| # | App | What it needs from the platform |
|---|---|---|
| UM1 | "Is selling this item at this price worth it (taxes, fees)?" | UI + logic + SQLite (history). Nothing else: the first acceptance test |
| UM2 | "Spell-check this text, list the mistakes below" (text pasted in) | egress to a model + its key (§6) |
| UM3 | "Summarize this text" | the same; may be answered later if the host is off (§5.3) |
| UM4 | Personal coach: asks whether a task is progressing, reminds me of today's meetings | an automation calling it at a time (§7), notifications (§7), a model, a calendar (a markdown file, or RustiCal over CalDAV on the local network), answers sent from the phone while the host is off (§5.3) |

## 2. Concepts

| Concept | Definition |
|---|---|
| **App** | A folder with a manifest (`app.toml`, contract `handler.app/v1`), a Bun backend in its own directory (`server/`, with its migrations and tests), a built UI (`ui/dist/`), the definitions of the agents it needs. Written by an agent with the `app-builder` addon's skill. **1 app = 1 UI.** Nothing in it is the person's: it says what it needs (§11b). |
| **Need, and what is given** | What an app needs, in its own words (`needs.files.tasks`, `needs.agents.planner`, a secret's name), and what the person gives each one at install (a folder, an agent, a value), kept by Handler by identity: a binding (§11b). |
| **Installed app** | A deployed version of an app on the host: its code (read-only, one folder per deploy) plus its **data** (one folder with its SQLite file, kept apart from the code, survives updates). |
| **App host** | The part of handlerd that registers, deploys, starts, stops and serves apps (`apps.py`, `app_http.py`). |
| **Person** | Who uses an app: `owner` (you, local UI and your devices) or a family member. Each paired device belongs to one person; each app lists the persons allowed to use it. |

## 3. Runtime: one stack

**Bun**, for the backend and the UI tooling:

- TypeScript for the backend and the UI (Svelte 5, built by vite, run by Bun), one language;
- SQLite (`bun:sqlite`), an HTTP server on a Unix socket (`Bun.serve`), a test runner
  (`bun:test`), all built in; one binary;
- light: a backend at rest takes about 20 MB and answers its first request about 80 ms after it
  starts (§12), which matters as each app in use is one more process, started on demand.

Bun runs TypeScript without checking its types: the template's `server/package.json` has the type
checker (`bun run check`) as a development dependency, for the agent; it is not installed with
the app.

Apps run on a **pinned** image, `docker.io/oven/bun:<version>-distroless` (~120 MB, not the
toolbox): an app is tested against it when it is deployed. The default toolbox installs the same
Bun version for the agents that write apps (a test keeps them equal); the person may change it,
so a toolbox rebuild only checks that Bun is there (a warning when it is not), never its version:
the deploy's tests are what run on the apps' own. Changing it is a platform
release: bump `RUNTIME_IMAGE` and the toolbox's `BUN_VERSION` together, then redeploy the apps
(their tests run on the new version).

The host never builds anything: a deployed app ships its UI already built and its backend as
source, with no dependency (`server/node_modules/` is not installed); the backend runs
`--no-install`, offline.

## 4. Running apps (on demand, not always up)

- **Scale to zero.** A backend runs only while it is used: handlerd starts it on the first `/api/`
  request and stops it after 10 minutes without one (`HANDLER_APP_IDLE_TIMEOUT`). The UI's files are
  served by handlerd itself, so opening an app does not start it; the first API call does (about 1 s).
- **One container per running app**, through the sandbox block (contract A,
  `handler-sandbox-podman`), confinement strict: the code read-only at `/opt/app`, the data folder
  read-write at its own path, the socket's folder; **no network** unless the manifest lists hosts
  (then the allow-list, enforced). App code is written by an agent: it gets the same treatment as
  agents. Bun has no permission system of its own: the sandbox is the only limit, as for agents.
- **ABI:** the backend serves HTTP on the Unix socket `$HANDLER_APP_SOCKET`, keeps its data in
  `$HANDLER_APP_DATA`, answers `GET /api/health` with 200 once ready (migrations done). Each request
  carries `X-HANDLER-Person` (set by Handler; a page cannot forge it); the app does no authentication.
  `$HANDLER_APP_API` is Handler's own API for the app (notifications, §7).
- **Deploy** (a human only, §10), the Deploy button or `handler app deploy`:
  1. snapshot the source folder: `app.toml`, the backend's directory, the built UI; symbolic
     links must stay inside, 256 MiB at most;
  2. run the backend's tests (`bun test`) in the sandbox, with an empty data folder;
  3. stop the backend, copy the data twice: a backup, and a scratch copy;
  4. start the new version on the scratch copy (its migrations run there) until `/api/health`
     answers;
  5. switch. The real data is migrated when the new version first starts.

  Any failure leaves the installed version and the data as they were; the log says why.
- **Rollback:** back to the previous version **and** the data backup taken just before the current
  version was deployed (migrations may not run backwards): what changed since is lost, and the
  UI says so. Three deployments are kept (current + two).
- **Files:** `<data>/apps/<name>/{versions/<n>, data, backups/<n>, app.log}` (`<data>` =
  `~/.local/share/handler-ai`, `HANDLER_DATA_DIR`), the registry in `<state>/apps.json`, sockets in
  `$XDG_RUNTIME_DIR/handler-ai/apps/<name>/` (`HANDLER_RUNTIME_DIR`). Uninstalling an app deletes its folder whole, its data with it
  (2026-10-22: kept until then, it was found by any app installed later under that name).

## 5. Access

### 5.1 Local (desktop)

- **Each app has its own origin:** `http://<name>.localhost:7430/`, served by handlerd (browsers
  resolve `*.localhost` to the loopback address and treat it as a secure context). App code is
  written by an agent: it must never share an origin with Handler's web UI, which holds the token,
  nor with another app. A request whose Host is not `<app>.localhost:<port>` goes to Handler, so DNS
  rebinding never reaches an app.
- **Opening:** the Apps page's Open button, or `handler app open <name>`: handlerd mints a one-time link
  (2 minutes) that sets the app's cookie (HttpOnly, SameSite=Strict, bound to the app and the
  daemon's token), then shows the app. Requests that change something must carry the app's own
  `Origin`, and requests another app's page sends are refused: apps are same-site with each other
  (`*.localhost`), so SameSite alone would not separate them.
- **CSP** on every app response: scripts, styles and connections from the app's origin only. A
  page cannot send what it shows anywhere else.
- **App window**: `handler app open <name>` opens Firefox with a dedicated profile (`handler-apps`:
  toolbars hidden, since Firefox has no `--app` mode; apps' cookies apart from normal browsing),
  else Chromium's app mode, else the default browser.
- Later: a real overlay (a GNOME Shell extension or a small launcher window), toggling one window.

### 5.2 Remote (phone), through the gateway — same app, same instance

The app stays on the host; the phone reaches it through the E2E channel that already exists
(`remote.md` §4). The gateway sees ciphertext only, as today; nothing changes in its trust model.

- **Who:** on the Apps page, each app lists the persons who may use it remotely (none by
  default: local only). You are `owner`; a family member's phone is paired for a person, with
  access to apps only (§8).
- The **remote client** lists the apps shared with its person above the shared sessions. An app
  is shown in a **sandboxed iframe** (`/appframe.html`, an opaque origin, a policy that allows no
  connection: its code can never read the device key, the sessions or the other apps, nor send
  anything anywhere by itself).
- The app's UI talks to its backend through the template's `api()` helper (`ui/src/api.ts`):
  `fetch` locally, `postMessage` to the client remotely, which seals the request as a frame of a
  new channel (`s: "app:<name>"`); handlerd opens it, checks the device's person against the app's
  allowed persons, and forwards to the app. The skill makes `api()` the only way to call the
  backend, so apps written today work remotely without a change.
- The app's UI comes through the same channel (encrypted, not served by the gateway), as **one
  page**: Handler inlines its script, stylesheet and files (the template builds one script and one
  stylesheet with images inside). The phone keeps the last version it got and shows it when the
  host does not answer ("offline copy").
- In the frame there is no storage either (`localStorage`, cookies): apps keep their state in the
  backend (the skill says so).
- A page may try to navigate itself to another site, carrying data in the address. On the
  phone the client's policy (`frame-src 'self'`) stops that navigation before anything is sent,
  and the client closes an app whose frame loads a second page (the browser's error, or another
  page of the gateway), so that page never reaches the app's backend. Known limit, on the
  computer only: no browser policy stops a top-level navigation, so the app's window can leave
  with data in its address. The CSP stops every other way out; what an app's page does is part
  of what you review before deploying.
- iOS: notifications need the remote client installed as a home-screen web app (§7), so it gets
  a web app manifest and a service worker.

### 5.3 When the host is off: queued requests

Each backend route is declared in the manifest as:

| Kind | Host off | Examples |
|---|---|---|
| `sync` (default) | fails at once, "host offline" | UM1 compute, reading the coach's list |
| `queued` | stored (encrypted) at the gateway, run when the host is back, answer delivered to the device afterwards | UM3 summarize, UM4 "I did it" |

- The gateway got a **persistent** queue (on disk, 7 days, 500 per host) next to the in-memory
  mailboxes; queueing wakes the host's poll, which then takes the queue.
- A queued envelope expires in 7 days (a direct one in 5 min: `remote.md` §4), and is taken
  once, before then, whichever way it comes; from the queue, only `_handler/app/http` calls to
  routes the installed version declares `queued`. Calls carry an `Idempotency-Key` for the app.
  A compromised gateway can delay them up to 7 days, or drop them: accepted, the route says so;
  the phone lists them as "waits for your computer" until the answer comes.
- The phone answers the app 202 `{queued: true}` at once. The answer goes back like any `up`
  envelope (the phone marks the call "done"), and the device gets a push (§7).

## 6. What an app may reach

Declared in the manifest (`[needs]`), shown at deploy; a deploy that adds to them asks first (the
Apps page and `handler app deploy` list what is new). **The app is responsible for its own model
calls** (local or paid, its choice, its cost): Handler gives it the network access and the keys,
nothing more.

| Need | For | How |
|---|---|---|
| `egress` | models (UM2–UM4), RustiCal (UM4) | hosts the backend may reach, through the filtered network (same mechanism as addons). The host's own services (the local model server on `:3000`) are reached as `host.containers.internal:<port>`, like `codex-local`. |
| `secrets` | API keys, the CalDAV password | named env vars; values entered in the Apps page (or `handler app secret`), stored in Handler's secret store, given to the backend as environment variables (not to its tests), hidden in its log; never in the app folder, so never seen by the agent that writes it |
| `files` | UM4 (calendar as a markdown file) | a folder (or file) per named need, which the person gives at install, mounted into the app, `ro` or `rw`, never one of Handler's own nor keys (§11b) |
| `notify` | UM4 | `POST $HANDLER_APP_API/notify {person, title}`: desktop (GNOME) and phone (§7) |
| `agents` | "ask an agent": a planner's "what matters most today?" | runs of the agent the person gave a named need (one of theirs that fits, or one set up from the definition the app ships), started while it answers the owner, their state and result read later (`contracts.md` H.11, §11b) |

The manifest is strict: a key this Handler does not know yet is an error, so an app never silently
runs without something it asked for.

## 7. At a time, and notifications

- At a time: an **automation** calls the app's route (`contracts.md` I: `when = { at = "08:30" }`
  or `{ every = "30m" }`, `run = { app = "coach", call = "POST /api/cron/morning" }`). handlerd starts
  the app and calls it; after the PC was off, only the latest missed time runs. The app had its
  own `[[schedule]]` until 2026-10-09: triggers live on automations only.
- `notify`: into the person's inbox (`contracts.md` I.9, with automations' results), on the
  desktop through the GNOME notification service (`org.freedesktop.Notifications`).
- Phone: **Web Push** (`remote.md` §8), **content-free** ("coach has something for you"); the text
  is fetched through the E2E channel when the notification is opened, so the push service learns
  nothing but "now". handlerd signs with its own VAPID key: no account with anyone. The browser picks
  the push service: Firefox on Android → Mozilla, iOS → Apple (only for a home-screen web app,
  §5.2), Chromium → Google, Edge → Windows. handlerd takes an endpoint of those services only
  (`webpush.PUSH_HOSTS`): it posts to it on each message, so any other address would let a paired
  device have handlerd call one of your network's. Also used when a queued request (§5.3) has
  been answered.
  (ntfy, self-hosted, was the alternative: it avoids the vendors' services on Android but not on
  iOS, and needs its own app.)

## 8. Persons and devices

- A family member's phone is paired like yours (Settings → Remote → New device, "For: alice"),
  and the device gets the **apps** scope only: never an agent session. Your own devices (person
  `owner`) reach both.
- Each app lists the persons it is shared with (none by default). Revoking a device is done in
  the local UI, as before.
- The app sees `X-HANDLER-Person` and keeps per-person data if it wants (the template does).
- A "shared token" per app was considered: pairing already exists, is as easy for the family
  (scan once), and gives per-device revocation and E2E encryption; a shared token would give
  neither.

## 9. Manifest

Normative in `contracts.md` §H:

```toml
apiVersion  = "handler.app/v1"
name        = "coach"             # a DNS label: http://coach.localhost:7430/
version     = "0.3.0"
description = "Asks how my tasks are going"

[server]
entry = "server/main.ts"          # default; its directory is installed whole
[ui]
dir = "ui/dist"                   # default; built, with an index.html
[needs]
egress = ["host.containers.internal:3000", "rustical.lan:443"]
[resources]
memory = "512m"                   # default
```

Also: `[needs] secrets = ["LLM_API_KEY"]`, `notify` (§6), `[needs.files.<name>]`,
`[needs.agents.<name>]` (§11b), and `[routes] "POST /api/checkin" = "queued"` (§5.3). Who may use an app and when it is called on
its own (an automation) are the person's settings, not the manifest's.

## 10. Authoring

The `app-builder` addon (built-in, `handler_harness/data/addons/app-builder/`; named `miniapp`
until 2026-10-22): the **skill** (layout, the `api()` helper, the ABI, what is not allowed,
migrations and tests) and a template (short notes: Svelte UI, Bun + SQLite backend, migrations,
tests) the agent copies. It has no image: Bun is in the toolbox, and an addon may not ship a
command the toolbox already has (G.4). `bun run dev` in `server/` and `ui/` runs a preview (vite
forwards `/api` to the backend), `bun test`, `bun run check` and `bun run build` do the rest. The
addon's egress is npm (the UI's build and the type checker).

**Only a human deploys.** The agent builds and tests in its sandbox; it has no way to deploy
(the sandbox has no Handler token). Handler keeps each app's code (`contracts.md` H.15): an app
file installed, or the App creator's draft used, becomes its next version; the app's page then
says what it may reach that it could not before, and deploying runs the steps of §4 (`handler
app deploy` from a terminal).

## 11. Not built yet

- A real overlay (a GNOME Shell extension or a small launcher window) toggling one window.
- WebSockets to backends.
- An app with no screen (agents, actions and automations only): today `server/` and a built UI
  are required. Waits for its first case (a weekly digest); then the draft (H.16), which has
  nothing to open without a screen, is tried from the app's page once installed, and later on a
  page of Handler's where a draft's actions run on copies (its agents set up for the draft only).

## 11a. An app's parts (was: an app in a project)

An app is what works for you; a project is a folder you work on. Planner was spread over five
places (its screens under Apps, its agent outside projects, its schedule, its inbox, its folder
typed in a dialog). The first answer (2026-10-18) put the app in the project of its data folder,
with its agent as one of the project's agents; it failed where an app has no folder (a
calculator, a chat) and made the place of an app depend on a folder. Since 2026-10-20 (H.14):

- **The app is the whole.** What you install, update, remove and share as one: its code, its
  agents, its schedules, what you can ask it. Its page lists its parts (*Under the hood*); they are
  nowhere else in the menu, so installing an app adds one thing to it.
- **Its agent is its part.** Set up for it from the definition it brings, started by it only,
  removed with it. Still an agent: its page reads its runs, its settings are yours to change and
  improve. Kept in its own sandbox: the app's backend never sits next to a model credential.
  Linked by the agent's id, a rename costs nothing. An agent of yours given to it stays yours.
- **A project sees the apps given its folder**, from its side: you work there with your agents,
  the app works for you on the same files.
- **The fit is checked at each run**, against the installed version's definition: a form changed
  in the editor, the agent deleted, and the app's page says why it no longer fits.
- **Installing is one page**, the agents set-up page's layout: where it keeps your files (a
  folder of yours, new or not), its agents, secrets, what you can ask it, the automations it
  suggests (each off unless switched on), who opens it, and what it will be allowed to do beside
  the button. Each step goes through its own request (no install endpoint): a step that fails
  leaves what was done, all states that exist anyway, and the page reopened goes on from there.
  Its folders come first: its agents work in one of them.

Also built: the agent's settings list the apps it was given to (*Used by apps*), and deleting it
says which apps and automations stop (the web UI, `handler agent rm`), read from the apps' needs
(no contract of its own). Automations too keep their agent by id (`contracts.md` I.1): the file
names it as a person writes it, handlerd binds that name the first time it reads it, so a rename
changes nothing; and an app suggests automations (`[[automations]]`), made from its page, off.
Handler's own features that need an agent are its needs the same way (`contracts.md` D.18): set
up from the definition Handler ships for each or given one that fits, Handler uses the one given. The App creator is
one of Handler's helpers, with the `app-builder` addon and no folder: each of its sessions works on a
draft of an app's code kept by Handler (`contracts.md` H.15), *New app* (empty) or *Change it* (a
copy), used when the person says so; the person never keeps an app's code. Not built yet: an app installed twice (two planners, home and work: the
manifest's `name` is also the installation's).

## 12. Decisions

2026-09-28: Deno (replaced by Bun on 2026-10-22, below); apps on the host only, never on the
gateway; no sync, ever; remote through the E2E channel, `queued` routes for when the host is off
(enough while the gateway is up more often than the PC); family members through device pairing; 1
app = 1 UI; the app calls its own models; text is copy/pasted (no selection grabbing); only a human
deploys; only apps I write; Svelte for UIs; Web Push for phones (Android and iOS, mostly Firefox,
then Chromium).

Made while building the app host:
- A pinned distroless image of the runtime, not the toolbox, runs apps: small, and what the tests
  ran on.
- One origin per app (`<name>.localhost`), not a path under Handler's origin: Handler's web UI keeps its
  token in the page, which an app's code must never reach.
- handlerd serves the UI; the backend only gets `/api/`: opening an app is instant and the UI works
  while the backend starts.
- Rollback restores the data backup of the rolled-back deploy.

Made while building secrets, remote access, queued calls and notifications:
- Who may use an app remotely is the person's setting (its page), not the manifest's: an agent
  does not share an app. (A keyboard shortcut per app, a GNOME keybinding, was built and removed
  on 2026-10-21: one more setting on the app's page for little use.)
- On a phone an app runs in a sandboxed frame served by the gateway (`/appframe.html`, no
  network, no storage); Handler sends it as one page. The template builds that way.
- The backend reaches Handler (notifications) through a Unix socket Handler serves per app, so no token
  is involved. Bun's `fetch` reaches it with its `unix` option; when the sandbox has a proxy, it
  writes the request's target in absolute form (`POST http://handler/runs`), which that server
  reads too.
- Queued calls take their own path from the gateway (list, take once, delete), not the 5-minute
  direct one.
- Pushes carry nothing, so no payload encryption is needed; the text travels in the E2E channel.

Not verified here (environment): Firefox (the tests use Chromium; Firefox resolves
`*.localhost` to the loopback address since version 84); a model server on the host itself
(`host.containers.internal`); real push services
(Mozilla, Apple) and the home-screen web app on iOS.

2026-10-22, one name per concept (the code says what the person reads):
- *Mini app* is **app** everywhere (`handler.app/v1`, `AppManifest`, the `app-builder` addon):
  with agents, actions and automations in it, an app is not mini, and nobody said the word but
  the docs.
- An app's *asks* are its **actions**: *Ask* is Handler's feature, which picks one action of one
  app.
- **Chat is no app**: nothing of it is installed, updated, removed, exported or shared, and its
  agents are made and deleted by the person. Its agents' home is `chat`, not `app`; the UI still
  lists it with the apps.
- **Uninstall deletes the app's own data** (it was kept, and found by any app installed later
  under that name: a leak once apps come from others). The folders given to it stay.
- An app and an agents file are not merged: the same agent definitions underneath, but an app's
  agents follow the app (updated, removed with it) while an agents file's are the person's once
  set up.

Made on 2026-10-22, **Bun replaces Deno** (Deno's support was to end within a year). Measured
with the same backend (Unix socket, SQLite, the template's routes) in each runtime's distroless
image: at rest Bun takes 19 MB, Deno 36 MB, Node 24 76 MB; after 5,000 requests 27, 60 and 106 MB;
the first answer comes 80, 100 and 290 ms after the start. Node kept a permission model, but a
partial one (its `node:sqlite` opens any file whatever `--allow-fs-*` says, and it has no network
permission); Bun's web `Request`/`Response` server kept the template's routes unchanged, and it
was already the toolbox's. What was lost is Deno's permissions as a second layer inside the
sandbox: the sandbox (strict confinement, no network or the enforced allow-list) is now the only
one, as it is for agents.
